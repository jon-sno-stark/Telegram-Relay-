import logging
import asyncio
from collections import defaultdict
from typing import List
from telegram import Update, Message, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.ext import ContextTypes
from telegram.error import Forbidden, TimedOut

from . import db
from .decorators import user_is_active

logger = logging.getLogger(__name__)

MEDIA_BUFFER = defaultdict(list)
PROCESSED_MEDIA_GROUPS = set()
MAX_ALBUM_SIZE = 10
RELAY_BATCH_SIZE = 10
RELAY_BATCH_DELAY = 3

def _create_album_from_messages(messages: List[Message]) -> List:
    """Helper to build a single InputMedia album from a list of Message objects."""
    if not messages:
        return []

    # Use the caption from the first message in the group that has one
    caption = next((msg.caption for msg in messages if msg.caption), None)
    
    album = []
    
    # First item gets the caption
    first_msg = messages[0]
    if first_msg.photo:
        album.append(InputMediaPhoto(media=first_msg.photo[-1].file_id, caption=caption))
    elif first_msg.video:
        album.append(InputMediaVideo(media=first_msg.video.file_id, caption=caption))
    elif first_msg.document:
        album.append(InputMediaDocument(media=first_msg.document.file_id, caption=caption))

    # The rest of the items have no caption
    for msg in messages[1:]:
        if msg.photo:
            album.append(InputMediaPhoto(media=msg.photo[-1].file_id))
        elif msg.video:
            album.append(InputMediaVideo(media=msg.video.file_id))
        elif msg.document:
            album.append(InputMediaDocument(media=msg.document.file_id))
            
    return album


async def _relay_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = update.effective_user
    recipients = await db.get_all_active_users()
    relayed_message_ids = {}

    for recipient in recipients:
        if recipient['user_id'] == sender.id:
            continue
        try:
            reply_to_msg_id = None
            if update.message.reply_to_message:
                msg_map = await db.get_relayed_message_info(update.message.reply_to_message.message_id)
                if msg_map and str(recipient['user_id']) in msg_map.get('relayed_to', {}):
                    reply_to_msg_id = msg_map['relayed_to'][str(recipient['user_id'])]
            
            sent_msg = None
            # Requirement: Sender's name only on text messages
            if update.message.text:
                text_to_send = f"<b>From: {sender.full_name}</b>\n\n{update.message.text_html}"
                sent_msg = await context.bot.send_message(
                    chat_id=recipient['user_id'], text=text_to_send, reply_to_message_id=reply_to_msg_id
                )
            else: # Sticker, audio, voice, etc. are copied anonymously.
                sent_msg = await context.bot.copy_message(
                    chat_id=recipient['user_id'], from_chat_id=sender.id,
                    message_id=update.message.message_id, reply_to_message_id=reply_to_msg_id
                )
            
            if sent_msg:
                relayed_message_ids[str(recipient['user_id'])] = sent_msg.message_id
            await asyncio.sleep(0.05)
        except Forbidden:
            await db.update_user_status(recipient['user_id'], 'inactive')
        except Exception as e:
            logger.error(f"Failed relaying text to {recipient['user_id']}: {e}")

    await db.log_relayed_message(update.message.message_id, sender.id, relayed_message_ids)
    await db.increment_user_stat(sender.id, message_count=1)

@user_is_active
async def media_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.update_last_active(update.effective_user.id)
    
    if update.message.media_group_id:
        if not context.bot_data.get(update.message.media_group_id):
            context.bot_data[update.message.media_group_id] = []
        context.bot_data[update.message.media_group_id].append(update.message)

        if update.message.media_group_id not in PROCESSED_MEDIA_GROUPS:
            PROCESSED_MEDIA_GROUPS.add(update.message.media_group_id)
            context.job_queue.run_once(
                lambda ctx: _add_media_group_to_buffer(ctx, update.message.media_group_id, update.effective_user.id),
                when=2, name=f"buffer_group_{update.message.media_group_id}"
            )
    elif update.message.photo or update.message.video or update.message.document:
        MEDIA_BUFFER[update.effective_user.id].append(update.message)
    else:
        await _relay_text_message(update, context)

async def _add_media_group_to_buffer(context: ContextTypes.DEFAULT_TYPE, media_group_id: str, user_id: int):
    messages = context.bot_data.pop(media_group_id, [])
    if messages:
        MEDIA_BUFFER[user_id].extend(messages)
    PROCESSED_MEDIA_GROUPS.discard(media_group_id)


async def process_media_buffers(context: ContextTypes.DEFAULT_TYPE):
    if not MEDIA_BUFFER: return
    buffer_copy = MEDIA_BUFFER.copy()
    MEDIA_BUFFER.clear()
    recipients = await db.get_all_active_users()
    if not recipients: return
    
    for sender_id, messages in buffer_copy.items():
        if not messages: continue
        
        # --- 1. Group messages by type and order ---
        all_albums_to_send = []
        current_album_messages = []
        
        for msg in messages:
            # Check if the current message can be added to the current album
            is_new_album = False
            if not current_album_messages:
                is_new_album = True
            else:
                first_msg_in_album = current_album_messages[0]
                is_pv_album = first_msg_in_album.photo or first_msg_in_album.video
                is_doc_album = first_msg_in_album.document
                
                is_current_msg_pv = msg.photo or msg.video
                
                # If types don't match, or album is full, start a new one
                if (is_pv_album and not is_current_msg_pv) or \
                   (is_doc_album and is_current_msg_pv) or \
                   (len(current_album_messages) >= MAX_ALBUM_SIZE):
                    is_new_album = True

            if is_new_album and current_album_messages:
                # Finalize the old album
                all_albums_to_send.append(_create_album_from_messages(current_album_messages))
                current_album_messages = []
            
            current_album_messages.append(msg)
            
        # Add the last album from the buffer
        if current_album_messages:
            all_albums_to_send.append(_create_album_from_messages(current_album_messages))

        # --- 2. Relay the generated albums ---
        final_recipients = [r for r in recipients if r['user_id'] != sender_id]
        recipient_batches = [final_recipients[i:i + RELAY_BATCH_SIZE] for i in range(0, len(final_recipients), RELAY_BATCH_SIZE)]
        
        total_media_sent = len(messages)
        
        for i, batch in enumerate(recipient_batches):
            logger.info(f"Relaying {len(all_albums_to_send)} albums to batch {i+1}/{len(recipient_batches)}")
            for recipient in batch:
                for album in all_albums_to_send:
                    if not album: continue
                    try:
                        await context.bot.send_media_group(
                            chat_id=recipient['user_id'], 
                            media=album,
                            read_timeout=60, # Increased timeout
                            connect_timeout=60 # Increased timeout
                        )
                    except Forbidden:
                        await db.update_user_status(recipient['user_id'], 'inactive')
                        logger.warning(f"User {recipient['user_id']} blocked the bot.")
                    except TimedOut:
                        logger.error(f"Failed album send to {recipient['user_id']}: Timed out")
                    except Exception as e:
                        logger.error(f"Failed album send to {recipient['user_id']}: {e}")
            
            if len(recipient_batches) > 1: await asyncio.sleep(RELAY_BATCH_DELAY)
        
        await db.increment_user_stat(sender_id, media_count=total_media_sent)
        logger.info(f"Finished relaying buffer for user {sender_id}")

import logging
import asyncio
from collections import defaultdict
from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.ext import ContextTypes
from telegram.error import Forbidden

from . import db
from .decorators import user_is_active

logger = logging.getLogger(__name__)

MEDIA_BUFFER = defaultdict(list)
PROCESSED_MEDIA_GROUPS = set()
MAX_ALBUM_SIZE = 10
RELAY_BATCH_SIZE = 10
RELAY_BATCH_DELAY = 3

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
            logger.error(f"Failed relaying to {recipient['user_id']}: {e}")

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

async def _add_media_group_to_buffer(context: ContextTypes.DEFAULT_TYPE, media_group_id, user_id):
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
        
        # --- 1. Separate media types and get caption ---
        photos_videos_data = []
        documents_data = []
        caption = next((msg.caption for msg in messages if msg.caption), None)
        sender = await db.get_user(sender_id)
        final_caption = f"From: {sender.get('full_name', 'Anonymous')}\n\n{caption}" if caption else f"From: {sender.get('full_name', 'Anonymous')}"

        for msg in messages:
            if msg.photo: photos_videos_data.append(msg)
            elif msg.video: photos_videos_data.append(msg)
            elif msg.document: documents_data.append(msg)

        # --- 2. Build InputMedia lists with caption on the first item ---
        photos_videos = []
        if photos_videos_data:
            first_pv = photos_videos_data[0]
            if first_pv.photo:
                photos_videos.append(InputMediaPhoto(media=first_pv.photo[-1].file_id, caption=final_caption))
            elif first_pv.video:
                photos_videos.append(InputMediaVideo(media=first_pv.video.file_id, caption=final_caption))
            
            for msg in photos_videos_data[1:]:
                if msg.photo: photos_videos.append(InputMediaPhoto(media=msg.photo[-1].file_id))
                elif msg.video: photos_videos.append(InputMediaVideo(media=msg.video.file_id))

        documents = []
        if documents_data:
            first_doc = documents_data[0]
            documents.append(InputMediaDocument(media=first_doc.document.file_id, caption=final_caption))
            for msg in documents_data[1:]:
                documents.append(InputMediaDocument(media=msg.document.file_id))

        # --- 3. Chunk and send ---
        all_albums = [photos_videos[i:i+MAX_ALBUM_SIZE] for i in range(0, len(photos_videos), MAX_ALBUM_SIZE)]
        all_albums += [documents[i:i+MAX_ALBUM_SIZE] for i in range(0, len(documents), MAX_ALBUM_SIZE)]

        final_recipients = [r for r in recipients if r['user_id'] != sender_id]
        recipient_batches = [final_recipients[i:i + RELAY_BATCH_SIZE] for i in range(0, len(final_recipients), RELAY_BATCH_SIZE)]
        
        for i, batch in enumerate(recipient_batches):
            for recipient in batch:
                for album in all_albums:
                    if not album: continue
                    try:
                        await context.bot.send_media_group(chat_id=recipient['user_id'], media=album)
                    except Forbidden:
                        await db.update_user_status(recipient['user_id'], 'inactive')
                    except Exception as e:
                        logger.error(f"Failed album send to {recipient['user_id']}: {e}")
            if len(recipient_batches) > 1: await asyncio.sleep(RELAY_BATCH_DELAY)
        
        await db.increment_user_stat(sender_id, media_count=len(photos_videos) + len(documents))


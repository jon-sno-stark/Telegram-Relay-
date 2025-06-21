import logging
import asyncio
from collections import defaultdict
from telegram import Update, Message, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

from . import db
from .decorators import user_is_active

logger = logging.getLogger(__name__)

# In-memory buffer for media messages.
# Format: {user_id: [message1, message2, ...]}
MEDIA_BUFFER = defaultdict(list)
# To avoid processing the same album multiple times
PROCESSED_MEDIA_GROUPS = set()

# --- Constants for Media Handling ---
MAX_ALBUM_SIZE = 10 # Telegram API limit
RELAY_BATCH_SIZE = 10 # Number of users to send to at once
RELAY_BATCH_DELAY = 3 # Seconds to wait between user batches

async def _relay_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Directly relays non-media messages (text, sticker, etc.)."""
    sender = update.effective_user
    recipients = await db.get_all_active_users()
    
    relayed_message_ids = {}

    for recipient in recipients:
        if recipient['user_id'] == sender.id:
            continue
        try:
            # Handle replies
            reply_to_msg_id = None
            if update.message.reply_to_message:
                original_reply_id = update.message.reply_to_message.message_id
                msg_map = await db.get_relayed_message_info(original_reply_id)
                if msg_map and str(recipient['user_id']) in msg_map.get('relayed_to', {}):
                    reply_to_msg_id = msg_map['relayed_to'][str(recipient['user_id'])]

            sent_msg = await context.bot.copy_message(
                chat_id=recipient['user_id'],
                from_chat_id=sender.id,
                message_id=update.message.message_id,
                reply_to_message_id=reply_to_msg_id
            )
            relayed_message_ids[str(recipient['user_id'])] = sent_msg.message_id
            await asyncio.sleep(0.05) # Small delay to avoid hitting limits
        except Forbidden:
            logger.warning(f"User {recipient['user_id']} has blocked the bot. Setting status to inactive.")
            await db.update_user_status(recipient['user_id'], 'inactive')
        except Exception as e:
            logger.error(f"Failed to relay text message to {recipient['user_id']}: {e}")

    await db.log_relayed_message(update.message.message_id, sender.id, relayed_message_ids)
    await db.increment_user_stat(sender.id, message_count=1)

@user_is_active
async def media_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives all messages, decides whether to buffer (media) or relay directly."""
    await db.update_last_active(update.effective_user.id)
    
    # Handle media groups (albums)
    if update.message.media_group_id:
        if update.message.media_group_id in PROCESSED_MEDIA_GROUPS:
            return # Already handled this group
        # Add the entire group to the buffer at once
        PROCESSED_MEDIA_GROUPS.add(update.message.media_group_id)
        # We use a short delay to ensure all messages in the group have arrived
        context.job_queue.run_once(
            lambda ctx: _add_media_group_to_buffer(ctx, update.message.media_group_id, update.effective_user.id),
            when=2,
            name=f"buffer_group_{update.message.media_group_id}"
        )
    # Handle single media messages
    elif update.message.photo or update.message.video or update.message.document:
        MEDIA_BUFFER[update.effective_user.id].append(update.message)
        logger.info(f"Buffered single media from {update.effective_user.id}. Total buffer size: {len(MEDIA_BUFFER[update.effective_user.id])}")
    # Handle text, stickers, etc.
    else:
        await _relay_text_message(update, context)

async def _add_media_group_to_buffer(context: ContextTypes.DEFAULT_TYPE, media_group_id, user_id):
    """Job to collect and buffer an entire media group."""
    messages = context.bot_data.get(media_group_id)
    if messages:
        MEDIA_BUFFER[user_id].extend(messages)
        logger.info(f"Buffered media group {media_group_id} ({len(messages)} items) from {user_id}. Total buffer: {len(MEDIA_BUFFER[user_id])}")
        del context.bot_data[media_group_id]
    PROCESSED_MEDIA_GROUPS.discard(media_group_id)


async def process_media_buffers(context: ContextTypes.DEFAULT_TYPE):
    """
    This job runs periodically to process the media buffers for all users.
    It implements the core batching and relaying logic.
    """
    if not MEDIA_BUFFER:
        return

    # Create a copy of the buffer to work with, and clear the global one
    buffer_copy = MEDIA_BUFFER.copy()
    MEDIA_BUFFER.clear()

    recipients = await db.get_all_active_users()
    
    for sender_id, messages in buffer_copy.items():
        if not messages:
            continue
            
        logger.info(f"Processing buffer for user {sender_id} with {len(messages)} items.")

        # --- 1. Prepare Media Groups ---
        photos_videos = []
        documents = []
        
        caption = None
        for msg in messages:
            # Find the first valid caption to use for the album
            if msg.caption and not caption:
                caption = msg.caption
            
            if msg.photo:
                photos_videos.append(InputMediaPhoto(media=msg.photo[-1].file_id))
            elif msg.video:
                photos_videos.append(InputMediaVideo(media=msg.video.file_id))
            elif msg.document:
                documents.append(InputMediaDocument(media=msg.document.file_id))

        # Apply caption to the first item of each album type
        sender_user = await db.get_user(sender_id)
        sender_name = sender_user.get('full_name', 'Anonymous')
        final_caption = f"From: {sender_name}\n\n{caption}" if caption else f"From: {sender_name}"
        
        if photos_videos: photos_videos[0].caption = final_caption
        if documents: documents[0].caption = final_caption

        # Chunk media into albums of 10
        pv_albums = [photos_videos[i:i + MAX_ALBUM_SIZE] for i in range(0, len(photos_videos), MAX_ALBUM_SIZE)]
        doc_albums = [documents[i:i + MAX_ALBUM_SIZE] for i in range(0, len(documents), MAX_ALBUM_SIZE)]
        all_albums = pv_albums + doc_albums

        # --- 2. Send in Batches to Users ---
        # Filter out the sender from recipients
        recipient_batches = [
            recipients[i:i + RELAY_BATCH_SIZE]
            for i in range(0, len(recipients), RELAY_BATCH_SIZE)
            if recipients[i]['user_id'] != sender_id
        ]
        
        total_media_sent = len(photos_videos) + len(documents)

        for i, recipient_batch in enumerate(recipient_batches):
            logger.info(f"Sending to user batch {i+1}/{len(recipient_batches)}...")
            for recipient in recipient_batch:
                for album in all_albums:
                    try:
                        sent_messages = await context.bot.send_media_group(chat_id=recipient['user_id'], media=album)
                        # TODO: Log these messages for /delete. This is complex as send_media_group returns a list.
                    except Forbidden:
                        logger.warning(f"User {recipient['user_id']} blocked the bot. Deactivating.")
                        await db.update_user_status(recipient['user_id'], 'inactive')
                    except Exception as e:
                        logger.error(f"Failed to send album to {recipient['user_id']}: {e}")
            
            await asyncio.sleep(RELAY_BATCH_DELAY)
        
        # --- 3. Update Sender Stats ---
        await db.increment_user_stat(sender_id, media_count=total_media_sent)
        logger.info(f"Finished processing buffer for user {sender_id}.")

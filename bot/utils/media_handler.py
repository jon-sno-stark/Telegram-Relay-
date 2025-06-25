import logging
import asyncio
from collections import defaultdict
from typing import List, Dict, Any
from datetime import datetime
from telegram import Update, Message, InputMediaPhoto, InputMediaVideo, InputMediaDocument
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

async def _send_user_media_job(context: ContextTypes.DEFAULT_TYPE):
    """Worker job that processes and sends all media for a single user."""
    job_data = context.job.data
    sender_id: int = job_data["sender_id"]
    messages: List[Message] = job_data["messages"]
    
    recipients = await db.get_all_active_users()
    if not recipients: return
        
    # Group messages into albums while preserving order
    all_albums_to_send: List[Dict[str, Any]] = []
    current_album_messages: List[Message] = []
    for msg in messages:
        is_new_album = False
        if not current_album_messages: is_new_album = True
        else:
            first_in_album = current_album_messages[0]
            is_pv_album = bool(first_in_album.photo or first_in_album.video)
            is_doc_album = bool(first_in_album.document)
            is_current_pv = bool(msg.photo or msg.video)
            is_current_doc = bool(msg.document)
            if (is_pv_album and not is_current_pv) or \
               (is_doc_album and not is_current_doc) or \
               (len(current_album_messages) >= MAX_ALBUM_SIZE):
                is_new_album = True
        if is_new_album and current_album_messages:
            all_albums_to_send.append({"messages": current_album_messages})
            current_album_messages = []
        current_album_messages.append(msg)
    if current_album_messages:
        all_albums_to_send.append({"messages": current_album_messages})

    # Relay albums to recipients
    final_recipients = [r for r in recipients if r['user_id'] != sender_id]
    for recipient in final_recipients:
        for album_data in all_albums_to_send:
            original_msgs = album_data["messages"]
            album_input_media = _create_album_from_messages(original_msgs)
            if not album_input_media: continue
            try:
                reply_to_msg_id = await _get_reply_id_for_recipient(sender_id, original_msgs[0], recipient['user_id'])
                sent_messages = await context.bot.send_media_group(recipient['user_id'], album_input_media, reply_to_message_id=reply_to_msg_id, read_timeout=60, connect_timeout=60)
                for j, original_msg in enumerate(original_msgs):
                    await db.log_relayed_message(original_msg.message_id, sender_id, {str(recipient['user_id']): sent_messages[j].message_id})
            except Exception as e:
                logger.error(f"Failed album send to {recipient['user_id']}: {e}")
        await asyncio.sleep(0.05)
    
    await db.increment_user_stat(sender_id, media_count=len(messages))

async def dispatch_media_processing(context: ContextTypes.DEFAULT_TYPE):
    """Dispatcher job. Quickly checks buffer and schedules worker jobs."""
    if not MEDIA_BUFFER: return
    buffer_copy = MEDIA_BUFFER.copy()
    MEDIA_BUFFER.clear()
    for sender_id, messages in buffer_copy.items():
        if messages:
            context.job_queue.run_once(
                _send_user_media_job, when=1,
                data={"sender_id": sender_id, "messages": messages},
                name=f"send_media_{sender_id}_{datetime.now().timestamp()}"
            )

def _create_album_from_messages(messages: List[Message]) -> List:
    if not messages: return []
    caption = next((msg.caption for msg in messages if msg.caption), None)
    album = []
    
    first_msg = messages[0]
    if first_msg.photo: album.append(InputMediaPhoto(first_msg.photo[-1].file_id, caption=caption))
    elif first_msg.video: album.append(InputMediaVideo(first_msg.video.file_id, caption=caption))
    elif first_msg.document: album.append(InputMediaDocument(first_msg.document.file_id, caption=caption))

    for msg in messages[1:]:
        if msg.photo: album.append(InputMediaPhoto(msg.photo[-1].file_id))
        elif msg.video: album.append(InputMediaVideo(msg.video.file_id))
        elif msg.document: album.append(InputMediaDocument(msg.document.file_id))
    return album

async def _get_reply_id_for_recipient(sender_id: int, original_msg: Message, recipient_id: int) -> int or None:
    if not original_msg.reply_to_message: return None
    msg_map = await db.get_relayed_message_info_by_any_id(sender_id, original_msg.reply_to_message.message_id)
    return msg_map.get('relayed_to', {}).get(str(recipient_id)) if msg_map else None

async def _relay_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = update.effective_user
    recipients = await db.get_all_active_users()
    sent_to_map = {}
    for recipient in recipients:
        if recipient['user_id'] == sender.id: continue
        try:
            reply_to_msg_id = await _get_reply_id_for_recipient(sender.id, update.message, recipient['user_id'])
            
            if update.message.text:
                text_to_send = f"<b>From: {sender.full_name}</b>\n\n{update.message.text_html}"
                sent_msg = await context.bot.send_message(recipient['user_id'], text_to_send, reply_to_message_id=reply_to_msg_id)
            else:
                sent_msg = await context.bot.copy_message(recipient['user_id'], sender.id, update.message.message_id, reply_to_message_id=reply_to_msg_id)
            
            if sent_msg: sent_to_map[str(recipient['user_id'])] = sent_msg.message_id
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed relaying text to {recipient['user_id']}: {e}")

    if sent_to_map: await db.log_relayed_message(update.message.message_id, sender.id, sent_to_map)
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
    if messages: MEDIA_BUFFER[user_id].extend(messages)
    PROCESSED_MEDIA_GROUPS.discard(media_group_id)

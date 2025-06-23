import os
import logging
from telegram.ext import ContextTypes
from telegram.error import Forbidden

from ..utils import db
from ..utils.media_handler import dispatch_media_processing

logger = logging.getLogger(__name__)
APPROVAL_CHANNEL_ID = os.getenv("APPROVAL_CHANNEL_ID")
INACTIVITY_DAYS = 7

async def check_inactive_users(context: ContextTypes.DEFAULT_TYPE):
    inactive_users = await db.find_inactive_users(days=INACTIVITY_DAYS)
    if not inactive_users: return
    count = 0
    for user in inactive_users:
        await db.update_user_status(user['user_id'], 'inactive')
        count += 1
        try:
            await context.bot.send_message(user['user_id'], "You have been marked as inactive.")
        except Exception: pass
    logger.info(f"Deactivated {count} inactive users.")
    if count > 0:
        await context.bot.send_message(APPROVAL_CHANNEL_ID, f"🧹 Deactivated {count} users.")

async def send_service_message(context: ContextTypes.DEFAULT_TYPE):
    service_message = await db.get_config_value('service_message')
    if not service_message: return
    active_users = await db.get_all_active_users()
    for user in active_users:
        try:
            await context.bot.send_message(chat_id=user['user_id'], text=service_message)
        except Exception: pass

async def _send_summary(context: ContextTypes.DEFAULT_TYPE, period: str):
    all_users = await db.get_all_users()
    total_msgs = sum(u.get('total_messages_sent', 0) for u in all_users)
    sorted_users = sorted(all_users, key=lambda u: u.get('media_sent_count', 0), reverse=True)
    
    text = f"🗓️ <b>{period.title()} Summary</b>\nTotal Msgs: {total_msgs}\n\n<b>🏆 Top 10 by Media:</b>\n"
    top_ten = [u for u in sorted_users[:10] if u.get('media_sent_count', 0) > 0]
    if not top_ten:
        text += "<i>No media activity.</i>"
    else:
        for i, user in enumerate(top_ten):
            text += f"<b>{i+1}.</b> {user.get('full_name')} - {user.get('media_sent_count')}\n"
    await context.bot.send_message(chat_id=APPROVAL_CHANNEL_ID, text=text)

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    await _send_summary(context, 'daily')
    
async def send_weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    await _send_summary(context, 'weekly')
    
async def process_media_buffers_job(context: ContextTypes.DEFAULT_TYPE):
    """
    This is the entry point for the periodic job. It calls the dispatcher.
    """
    await dispatch_media_processing(context)

import os
import logging
from telegram.ext import ContextTypes
from telegram.error import Forbidden
from datetime import datetime

from ..utils import db
from ..utils.media_handler import process_media_buffers

logger = logging.getLogger(__name__)
APPROVAL_CHANNEL_ID = os.getenv("APPROVAL_CHANNEL_ID")
INACTIVITY_DAYS = 7
MIN_MEDIA_FOR_ACTIVE = 25 # Not implemented, but can be added to inactivity check

async def check_inactive_users(context: ContextTypes.DEFAULT_TYPE):
    """Job to find and deactivate users who have been inactive for too long."""
    logger.info("Running scheduled job: check_inactive_users")
    inactive_users = await db.find_inactive_users(days=INACTIVITY_DAYS)
    
    if not inactive_users:
        logger.info("No inactive users found.")
        return

    deactivated_count = 0
    for user in inactive_users:
        user_id = user['user_id']
        await db.update_user_status(user_id, 'inactive')
        deactivated_count += 1
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Hi, you have been marked as inactive due to no activity for {INACTIVITY_DAYS} days. "
                     "Please use /start to request re-activation."
            )
        except Forbidden:
            logger.warning(f"User {user_id} blocked bot, could not send inactivity notice.")
        except Exception as e:
            logger.error(f"Error sending inactivity notice to {user_id}: {e}")
    
    logger.info(f"Deactivated {deactivated_count} inactive users.")
    if deactivated_count > 0:
        await context.bot.send_message(
            chat_id=APPROVAL_CHANNEL_ID,
            text=f"🧹 **Automatic Cleanup**\n\nDeactivated {deactivated_count} users due to inactivity."
        )


async def send_service_message(context: ContextTypes.DEFAULT_TYPE):
    """Job to send the recurring service message to all active users."""
    service_message = await db.get_config_value('service_message')
    if not service_message:
        return

    logger.info("Running scheduled job: send_service_message")
    active_users = await db.get_all_active_users()
    
    for user in active_users:
        try:
            await context.bot.send_message(chat_id=user['user_id'], text=service_message)
        except Exception as e:
            logger.warning(f"Failed to send service message to {user['user_id']}: {e}")


async def _send_summary(context: ContextTypes.DEFAULT_TYPE, period: str):
    """Helper to generate and send daily/weekly summaries."""
    logger.info(f"Running scheduled job: send_{period}_summary")
    
    all_users = await db.get_all_users()
    total_messages = sum(u.get('total_messages_sent', 0) for u in all_users)

    # Sort users by media sent count in descending order
    sorted_users = sorted(all_users, key=lambda u: u.get('media_sent_count', 0), reverse=True)
    
    summary_text = f"🗓️ <b>{period.title()} Summary</b>\n\n"
    summary_text += f"<b>Total Messages Relayed:</b> {total_messages}\n\n"
    summary_text += "<b>🏆 Top 10 Most Active Users (by Media Sent):</b>\n"
    
    if not sorted_users:
        summary_text += "<i>No activity to report.</i>"
    else:
        for i, user in enumerate(sorted_users[:10]):
            summary_text += f"<b>{i+1}.</b> {user.get('full_name')} - {user.get('media_sent_count', 0)} media\n"
    
    await context.bot.send_message(chat_id=APPROVAL_CHANNEL_ID, text=summary_text)

async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    await _send_summary(context, 'daily')
    
async def send_weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    await _send_summary(context, 'weekly')
    # Optionally, reset stats weekly here if desired
    
async def process_media_buffers_job(context: ContextTypes.DEFAULT_TYPE):
    """Wrapper function to call the media buffer processor from the job queue."""
    await process_media_buffers(context)

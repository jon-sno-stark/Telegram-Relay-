import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime

from ..utils import db
from ..utils.decorators import user_is_registered

logger = logging.getLogger(__name__)
APPROVAL_CHANNEL_ID = os.getenv("APPROVAL_CHANNEL_ID", "-1002556330446")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command. Registers new users and guides existing ones."""
    user = update.effective_user
    user_doc = await db.get_user(user.id)

    if not user_doc:
        await db.add_user(user.id, user.full_name, user.username)
        # Re-fetch to ensure we have the doc
        user_doc = await db.get_user(user.id)
        
        keyboard = [[InlineKeyboardButton("➡️ Request Approval", callback_data=f"request_approval_{user.id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "👋 Welcome to\n🎀🍭𝕁𝕦𝕝𝕚𝕒'𝕤 ℙ𝕝𝕒𝕪𝕙𝕠𝕦𝕤𝕖🍭🎀\n\nTo join this bot chat , your account must be approved by an administrator. "
            "Please click the button below to send your request.",
            reply_markup=reply_markup
        )
        logger.info(f"New user {user.full_name} ({user.id}) started the bot.")
        return # Stop further processing for new users

    # Update user details if they have changed
    if user_doc.get('full_name') != user.full_name or user_doc.get('username') != user.username:
        await db.update_user_info(user.id, user.full_name, user.username)

    status = user_doc.get('status', 'pending')
    
    if status == 'active':
        await update.message.reply_text("✅ Welcome back! You are an active user. You can now send messages to others.")
    elif status == 'banned':
        await update.message.reply_text("🚫 You are banned from using this bot.")
    elif status == 'denied':
         await update.message.reply_text("❌ Your previous request was denied. You may contact an admin via /admin command for more information.")
    else: # 'pending' or 'inactive'
        keyboard = [[InlineKeyboardButton("➡️ Re-request Approval", callback_data=f"request_approval_{user.id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Your account is not currently active. Please request approval to join or re-join the bot chat.",
            reply_markup=reply_markup
        )

@user_is_registered
async def admin_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /admin command for users to send a message to the approval channel."""
    user = update.effective_user
    message_text = update.message.text.replace("/admin", "").strip()

    if not message_text:
        await update.message.reply_text("Please provide a message to send. Usage:\n`/admin Your question here`")
        return

    admin_message = (
        f"📩 <b>Message to Admins</b>\n\n"
        f"<b>From:</b> {user.full_name} (@{user.username or 'N/A'})\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n\n"
        f"<b>Message:</b>\n<i>{message_text}</i>"
    )

    try:
        await context.bot.send_message(chat_id=APPROVAL_CHANNEL_ID, text=admin_message)
        await update.message.reply_text("✅ Your message has been sent to the admins.")
    except Exception as e:
        logger.error(f"Failed to send user message to admin channel: {e}")
        await update.message.reply_text("❌ Sorry, there was an error sending your message. Please try again later.")

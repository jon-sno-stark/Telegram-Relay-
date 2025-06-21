import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from ..utils import db

logger = logging.getLogger(__name__)
APPROVAL_CHANNEL_ID = os.getenv("APPROVAL_CHANNEL_ID", "-1002556330446")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses callback data and routes to the correct function."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split('_')
    action = parts[0]
    
    if action == "request": # Callback is request_approval_{user_id}
        await handle_approval_request(update, context)
    elif action in ["approve", "deny"]: # approve_{user_id} or deny_{user_id}
        await handle_user_approval_decision(update, context)
    else:
        logger.warning(f"Unhandled callback query action: {action}")
        await query.edit_message_text("This button seems to be outdated or invalid.")
        
async def handle_approval_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles when a user clicks 'Request Approval'."""
    query = update.callback_query
    user = query.from_user
    
    # Notify admins in the approval channel
    admin_notification_text = (
        f"📢 <b>New User Approval Request</b>\n\n"
        f"<b>Name:</b> {user.full_name}\n"
        f"<b>Username:</b> @{user.username or 'N/A'}\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n\n"
        "An admin needs to review this request."
    )
    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
        InlineKeyboardButton("❌ Deny", callback_data=f"deny_{user.id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=APPROVAL_CHANNEL_ID,
            text=admin_notification_text,
            reply_markup=reply_markup
        )
        await query.edit_message_text(text="✅ Your request has been sent to the admins for review. You will be notified of their decision.")
        logger.info(f"User {user.id} sent an approval request to the admin channel.")
    except Exception as e:
        logger.error(f"Failed to send approval request for {user.id} to channel {APPROVAL_CHANNEL_ID}: {e}")
        await query.edit_message_text(text="❌ There was an error sending your request. Please contact an admin directly.")


async def handle_user_approval_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin decisions to approve or deny a user from the channel buttons."""
    query = update.callback_query
    admin = query.from_user
    
    is_admin = await db.is_admin(admin.id)
    if not is_admin:
        await query.answer("You are not authorized to perform this action.", show_alert=True)
        return

    parts = query.data.split('_')
    action = parts[0]
    user_id_to_manage = int(parts[1])

    user_to_manage = await db.get_user(user_id_to_manage)
    if not user_to_manage:
        await query.edit_message_text(f"{query.message.text_html}\n\n<i>Decision failed: User not found in database.</i>")
        return

    if action == "approve":
        await db.update_user_status(user_id_to_manage, "active")
        decision_text = f"✅ Approved by {admin.full_name}"
        user_notification = "🎉 Congratulations! Your request has been approved. You can now send messages to be relayed to other users."
    else: # deny
        await db.update_user_status(user_id_to_manage, "denied")
        decision_text = f"❌ Denied by {admin.full_name}"
        user_notification = "😔 We're sorry, your request to join the relay network has been denied."

    # Notify the user of the decision
    try:
        await context.bot.send_message(chat_id=user_id_to_manage, text=user_notification)
    except Exception as e:
        logger.warning(f"Failed to notify user {user_id_to_manage} of decision: {e}")
        decision_text += f"\n<i>(Could not notify user)</i>"

    # Update the message in the admin channel
    await query.edit_message_text(f"{query.message.text_html}\n\n<b>Decision:</b> {decision_text}")
    logger.info(f"Admin {admin.id} '{action}d' user {user_id_to_manage}")

import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden

from ..utils import db
from ..utils.decorators import admin_only
from ..utils.helpers import get_user_id_from_command

logger = logging.getLogger(__name__)

# --- User Management ---
@admin_only
async def promote_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Promotes a user to admin."""
    admin_user = update.effective_user
    user_id_to_promote = get_user_id_from_command(update.message)

    if not user_id_to_promote:
        await update.message.reply_text("Please provide a user ID. Usage: `/promote <user_id>`")
        return

    target_user = await db.get_user(user_id_to_promote)
    if not target_user:
        await update.message.reply_text("User not found in the database.")
        return

    if target_user.get('is_admin'):
        await update.message.reply_text(f"User <code>{user_id_to_promote}</code> is already an admin.")
        return

    await db.set_admin_status(user_id_to_promote, True)
    logger.info(f"Admin {admin_user.id} promoted {user_id_to_promote} to admin.")
    await update.message.reply_text(f"✅ User <code>{user_id_to_promote}</code> has been promoted to admin.")
    try:
        await context.bot.send_message(chat_id=user_id_to_promote, text="Congratulations! You have been promoted to an admin.")
    except Exception:
        pass

@admin_only
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bans a user from the bot."""
    admin_user = update.effective_user
    user_id_to_ban = get_user_id_from_command(update.message)
    if not user_id_to_ban:
        await update.message.reply_text("Please provide a user ID or reply to a user's message. Usage: `/ban <user_id>`")
        return
        
    if user_id_to_ban == admin_user.id:
        await update.message.reply_text("You cannot ban yourself.")
        return
        
    target_user = await db.get_user(user_id_to_ban)
    if not target_user:
        await update.message.reply_text("User not found.")
        return
        
    if target_user.get('status') == 'banned':
        await update.message.reply_text(f"User <code>{user_id_to_ban}</code> is already banned.")
        return

    await db.update_user_status(user_id_to_ban, 'banned')
    logger.info(f"Admin {admin_user.id} banned user {user_id_to_ban}.")
    await update.message.reply_text(f"🚫 User <code>{user_id_to_ban}</code> has been banned.")
    try:
        await context.bot.send_message(chat_id=user_id_to_ban, text="You have been banned from using this bot.")
    except Exception:
        pass

@admin_only
async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unbans a user."""
    admin_user = update.effective_user
    user_id_to_unban = get_user_id_from_command(update.message)
    if not user_id_to_unban:
        await update.message.reply_text("Please provide a user ID. Usage: `/unban <user_id>`")
        return

    target_user = await db.get_user(user_id_to_unban)
    if not target_user or target_user.get('status') != 'banned':
        await update.message.reply_text(f"User <code>{user_id_to_unban}</code> is not currently banned.")
        return

    await db.update_user_status(user_id_to_unban, 'inactive')
    logger.info(f"Admin {admin_user.id} unbanned user {user_id_to_unban}.")
    await update.message.reply_text(f"✅ User <code>{user_id_to_unban}</code> has been unbanned. They will need to request approval again.")
    try:
        await context.bot.send_message(chat_id=user_id_to_unban, text="You have been unbanned. You can use /start to request access again.")
    except Exception:
        pass
        
@admin_only
async def whitelist_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a user to the whitelist (immune to inactivity checks)."""
    user_id = get_user_id_from_command(update.message)
    if not user_id:
        await update.message.reply_text("Please provide a user ID. Usage: `/whitelist <user_id>`")
        return

    if not await db.get_user(user_id):
        await update.message.reply_text("User not found.")
        return
        
    await db.set_whitelist_status(user_id, True)
    await update.message.reply_text(f"✅ User <code>{user_id}</code> is now whitelisted and immune to inactivity removal.")

@admin_only
async def unwhitelist_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a user from the whitelist."""
    user_id = get_user_id_from_command(update.message)
    if not user_id:
        await update.message.reply_text("Please provide a user ID. Usage: `/unwhitelist <user_id>`")
        return
        
    if not await db.get_user(user_id):
        await update.message.reply_text("User not found.")
        return

    await db.set_whitelist_status(user_id, False)
    await update.message.reply_text(f"User <code>{user_id}</code> is no longer whitelisted.")

# --- Content Management ---
@admin_only
async def set_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the recurring service message."""
    message_text = update.message.text.replace('/service_message', '').strip()
    if not message_text:
        await db.set_config_value('service_message', None)
        await update.message.reply_text("Service message cleared.")
    else:
        await db.set_config_value('service_message', message_text)
        await update.message.reply_text("✅ Service message has been set. It will be sent to all active users every 3 hours.")

@admin_only
async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes a relayed message for all recipients."""
    if not update.message.reply_to_message:
        await update.message.reply_text("You must reply to a message to delete it.")
        return

    original_message_id = update.message.reply_to_message.message_id
    message_log = await db.get_relayed_message_info(original_message_id)

    if not message_log:
        await update.message.reply_text("This message was not found in the relay logs, or it was not sent by you through the bot.")
        return
        
    # Check if the admin is deleting their own message
    if message_log['sender_id'] != update.effective_user.id:
        await update.message.reply_text("You can only delete messages that you have sent.")
        return

    deleted_count = 0
    failed_count = 0
    relayed_to = message_log.get('relayed_to', {})

    for recipient_id, message_id in relayed_to.items():
        try:
            await context.bot.delete_message(chat_id=recipient_id, message_id=message_id)
            deleted_count += 1
            await asyncio.sleep(0.1) # Avoid rate limits
        except (BadRequest, Forbidden) as e:
            failed_count += 1
            logger.warning(f"Failed to delete message {message_id} for user {recipient_id}: {e}")

    await db.delete_relayed_message_log(original_message_id)
    await update.message.reply_text(f"Deletion complete.\nSuccessfully deleted for {deleted_count} users.\nFailed for {failed_count} users.")

@admin_only
async def pin_message_globally(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pins a message in every active user's chat with the bot."""
    if not update.message.reply_to_message:
        await update.message.reply_text("Please reply to the message you want to pin globally.")
        return

    message_to_pin = update.message.reply_to_message
    active_users = await db.get_all_active_users()
    
    pinned_count = 0
    failed_count = 0

    await update.message.reply_text(f"Starting to pin message for {len(active_users)} active users. This may take a while...")

    for user in active_users:
        user_id = user['user_id']
        try:
            # First, send a copy of the message to the user
            sent_message = await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=message_to_pin.chat_id,
                message_id=message_to_pin.message_id
            )
            # Then, pin the newly sent message
            await context.bot.pin_chat_message(
                chat_id=user_id,
                message_id=sent_message.message_id,
                disable_notification=True
            )
            pinned_count += 1
            await asyncio.sleep(0.2) # Be gentle with the API
        except (Forbidden, BadRequest) as e:
            failed_count += 1
            logger.warning(f"Failed to pin message for user {user_id}: {e}")
            if isinstance(e, Forbidden):
                await db.update_user_status(user_id, 'inactive')
    
    await update.message.reply_text(f"Pinning complete.\nSuccessfully pinned for {pinned_count} users.\nFailed for {failed_count} users.")

# --- Stats and Info ---
@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows bot usage statistics."""
    all_users = await db.get_all_users()
    
    total_users = len(all_users)
    active_users = sum(1 for u in all_users if u.get('status') == 'active')
    banned_users = sum(1 for u in all_users if u.get('status') == 'banned')
    
    # Sort users by media sent count in descending order
    sorted_users = sorted(all_users, key=lambda u: u.get('media_sent_count', 0), reverse=True)

    stats_message = (
        f"📊 <b>Bot Statistics</b> 📊\n\n"
        f"<b>Total Users:</b> {total_users}\n"
        f"<b>Active Users:</b> {active_users}\n"
        f"<b>Banned Users:</b> {banned_users}\n\n"
        "<b>User Activity (Top 20 by Media Sent):</b>\n"
        "-----------------------------------\n"
    )
    
    for i, user in enumerate(sorted_users[:20]):
        stats_message += (
            f"<b>{i+1}.</b> {user.get('full_name', 'N/A')} (@{user.get('username', 'N/A')})\n"
            f"   - <b>ID:</b> <code>{user['user_id']}</code>\n"
            f"   - <b>Media Sent:</b> {user.get('media_sent_count', 0)}\n"
            f"   - <b>Total Msgs:</b> {user.get('total_messages_sent', 0)}\n\n"
        )
    
    await update.message.reply_text(stats_message)

@admin_only
async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gets detailed information about a specific user."""
    user_id = get_user_id_from_command(update.message)
    if not user_id:
        await update.message.reply_text("Please provide a user ID. Usage: `/userinfo <user_id>`")
        return

    user_data = await db.get_user(user_id)
    if not user_data:
        await update.message.reply_text("User not found in the database.")
        return
        
    status_emoji = {
        'active': '✅',
        'inactive': '⚪️',
        'banned': '🚫',
        'pending': '⏳',
        'denied': '❌'
    }

    info_text = (
        f"👤 <b>User Information</b> 👤\n\n"
        f"<b>Name:</b> {user_data.get('full_name', 'N/A')}\n"
        f"<b>Username:</b> @{user_data.get('username', 'N/A')}\n"
        f"<b>User ID:</b> <code>{user_data['user_id']}</code>\n\n"
        f"<b>Status:</b> {status_emoji.get(user_data.get('status'), '❓')} {user_data.get('status', 'Unknown').title()}\n"
        f"<b>Admin:</b> {'Yes' if user_data.get('is_admin') else 'No'}\n"
        f"<b>Whitelisted:</b> {'Yes' if user_data.get('is_whitelisted') else 'No'}\n\n"
        f"<b>Total Messages Sent:</b> {user_data.get('total_messages_sent', 0)}\n"
        f"<b>Media Messages Sent:</b> {user_data.get('media_sent_count', 0)}\n\n"
        f"<b>Join Date:</b> {user_data.get('join_date', 'N/A').strftime('%Y-%m-%d %H:%M') if user_data.get('join_date') else 'N/A'} UTC\n"
        f"<b>Last Active:</b> {user_data.get('last_active', 'N/A').strftime('%Y-%m-%d %H:%M') if user_data.get('last_active') else 'N/A'} UTC"
    )

    await update.message.reply_text(info_text)

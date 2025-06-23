import logging
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden

from ..utils import db
from ..utils.decorators import admin_only
from ..utils.helpers import get_user_id_from_command

logger = logging.getLogger(__name__)

@admin_only
async def promote_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_user = update.effective_user
    user_id_to_promote = await get_user_id_from_command(update.message)
    if not user_id_to_promote:
        await update.message.reply_text("Usage: `/promote <user_id>` or reply to a message.")
        return
    target_user = await db.get_user(user_id_to_promote)
    if not target_user:
        await update.message.reply_text("User not found.")
        return
    if target_user.get('is_admin'):
        await update.message.reply_text(f"User <code>{user_id_to_promote}</code> is already an admin.")
        return
    await db.set_admin_status(user_id_to_promote, True)
    logger.info(f"Admin {admin_user.id} promoted {user_id_to_promote}.")
    await update.message.reply_text(f"✅ User <code>{user_id_to_promote}</code> is now an admin.")
    try:
        await context.bot.send_message(chat_id=user_id_to_promote, text="You have been promoted to an admin.")
    except Exception: pass

@admin_only
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_user = update.effective_user
    user_id_to_ban = await get_user_id_from_command(update.message)
    if not user_id_to_ban:
        await update.message.reply_text("Usage: `/ban <user_id>` or reply to a user's message.")
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
    logger.info(f"Admin {admin_user.id} banned {user_id_to_ban}.")
    await update.message.reply_text(f"🚫 User <code>{user_id_to_ban}</code> has been banned.")
    try:
        await context.bot.send_message(chat_id=user_id_to_ban, text="You have been banned.")
    except Exception: pass

@admin_only
async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id_to_unban = await get_user_id_from_command(update.message)
    if not user_id_to_unban:
        await update.message.reply_text("Usage: `/unban <user_id>`")
        return
    target_user = await db.get_user(user_id_to_unban)
    if not target_user or target_user.get('status') != 'banned':
        await update.message.reply_text(f"User <code>{user_id_to_unban}</code> is not banned.")
        return
    await db.update_user_status(user_id_to_unban, 'inactive')
    logger.info(f"Admin {update.effective_user.id} unbanned {user_id_to_unban}.")
    await update.message.reply_text(f"✅ User <code>{user_id_to_unban}</code> unbanned.")
    try:
        await context.bot.send_message(chat_id=user_id_to_unban, text="You have been unbanned. Use /start to rejoin.")
    except Exception: pass
        
@admin_only
async def whitelist_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = await get_user_id_from_command(update.message)
    if not user_id:
        await update.message.reply_text("Usage: `/whitelist <user_id>`")
        return
    if not await db.get_user(user_id):
        await update.message.reply_text("User not found.")
        return
    await db.set_whitelist_status(user_id, True)
    await update.message.reply_text(f"✅ User <code>{user_id}</code> is whitelisted.")

@admin_only
async def unwhitelist_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = await get_user_id_from_command(update.message)
    if not user_id:
        await update.message.reply_text("Usage: `/unwhitelist <user_id>`")
        return
    if not await db.get_user(user_id):
        await update.message.reply_text("User not found.")
        return
    await db.set_whitelist_status(user_id, False)
    await update.message.reply_text(f"User <code>{user_id}</code> is no longer whitelisted.")

@admin_only
async def set_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.replace('/service_message', '').strip()
    if not message_text:
        await db.set_config_value('service_message', None)
        await update.message.reply_text("Service message cleared.")
    else:
        await db.set_config_value('service_message', message_text)
        await update.message.reply_text("Service message set.")

@admin_only
async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("You must reply to a message to delete it.")
        return
        
    replied_to_id = update.message.reply_to_message.message_id
    
    # Check if the admin is deleting a message in their own chat that they sent
    message_log = await db.get_relayed_message_info_by_original_id(replied_to_id)
    
    # If not found, check if they are replying to a relayed message from someone else
    if not message_log:
        message_log = await db.get_relayed_message_info_by_relayed_id(update.effective_chat.id, replied_to_id)

    if not message_log:
        await update.message.reply_text("Message not found in relay logs.")
        return

    deleted_count, failed_count = 0, 0
    # Also delete the sender's original message
    all_to_delete = {**message_log.get('relayed_to', {}), message_log['sender_id']: message_log['original_message_id']}

    for chat_id, message_id in all_to_delete.items():
        try:
            await context.bot.delete_message(chat_id=int(chat_id), message_id=message_id)
            deleted_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed_count += 1
            
    await db.delete_relayed_message_log(message_log['original_message_id'])
    await update.message.reply_text(f"Delete complete. Success: {deleted_count}, Failed: {failed_count}.")

@admin_only
async def pin_message_globally(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to pin it.")
        return
    message_to_pin = update.message.reply_to_message
    active_users = await db.get_all_active_users()
    pinned_count, failed_count = 0, 0
    await update.message.reply_text(f"Pinning message for {len(active_users)} users...")
    for user in active_users:
        try:
            sent_msg = await context.bot.copy_message(
                chat_id=user['user_id'], from_chat_id=message_to_pin.chat_id, message_id=message_to_pin.message_id
            )
            await context.bot.pin_chat_message(
                chat_id=user['user_id'], message_id=sent_msg.message_id, disable_notification=True
            )
            pinned_count += 1
            await asyncio.sleep(0.1)
        except Forbidden:
            failed_count += 1
            await db.update_user_status(user['user_id'], 'inactive')
        except Exception:
            failed_count += 1
    await update.message.reply_text(f"Pinning complete. Pinned: {pinned_count}, Failed: {failed_count}.")

@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_users = await db.get_all_users()
    total = len(all_users)
    active = sum(1 for u in all_users if u.get('status') == 'active')
    banned = sum(1 for u in all_users if u.get('status') == 'banned')
    sorted_users = sorted(all_users, key=lambda u: u.get('media_sent_count', 0), reverse=True)
    stats_msg = (
        f"📊 <b>Bot Statistics</b>\n"
        f"Total: {total}, Active: {active}, Banned: {banned}\n\n"
        "<b>Top 20 by Media Sent:</b>\n"
    )
    if not sorted_users:
        stats_msg += "<i>No activity yet.</i>"
    else:
        for i, user in enumerate(sorted_users[:20]):
            stats_msg += (
                f"<b>{i+1}.</b> {user.get('full_name')} (@{user.get('username')})\n"
                f"   ID: <code>{user['user_id']}</code>, Media: {user.get('media_sent_count', 0)}\n"
            )
    await update.message.reply_text(stats_msg)

@admin_only
async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = await get_user_id_from_command(update.message)
    if not user_id:
        await update.message.reply_text("Usage: `/userinfo <user_id>` or reply to a message.")
        return
    user_data = await db.get_user(user_id)
    if not user_data:
        await update.message.reply_text("User not found.")
        return
    status_emoji = {'active': '✅','inactive': '⚪️','banned': '🚫','pending': '⏳','denied': '❌'}
    info_text = (
        f"👤 <b>User Info</b>\n"
        f"Name: {user_data.get('full_name')}\n"
        f"Username: @{user_data.get('username')}\n"
        f"ID: <code>{user_data['user_id']}</code>\n"
        f"Status: {status_emoji.get(user_data.get('status'), '❓')} {user_data.get('status', 'N/A').title()}\n"
        f"Admin: {'Yes' if user_data.get('is_admin') else 'No'}\n"
        f"Whitelisted: {'Yes' if user_data.get('is_whitelisted') else 'No'}\n"
        f"Total Msgs: {user_data.get('total_messages_sent', 0)}\n"
        f"Media Msgs: {user_data.get('media_sent_count', 0)}\n"
        f"Joined: {user_data.get('join_date', 'N/A').strftime('%Y-%m-%d') if user_data.get('join_date') else 'N/A'}\n"
        f"Last Active: {user_data.get('last_active', 'N/A').strftime('%Y-%m-%d %H:%M') if user_data.get('last_active') else 'N/A'} UTC"
    )
    await update.message.reply_text(info_text)

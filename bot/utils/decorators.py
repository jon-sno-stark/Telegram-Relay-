import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

from . import db

logger = logging.getLogger(__name__)

def admin_only(func):
    """Decorator to restrict access to admins only."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if await db.is_admin(user_id):
            return await func(update, context, *args, **kwargs)
        else:
            logger.warning(f"Unauthorized access denied for {user_id} to admin command '{func.__name__}'.")
            await update.message.reply_text("⛔️ Sorry, this is an admin-only command.")
            return
    return wrapped

def user_is_registered(func):
    """Decorator to ensure a user exists in the database."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = await db.get_user(update.effective_user.id)
        if user:
            return await func(update, context, *args, **kwargs)
        else:
            await update.message.reply_text("You need to /start the bot first to register.")
            return
    return wrapped

def user_is_active(func):
    """Decorator to check if a user's status is 'active' before processing messages."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = await db.get_user(update.effective_user.id)
        if user and user.get('status') == 'active':
            return await func(update, context, *args, **kwargs)
        elif user and user.get('status') == 'banned':
            await update.message.reply_text("🚫 You are banned and cannot send messages.")
        else:
            await update.message.reply_text("⚠️⚠️ Your account is not active. Please use /start to request access and send atleast 10 media if you don't want to get removed.")
        return
    return wrapped

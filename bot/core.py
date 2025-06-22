import os
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    Defaults,
)
from telegram.constants import ParseMode

from .handlers import user_handlers, admin_handlers, callback_handlers
from .jobs import scheduled_jobs
from .utils.media_handler import media_message_handler

def create_bot_application(bot_token: str) -> Application:
    """Builds the bot application and registers all handlers and jobs."""
    
    # Use the Defaults class as required by the library
    defaults = Defaults(
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    application = ApplicationBuilder().token(bot_token).defaults(defaults).build()
    
    # --- Register Handlers ---
    application.add_handler(CommandHandler("start", user_handlers.start, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("admin", user_handlers.admin_contact, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("promote", admin_handlers.promote_admin, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("stats", admin_handlers.stats, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("ban", admin_handlers.ban_user, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("unban", admin_handlers.unban_user, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("whitelist", admin_handlers.whitelist_user, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("unwhitelist", admin_handlers.unwhitelist_user, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("service_message", admin_handlers.set_service_message, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("pin", admin_handlers.pin_message_globally, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("userinfo", admin_handlers.user_info, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler(
        "delete",
        admin_handlers.delete_message,
        filters=filters.REPLY & filters.ChatType.PRIVATE
    ))
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (~filters.COMMAND),
        media_message_handler
    ))
    application.add_handler(CallbackQueryHandler(callback_handlers.handle_callback))
    
    # --- Schedule Background Jobs ---
    job_queue = application.job_queue
    job_queue.run_repeating(scheduled_jobs.check_inactive_users, interval=3600, first=60)
    job_queue.run_repeating(scheduled_jobs.send_service_message, interval=3600 * 3, first=120)
    job_queue.run_repeating(scheduled_jobs.send_daily_summary, interval=3600 * 24, first=180)
    job_queue.run_repeating(scheduled_jobs.send_weekly_summary, interval=3600 * 24 * 7, first=300)
    job_queue.run_repeating(scheduled_jobs.process_media_buffers_job, interval=20, first=20)

    return application

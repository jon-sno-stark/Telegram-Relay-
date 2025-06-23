import os
import logging
import asyncio
from threading import Thread

from flask import Flask
from telegram.ext import Application
from dotenv import load_dotenv

from bot.core import create_bot_application
from bot.utils.db import init_database

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Flask App for Health Checks (for Koyeb) ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    """Provides a simple health check endpoint for deployment platforms."""
    return "Relay bot is running.", 200

# --- Main Bot Logic ---
async def main():
    """Initializes and runs the Telegram bot."""
    logger.info("Starting bot initialization...")
    
    load_dotenv()

    # --- Configuration Validation ---
    bot_token = os.getenv("BOT_TOKEN", "7790576990:AAFYKKnRqjFxpPhCjHqzmoXrPSuJNT9yrDA")
    mongo_uri = os.getenv("MONGO_URI", "mongodb+srv://bhahubalee:jzlnJ5LQSK6fEQm6@cluster0.di8ob0a.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
    db_name = os.getenv("MONGO_DB_NAME", "telegram_relay_a")
    approval_channel_id = os.getenv("APPROVAL_CHANNEL_ID", "-1002556330446")
    admin_ids_str = os.getenv("INITIAL_ADMIN_IDS", "7959714788,7895505501,7572984675")

    required_vars = {
        "BOT_TOKEN": bot_token,
        "MONGO_URI": mongo_uri,
        "MONGO_DB_NAME": db_name,
        "APPROVAL_CHANNEL_ID": approval_channel_id,
        "INITIAL_ADMIN_IDS": admin_ids_str,
    }

    missing_vars = [key for key, value in required_vars.items() if not value]
    if missing_vars:
        logger.critical(f"FATAL: Missing critical environment variables: {', '.join(missing_vars)}")
        return

    # --- Database Initialization ---
    try:
        logger.info("Initializing database connection...")
        await init_database(mongo_uri, db_name, admin_ids_str)
        logger.info("Database connection successful.")
    except Exception as e:
        logger.critical(f"FATAL: Could not connect to MongoDB. Error: {e}", exc_info=True)
        return

    # --- Bot Application Setup ---
    logger.info("Creating bot application...")
    application = create_bot_application(bot_token)
    
    logger.info("Bot setup complete. Starting polling...")
    
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=['message', 'callback_query'])
        logger.info("Bot is now running and polling for updates.")
        # This will keep the application running indefinitely
        await asyncio.Event().wait()
    except Exception as e:
        logger.critical(f"An error occurred while running the bot: {e}", exc_info=True)
    finally:
        await application.updater.stop()
        await application.stop()
        logger.info("Bot has been stopped.")


def run_flask():
    """Runs the Flask app in a separate thread."""
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    # Run Flask in a background thread for health checks
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Run the main async bot function
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        logger.critical(f"Unhandled exception in main: {e}", exc_info=True)

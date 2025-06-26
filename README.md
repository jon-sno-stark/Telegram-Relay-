# Telegram Relay Bot for Koyeb
This is a powerful and scalable Telegram relay bot designed to be deployed on Koyeb's free tier. It facilitates communication between approved users, ensuring efficient message delivery even with high media traffic. The bot uses MongoDB to persist all user data, messages, and settings, so no information is lost on restart.

# Key Features
Advanced Message Relaying:

Relays text, photos, videos, GIFs, stickers, files, audio, and voice messages.

Text messages include the sender's name.

Media messages (photos, videos, documents) are grouped into albums of 10 to avoid spam and hitting API limits.

An efficient batch-sending mechanism delivers messages to users in chunks, optimizing for large user bases.

Replies are relayed with context, showing the original message that was replied to.

User Management & Security:

Approval System: New users must request approval via an interactive button. Admins approve or deny requests in a dedicated channel.

# Admin Controls:

/promote <user_id>: Promote a user to admin.

/ban <user_id>: Ban a user, stopping them from receiving or sending messages.

/unban <user_id>: Unban a user.

/whitelist <user_id>: Exempt a user from inactivity checks.

/unwhitelist <user_id>: Remove a user from the whitelist.

Inactive User Cleaning: Automatically removes users who are inactive for 7 days (haven't sent at least 25 media messages). Whitelisted users are exempt.

# Content & Administration:

/delete: Admins can delete any relayed message for all recipients by replying to it.

/pin: Admins can pin a message in every user's private chat with the bot.

/service_message <message>: Set a recurring message to be sent to all active users every 3 hours.

/admin <message>: Allows any user to send a message directly to the admin approval channel.

Monitoring & Stats:

/stats: View a list of all users, their status, and total sent media message count in descending order.

/userinfo <user_id>: Get detailed information about a specific user (status, message count, last active).

Daily/Weekly Summaries: Automatically sends a summary to the admin channel with total relayed messages and a top 10 list of active users.

# Deployment & Persistence:

Ready for deployment on Koyeb using a Procfile.

Includes a simple Flask web server for health checks required by Koyeb.

MongoDB Integration: All user data, message logs, whitelists, bans, and admin lists are stored in a MongoDB database, ensuring data persistence.

# Setup & Deployment
Prerequisites
A Telegram Bot Token from BotFather.

A MongoDB Atlas account and a connection string.

A Koyeb account.

Configuration (Environment Variables)
Create a .env file or set these environment variables directly in the Koyeb service configuration:

BOT_TOKEN=your_telegram_bot_token
MONGO_URI=your_mongodb_connection_string
DB_NAME=telegram_relay_bot_db
ADMIN_IDS=initial_admin_user_id_1,initial_admin_user_id_2
APPROVAL_CHANNEL_ID=your_telegram_channel_id_for_approvals

BOT_TOKEN: Your Telegram bot's API token.

MONGO_URI: Your MongoDB connection string.

DB_NAME: The name for your database.

ADMIN_IDS: A comma-separated list of Telegram user IDs for the initial administrators.

APPROVAL_CHANNEL_ID: The unique ID of the private channel where admins will manage approval requests. The bot must be an administrator in this channel.

# Deployment to Koyeb
Push to GitHub: Create a new GitHub repository and push all the files (main.py, bot.py, database.py, utils.py, Procfile, requirements.txt, README.md).

Create Koyeb App:

On the Koyeb dashboard, click "Create App".

Choose "GitHub" as the deployment method and select your repository.

Under "Environment Variables", add the secrets listed above.

Koyeb will automatically detect the Procfile and use gunicorn to run the web service.

Deploy the service.

The bot will start, and Koyeb will use the running Flask server for health checks to keep your service online.

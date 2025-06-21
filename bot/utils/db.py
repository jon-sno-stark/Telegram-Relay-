import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Global client and db objects, initialized in app.py
client: AsyncIOMotorClient = None
db = None

async def init_database(mongo_uri: str, db_name: str, admin_ids_str: str):
    """Initializes the database connection and collections."""
    global client, db
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    logger.info(f"Connected to MongoDB. Database: '{db_name}'")
    
    # --- Create Indexes for performance ---
    await db.users.create_index("user_id", unique=True)
    await db.users.create_index("status")
    await db.messages.create_index("original_message_id")
    await db.messages.create_index("sender_id")
    
    # --- Setup Initial Admins ---
    try:
        admin_ids = [int(admin_id.strip()) for admin_id in admin_ids_str.split(',')]
        for admin_id in admin_ids:
            # Upsert ensures the user exists and sets them as an admin
            await db.users.update_one(
                {'user_id': admin_id},
                {'$set': {
                    'is_admin': True, 
                    'is_whitelisted': True, 
                    'status': 'active'
                },
                 '$setOnInsert': {
                    'full_name': 'Initial Admin',
                    'username': 'N/A',
                    'join_date': datetime.utcnow(),
                    'last_active': datetime.utcnow(),
                    'media_sent_count': 0,
                    'total_messages_sent': 0
                 }},
                upsert=True
            )
        logger.info(f"Initial admins processed: {admin_ids}")
    except ValueError:
        logger.error("INITIAL_ADMIN_IDS contains non-integer values. Please check your .env file.")

# --- User Functions ---
async def add_user(user_id: int, full_name: str, username: str):
    await db.users.insert_one({
        'user_id': user_id,
        'full_name': full_name,
        'username': username,
        'status': 'pending', # Users must be approved
        'is_admin': False,
        'is_whitelisted': False,
        'join_date': datetime.utcnow(),
        'last_active': datetime.utcnow(),
        'media_sent_count': 0,
        'total_messages_sent': 0,
    })

async def get_user(user_id: int):
    return await db.users.find_one({'user_id': user_id})

async def get_all_users():
    return await db.users.find({}).to_list(length=None)

async def get_all_active_users():
    return await db.users.find({'status': 'active'}).to_list(length=None)

async def update_user_status(user_id: int, status: str):
    await db.users.update_one({'user_id': user_id}, {'$set': {'status': status}})
    
async def update_user_info(user_id: int, full_name: str, username: str):
    await db.users.update_one(
        {'user_id': user_id}, 
        {'$set': {'full_name': full_name, 'username': username}}
    )

async def set_admin_status(user_id: int, is_admin: bool):
    await db.users.update_one({'user_id': user_id}, {'$set': {'is_admin': is_admin}})

async def set_whitelist_status(user_id: int, is_whitelisted: bool):
    await db.users.update_one({'user_id': user_id}, {'$set': {'is_whitelisted': is_whitelisted}})

async def is_admin(user_id: int) -> bool:
    user = await get_user(user_id)
    return user.get('is_admin', False) if user else False

async def update_last_active(user_id: int):
    await db.users.update_one({'user_id': user_id}, {'$set': {'last_active': datetime.utcnow()}})

async def find_inactive_users(days: int):
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    query = {
        'last_active': {'$lt': cutoff_date},
        'is_whitelisted': False,
        'status': 'active'
    }
    return await db.users.find(query).to_list(length=None)

async def increment_user_stat(user_id: int, media_count: int = 0, message_count: int = 0):
    update_doc = {'$inc': {}}
    if media_count > 0:
        update_doc['$inc']['media_sent_count'] = media_count
    if message_count > 0:
        update_doc['$inc']['total_messages_sent'] = message_count
    
    if update_doc['$inc']:
        await db.users.update_one({'user_id': user_id}, update_doc)

# --- Message Logging ---
async def log_relayed_message(original_msg_id: int, sender_id: int, relayed_to: dict):
    await db.messages.insert_one({
        'original_message_id': original_msg_id,
        'sender_id': sender_id,
        'relayed_to': relayed_to, # Dict of {recipient_id: sent_message_id}
        'timestamp': datetime.utcnow()
    })

async def get_relayed_message_info(original_msg_id: int):
    return await db.messages.find_one({'original_message_id': original_msg_id})

async def delete_relayed_message_log(original_msg_id: int):
    await db.messages.delete_one({'original_message_id': original_msg_id})

# --- Config Functions ---
async def set_config_value(key: str, value):
    await db.config.update_one({'_id': key}, {'$set': {'value': value}}, upsert=True)

async def get_config_value(key: str):
    doc = await db.config.find_one({'_id': key})
    return doc.get('value') if doc else None
  

import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

client: AsyncIOMotorClient = None
db = None

async def init_database(mongo_uri: str, db_name: str, admin_ids_str: str):
    global client, db
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    logger.info(f"Connected to MongoDB: '{db_name}'")
    await db.users.create_index("user_id", unique=True)
    await db.messages.create_index("original_message_id", unique=True)
    await db.messages.create_index("relayed_to_flat")
    try:
        admin_ids = [int(i.strip()) for i in admin_ids_str.split(',')]
        for admin_id in admin_ids:
            await db.users.update_one(
                {'user_id': admin_id},
                {'$set': {'is_admin': True, 'is_whitelisted': True, 'status': 'active'},
                 '$setOnInsert': {
                    'full_name': 'Initial Admin', 'username': 'N/A',
                    'join_date': datetime.utcnow(), 'last_active': datetime.utcnow(),
                    'media_sent_count': 0, 'total_messages_sent': 0
                 }},
                upsert=True
            )
        logger.info(f"Initial admins processed: {admin_ids}")
    except ValueError:
        logger.error("INITIAL_ADMIN_IDS is invalid.")

async def add_user(user_id: int, full_name: str, username: str):
    await db.users.insert_one({
        'user_id': user_id, 'full_name': full_name, 'username': username,
        'status': 'pending', 'is_admin': False, 'is_whitelisted': False,
        'join_date': datetime.utcnow(), 'last_active': datetime.utcnow(),
        'media_sent_count': 0, 'total_messages_sent': 0,
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
    await db.users.update_one({'user_id': user_id}, {'$set': {'full_name': full_name, 'username': username}})

async def set_admin_status(user_id: int, is_admin: bool):
    await db.users.update_one({'user_id': user_id}, {'$set': {'is_admin': is_admin}})

async def set_whitelist_status(user_id: int, is_whitelisted: bool):
    await db.users.update_one({'user_id': user_id}, {'$set': {'is_whitelisted': is_whitelisted}})

async def is_admin(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user and user.get('is_admin'))

async def update_last_active(user_id: int):
    await db.users.update_one({'user_id': user_id}, {'$set': {'last_active': datetime.utcnow()}})

async def find_inactive_users(days: int):
    cutoff = datetime.utcnow() - timedelta(days=days)
    return await db.users.find({'last_active': {'$lt': cutoff}, 'is_whitelisted': False, 'status': 'active'}).to_list(length=None)

async def increment_user_stat(user_id: int, media_count: int = 0, message_count: int = 0):
    inc_doc = {}
    if media_count > 0: inc_doc['media_sent_count'] = media_count
    if message_count > 0: inc_doc['total_messages_sent'] = message_count
    if inc_doc: await db.users.update_one({'user_id': user_id}, {'$inc': inc_doc})

async def log_relayed_message(original_msg_id: int, sender_id: int, relayed_to: dict):
    relayed_to_flat = [f"{chat_id}_{msg_id}" for chat_id, msg_id in relayed_to.items()]
    await db.messages.update_one(
        {'original_message_id': original_msg_id},
        {
            '$set': {'sender_id': sender_id, 'timestamp': datetime.utcnow()},
            '$addToSet': {'relayed_to_flat': {'$each': relayed_to_flat}},
            '$inc': {f'relayed_to.{k}': v for k, v in relayed_to.items()}
        },
        upsert=True
    )
    
async def get_relayed_message_info_by_original_id(original_msg_id: int):
    return await db.messages.find_one({'original_message_id': original_msg_id})

async def get_relayed_message_info_by_relayed_id(chat_id: int, message_id: int):
    return await db.messages.find_one({'relayed_to_flat': f"{chat_id}_{message_id}"})

async def delete_relayed_message_log(original_msg_id: int):
    await db.messages.delete_one({'original_message_id': original_msg_id})

async def set_config_value(key: str, value):
    await db.config.update_one({'_id': key}, {'$set': {'value': value}}, upsert=True)

async def get_config_value(key: str):
    doc = await db.config.find_one({'_id': key})
    return doc.get('value') if doc else None

    

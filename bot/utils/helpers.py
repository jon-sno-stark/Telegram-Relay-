# =================================================================
# File: bot/utils/helpers.py
# Description: Helper functions used across the application. (Corrected)
# =================================================================
from telegram import Message
from typing import Union
from . import db

async def get_user_id_from_command(message: Message) -> Union[int, None]:
    """
    Parses a user ID from a command.
    Checks for arguments first, then for a replied-to message by looking up the DB.
    """
    # Check for arguments first, as it's the most explicit.
    parts = message.text.split()
    if len(parts) > 1 and parts[1].isdigit():
        return int(parts[1])
            
    # Then, check if the admin is replying to a message from the bot
    # that might contain a user ID.
    if message.reply_to_message:
        replied_message_id = message.reply_to_message.message_id
        # Find the message log based on the replied-to message in the admin's chat
        message_log = await db.get_relayed_message_info_by_relayed_id(
            chat_id=message.chat_id, 
            message_id=replied_message_id
        )
        if message_log:
            return message_log.get('sender_id')

        # Fallback for old messages that might not have the new index
        text_to_check = message.reply_to_message.text or message.reply_to_message.caption
        if text_to_check:
            for line in text_to_check.split('\n'):
                if 'ID:' in line:
                    try:
                        potential_id_str = ''.join(filter(str.isdigit, line.split('ID:')[1]))
                        if potential_id_str:
                            return int(potential_id_str)
                    except (ValueError, IndexError):
                        continue
    
    return None

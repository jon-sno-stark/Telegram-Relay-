# =================================================================
# File: bot/utils/helpers.py
# Description: Helper functions used across the application.
# (This file is corrected for Python version compatibility)
# =================================================================
from telegram import Message
from typing import Union

def get_user_id_from_command(message: Message) -> Union[int, None]:
    """
    Parses a user ID from a command.
    Checks for a replied-to message first, then checks command arguments.
    """
    # Check for arguments first, as it's the most explicit.
    parts = message.text.split()
    if len(parts) > 1 and parts[1].isdigit():
        return int(parts[1])
            
    # Then, check if the admin is replying to a message from the bot
    # that might contain a user ID.
    if message.reply_to_message:
        text_to_check = message.reply_to_message.text or message.reply_to_message.caption
        if text_to_check:
            for line in text_to_check.split('\n'):
                # Look for lines formatted like "ID: 12345" or "User ID: 12345"
                if 'ID:' in line:
                    try:
                        # Extract the numeric part of the string
                        potential_id_str = ''.join(filter(str.isdigit, line.split('ID:')[1]))
                        if potential_id_str:
                            return int(potential_id_str)
                    except (ValueError, IndexError):
                        continue # Move to the next line if parsing fails
    
    # If no ID is found, return None
    return None

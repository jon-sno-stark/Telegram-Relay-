from telegram import Message

def get_user_id_from_command(message: Message) -> int | None:
    """
    Parses a user ID from a command.
    Checks for a replied-to message first, then checks the command arguments.
    """
    user_id = None
    # 1. Check for reply
    if message.reply_to_message:
        # Check if the replied message was forwarded from a user
        if message.reply_to_message.forward_from:
            user_id = message.reply_to_message.forward_from.id
        else:
            # Check for a logged message in our DB based on the replied-to message ID
            # This is complex and might not be needed for ban/promote, but useful for context.
            # For now, we assume a direct reply to a user's message in the bot chat is not possible for admins.
            pass
    
    # 2. Check for command arguments
    if not user_id:
        parts = message.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            user_id = int(parts[1])
            
    return user_id

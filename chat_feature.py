import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, MessageHandler, filters
from telegram import Bot

message_id_map = {}

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize the database connection
conn = sqlite3.connect('dating_bot.db')
cursor = conn.cursor()

async def handle_chat_message(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id

    if context.user_data.get('creating_profile'):
        return

    cursor.execute('SELECT chat_partner, name FROM users WHERE user_id = ? AND is_matched = 1', (user_id,))
    result = cursor.fetchone()

    if not result or not result[0]:
        keyboard = [
            [InlineKeyboardButton("Find Match 🚀", callback_data='findmatch')],
            [InlineKeyboardButton("Start  ✮⋆˙", callback_data='start')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("You are not currently matched with anyone. What would you like to do?", reply_markup=reply_markup)
        return

    chat_partner, sender_name = result
    cursor.execute('SELECT name FROM users WHERE user_id = ?', (chat_partner,))
    receiver_name_result = cursor.fetchone()
    receiver_name = receiver_name_result[0] if receiver_name_result else "Unknown"

    cursor.execute('SELECT chat_partner FROM users WHERE user_id = ? AND is_matched = 1', (user_id,))
    result = cursor.fetchone()


    chat_partner = result[0]

    try:
        forward_header = f"{sender_name} ({user_id}) sent message to {receiver_name} ({chat_partner}): "

        if update.message.reply_to_message:
            original_message_id = update.message.reply_to_message.message_id
            partner_message_id = context.bot_data.get(f"{chat_partner}_{original_message_id}")

            if partner_message_id:
                sent_message = await context.bot.send_message(
                    chat_id=chat_partner,
                    text=update.message.text,
                    reply_to_message_id=partner_message_id
                )
            else:
                sent_message = await context.bot.send_message(chat_id=chat_partner, text=update.message.text)
        elif update.message.text:
            sent_message = await context.bot.send_message(chat_id=chat_partner, text=update.message.text)
        elif update.message.photo:
            sent_message = await context.bot.send_photo(chat_id=chat_partner, photo=update.message.photo[-1].file_id)
        elif update.message.animation:
            sent_message = await context.bot.send_animation(chat_id=chat_partner, animation=update.message.animation.file_id)
        elif update.message.voice:
            sent_message = await context.bot.send_voice(chat_id=chat_partner, voice=update.message.voice.file_id)
        elif update.message.video:
            sent_message = await context.bot.send_video(chat_id=chat_partner, video=update.message.video.file_id)
        elif update.message.sticker:
            sent_message = await context.bot.send_sticker(chat_id=chat_partner, sticker=update.message.sticker.file_id)
        else:
            await update.message.reply_text("This type of message is not supported.")
            return

        # Store the mapping of message IDs
        context.bot_data[f"{user_id}_{update.message.message_id}"] = sent_message.message_id
        context.bot_data[f"{chat_partner}_{sent_message.message_id}"] = update.message.message_id

        logger.info(f"User {user_id} sent a message to {chat_partner}")

    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        await update.message.reply_text("An error occurred while sending your message. Please try again.")
        return

def setup_chat_handlers(application):
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(Next|Stop)$") |
        filters.PHOTO |
        filters.ANIMATION |
        filters.VOICE |
        filters.VIDEO |
        filters.Sticker.ALL,
        handle_chat_message
    ))

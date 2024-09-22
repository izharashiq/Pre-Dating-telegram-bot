import os, logging, pytz, sqlite3, re, itertools, string, random
from datetime import datetime, timedelta, timezone
from telegram import Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove, BotCommand
from telegram.ext import ApplicationBuilder, CallbackContext, CommandHandler, MessageHandler, filters
from telegram.ext import Application,  ConversationHandler, CallbackQueryHandler, Defaults, ApplicationHandlerStop
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from chat_feature import handle_chat_message, setup_chat_handlers
from telegram.error import TelegramError, BadRequest
import asyncio

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

CHANNEL_ID = '@pre_dating'
ID = [ID] 


# Initialize the database connection
conn = sqlite3.connect('dating_bot.db')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    age INTEGER,
    gender TEXT,
    interests TEXT,
    photo TEXT,
    profile_status TEXT,
    chat_partner INTEGER,
    is_matched INTEGER DEFAULT 0,
    is_banned INTEGER DEFAULT 0,
    ban_until TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    referral_code TEXT,
    referral_count INTEGER DEFAULT 0,
    is_verified INTEGER,
    country TEXT
);
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS blocked_matches (
    user_id INTEGER,
    blocked_user_id INTEGER,
    PRIMARY KEY (user_id, blocked_user_id)
);
''')

conn.commit()
def ensure_connection():
    global conn
    global cursor
    try:
        cursor.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        conn = sqlite3.connect('dating_bot.db')
        cursor = conn.cursor()

# Define conversation states
NAME, AGE, GENDER, INTERESTS, COUNTRY, PHOTO, CANCEL_CONFIRM, FEEDBACK, REPORT_REASON, AWAITING_DELETE_CONFIRMATION, VOICE_VERIFICATION = range(11)

# Ensure the photos directory exists
if not os.path.exists('photos'):
    os.makedirs('photos')

if not os.path.exists('voice_verifications'):
    os.makedirs('voice_verifications')


async def check_ban(user_id: int) -> bool:
    cursor.execute('SELECT is_banned, ban_until FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result:
        is_banned, ban_until = result
        if is_banned:
            if ban_until is None:
                return True
            elif isinstance(ban_until, str):
                ban_until_dt = datetime.fromisoformat(ban_until).replace(tzinfo=timezone.utc)
                if ban_until_dt > datetime.now(timezone.utc):
                    return True
            else:
                # Unban the user if the ban period has expired
                cursor.execute('UPDATE users SET is_banned = 0, ban_until = NULL WHERE user_id = ?', (user_id,))
                conn.commit()
    return False

async def setup_bot_menu(bot):
    commands = [
        BotCommand("start", "Start"),
        BotCommand("create_profile", "Create new profile"),
        BotCommand("show_profile", "👤 My profile"),
        BotCommand("guide_me", "❓ How to use this bot"),
        BotCommand("my_id", "🪪 My username"),
        BotCommand("my_userid", "🆔 My User ID"),
        BotCommand("delete_profile", "❌ Delete profile"),
        BotCommand("feedback", "✍️ Provide feedback"),
        BotCommand("privacy_policy", "🔒 Privacy Policy"),
        BotCommand("terms_con", "📄 Terms and Conditions"),
        BotCommand("refer", "🔗 Refer friends and earn points"),
    ]
    await bot.set_my_commands(commands)

async def buttons(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    is_banned, _ = await check_ban(user_id)
    if is_banned:
        await query.message.reply_text("You have been banned. You have to wait until you get unbanned.")
        return

    if await check_ban(query.from_user.id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

async def banned_message(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    cursor.execute('SELECT ban_until FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result and result[0]:
        ban_until = datetime.fromisoformat(result[0])
        await update.effective_message.reply_text(f"Your profile is banned until {ban_until.strftime('%Y-%m-%d %H:%M:%S')}.\n<i>Refer 3 friends to unban your profile by using /refer.\n\nYou can contact us at @predatingsupportbot</i>", parse_mode='HTML')
    else:
        await update.effective_message.reply_text("Your profile is currently banned.\n\nRefer 3 friends to unban your profile by using /refer.")
    return ConversationHandler.END


async def check_channel_membership(update: Update, context: CallbackContext) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def channel_join_message(update: Update, context: CallbackContext) -> None:
    keyboard = [[InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_ID[1:]}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "Join our channel first, then use /start"

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    return ConversationHandler.END

async def handle_voice_verification(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if not update.message.voice:
        await update.message.reply_text("Now let\'s verify your gender.♂♀\n\nSend a voice note Saying:\n<i>\"I confirm my gender for verification.\"</i>", parse_mode='HTML')
        return VOICE_VERIFICATION

    cursor.execute('SELECT gender FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if not result:
        await update.message.reply_text("An error occurred. Please create your profile first.")
        return ConversationHandler.END

    user_gender = result[0]

    voice_file = await update.message.voice.get_file()
    voice_data = await voice_file.download_as_bytearray()
    voice_path = f'voice_verifications/{user_id}.ogg'

    try:
        with open(voice_path, 'wb') as f:
            f.write(voice_data)

        for admin_id in ID:
            await context.bot.send_voice(chat_id=admin_id, voice=open(voice_path, 'rb'),
                                 caption=f"User id: {user_id}\nClaimed gender: {user_gender}")
            await context.bot.send_message(chat_id=admin_id,
                                           text=f"/accept {user_id}")
            await context.bot.send_message(chat_id=admin_id,
                                           text=f"/reject {user_id}")


        await update.message.reply_text("Voice sent for verification.\nPlease wait for approval.")
        context.user_data['awaiting_voice_verification'] = False
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in voice verification for user {user_id}: {str(e)}")
        await update.message.reply_text("An error occurred during voice verification. Please try again later.")
        return ConversationHandler.END

async def handle_verification_result(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    try:
        action, user_id, user_gender = query.data.split('_')[1:]
        user_id = int(user_id)

        voice_path = f'voice_verifications/{user_id}.ogg'

        if action == 'accept':
            cursor.execute('UPDATE users SET is_verified = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            await context.bot.send_message(chat_id=user_id, text="Verification Successful.\nNow you can Find Match.")
            await query.edit_message_text(f"User {user_id} ({user_gender}) has been verified.")
        elif action == 'reject':
            cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            conn.commit()
            await context.bot.send_message(chat_id=user_id, text="Verification got rejected because of empty voice or fake information given.\nIf you think, this is a mistake, please contact us on @predatingsupportbot.\n\nYou can create a new profile.")
            await query.edit_message_text(f"User {user_id} ({user_gender}) has been rejected and their data got deleted.")

        # Delete the voice file
        if os.path.exists(voice_path):
            os.remove(voice_path)

    except Exception as e:
        logger.error(f"Error in handle_verification_result: {str(e)}")
        await query.edit_message_text("Voice verification failed. Please try again.")

async def accept(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id not in ID:      #do like this, where you want to give access to other admins
        await update.message.reply_text("Command not found.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /accept <user_id>")
        return

    try:
        user_id = int(context.args[0])

        cursor.execute('UPDATE users SET is_verified = 1, profile_status = "active" WHERE user_id = ?', (user_id,))
        conn.commit()

        keyboard = [
            [InlineKeyboardButton("Start  ✮⋆˙", callback_data='start'),
             InlineKeyboardButton("Find Match 🚀", callback_data='findmatch')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=user_id,
            text="Verification Successful.\nNow you can Find Match.",
            reply_markup=reply_markup
        )
        await update.message.reply_text(f"User {user_id} has been verified.")

        voice_path = f'voice_verifications/{user_id}.ogg'
        if os.path.exists(voice_path):
            os.remove(voice_path)

    except ValueError:
        await update.message.reply_text("Invalid user ID. Please provide a valid id.")
    except Exception as e:
        logger.error(f"Error in accept: {str(e)}")
        await update.message.reply_text("An error occurred while processing the verification.")

async def reject(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Invalid command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /reject <user_id>")
        return

    try:
        user_id = int(context.args[0])

        cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.commit()

        keyboard = [
            [InlineKeyboardButton("Start  ✮⋆˙", callback_data='start'),
             InlineKeyboardButton("Create Profile", callback_data='create_profile')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=user_id,
            text="Verification got rejected because of empty voice or fake information given.\nIf you think, this is a mistake, then contact us on @predatingsupportbot.\n\nYou can create a new profile.",
            reply_markup=reply_markup
        )
        await update.message.reply_text(f"User {user_id} has been rejected and their data deleted.")

        voice_path = f'voice_verifications/{user_id}.ogg'
        if os.path.exists(voice_path):
            os.remove(voice_path)

    except ValueError:
        await update.message.reply_text("Invalid user ID. Please provide a valid id.")
    except Exception as e:
        logger.error(f"Error in reject: {str(e)}")
        await update.message.reply_text("An error occurred while processing the rejection.")


async def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    if await check_ban(query.from_user.id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    if query.data == 'create_profile':
        await query.message.delete()
        return await create_profile(update, context)
    elif query.data == 'findmatch':
        await query.message.delete()
        return await findmatch(update, context)
    elif query.data == 'delete_profile':
        await query.message.delete()
        return await delete_profile(update, context)
    elif query.data == 'show_profile':
        await query.message.delete()
        return await show_profile(update, context)
    elif query.data.startswith('report_'):
        # Don't delete the message for 'report' button
        return await handle_report(update, context)
    elif query.data == 'start':
        # Don't delete the message for 'start' button
        return await start(update, context)
    elif query.data == 'stop_matching':
        # Don't delete the message for 'stop matching' button
        return await stop_matching(update, context)
    elif query.data == 'confirm_skip_yes':
        await query.message.delete()
        return await confirm_skip(update, context, True)
    elif query.data == 'confirm_skip_no':
        await query.message.delete()
        return await confirm_skip(update, context, False)

ensure_connection()
async def message_handler(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    try:
        if await check_ban(user_id):
            await banned_message(update, context)
            return

        if not await check_channel_membership(update, context):
            await channel_join_message(update, context)
            return

        if context.user_data.get('awaiting_voice_verification', False) and update.message.voice:
            return await handle_voice_verification(update, context)

        if context.user_data.get('reporting', False):
            return await handle_report_reason(update, context)

        # Check if feedback was just submitted
        if context.user_data.get('feedback_submitted', False):
            context.user_data['feedback_submitted'] = False
            return

        # If the user is not banned and is a channel member, proceed with message handling
        return await handle_chat_message(update, context)
    except TelegramError as e:
        if "Forbidden: bot was blocked by the user" in str(e):
            # User has blocked the bot, delete their profile
            cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            conn.commit()
            logger.info(f"User {user_id} blocked the bot, profile deleted")
        elif "user is deactivated" in str(e):
            # User has deactivated their account, delete their profile
            cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            conn.commit()
            logger.info(f"User {user_id} deactivated their account, profile deleted")
        else:
            logger.error(f"TelegramError for user {user_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Error in message_handler for user {user_id}: {str(e)}")

async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started the bot")

    if await check_ban(user_id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    # Reactivate hidden profile
    cursor.execute('UPDATE users SET is_active = 1 WHERE user_id = ?', (user_id,))
    conn.commit()

    keyboard = [
        [InlineKeyboardButton("Find Partner 🚀", callback_data='findmatch')],
        [InlineKeyboardButton("Create Profile", callback_data='create_profile')],
        #[InlineKeyboardButton("Delete Profile ❌", callback_data='delete_profile')],
        [InlineKeyboardButton("My Profile 👤", callback_data='show_profile')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("Welcome to PreDating! 🩷\nFind your soulmate instantly 💯", reply_markup=reply_markup)

async def create_profile(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempted to create a profile")

    if await check_ban(user_id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    existing_profile = cursor.fetchone()
    if existing_profile:
        message = (update.message or update.callback_query.message)
        keyboard = [
            [InlineKeyboardButton("Delete Profile ❌", callback_data='delete_profile')],
            [InlineKeyboardButton("Start  ✮⋆˙", callback_data='start')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text("You already have a profile. Delete the existing one to create a new Profile.", reply_markup=reply_markup)
        return ConversationHandler.END

    context.user_data['creating_profile'] = True
    message = (update.message or update.callback_query.message)
    keyboard = [['Cancel']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await message.reply_text("What's your Name?", reply_markup=reply_markup)
    return NAME


async def cancel_confirmation(update: Update, context: CallbackContext) -> int:
    keyboard = [
        [InlineKeyboardButton("Yes", callback_data='cancel_yes'),
         InlineKeyboardButton("No", callback_data='cancel_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Are you sure you want to cancel profile creation?", reply_markup=reply_markup)
    return CANCEL_CONFIRM

async def cancel_yes(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Profile creation cancelled.")

    # Add inline buttons similar to the start function
    keyboard = [
        [InlineKeyboardButton("Find Partner 🚀", callback_data='findmatch')],
        [InlineKeyboardButton("Create Profile", callback_data='create_profile')],
        #[InlineKeyboardButton("Delete Profile ❌", callback_data='delete_profile')],
        [InlineKeyboardButton("My Profile 👤", callback_data='show_profile')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("What would you like to do?", reply_markup=reply_markup)

    return ConversationHandler.END

async def cancel_no(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Profile creation is continues.")
    # Return to the last state the user was in
    return context.user_data.get('last_state', NAME)

async def create_profile_command(update: Update, context: CallbackContext) -> int:
    return await create_profile(update, context)

async def handle_cancel(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    context.user_data.clear()  # Clear all user data
    await update.message.reply_text('Profile creation cancelled.', reply_markup=ReplyKeyboardRemove())
    logger.info(f"User {user_id} cancelled profile creation")

    keyboard = [
        [InlineKeyboardButton("Find Partner 🚀", callback_data='findmatch')],
        [InlineKeyboardButton("Create Profile", callback_data='create_profile')],
        #[InlineKeyboardButton("Delete Profile ❌", callback_data='delete_profile')],
        [InlineKeyboardButton("My Profile 👤", callback_data='show_profile')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("What would you like to do?", reply_markup=reply_markup)

    return ConversationHandler.END

cancel_keyboard = ReplyKeyboardMarkup([['Cancel']], one_time_keyboard=True, resize_keyboard=True)

async def set_name(update: Update, context: CallbackContext) -> int:
    if await check_ban(update.effective_user.id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    if update.message.text.lower() == 'cancel':
        return await handle_cancel(update, context)

    # Check if the name contains only letters and spaces
    if not re.match(r'^[A-Za-z\s]+$', update.message.text):
        await update.message.reply_text("Please enter a valid name.")
        return NAME

    context.user_data['name'] = update.message.text
    logger.info(f"User {update.effective_user.id} set name: {context.user_data['name']}")
    await update.message.reply_text('Your age?', reply_markup=cancel_keyboard)
    return AGE

cancel_keyboard = ReplyKeyboardMarkup([['Cancel']], one_time_keyboard=True, resize_keyboard=True)
async def set_age(update: Update, context: CallbackContext) -> int:
    if await check_ban(update.effective_user.id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    if update.message.text.lower() == 'cancel':
        return await handle_cancel(update, context)
    try:
        age = int(update.message.text)
        if age < 16 or age > 60:
            raise ValueError
        context.user_data['age'] = age
        logger.info(f"User {update.effective_user.id} set age: {age}")
        await update.message.reply_text('Specify gender (male/female)', reply_markup=cancel_keyboard)
        return GENDER
    except ValueError:
        logger.warning(f"User {update.effective_user.id} entered invalid age: {update.message.text}")
        await update.message.reply_text("This age group is not Allowed.")
        return AGE

cancel_keyboard = ReplyKeyboardMarkup([['Cancel']], one_time_keyboard=True, resize_keyboard=True)
async def set_gender(update: Update, context: CallbackContext) -> int:
    if await check_ban(update.effective_user.id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    if update.message.text.lower() == 'cancel':
        return await handle_cancel(update, context)
    gender = update.message.text.strip().lower()
    if gender not in ['male', 'female']:
        logger.warning(f"User {update.effective_user.id} entered invalid gender: {gender}")
        await update.message.reply_text('Please specify your gender correctly (male/female).')
        return GENDER
    context.user_data['gender'] = gender
    logger.info(f"User {update.effective_user.id} set gender: {gender}")
    await update.message.reply_text('What are you looking for?', reply_markup=cancel_keyboard)
    return INTERESTS

cancel_keyboard = ReplyKeyboardMarkup([['Cancel']], one_time_keyboard=True, resize_keyboard=True)
async def set_interests(update: Update, context: CallbackContext) -> int:
    if await check_ban(update.effective_user.id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    if update.message.text.lower() == 'cancel':
        return await handle_cancel(update, context)
    # Check if the name contains only letters and spaces
    if not re.match(r'^[A-Za-z\s\,\&]+$', update.message.text):
        await update.message.reply_text("Wrong! What are you looking for?")
        return INTERESTS
    context.user_data['interests'] = update.message.text
    logger.info(f"User {update.effective_user.id} set interests: {context.user_data['interests']}")
    await update.message.reply_text('What is your country?', reply_markup=cancel_keyboard)
    return COUNTRY
async def set_country(update: Update, context: CallbackContext) -> int:
    if await check_ban(update.effective_user.id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    if update.message.text.lower() == 'cancel':
        return await handle_cancel(update, context)
    # Check if the name contains only letters and spaces
    if not re.match(r'^[A-Za-z\s]+$', update.message.text):
        await update.message.reply_text("Invalid country name!!!")
        return COUNTRY
    country = update.message.text.strip().lower()
    context.user_data['country'] = country
    logger.info(f"User {update.effective_user.id} set country: {country}")
    await update.message.reply_text('Set a Profile Pic', reply_markup=cancel_keyboard)
    return PHOTO

async def set_photo(update: Update, context: CallbackContext) -> int:
    if await check_ban(update.effective_user.id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    user_id = update.message.from_user.id
    if not update.message.photo:
        logger.warning(f"User {user_id} did not send a photo")
        await update.message.reply_text('Invalid Photo. Please Try Again.')
        return PHOTO

    photo_file = await update.message.photo[-1].get_file()
    photo_data = await photo_file.download_as_bytearray()
    photo_path = f'photos/{user_id}.jpg'

    with open(photo_path, 'wb') as f:
        f.write(photo_data)

    cursor.execute('''
    INSERT OR REPLACE INTO users (user_id, username, name, age, gender, interests, country, photo, profile_status, is_matched, is_active, is_verified)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, 1, 0)
''', (
    user_id, update.message.from_user.username, context.user_data['name'], context.user_data['age'],
    context.user_data['gender'], context.user_data['interests'], context.user_data['country'], photo_path
))
    conn.commit()

    logger.info(f"User {user_id} completed profile creation")
    context.user_data.pop('creating_profile', None)  # Remove the flag

    await update.message.reply_text('Profile Created Successfully!️️', reply_markup=ReplyKeyboardRemove())
    return await request_voice_verification(update, context)

async def cancel(update: Update, context: CallbackContext) -> int:
    logger.info(f"User {update.effective_user.id} canceled profile creation")
    await update.message.reply_text('Profile creation cancelled.', reply_markup=ReplyKeyboardRemove())
    keyboard = [
        [InlineKeyboardButton("Find Partner 🚀", callback_data='findmatch')],
        [InlineKeyboardButton("Create Profile", callback_data='create_profile')],
        [InlineKeyboardButton("My Profile 👤", callback_data='show_profile')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Now, what do you want to do?", reply_markup=reply_markup)
    return ConversationHandler.END

async def findmatch(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to find a match")

    if await check_ban(user_id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

        # Check if the user's profile is active
    cursor.execute('SELECT is_active FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    message = update.effective_message

    if not result or result[0] == 0:
        logger.info(f"User {user_id} tried to find match but his profile is deactivated.")
        keyboard = [[InlineKeyboardButton("Activate  ✮⋆˙", callback_data='start')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text("You need an active profile to find a match. Please create or activate your profile.", reply_markup=reply_markup)
        return


    cursor.execute('''
        SELECT * FROM users
        WHERE user_id = ? AND is_active = 1 AND (is_banned = 0 OR ban_until < CURRENT_TIMESTAMP)
    ''', (user_id,))
    user = cursor.fetchone()

    if user:
        if not user[15]:  # Assuming is_verified is at index 15
            return await request_voice_verification(update, context)

        user_gender = user[4].lower()
        user_country = user[19].lower()  # Assuming country is at index 9
        opposite_gender = 'female' if user_gender == 'male' else 'male'

        cursor.execute('''
    SELECT u.user_id, u.username, u.name, u.age, u.gender, u.interests, u.country, u.photo, u.is_verified
    FROM users u
    LEFT JOIN blocked_matches bm ON u.user_id = bm.blocked_user_id AND bm.user_id = ?
    WHERE u.gender = ? AND u.country = ? AND u.profile_status = 'active' AND u.user_id != ?
    AND bm.blocked_user_id IS NULL AND u.is_matched = 0 AND u.is_active = 1
    AND (u.is_banned = 0 OR u.ban_until < CURRENT_TIMESTAMP)
    AND u.is_verified = 1
    ORDER BY RANDOM()
    LIMIT 1
''', (user_id, opposite_gender, user_country, user_id))
        match = cursor.fetchone()

        if match:
            try:
                # Notify both users
                await context.bot.send_photo(chat_id=user_id, photo=open(match[7], 'rb'))
                verified_symbol = "✅" if match[8] else "❌"
                match_info = f"Name: {match[2].capitalize()}  {verified_symbol}\nAge: {match[3]}\nGender: {match[4].capitalize()}\nCountry: {match[6].capitalize()}"
                await context.bot.send_message(chat_id=user_id, text=match_info)
                await context.bot.send_photo(chat_id=match[0], photo=open(user[6], 'rb'))
                user_verified_symbol = "✅" if user[15] else "❌"
                user_info = f"Name: {user[2].capitalize()}  {user_verified_symbol}\nAge: {user[3]}\nGender: {user[4].capitalize()}\nCountry: {user[19].capitalize()}"
                await context.bot.send_message(chat_id=match[0], text=user_info)

                # Update chat partners and set is_matched to 1 in the database
                cursor.execute('''
                    UPDATE users
                    SET chat_partner = ?, is_matched = 1
                    WHERE user_id = ?
                ''', (match[0], user_id))
                cursor.execute('''
                    UPDATE users
                    SET chat_partner = ?, is_matched = 1
                    WHERE user_id = ?
                ''', (user_id, match[0]))
                conn.commit()

                logger.info(f"Match found between users {user_id} and {match[0]}")

                # Send the Next and Stop buttons to both users
                keyboard = ReplyKeyboardMarkup([['Next', 'Stop']], resize_keyboard=True)
                await context.bot.send_message(chat_id=user_id, text="Partner found. Say Hi!", reply_markup=keyboard)
                await context.bot.send_message(chat_id=match[0], text="Partner matched. Say Hi!", reply_markup=keyboard)

            except Exception as e:
                logger.error(f"Error in findmatch for user {user_id}: {str(e)}")
                await message.reply_text("An error occurred while finding a match. Please try again later.")
        else:
            logger.info(f"No match found for user {user_id}")
            keyboard = [
                [InlineKeyboardButton("Find Match Again 🚀", callback_data='findmatch')],
                [InlineKeyboardButton("Hide me ⭕", callback_data='stop_matching')],
                [InlineKeyboardButton("Home  ✮⋆˙", callback_data='start')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text("No available matches at the moment. Please try again later.", reply_markup=reply_markup)
    else:
        keyboard = [[InlineKeyboardButton("Create Profile", callback_data='create_profile')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text("You don't have an active profile. Please create one first.", reply_markup=reply_markup)


async def request_voice_verification(update: Update, context: CallbackContext) -> int:
    await update.effective_message.reply_text("Let\'s verify your gender.♂♀\n\nSend a voice note Saying:\n\"I confirm my gender for verification.\"")
    context.user_data['awaiting_voice_verification'] = True
    return VOICE_VERIFICATION

def generate_confirmation_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

async def delete_profile(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id

    # Check if the user has a profile
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()

    if not user:
        # User doesn't have a profile
        keyboard = [[InlineKeyboardButton("Create Profile", callback_data='create_profile')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_message.reply_text(
            "You don't have a profile to delete. Would you like to create one?",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

    # If the user has a profile, proceed with the deletion process
    confirmation_code = generate_confirmation_code()
    context.user_data['delete_confirmation_code'] = confirmation_code

    message = update.message or update.callback_query.message
    await message.reply_text(
        f"Your confirmation code is:  {confirmation_code}\n\n"
        f"Enter the confirmation code to proceed:\n"
        f"Or type 'cancel' to keep your profile."
    )
    return 'AWAITING_DELETE_CONFIRMATION'

async def handle_delete_confirmation(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    user_input = update.message.text.strip().upper()

    if user_input == 'CANCEL':
        await update.message.reply_text("Profile deletion cancelled.")
        return ConversationHandler.END

    if user_input == context.user_data.get('delete_confirmation_code'):
        # Check if the user is currently matched
        cursor.execute('SELECT chat_partner FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            chat_partner = result[0]
            # End the match
            cursor.execute('UPDATE users SET chat_partner = NULL, is_matched = 0 WHERE user_id IN (?, ?)', (user_id, chat_partner))
            conn.commit()
            # Notify the chat partner
            try:
                await context.bot.send_message(chat_id=chat_partner, text="Your partner ended the chat.")
            except Exception as e:
                logger.error(f"Failed to notify chat partner {chat_partner} about profile deletion: {str(e)}")

        # Delete the user's profile
        cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.commit()
        logger.info(f"User {user_id} profile deleted")
        await update.message.reply_text('Your profile has been deleted successfully.')

        keyboard = [
            [InlineKeyboardButton("Create New Profile", callback_data='create_profile')],
            [InlineKeyboardButton("Home ✮", callback_data='start')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("What would you like to do?", reply_markup=reply_markup)
        return ConversationHandler.END
    else:
        await update.message.reply_text("Incorrect confirmation code. Profile deletion cancelled.")
        return ConversationHandler.END

async def next(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to find a new match using Next")

    if await check_ban(user_id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    keyboard = [
        [InlineKeyboardButton("Yes", callback_data='confirm_skip_yes')],
        [InlineKeyboardButton("No", callback_data='confirm_skip_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Are you sure you want to skip this chat?", reply_markup=reply_markup)

async def confirm_skip(update: Update, context: CallbackContext, confirmed: bool) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    if not confirmed:
        pass
        return

    cursor.execute('SELECT chat_partner FROM users WHERE user_id = ?', (user_id,))
    current_match = cursor.fetchone()

    if current_match and current_match[0]:
        chat_partner = current_match[0]
        try:
            # Notify both users about the skip and remove the Next and Stop buttons
            await context.bot.send_message(chat_id=user_id, text="You ended the chat.", reply_markup=ReplyKeyboardRemove())
            await context.bot.send_message(chat_id=chat_partner, text="Your partner ended the chat.", reply_markup=ReplyKeyboardRemove())

            # Update the database to set is_matched to 0 for both users
            cursor.execute('UPDATE users SET chat_partner = NULL, is_matched = 0 WHERE user_id = ?', (user_id,))
            cursor.execute('UPDATE users SET chat_partner = NULL, is_matched = 0 WHERE user_id = ?', (chat_partner,))
            conn.commit()

            # Add to blocked_matches to ensure they don't match again
            cursor.execute('INSERT OR IGNORE INTO blocked_matches (user_id, blocked_user_id) VALUES (?, ?)', (user_id, chat_partner))
            cursor.execute('INSERT OR IGNORE INTO blocked_matches (user_id, blocked_user_id) VALUES (?, ?)', (chat_partner, user_id))
            conn.commit()

            # Send report button to both users
            report_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Report ⚠️", callback_data=f"report_{chat_partner}")]])
            await context.bot.send_message(chat_id=user_id, text="If you want to Report this user, click the button below:", reply_markup=report_keyboard)

            report_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Report ⚠️", callback_data=f"report_{user_id}")]])
            await context.bot.send_message(chat_id=chat_partner, text="If you want to Report this user, use button below:", reply_markup=report_keyboard)

            # Send 'Find Match', 'Stop Matching', and 'Start' buttons to both users
            keyboard = [
                [InlineKeyboardButton("Find Match 🚀", callback_data='findmatch')],
                [InlineKeyboardButton("Hide me ⭕", callback_data='stop_matching')],
                [InlineKeyboardButton("Home ✮", callback_data='start')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(chat_id=user_id, text="What would you like to do?", reply_markup=reply_markup)
            await context.bot.send_message(chat_id=chat_partner, text="What would you like to do?", reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error in Next for user {user_id}: {str(e)}")
            await query.edit_message_text("An error occurred while processing your request. Please try again later.")
    else:
        logger.info(f"User {user_id} has no current match to skip")
        await not_in_match_buttons(update, context)

async def stop(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to stop matching using Stop")

    if await check_ban(user_id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    keyboard = [
        [InlineKeyboardButton("Yes", callback_data='confirm_skip_yes')],
        [InlineKeyboardButton("No", callback_data='confirm_skip_no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Are you sure you want to end this chat?", reply_markup=reply_markup)

async def stop_matching(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to hide his profile")

    if await check_ban(user_id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    cursor.execute('UPDATE users SET is_active = 0, is_matched = 0, chat_partner = NULL WHERE user_id = ?', (user_id,))
    conn.commit()

    keyboard = [[InlineKeyboardButton("Unhide ✮", callback_data='start')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text("Your profile is now Hidden.", reply_markup=reply_markup)

async def handle_report(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    reported_user_id = query.data.split('_')[1]

    context.user_data['reporting'] = True
    context.user_data['reported_user_id'] = reported_user_id

    await query.answer()
    await query.edit_message_text("Please type your report:")
    return REPORT_REASON

async def handle_report_reason(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    reported_user_id = context.user_data.pop('reported_user_id', None)
    context.user_data['reporting'] = False

    if reported_user_id is None:
        await update.message.reply_text("An error occurred. Please try reporting again.")
        return ConversationHandler.END

    reason = update.message.text
    report_message = f"REPORT: User {user_id} reported user {reported_user_id} for: {reason}"

    try:
        # Send report reason to forward_bot
        await forward_bot.send_message(chat_id=chat_id, text=report_message)

        logger.info(f"Report forwarded: {report_message}")
        await update.message.reply_text("Thank you for your report. We will review it shortly.")
    except Exception as e:
        logger.error(f"Failed to forward report: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again later.")

    return ConversationHandler.END

async def show_profile(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to view their profile")

    if await check_ban(user_id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    message = update.effective_message

    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()

    if user:
        photo_path = user[6]
        is_verified = user[15]  # Assuming index 15 is is_verified
        verified_symbol = "✅" if is_verified else "❌"
        profile_text = f"Name: {user[2].capitalize()}   {verified_symbol}\nAge: {user[3]}\nGender: {user[4].capitalize()}\nInterests: {user[5].capitalize()}\nCountry: {user[19].capitalize()}"

        await context.bot.send_photo(chat_id=user_id, photo=open(photo_path, 'rb'), caption=profile_text)

        keyboard = [[InlineKeyboardButton("Home ✮", callback_data='start')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text("Would you like to go back?", reply_markup=reply_markup)
    else:
        keyboard = [[InlineKeyboardButton("Create Profile", callback_data='create_profile')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text("You don't have a profile yet. Would you like to create one?", reply_markup=reply_markup)



async def not_in_match_buttons(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if await check_ban(user_id):
        return await banned_message(update, context)

    if not await check_channel_membership(update, context):
        return await channel_join_message(update, context)

    keyboard = [
        [InlineKeyboardButton("Find Match 🚀", callback_data='findmatch')],
        [InlineKeyboardButton("Stop Matching 🛑", callback_data='stop_matching')],
        [InlineKeyboardButton("Home ✮", callback_data='start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("What would you like to do?", reply_markup=reply_markup)

def generate_word_forms(word):
    return set(''.join(form) for form in itertools.product(*((c.lower(), c.upper()) for c in word)))


async def privacy_policy(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to read privacy policy.")

    policy_text = ('''
<b>Privacy Policy:</b>\n

▪️ <b>Information We Collect:</b> PreDating bot collects personal information including your name, age, gender, interests, country.\nA voice recording is temporarily collected for gender verification purposes.\n
▪️ <b>Use of Information:</b> We use the collected information to create and manage your dating profile, verify your gender, facilitate matches and interactions with other users, and ensure user safety through chat review.\nThis information helps us improve our services and enhance User Experience.\n
▪️ <b>Data Storage and Security:</b> We implement appropriate technical measures to protect your personal data. Voice recordings are automatically deleted from our database immediately after verification.
Other personal data is retained only as long as necessary to provide our services or as required by law. Upon account deletion, all user data is permanently removed from our database.\n
▪️ <b>Data Sharing:</b> We do not sell or share your personal data with third parties. Additionally, your chat messages are being reviewed to ensure user safety and the messages are being deleted after a certain period.
We never ask for such sensitive information like (passwords, phone number, card details etc.). If you are being asked to share such details, please send a screenshot of the chat to @predatingsupportbot immediately.\nYour privacy is your right.\n
▪ <b>️Data Shared with matches:</b> We share your name, age, gender, country and photo with your matched partner to keep both partners informed about each other.\n
▪ <b>️Your Rights:</b> You have the right to access, or delete your personal data. You can request a copy of your data if needed.\n
▪️ <b>Changes to Privacy Policy:</b> We may update this policy from time to time. You will be notified about the changes.\n
▪️ <b>Contact Us:</b> <i>If you have any questions or concerns about our privacy policy, please contact @predatingsupportbot  (remember, don't click on anything in the support bot, just send your message directly)</i>.''')

    keyboard = [[InlineKeyboardButton("Okay ✮⋆˙", callback_data='start')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(policy_text, reply_markup=reply_markup, parse_mode='HTML')

async def terms_conditions(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requested to read  terms and conditions.")

    terms_con = ('''
<b>Terms and Conditions:</b>\n

<i>By Creating the profile on PreDating, you agree our Terms and Conditions.</i>\n

▪ ️<b>User Conduct:</b> You agree to behave respectfully and not to harass or abuse other users. Sharing explicit or inappropriate content is strictly prohibited.\n
▪ ️<b>Profile Verification:</b> You agree to complete the voice verification process. Misrepresenting gender or other personal information will cause immediate account termination.\n
▪ ️<b>Verified users:</b> The verified users have ✅ with their name, and non-verified users have ❌ with their name. This keeps the user aware about the partner.\n
▪️ <b>Content Moderation:</b: We reserve the right to review chat messages for safety purposes. We may terminate accounts of users who violate our guidelines.\n
▪️ <b>Sharing Personal Information:</b> You are strictly prohibited from sharing any personal information such as Telegram IDs, Instagram IDs, phone numbers, email addresses, or any other type of contactable information.
Additionally, you must not ask or encourage others to share their personal information under any circumstances.\n
▪️ <b>Use of Inappropriate Language:</b> The use of any inappropriate, offensive, or abusive language within the bot is strictly forbidden. This includes hate speech, derogatory remarks, and any other form of verbal abuse.\n
▪️ <b>Eligibility:</b> You must be at least 16 years old to use the PreDating. All users are required to provide accurate information when creating their profile.\n
▪️ <b>Liability:</b> We are not responsible for user-generated content or interactions between users. You use the service at your own risk.\n
▪ <b>Intellectual Property:</b> You retain rights to your content but grant us a license to use it for improving our services.\n
▪️ <b>Termination:</b> We reserve the right to terminate or suspend accounts at our discretion. Upon termination, all user data is permanently deleted from our database.\n
▪️ <b>Consequences of Violation:</b> Any user found violating these terms and conditions may face immediate and permanent banning from using the bot.
This action may be taken at the sole discretion of the bot admin.\n
▪️ <b>Changes to Terms:</b> We may update these terms from time to time. Continued use of the service constitutes acceptance of updated terms.\n
▪️ <b>Contact Us:</b> <i>If you have any questions or concerns about terms and conditions, please contact @predatingsupportbot (remember, don't click on anything in the support bot, just send your message directly)</i>.''')

    keyboard = [[InlineKeyboardButton("I Agree ✮", callback_data='start')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(terms_con, reply_markup=reply_markup, parse_mode='HTML')

async def instructions(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} wants to know how to use this bot.")

    guide_me = ('''
 <b>How to Use This Bot (Guide):</b>\n
<i>Note: You must have joined the channel to use this bot.</i>\n\n
1. <b>Start the Bot:</b> To start the bot, send the /start command to the bot. This will bring up the main menu with the following options:\n

▪️ Create Profile.
▪️ Find Partner.
▪️ Delete Profile.
▪️ My Profile.

2. <b>Create a Profile:</b> If you don't have a profile yet, select the "Create Profile" option. The bot will guide you through the process of creating your profile by asking for your name, age, gender, interests and country.\nBe sure to provide accurate information.\n
3. <b>Find a Match:</b> Once your profile is created, you can select the "Find Partner" option to start searching for a match. The bot will automatically find a partner for you.\n
4. <b>Hide Profile:</b> If you don't want to get matched with anyone, you can select the "Hide Me" option to hide your profile. By this option, no one will be able to find you or get matched with you.
<i>(Note: By hiding your profile, you cannot use "find match" until you unhide your profile.)</i>\n
5. <b>Unhide Profile:</b> After hiding profile, if you want to unhide it and find matches, just use "Unhide me" option to make your profile visible again.\n
6. <b>Interact with Your Match:</b> After a match is found, you can start chatting with your partner. Use the "Next" and "Stop" buttons to control the conversation.\nIf you want to end the match, simply click the "Stop" button.\n
7. <b>View Your Profile:</b> You can view your profile at any time by selecting the "My Profile" option. This will show your profile information and photo.\n
8. <b>Delete Your Profile:</b> If you want to delete your profile, select the "Delete Profile" option. The bot will ask you to confirm the deletion by entering a verification code.\n
9. <b>Verify Your Gender:</b> After creating the profile, the bot may ask you to verify your gender by sending a voice note.\nThis is a security feature to ensure the accuracy of the gender information.\n
10. <b>Report a User:</b> If you encounter any issues with a matched user, you can report them by clicking the "Report" button.\nThe bot will ask you to provide a reason for the report, which will be forwarded to the Team.\n
11. <b>Navigate the Main Menu:</b> You can always return to the main menu by selecting the "Start" option, which will display the available actions.\n


<i>Remember, the bot has several features to ensure a safe and enjoyable dating experience.
Follow the instructions and feel free to reach out to the Team if you have any questions or concerns @predatingsupportbot (don't click on any start ads, just send the message).</i>''')

    keyboard = [[InlineKeyboardButton("Done ✮", callback_data='start')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(guide_me, reply_markup=reply_markup, parse_mode='HTML')

async def post_init(application: Application) -> None:
    await setup_bot_menu(application.bot)

async def my_id(update: Update, context: CallbackContext) -> None:
    username = update.effective_user.username
    await update.message.reply_text(f"My Username: @{username}")

async def my_user_id(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(f"My User id:  `{user_id}`\nDon't share this with any partner.", parse_mode='Markdown')

async def feedback(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Please provide your feedback:")
    return FEEDBACK

async def handle_feedback(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    feedback_text = update.message.text
    await forward_bot.send_message(chat_id=chat_id, text=f"Feedback from user {user_id}:\n{feedback_text}")
    await update.message.reply_text("Thanks for your feedback! 🥰")

    context.user_data['feedback_submitted'] = True
    return ConversationHandler.END


def generate_referral_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

async def refer(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} used refer command")
    cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result and result[0]:
        referral_code = result[0]
    else:
        referral_code = generate_referral_code()
        cursor.execute('UPDATE users SET referral_code = ? WHERE user_id = ?', (referral_code, user_id))
        conn.commit()

    bot_username = await context.bot.get_me()
    referral_link = f"https://t.me/{bot_username.username}?start={referral_code}"

    await update.message.reply_text(f"Refer this link to your friends:\n{referral_link}")

async def handle_referral(update: Update, context: CallbackContext) -> None:
    referral_code = context.args[0] if context.args else None

    if not referral_code:
        return

    cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
    referrer = cursor.fetchone()

    if referrer:
        referrer_id = referrer[0]
        cursor.execute('UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?', (referrer_id,))
        conn.commit()

        cursor.execute('SELECT referral_count, is_banned FROM users WHERE user_id = ?', (referrer_id,))
        referral_count, is_banned = cursor.fetchone()

        await context.bot.send_message(chat_id=referrer_id, text=f"You've got a new referral! Total referrals: {referral_count}")

        if is_banned and referral_count >= 3:
            cursor.execute('UPDATE users SET is_banned = 0, ban_until = NULL WHERE user_id = ?', (referrer_id,))
            conn.commit()
            await context.bot.send_message(chat_id=referrer_id, text="Congratulations! Your profile has been unbanned for referring 3 friends.")
            await forward_bot.send_message(chat_id=chat_id, text=f"User {referrer_id} has been unbanned by referring 3 friends.")

def main() -> None:
    defaults = Defaults(tzinfo=pytz.timezone('Asia/Kolkata'))
    application = (
        ApplicationBuilder()
        .token('bot_token')
        .defaults(defaults)
        .post_init(post_init)
        .build()
    )


    conv_handler = ConversationHandler(
    entry_points=[CommandHandler('create_profile', create_profile), CallbackQueryHandler(button, pattern='^create_profile$')],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_name)],
        AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_age)],
        GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_gender)],
        INTERESTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_interests)],
        COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_country)],
        PHOTO: [MessageHandler(filters.PHOTO, set_photo)],
        VOICE_VERIFICATION: [MessageHandler(filters.VOICE, handle_voice_verification)],
        CANCEL_CONFIRM: [
            CallbackQueryHandler(cancel_yes, pattern='^cancel_yes$'),
            CallbackQueryHandler(cancel_no, pattern='^cancel_no$')
        ]
    },
    fallbacks=[MessageHandler(filters.Regex('^Cancel$'), cancel_confirmation)],
    per_message=False
)

    feedback_handler = ConversationHandler(
    entry_points=[CommandHandler('feedback', feedback)],
    states={
        FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback)]
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    allow_reentry=True
)

    delete_handler = ConversationHandler(
    entry_points=[
        CommandHandler('delete_profile', delete_profile),
        CallbackQueryHandler(delete_profile, pattern='^delete_profile$')
    ],
    states={
        'AWAITING_DELETE_CONFIRMATION': [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete_confirmation)]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

    application.add_handler(delete_handler)


    application.add_handler(CommandHandler('start', start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('lookmatch', findmatch), group=3)
    application.add_handler(CommandHandler('delete_profile', delete_profile))
    application.add_handler(CommandHandler('show_profile', show_profile))
    application.add_handler(CommandHandler('ban', ban_user))
    application.add_handler(CommandHandler('unban', unban_user))
    application.add_handler(CommandHandler('privacy_policy', privacy_policy))
    application.add_handler(CommandHandler('terms_con', terms_conditions))
    application.add_handler(CommandHandler('guide_me', instructions))
    application.add_handler(MessageHandler(filters.Regex('^Next$'), next))
    application.add_handler(MessageHandler(filters.Regex('^Stop$'), stop))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(CallbackQueryHandler(buttons))
    application.add_handler(CommandHandler('create_profile', create_profile_command))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
    application.add_handler(CommandHandler('my_id', my_id))
    application.add_handler(CommandHandler('my_userid', my_user_id))
    application.add_handler(CommandHandler('refer', refer), group=-1)
    application.add_handler(CommandHandler('start', handle_referral))
    application.add_handler(CommandHandler('accept', accept))
    application.add_handler(CommandHandler('reject', reject))
    application.add_handler(CallbackQueryHandler(handle_report, pattern='^report_'))


    # Add a handler for all messages to check for bans
    application.add_handler(MessageHandler(filters.ALL, check_ban_wrapper), group=-1)

    # Add a handler for all text messages to check channel membership
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_membership_wrapper), group=-2)

    # Set up chat handlers
    setup_chat_handlers(application)

    application.run_polling()


async def check_ban_wrapper(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if await check_ban(user_id):
        await banned_message(update, context)
        raise ApplicationHandlerStop()

    # If the user is not banned, allow the message to be processed by other handlers
    return None

async def check_membership_wrapper(update: Update, context: CallbackContext) -> None:
    if not await check_channel_membership(update, context):
        await channel_join_message(update, context)
        raise ApplicationHandlerStop()

    return None


if __name__ == '__main__':
    main()

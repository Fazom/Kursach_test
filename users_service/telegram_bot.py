import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler
import requests

# Настройка логирования
logger = logging.getLogger("telegram_bot")
logger.setLevel(logging.INFO)

# Обработчик для записи в файл с кодировкой UTF-8
file_handler = logging.FileHandler("telegram_bot.log", encoding='utf-8')  # Убедитесь, что путь правильный
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Обработчик для вывода в консоль с кодировкой UTF-8
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(name)s - %(levelname)s - %(message)s"))

# Добавление обработчиков к логгеру
logger.addHandler(file_handler)
logger.addHandler(console_handler)

BOT_TOKEN = "7872240184:AAH2D1qDXKha4OLfgmBBGsM_Ox3IODvkbNc"  
API_URL = "http://127.0.0.1:8000/api/v1"  #FastAPI сервер

# Состояния для разговора
STATE_USERNAME, STATE_PASSWORD, STATE_MENU = range(3)

# Функция для авторизации (обращение к API)
async def login(update: Update, context: CallbackContext):
    logger.info("User is attempting to log in.")
    await update.message.reply_text("Please send your username to log in.")
    return STATE_USERNAME

# Функция для сбора username
async def get_username(update: Update, context: CallbackContext):
    context.user_data["username"] = update.message.text
    logger.info(f"User entered username: {update.message.text}")
    await update.message.reply_text("Please enter your password.")
    return STATE_PASSWORD

# Функция для сбора пароля и авторизации через API
async def get_password(update: Update, context: CallbackContext):
    context.user_data["password"] = update.message.text
    username = context.user_data["username"]
    password = context.user_data["password"]

    try:
        # Запрос к API для авторизации
        login_response = requests.post(f"{API_URL}/auth/login", json={"username": username, "password": password})
        if login_response.status_code == 200:
            token = login_response.json()["access_token"]
            context.user_data["token"] = token  # Сохраняем токен
            logger.info(f"User {username} successfully logged in.")
            await update.message.reply_text("You are successfully logged in. Please choose an action.")
            return await show_menu(update, context)  # Переходим к меню
        else:
            logger.error(f"Login failed for user {username}. Status code: {login_response.status_code}")
            await update.message.reply_text("Authorization failed. Please check your credentials.")
            return STATE_USERNAME
    except Exception as e:
        logger.error(f"Error during login attempt for user {username}: {e}")
        await update.message.reply_text("An error occurred during login. Please try again.")
        return STATE_USERNAME

# Команда для отображения меню
async def show_menu(update: Update, context: CallbackContext):
    logger.info("Showing menu to the user.")
    await update.message.reply_text(
        "Choose an option:\n"
        "/view_records - Просмотр записей\n"
        "/exit - Выход"
    )
    return STATE_MENU

# Обработчик для команды "Просмотр записей"
async def handle_view_appointments(update: Update, context: CallbackContext):
    user_token = context.user_data.get("token")
    if not user_token:
        logger.warning("User is not authorized, prompting for login.")
        await update.message.reply_text("Please log in first.")
        return STATE_USERNAME

    try:
        # Получаем записи пользователя из API
        response = requests.get(f"{API_URL}/appointments", headers={"Authorization": f"Bearer {user_token}"})
        if response.status_code == 200:
            appointments = response.json()
            if not appointments:
                logger.info(f"No appointments found for user {context.user_data['username']}.")
                await update.message.reply_text("You have no appointments.")
            else:
                for appointment in appointments:
                    appointment_time = datetime.fromisoformat(appointment["appointment_time"])
                    formatted_time = appointment_time.strftime("%d %B %Y, %H:%M")
                    await update.message.reply_text(f"Appointment:\nDate and time: {formatted_time}\nService: {appointment['service']}")
        else:
            logger.error(f"Failed to retrieve appointments for user {context.user_data['username']}. Status code: {response.status_code}")
            await update.message.reply_text("Failed to retrieve appointments.")
    except Exception as e:
        logger.error(f"Error retrieving appointments for user {context.user_data['username']}: {e}")
        await update.message.reply_text("An error occurred while fetching your appointments. Please try again.")
    
    return await show_menu(update, context)

# Обработчик для команды "Выйти"
async def exit(update: Update, context: CallbackContext):
    logger.info(f"User {context.user_data['username']} has exited the bot.")
    await update.message.reply_text("You have logged out.")
    return ConversationHandler.END

# Определение шагов разговора
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', login)],
    states={
        STATE_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_username)],
        STATE_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_password)],
        STATE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_menu)],
    },
    fallbacks=[CommandHandler('exit', exit)],
)

# Настроим бота
async def start(update: Update, context: CallbackContext):
    logger.info("User initiated the bot session.")
    await update.message.reply_text("Welcome! Please log in.")
    return STATE_USERNAME

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики для команд
    application.add_handler(CommandHandler("view_records", handle_view_appointments))
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == "__main__":
    main()

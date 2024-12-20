from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler
import requests

BOT_TOKEN = "7872240184:AAH2D1qDXKha4OLfgmBBGsM_Ox3IODvkbNc"  # Замените на свой токен
API_URL = "http://127.0.0.1:8000/api/v1"  # Ваш FastAPI сервер

# Состояния для разговора
STATE_USERNAME, STATE_PASSWORD, STATE_MENU = range(3)


# Функция для авторизации (обращение к API)
async def login(update: Update, context: CallbackContext):
    await update.message.reply_text("Пожалуйста, отправьте ваше имя пользователя для входа.")
    return STATE_USERNAME

# Функция для сбора username
async def get_username(update: Update, context: CallbackContext):
    context.user_data["username"] = update.message.text
    await update.message.reply_text("Пожалуйста, введите ваш пароль.")
    return STATE_PASSWORD

# Функция для сбора пароля и авторизации через API
async def get_password(update: Update, context: CallbackContext):
    context.user_data["password"] = update.message.text
    username = context.user_data["username"]
    password = context.user_data["password"]

    # Запрос к API для авторизации
    login_response = requests.post(f"{API_URL}/auth/login", json={"username": username, "password": password})
    
    if login_response.status_code == 200:
        token = login_response.json()["access_token"]
        context.user_data["token"] = token  # Сохраняем токен
        await update.message.reply_text("Вы успешно авторизованы. Пожалуйста, выберите действие.")
        return await show_menu(update, context)  # Переходим к меню
    else:
        await update.message.reply_text("Ошибка авторизации. Пожалуйста, проверьте свои данные.")
        return STATE_USERNAME

# Команда для отображения меню
async def show_menu(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "Выберите опцию:\n"
        "/view_records - Просмотр записей\n"
        "/exit - Выйти"
    )
    return STATE_MENU

# Обработчик для команды "Просмотр записей"
async def handle_view_appointments(update: Update, context: CallbackContext):
    user_token = context.user_data.get("token")
    if not user_token:
        await update.message.reply_text("Пожалуйста, авторизуйтесь сначала.")
        return STATE_USERNAME
    # Получаем записи пользователя из API
    response = requests.get(f"{API_URL}/appointments", headers={"Authorization": f"Bearer {user_token}"})
    if response.status_code == 200:
        appointments = response.json()
        if not appointments:
            await update.message.reply_text("У вас нет записей.")
        else:
            for appointment in appointments:
                # Форматируем вывод
                appointment_time = datetime.fromisoformat(appointment["appointment_time"])
                formatted_time = appointment_time.strftime("%d %B %Y, %H:%M")
                await update.message.reply_text(f"Запись:\nДата и время: {formatted_time}\nУслуга: {appointment['service']}")
    else:
        await update.message.reply_text("Не удалось получить записи.")
    
    # После вывода записей, снова показать меню
    return await show_menu(update, context)

# Обработчик для команды "Выйти"
async def exit(update: Update, context: CallbackContext):
    await update.message.reply_text("Вы вышли из бота.")
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
    await update.message.reply_text("Добро пожаловать! Пожалуйста, авторизуйтесь.")
    return STATE_USERNAME

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики для команд
    application.add_handler(CommandHandler("view_records", handle_view_appointments))
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == "__main__":
    main()

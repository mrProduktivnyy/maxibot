"""
Тестовый бот для проверки функциональности maxibot.

Запуск:
    export MAX_BOT_TOKEN="ваш_токен"
    python examples/test_bot.py

Команды для проверки в чате с ботом:
    /start          — приветствие, проверка send_message
    /info           — информация о боте, проверка get_me
    /photo          — отправка фото из файла, проверка send_photo
    /photourl       — отправка фото по URL-строке, проверка send_photo
    /document       — отправка документа, проверка send_document
    /video          — отправка видео, проверка send_video
                      (нужен путь к mp4 в переменной MAX_TEST_VIDEO)
    /keyboard       — inline-клавиатура, проверка InlineKeyboardMarkup и
                      кнопки мини-приложения (WebAppInfo)
    /replykb        — reply-клавиатура, проверка ReplyKeyboardMarkup
    /edit           — редактирование сообщения, проверка edit_message_text
    /delete         — удаление сообщения, проверка delete_message
    /steps          — многошаговый диалог, проверка register_next_step_handler
    /middleware     — атрибут, выставленный в middleware, проверка middleware_handler
    /reply          — ответ-цитата на команду, проверка reply_to
    /exception      — намеренный вызов ошибки, проверка MaxApiException
    любой текст     — эхо, проверка content_types и func-фильтра
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot, apihelper
from maxibot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from maxibot.exceptions import MaxApiException

TOKEN = os.getenv("MAX_BOT_TOKEN")
if not TOKEN:
    print("Ошибка: переменная окружения MAX_BOT_TOKEN не задана")
    sys.exit(1)

apihelper.ENABLE_MIDDLEWARE = True  # как в telebot: до регистрации middleware
bot = MaxiBot(TOKEN)


# ---------------------------------------------------------------------------
# Middleware — вызываются до обработчиков для каждого обновления
# ---------------------------------------------------------------------------

@bot.middleware_handler()
def log_update(bot_instance, update):
    print(f"[middleware] update_type={update.update_type}")


@bot.middleware_handler(update_types=["message_created"])
def stamp_message(bot_instance, message):
    message.middleware_tag = f"middleware видел текст {message.text!r}"


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        f"Привет, {message.from_user.first_name}!\n\n"
        "Доступные команды:\n"
        "/start — это сообщение\n"
        "/info — информация о боте\n"
        "/photo — тест send\\_photo\n"
        "/photourl — тест send\\_photo по URL\n"
        "/document — тест send\\_document\n"
        "/video — тест send\\_video\n"
        "/keyboard — тест inline-клавиатуры\n"
        "/replykb — тест reply-клавиатуры\n"
        "/edit — тест edit\\_message\\_text\n"
        "/delete — тест delete\\_message\n"
        "/steps — тест register\\_next\\_step\\_handler\n"
        "/middleware — тест middleware\\_handler\n"
        "/reply — тест reply\\_to\n"
        "/exception — тест обработки исключений"
    )


# ---------------------------------------------------------------------------
# /info — get_me
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["info"])
def cmd_info(message):
    me = bot.get_me()
    bot.send_message(
        message.chat.id,
        f"Имя бота: {me.get('name')}\n"
        f"username: {me.get('username')}\n"
        f"user\\_id: {me.get('user_id')}"
    )


# ---------------------------------------------------------------------------
# /photo — send_photo
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["photo"])
def cmd_photo(message):
    with open(os.path.join(os.path.dirname(__file__), "../maxibot/docs/tg_to_max.png"), "rb") as f:
        photo_bytes = f.read()
    bot.send_photo(
        chat_id=message.chat.id,
        photo=photo_bytes,
        caption="Тест send\\_photo"
    )


# ---------------------------------------------------------------------------
# /photourl — send_photo по URL-строке
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["photourl"])
def cmd_photourl(message):
    bot.send_photo(
        chat_id=message.chat.id,
        photo="https://raw.githubusercontent.com/mrProduktivnyy/maxibot/main/maxibot/docs/tg_to_max.png",
        caption="Тест send\\_photo по URL — MAX скачал картинку сам"
    )


# ---------------------------------------------------------------------------
# /document — send_document
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["document"])
def cmd_document(message):
    content = b"Hello from maxibot test!\nThis is a test document."
    bot.send_document(
        chat_id=message.chat.id,
        document=content,
        caption="Тест send\\_document",
        visible_file_name="test.txt"
    )


# ---------------------------------------------------------------------------
# /video — send_video
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["video"])
def cmd_video(message):
    video_path = os.getenv("MAX_TEST_VIDEO")
    if not video_path or not os.path.exists(video_path):
        bot.send_message(
            message.chat.id,
            "Для теста задай путь к mp4-файлу:\n"
            "`export MAX_TEST_VIDEO=/путь/к/видео.mp4`"
        )
        return
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    bot.send_video(
        chat_id=message.chat.id,
        video=video_bytes,
        caption="Тест send\\_video"
    )


# ---------------------------------------------------------------------------
# /keyboard — InlineKeyboardMarkup + WebAppInfo + answer_callback_query
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["keyboard"])
def cmd_keyboard(message):
    # Кнопка open_app открывает мини-приложение бота, если оно настроено
    # в MAX; как в telebot, web_app=WebAppInfo(...), но url здесь —
    # ссылка на бота, а не адрес приложения
    me = bot.get_me()
    username = me.get("username")
    web_app = WebAppInfo(f"https://max.ru/{username}") if username \
        else WebAppInfo(None, contact_id=me["user_id"])
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Кнопка 1", callback_data="btn_1"),
        InlineKeyboardButton("Кнопка 2", callback_data="btn_2"),
        InlineKeyboardButton("Ссылка", url="https://max.ru"),
        InlineKeyboardButton("Мини-приложение", web_app=web_app),
    )
    bot.send_message(
        message.chat.id,
        "Тест inline-клавиатуры. Нажми любую кнопку:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda cb: cb.data in ("btn_1", "btn_2"))
def handle_button(callback):
    success = bot.answer_callback_query(
        callback.id,
        text=f"Ты нажал {callback.data}"
    )
    bot.send_message(
        callback.message.chat.id,
        f"Получен callback: `{callback.data}`\n"
        f"answer\\_callback\\_query вернул: `{success}`"
    )


# ---------------------------------------------------------------------------
# /replykb — ReplyKeyboardMarkup + KeyboardButton
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["replykb"])
def cmd_replykb(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("Да", "Нет")
    markup.row(KeyboardButton("Контакт", request_contact=True),
               KeyboardButton("Гео", request_location=True))
    bot.send_message(
        message.chat.id,
        "Тест reply-клавиатуры. «Да»/«Нет» отправят текст в чат, "
        "остальные запросят контакт и гео:",
        reply_markup=markup
    )


# ---------------------------------------------------------------------------
# /edit — edit_message_text
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["edit"])
def cmd_edit(message):
    sent = bot.send_message(message.chat.id, "Оригинальный текст...")
    if sent and sent.message_id:
        bot.edit_message_text(
            text="Текст успешно отредактирован!",
            chat_id=message.chat.id,
            message_id=sent.message_id
        )


# ---------------------------------------------------------------------------
# /delete — delete_message
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["delete"])
def cmd_delete(message):
    sent = bot.send_message(message.chat.id, "Это сообщение сейчас удалится...")
    if sent and sent.message_id:
        bot.delete_message(
            chat_id=message.chat.id,
            message_id=sent.message_id
        )
        bot.send_message(message.chat.id, "Сообщение удалено")


# ---------------------------------------------------------------------------
# /steps — register_next_step_handler
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["steps"])
def cmd_steps(message):
    bot.send_message(message.chat.id, "Шаг 1: как тебя зовут?")
    bot.register_next_step_handler(message, step_name)


def step_name(message):
    name = message.text
    bot.send_message(message.chat.id, f"Шаг 2: сколько тебе лет, {name}?")
    bot.register_next_step_handler(message, step_age, name=name)


def step_age(message, name):
    bot.send_message(
        message.chat.id,
        f"Готово! {name}, {message.text} лет. Диалог завершён."
    )


# ---------------------------------------------------------------------------
# /reply — reply_to
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["reply"])
def cmd_reply(message):
    bot.reply_to(message, "Это ответ-цитата на твоё сообщение (reply\\_to)")


# ---------------------------------------------------------------------------
# /exception — проверка MaxApiException
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["exception"])
def cmd_exception(message):
    try:
        bot.api.send_message(chat_id="невалидный_id", text="test")
    except MaxApiException as e:
        bot.send_message(
            message.chat.id,
            f"Исключение поймано:\n`{type(e).__name__}: {e}`"
        )


# ---------------------------------------------------------------------------
# /middleware — middleware_handler
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["middleware"])
def cmd_middleware(message):
    bot.send_message(message.chat.id, f"Атрибут из middleware: {message.middleware_tag}")


# ---------------------------------------------------------------------------
# Эхо — любой текст
# ---------------------------------------------------------------------------

@bot.message_handler(func=lambda m: True)
def echo(message):
    if message.text:
        bot.send_message(message.chat.id, f"Эхо: {message.text}")


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Бот запущен в режиме infinity polling...")
    bot.infinity_polling()

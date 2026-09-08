"""
Недекораторная регистрация: add_message_handler,
register_message_handler, register_callback_query_handler
(add_callback_query_handler был раньше).

Запуск:
    python3 tests/test_register_handlers.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

from maxibot import MaxiBot
from maxibot.custom_filters import IsDigitFilter


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


def capture_warnings(fn):
    capture = LogCapture()
    logging.getLogger("maxibot").addHandler(capture)
    try:
        result = fn()
    finally:
        logging.getLogger("maxibot").removeHandler(capture)
    return result, capture.warnings()


class FakeApi:
    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot():
    bot = MaxiBot("t", threaded=False)
    bot.api = FakeApi()
    return bot


USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u"}


def message_update(text="привет", chat_type="dialog", attachments=None):
    body = {"mid": "mid.1", "seq": 1, "text": text}
    if attachments is not None:
        body["attachments"] = attachments
    return {
        "update_type": "message_created",
        "timestamp": 1751400000000,
        "message": {
            "sender": USER,
            "recipient": {"chat_id": 42, "chat_type": chat_type, "user_id": 7},
            "timestamp": 1751400000000,
            "body": body,
        },
    }


def callback_update(payload="ok"):
    return {
        "update_type": "message_callback",
        "timestamp": 1751400000000,
        "callback": {"callback_id": "cb.1", "payload": payload, "user": USER},
        "message": {
            "sender": USER,
            "recipient": {"chat_id": 42, "chat_type": "chat", "user_id": 7},
            "timestamp": 1751400000000,
            "body": {"mid": "mid.1", "seq": 1, "text": "кнопки", "attachments": []},
        },
    }


# 1. Сигнатуры — как в telebot (имена и дефолты)
for name in ("add_message_handler", "register_message_handler",
             "register_callback_query_handler", "add_callback_query_handler"):
    ours = inspect.signature(getattr(MaxiBot, name))
    theirs = inspect.signature(getattr(telebot.TeleBot, name))
    assert list(ours.parameters) == list(theirs.parameters), name
    for p_name, p in theirs.parameters.items():
        assert ours.parameters[p_name].default == p.default, (name, p_name)
print("1 ok: сигнатуры как в telebot")

# 2. register_message_handler: фильтры работают, pass_bot отдаёт бота
bot = make_bot()
fired = []

def on_hello(message):
    fired.append(("hello", message.text))

def on_cmd(message, bot=None):
    fired.append(("cmd", bot))

bot.register_message_handler(on_hello, func=lambda m: m.text == "привет")
bot.register_message_handler(on_cmd, commands=["start"], pass_bot=True)
bot.process_new_updates([message_update()])
bot.process_new_updates([message_update(text="/start")])
assert fired == [("hello", "привет"), ("cmd", bot)]
print("2 ok: register_message_handler + pass_bot")

# 3. Без content_types register_ матчит ЛЮБОЙ тип (как в telebot),
# а декоратор — только текст
bot = make_bot()
fired = []
bot.register_message_handler(lambda m: fired.append("reg"))

@bot.message_handler()
def h_deco(m):
    fired.append("deco")

photo = message_update(text=None,
                       attachments=[{"type": "image", "payload": {"url": "u"}}])
bot.process_new_updates([photo])
assert fired == ["reg"]                      # декоратор фото не берёт
bot.process_new_updates([message_update()])  # текст берут оба, первый в списке
assert fired == ["reg", "reg"]
print("3 ok: register_ без content_types матчит все типы, декоратор — текст")

# 4. Строки commands/content_types оборачиваются с предупреждением
bot = make_bot()
fired = []
_, warns = capture_warnings(lambda: bot.register_message_handler(
    lambda m: fired.append("s"), content_types="text", commands="start"))
assert sum("обернул строку" in w for w in warns) == 2, warns
bot.process_new_updates([message_update(text="/start")])
assert fired == ["s"]
bot.process_new_updates([message_update(text="не команда")])
assert fired == ["s"]                        # фильтр commands действует
print("4 ok: строки оборачиваются в списки")

# 5. chat_types через register_ нормализуется (оба словаря имён)
bot = make_bot()
fired = []
bot.register_message_handler(lambda m: fired.append("group"),
                             chat_types=["group"])
bot.register_message_handler(lambda m: fired.append("private"),
                             chat_types=["dialog"])   # сырое имя MAX
bot.process_new_updates([message_update(chat_type="chat")])
bot.process_new_updates([message_update(chat_type="dialog")])
assert fired == ["group", "private"]
print("5 ok: chat_types нормализуются")

# 6. Кастом-фильтры через **kwargs у register_
bot = make_bot()
bot.add_custom_filter(IsDigitFilter())
fired = []
bot.register_message_handler(lambda m: fired.append(m.text), is_digit=True)
bot.process_new_updates([message_update(text="123")])
bot.process_new_updates([message_update(text="сто")])
assert fired == ["123"]
print("6 ok: кастом-фильтры через register_")

# 7. add_message_handler: сырой словарь, реестр общий с декоратором
bot = make_bot()
fired = []
bot.add_message_handler(bot._build_handler_dict(
    lambda m: fired.append("raw"), content_types=["text"]))
assert len(bot.message_handlers) == 1
bot.process_new_updates([message_update()])
assert fired == ["raw"]
print("7 ok: add_message_handler")

# 8. register_callback_query_handler: func, func=None, data и pass_bot
bot = make_bot()
fired = []
bot.register_callback_query_handler(
    lambda c: fired.append("да"), func=lambda c: c.data == "да")
bot.register_callback_query_handler(
    lambda c, bot=None: fired.append(("любой", bot)), func=None, pass_bot=True)
bot.process_new_updates([callback_update(payload="да")])
bot.process_new_updates([callback_update(payload="нет")])
# первый совпавший обработчик забирает коллбэк: 'да' уходит в первый
assert fired == ["да", ("любой", bot)], fired
bot2 = make_bot()
fired2 = []
bot2.register_callback_query_handler(
    lambda c: fired2.append("data"), func=None, data="да")
bot2.process_new_updates([callback_update(payload="нет")])
bot2.process_new_updates([callback_update(payload="да")])
assert fired2 == ["data"]
# func обязателен позиционно, как в telebot
try:
    bot2.register_callback_query_handler(lambda c: None)
    assert False, "ожидался TypeError"
except TypeError:
    pass
print("8 ok: register_callback_query_handler")

print("ALL OK")

"""
Обработчики правок сообщений: @bot.edited_message_handler,
add_edited_message_handler, register_edited_message_handler (pass_bot)
и диспатч message_edited в _process_update.

Запуск:
    python3 tests/test_edited_messages.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

from maxibot import MaxiBot, apihelper
from maxibot.types import Message


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
    """Message/Chat при разборе обновления ходят за названием чата — считаем."""

    def __init__(self):
        self.chat_info_calls = 0

    def get_chat_info(self, chat_id):
        self.chat_info_calls += 1
        return {"title": "chat"}


def make_bot():
    bot = MaxiBot("t", threaded=False)  # обработчики синхронно
    bot.api = FakeApi()
    return bot


USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u"}


def edited_update(text="привет", attachments=None, update_type="message_edited"):
    body = {"mid": "mid.1", "seq": 2, "text": text}
    if attachments is not None:
        body["attachments"] = attachments
    return {
        "update_type": update_type,
        "timestamp": 1751400000000,
        "message": {
            "sender": USER,
            "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
            "timestamp": 1751400000000,
            "body": body,
        },
    }


# 1. Сигнатуры как в telebot (у telebot есть **kwargs под кастом-фильтры —
#    их в maxibot пока нет, №17; сравниваем остальные параметры)
for name in ("edited_message_handler", "add_edited_message_handler",
             "register_edited_message_handler"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = {n: p for n, p in
                   inspect.signature(getattr(telebot.TeleBot, name)).parameters.items()
                   if p.kind is not inspect.Parameter.VAR_KEYWORD}
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры трёх методов как в telebot (без **kwargs — №17)")

# 2. Диспатч: правка попадает в edited-обработчик и НЕ попадает в обычные;
#    обычное сообщение не попадает в edited-обработчик
bot = make_bot()
got = []


@bot.edited_message_handler(func=lambda m: True)
def on_edit(message):
    got.append(("edited", message))


@bot.message_handler(func=lambda m: True)
def on_message(message):
    got.append(("created", message))


bot._process_update(edited_update(text="исправил"))
assert [tag for tag, _ in got] == ["edited"], got
assert isinstance(got[0][1], Message) and got[0][1].text == "исправил"
bot._process_update(edited_update(text="новое", update_type="message_created"))
assert [tag for tag, _ in got] == ["edited", "created"], got
print("2 ok: message_edited -> edited-обработчик, message_created -> обычный")

# 3. Дефолт content_types=['text']: правка с фото не матчится текстовым,
#    ловится подпиской на ['photo']
bot = make_bot()
got = []


@bot.edited_message_handler()
def on_text_edit(message):
    got.append("text")


@bot.edited_message_handler(content_types=["photo"])
def on_photo_edit(message):
    got.append("photo")


bot._process_update(edited_update(
    text=None,
    attachments=[{"type": "image", "payload": {"token": "t", "url": "https://u"}}],
))
assert got == ["photo"], got
print("3 ok: без content_types edited-обработчик ловит только текст")

# 4. commands и regexp работают на правках; первый совпавший — единственный
bot = make_bot()
got = []


@bot.edited_message_handler(commands=["start"])
def on_start_edit(message):
    got.append("start")


@bot.edited_message_handler(regexp="испр")
def on_regexp_edit(message):
    got.append("regexp")


@bot.edited_message_handler(regexp="испр")
def on_regexp_edit_2(message):
    got.append("regexp-2")


bot._process_update(edited_update(text="/start тут"))
bot._process_update(edited_update(text="исправлено"))
assert got == ["start", "regexp"], got
print("4 ok: commands/regexp на правках, первый совпавший выигрывает")

# 5. Без edited-обработчиков и middleware правка не строит Message
#    (нет похода в API за названием чата)
bot = make_bot()
bot._process_update(edited_update())
assert bot.api.chat_info_calls == 0, bot.api.chat_info_calls
# с обработчиком — строит
bot.register_edited_message_handler(lambda m: None)
bot._process_update(edited_update())
assert bot.api.chat_info_calls > 0
print("5 ok: без подписки правки не разбираются (экономия походов в API)")

# 6. register_edited_message_handler: pass_bot=True передаёт бота kwarg'ом
bot = make_bot()
got = []


def with_bot(message, bot=None):
    got.append((message.text, bot))


def without_bot(message):
    got.append((message.text,))


bot.register_edited_message_handler(with_bot, regexp="раз", pass_bot=True)
bot.register_edited_message_handler(without_bot, regexp="два")
bot._process_update(edited_update(text="раз"))
bot._process_update(edited_update(text="два"))
assert got[0] == ("раз", bot), got
assert got[1] == ("два",), got
# как в telebot: register_ БЕЗ content_types матчит любой тип контента
# (телеботовские register_, в отличие от декораторов, ['text'] не подставляют)
bot = make_bot()
got = []
bot.register_edited_message_handler(lambda m: got.append(m.content_type))
assert bot.edited_message_handlers[-1]["filters"] == {}, bot.edited_message_handlers
bot._process_update(edited_update(
    text=None,
    attachments=[{"type": "image", "payload": {"token": "t", "url": "https://u"}}],
))
assert got == ["photo"], got
print("6 ok: register_edited_message_handler — pass_bot, без content_types матчит всё")

# 7. add_edited_message_handler — низкоуровневая регистрация
bot = make_bot()
got = []
bot.add_edited_message_handler(bot._build_handler_dict(
    lambda m: got.append(m.text), content_types=["text"]))
bot._process_update(edited_update(text="напрямую"))
assert got == ["напрямую"], got
print("7 ok: add_edited_message_handler")

# 8. Нормализация фильтров общая с message_handler: строки оборачиваются,
#    по 'voice' предупреждение (в MAX голосовые приходят как audio)
bot = make_bot()
_, warns = capture_warnings(
    lambda: bot.edited_message_handler(content_types="voice")(lambda m: None))
assert any("не порождает" in w for w in warns), warns
assert any("списком" in w for w in warns), warns
# рефакторинг не сломал те же предупреждения у message_handler
bot = make_bot()
_, warns = capture_warnings(
    lambda: bot.message_handler(content_types="voice")(lambda m: None))
assert any("не порождает" in w for w in warns), warns
print("8 ok: нормализация фильтров общая, предупреждения на месте")

# 9. Middleware message_edited получает тот же Message, что и обработчик
apihelper.ENABLE_MIDDLEWARE = True
try:
    bot = make_bot()
    got = []

    @bot.middleware_handler(update_types=["message_edited"])
    def mark(bot_instance, message):
        message.marked = "из middleware"

    @bot.edited_message_handler(func=lambda m: True)
    def on_edit_mw(message):
        got.append(message.marked)

    bot._process_update(edited_update())
    assert got == ["из middleware"], got
finally:
    apihelper.ENABLE_MIDDLEWARE = False
print("9 ok: middleware и обработчик правок делят один объект Message")

# 10. pass_bot работает и у callback-обработчиков (общий handler_dict)
bot = make_bot()
got = []


@bot.callback_query_handler(func=lambda c: True, pass_bot=True)
def on_callback(callback, bot=None):
    got.append(bot)


bot._process_update({
    "update_type": "message_callback",
    "timestamp": 1751400000000,
    "callback": {"callback_id": "cb1", "payload": "x", "user": USER},
    "message": {
        "sender": USER,
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.1", "seq": 1, "text": "кнопки", "attachments": []},
    },
})
assert got == [bot], got

# 11. chat_types сверяется с сырыми типами MAX (dialog/chat/channel) —
#     задокументированная особенность, телеботовский 'private' не совпадёт
bot = make_bot()
got = []
bot.register_edited_message_handler(lambda m: got.append("private"),
                                    chat_types=["private"])
bot.register_edited_message_handler(lambda m: got.append("dialog"),
                                    chat_types=["dialog"])
bot._process_update(edited_update(text="в личке"))
assert got == ["dialog"], got
print("10-11 ok: pass_bot у callback, chat_types — сырые типы MAX")

print("ALL OK")

"""
edit_message_caption: своего editMessageCaption в MAX нет, а PUT /messages
заменяет body целиком — честная эмуляция: GET /messages/{messageId} →
пересборка текущих вложений (медиа по token и т.д.) → PUT с новой
подписью и теми же вложениями, notify=False.

Как в telebot: без reply_markup клавиатура исходного сообщения снимается;
к аудио/файлу/стикеру/контакту клавиатура не прикладывается (warning).

Запуск:
    python3 tests/test_edit_message_caption.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

from maxibot import MaxiBot
from maxibot.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


def photo_message(attachments):
    return {
        "message": {
            "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
            "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
            "timestamp": 1751400000000,
            "body": {"mid": "mid.1", "seq": 5, "text": "старая подпись",
                     "attachments": attachments},
        }
    }


class FakeApi:
    def __init__(self, message=None, success=True):
        self.message = message if message is not None else photo_message(
            [{"type": "image", "payload": {"token": "img-tok", "url": "https://cdn/i.jpg"}}]
        )
        self.success = success
        self.get_calls = []
        self.send_kwargs = []

    def get_message(self, msg_id):
        self.get_calls.append(msg_id)
        return self.message

    def send_message(self, **kwargs):
        self.send_kwargs.append(kwargs)
        return {"success": self.success}

    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot(api):
    bot = MaxiBot("t")
    bot.api = api
    return bot


def capture_warnings(fn):
    capture = LogCapture()
    logging.getLogger("maxibot").addHandler(capture)
    try:
        result = fn()
    finally:
        logging.getLogger("maxibot").removeHandler(capture)
    return result, capture.warnings()


# 1. Сигнатура один в один с telebot
maxi_params = inspect.signature(MaxiBot.edit_message_caption).parameters
tele_params = inspect.signature(telebot.TeleBot.edit_message_caption).parameters
assert list(maxi_params) == list(tele_params), (list(maxi_params), list(tele_params))
for param in tele_params:
    assert maxi_params[param].default == tele_params[param].default, param
print("1 ok: сигнатура edit_message_caption как в telebot")

# 2. Счастливый путь: GET → PUT с новой подписью, вложение по token,
#    notify=False, возвращается Message
api = FakeApi()
msg = make_bot(api).edit_message_caption("новая подпись", 42, "mid.1")
assert api.get_calls == ["mid.1"], api.get_calls
kw = api.send_kwargs[0]
assert kw["method"] == "PUT", kw
assert kw["msg_id"] == "mid.1", kw
assert kw["text"] == "новая подпись", kw
assert kw["attachments"] == [{"type": "image", "payload": {"token": "img-tok"}}], kw["attachments"]
assert kw["notify"] is False, kw
assert isinstance(msg, Message), type(msg)
print("2 ok: GET -> PUT c token-вложением, notify=False")

# 3. Без message_id — ValueError (инлайн-сообщений в MAX нет)
try:
    make_bot(FakeApi()).edit_message_caption("подпись", chat_id=42)
    assert False, "ожидался ValueError"
except ValueError as e:
    assert "message_id" in str(e), str(e)
print("3 ok: без message_id -> ValueError")

# 4. Клавиатура: без reply_markup исходная снимается; с reply_markup —
#    прикладывается новая
api = FakeApi(photo_message([
    {"type": "image", "payload": {"token": "img-tok"}},
    {"type": "inline_keyboard", "payload": {"buttons": [[{"type": "callback", "text": "x", "payload": "d"}]]}},
]))
make_bot(api).edit_message_caption("п", 42, "mid.1")
assert api.send_kwargs[0]["attachments"] == [
    {"type": "image", "payload": {"token": "img-tok"}}
], api.send_kwargs[0]["attachments"]
api = FakeApi()
markup = InlineKeyboardMarkup()
markup.add(InlineKeyboardButton("кнопка", callback_data="d"))
make_bot(api).edit_message_caption("п", 42, "mid.1", reply_markup=markup)
attachments = api.send_kwargs[0]["attachments"]
assert len(attachments) == 2 and attachments[1]["type"] == "inline_keyboard", attachments
print("4 ok: клавиатура снимается без reply_markup, прикладывается с ним")

# 5. must_be_alone: клавиатура к подписи аудио — warning + не прикладывается
api = FakeApi(photo_message([{"type": "audio", "payload": {"token": "aud-tok"}}]))
_, warns = capture_warnings(
    lambda: make_bot(api).edit_message_caption("п", 42, "mid.1", reply_markup=markup)
)
assert any("единственным вложением" in w for w in warns), warns
attachments = api.send_kwargs[0]["attachments"]
assert attachments == [{"type": "audio", "payload": {"token": "aud-tok"}}], attachments
print("5 ok: клавиатура к аудио-подписи игнорируется с предупреждением")

# 6. parse_mode резолвится; inline_message_id/caption_entities игнорируются
#    (телеботовский порядок параметров)
api = FakeApi()
make_bot(api).edit_message_caption("п", 42, "mid.1", "inline.9", "HTML", None)
kw = api.send_kwargs[0]
assert kw["parse_mode"] == "html", kw
assert kw["msg_id"] == "mid.1", kw
print("6 ok: parse_mode резолвится, inline_message_id игнорируется")

# 7. Не-успех API — возвращается {}
api = FakeApi(success=False)
result = make_bot(api).edit_message_caption("п", 42, "mid.1")
assert result == {}, result
print("7 ok: success: false -> {}")

# 8. Чисто текстовое сообщение: текст заменяется, вложений нет
#    (отличие от telebot задокументировано)
api = FakeApi(photo_message([]))
make_bot(api).edit_message_caption("новый текст", 42, "mid.1")
kw = api.send_kwargs[0]
assert kw["text"] == "новый текст" and kw["attachments"] == [], kw
print("8 ok: у текстового сообщения просто заменяется текст")

# 9. Спекова форма GET-ответа — голый Message без обёртки {"message"}:
#    боевая ветка «or info» работает так же
bare = photo_message(
    [{"type": "image", "payload": {"token": "img-tok"}}]
)["message"]
api = FakeApi(bare)
make_bot(api).edit_message_caption("п", 42, "mid.1")
assert api.send_kwargs[0]["attachments"] == [
    {"type": "image", "payload": {"token": "img-tok"}}
], api.send_kwargs[0]["attachments"]
print("9 ok: голый Message из спеки разбирается так же")

# 10. Reply-связка исходного сообщения переносится в PUT (правка подписи
#     не снимает ответ, как и в Telegram); без link в PUT уходит None
with_link = photo_message([{"type": "image", "payload": {"token": "img-tok"}}])
with_link["message"]["link"] = {
    "type": "reply",
    "chat_id": 42,
    "message": {"mid": "mid.0", "seq": 1, "text": "исходное"},
}
api = FakeApi(with_link)
make_bot(api).edit_message_caption("п", 42, "mid.1")
assert api.send_kwargs[0]["link"] == {"type": "reply", "mid": "mid.0"}, api.send_kwargs[0]
api = FakeApi()
make_bot(api).edit_message_caption("п", 42, "mid.1")
assert api.send_kwargs[0]["link"] is None, api.send_kwargs[0]
print("10 ok: reply-связка переносится в PUT, без неё link=None")

print("ALL OK")

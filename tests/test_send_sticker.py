"""
send_sticker: POST /messages со вложением
{"type": "sticker", "payload": {"code": ...}}.

Параметр sticker — строка-КОД стикера MAX (аналог file_id; код лежит
во входящем payload.code). Свои файлы загрузить нельзя — типа sticker
в POST /uploads нет: файл/байты/URL — ValueError. По спеке стикер
обязан быть единственным вложением — reply_markup игнорируется
с предупреждением. data — устаревший алиас sticker, как в telebot.

Запуск:
    python3 tests/test_send_sticker.py
"""
import inspect
import io
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


SEND_OK = {
    "message": {
        "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.123", "seq": 5, "text": None, "attachments": [
            {"type": "sticker", "payload": {"code": "st-code", "url": "https://cdn/st.png"}}
        ]},
    }
}


class FakeApi:
    def __init__(self):
        self.send_kwargs = []

    def send_message(self, **kwargs):
        self.send_kwargs.append(kwargs)
        return SEND_OK

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
maxi_params = inspect.signature(MaxiBot.send_sticker).parameters
tele_params = inspect.signature(telebot.TeleBot.send_sticker).parameters
assert list(maxi_params) == list(tele_params), (list(maxi_params), list(tele_params))
for param in tele_params:
    assert maxi_params[param].default == tele_params[param].default, param
print("1 ok: сигнатура send_sticker как в telebot")

# 2. Счастливый путь: код -> вложение sticker, text None, chat int -> str,
#    notify True; Message с content_type "sticker"
api = FakeApi()
msg = make_bot(api).send_sticker(42, "st-code")
kw = api.send_kwargs[0]
assert kw["chat_id"] == "42", kw
assert kw["text"] is None, kw
assert kw["attachments"] == [
    {"type": "sticker", "payload": {"code": "st-code"}}
], kw["attachments"]
assert kw["notify"] is True, kw
assert kw["link"] is None, kw
assert isinstance(msg, Message) and msg.message_id == "mid.123"
assert msg.content_type == "sticker", msg.content_type
print('2 ok: вложение {"type": "sticker", "payload": {"code": ...}}, content_type "sticker"')

# 3. disable_notification/timeout/reply_to_message_id; timeout=0 -> None
api = FakeApi()
make_bot(api).send_sticker(42, "st-code", reply_to_message_id="mid.0",
                           disable_notification=True, timeout=9)
kw = api.send_kwargs[0]
assert kw["link"] == {"type": "reply", "mid": "mid.0"}, kw
assert kw["notify"] is False, kw
assert kw["timeout"] == 9, kw
api = FakeApi()
make_bot(api).send_sticker(42, "st-code", timeout=0)
assert api.send_kwargs[0]["timeout"] is None, api.send_kwargs[0]
print("3 ok: link reply, notify=False, timeout (0 -> дефолт)")


# 4. reply_parameters важнее устаревшего reply_to_message_id, при конфликте —
#    предупреждение (как в telebot)
class ReplyParams:
    message_id = "mid.9"


api = FakeApi()
make_bot(api).send_sticker(42, "st-code", reply_parameters=ReplyParams())
assert api.send_kwargs[0]["link"] == {"type": "reply", "mid": "mid.9"}
api = FakeApi()
_, warns = capture_warnings(
    lambda: make_bot(api).send_sticker(42, "st-code", reply_to_message_id="mid.0",
                                       reply_parameters=ReplyParams())
)
assert api.send_kwargs[0]["link"] == {"type": "reply", "mid": "mid.9"}
assert any("send_sticker" in w and "конфликт" in w for w in warns), warns
print("4 ok: reply_parameters важнее, конфликт предупреждается")

# 5. reply_markup игнорируется с предупреждением (стикер — единственное вложение)
api = FakeApi()
markup = InlineKeyboardMarkup()
markup.add(InlineKeyboardButton("кнопка", callback_data="d"))
_, warns = capture_warnings(
    lambda: make_bot(api).send_sticker(42, "st-code", reply_markup=markup)
)
assert any("единственным вложением" in w for w in warns), warns
attachments = api.send_kwargs[0]["attachments"]
assert len(attachments) == 1 and attachments[0]["type"] == "sticker", attachments
print("5 ok: reply_markup у стикера не прикладывается, есть предупреждение")

# 6. data — устаревший алиас sticker: используется с предупреждением,
#    когда sticker не передан; при обоих — sticker важнее, без предупреждения
api = FakeApi()
_, warns = capture_warnings(
    lambda: make_bot(api).send_sticker(42, None, data="st-old")
)
assert api.send_kwargs[0]["attachments"][0]["payload"] == {"code": "st-old"}
assert any("data" in w and "устарел" in w for w in warns), warns
api = FakeApi()
_, warns = capture_warnings(
    lambda: make_bot(api).send_sticker(42, "st-code", data="st-old")
)
assert api.send_kwargs[0]["attachments"][0]["payload"] == {"code": "st-code"}
assert not any("устарел" in w for w in warns), warns
print("6 ok: data — алиас sticker с предупреждением, sticker важнее")

# 7. Файл/байты/URL/пустота -> ValueError с объяснением (загрузка своих
#    стикеров в MAX невозможна)
for bad in (io.BytesIO(b'sticker-bytes'), b'raw', None, "", 123):
    try:
        make_bot(FakeApi()).send_sticker(42, bad)
        assert False, f"ожидался ValueError для {bad!r}"
    except ValueError as e:
        assert "кодом стикера" in str(e), (bad, str(e))
try:
    make_bot(FakeApi()).send_sticker(42, "https://example.com/st.webp")
    assert False, "ожидался ValueError для URL"
except ValueError as e:
    assert "URL" in str(e), str(e)
print("7 ok: файл/байты/URL/пустота -> ValueError")

# 8. emoji и прочие телеботовские параметры принимаются и игнорируются;
#    телеботовский позиционный порядок
api = FakeApi()
make_bot(api).send_sticker(42, "st-code", None, None, None, None,
                           True, True, None, 7, "🔥")
kw = api.send_kwargs[0]
assert kw["attachments"][0]["payload"] == {"code": "st-code"}
assert kw["notify"] is True, kw
print("8 ok: позиционный порядок как в telebot, emoji игнорируется")

# 9. Входящий стикер: content_type "sticker", как в telebot
incoming = {
    "update_type": "message_created",
    "message": {
        "sender": {"user_id": 2, "is_bot": False, "first_name": "u", "name": "u", "last_name": None},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 1},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.7", "seq": 9, "text": None, "attachments": [
            {"type": "sticker", "payload": {"code": "st-in", "url": "https://cdn/st.png"},
             "width": 512, "height": 512}
        ]},
    },
}
msg = Message(update=incoming, api=FakeApi())
assert msg.content_type == "sticker", msg.content_type
print('9 ok: входящий стикер — content_type "sticker"')

print("ALL OK")

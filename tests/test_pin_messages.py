"""
Закрепы поверх PUT/DELETE/GET /chats/{chatId}/pin: pin_chat_message,
unpin_chat_message, unpin_all_chat_messages и MAX-бонус
get_pinned_message.

Закреп в MAX один на чат: новый вытесняет старый, unpin_all
эквивалентен обычному unpin; unpin с message_id сверяется с текущим
закрепом и не снимает чужой.

Запуск:
    python3 tests/test_pin_messages.py
"""
import inspect
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import telebot

from maxibot import MaxiBot
from maxibot.apihelper import Api
from maxibot.types import Message


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


PINNED = {
    "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
    "recipient": {"chat_id": 100, "chat_type": "chat", "user_id": None},
    "timestamp": 1751400000000,
    "body": {"mid": "mid.pin", "seq": 1, "text": "закреп", "attachments": None},
}


class FakeApi:
    def __init__(self, pinned=PINNED):
        self.pinned = pinned
        self.calls = []

    def pin_message(self, chat_id, message_id, notify=None, timeout=None):
        self.calls.append(("pin", chat_id, message_id, notify))
        return {"success": True}

    def unpin_message(self, chat_id, timeout=None):
        self.calls.append(("unpin", chat_id))
        return {"success": True}

    def get_pinned_message(self, chat_id, timeout=None):
        self.calls.append(("get_pin", chat_id))
        return {"message": self.pinned}

    def get_chat_info(self, chat_id):
        return {"chat_id": chat_id, "type": "chat", "title": "Чат"}


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


# 1. Сигнатуры один в один с telebot
for name in ("pin_chat_message", "unpin_chat_message", "unpin_all_chat_messages"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры всех трёх методов как в telebot")

# 2. pin: PUT без notify при дефолте (серверный default true = уведомлять);
#    disable_notification=True -> notify=False
api = FakeApi()
assert make_bot(api).pin_chat_message(100, "mid.1") is True
assert api.calls[-1] == ("pin", 100, "mid.1", None), api.calls
make_bot(api).pin_chat_message(100, "mid.1", disable_notification=True)
assert api.calls[-1] == ("pin", 100, "mid.1", False), api.calls
print("2 ok: pin_chat_message — notify только при отключении")

# 3. unpin без message_id: сразу DELETE, без лишнего GET
api = FakeApi()
assert make_bot(api).unpin_chat_message(100) is True
assert api.calls == [("unpin", 100)], api.calls
print("3 ok: unpin без message_id — сразу DELETE")

# 4. unpin с совпадающим message_id: GET + DELETE
api = FakeApi()
assert make_bot(api).unpin_chat_message(100, "mid.pin") is True
assert api.calls == [("get_pin", 100), ("unpin", 100)], api.calls
print("4 ok: unpin с совпадающим mid — сверился и снял")

# 5. unpin с чужим message_id: предупреждение, DELETE не зовётся, False
api = FakeApi()
result, warns = capture_warnings(lambda: make_bot(api).unpin_chat_message(100, "mid.other"))
assert result is False
assert api.calls == [("get_pin", 100)], api.calls
assert any("mid.other" in w for w in warns), warns
# закрепа нет вовсе — то же поведение
api = FakeApi(pinned=None)
result, warns = capture_warnings(lambda: make_bot(api).unpin_chat_message(100, "mid.pin"))
assert result is False and api.calls == [("get_pin", 100)]


# message в 200-ответе бывает СТРОКОЙ — текстом ошибки (формы
# {"success": false, "message": ...} и {code, message} проходят мимо
# guard'а клиента) — не падать
class ErrorBodyApi(FakeApi):
    def get_pinned_message(self, chat_id, timeout=None):
        self.calls.append(("get_pin", chat_id))
        return {"success": False, "message": "chat is not accessible"}


api = ErrorBodyApi()
result, _ = capture_warnings(lambda: make_bot(api).unpin_chat_message(100, "mid.pin"))
assert result is False and api.calls == [("get_pin", 100)]
assert make_bot(ErrorBodyApi()).get_pinned_message(100) is None
print("5 ok: unpin чужого/отсутствующего закрепа и строковый message — без падений")

# 6. unpin_all: тот же DELETE (закреп один)
api = FakeApi()
assert make_bot(api).unpin_all_chat_messages(100) is True
assert api.calls == [("unpin", 100)], api.calls
print("6 ok: unpin_all_chat_messages")

# 7. get_pinned_message: Message с текстом/mid/date; нет закрепа -> None;
#    закреп от имени канала (sender: null) не роняет
msg = make_bot(FakeApi()).get_pinned_message(100)
assert isinstance(msg, Message), type(msg)
assert msg.text == "закреп" and msg.message_id == "mid.pin"
assert msg.date is not None
assert make_bot(FakeApi(pinned=None)).get_pinned_message(100) is None
channel_pin = dict(PINNED, sender=None)
msg = make_bot(FakeApi(pinned=channel_pin)).get_pinned_message(100)
# с №14 (каналы) у поста от имени канала from_user = None, как в telebot
assert msg.message_id == "mid.pin" and msg.from_user is None
print("7 ok: get_pinned_message — Message, None, канальный закреп")

# 8. Wire-уровень: PUT/DELETE/GET на /chats/{chatId}/pin
calls = []


class OkResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"success": True}


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return OkResponse()


real_request = requests.Session.request
requests.Session.request = fake_request
try:
    api = Api("tok")
    api.pin_message(100, "mid.9", notify=False)
    kw = calls[-1]
    assert kw["method"] == "PUT"
    assert kw["url"] == "https://platform-api2.max.ru/chats/100/pin", kw["url"]
    assert json.loads(kw["data"]) == {"message_id": "mid.9", "notify": False}

    api.pin_message(100, "mid.9")
    assert json.loads(calls[-1]["data"]) == {"message_id": "mid.9"}

    api.unpin_message(100)
    assert calls[-1]["method"] == "DELETE"
    assert calls[-1]["url"] == "https://platform-api2.max.ru/chats/100/pin"

    api.get_pinned_message(100)
    assert calls[-1]["method"] == "GET"
finally:
    requests.Session.request = real_request
print("8 ok: wire-уровень — PUT/DELETE/GET /chats/{chatId}/pin")

print("ALL OK")

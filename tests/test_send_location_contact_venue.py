"""
send_location / send_contact / send_venue + edit/stop_message_live_location:
локация и контакт как в telebot поверх вложений MAX (location — координаты
на верхнем уровне вложения, contact — payload {name, vcf_phone, vcf_info}).

Попутно: Api.send_message шлёт notify=false явно (у NewMessageBody.notify
серверный default true) и принимает timeout; MaxiBot.send_message получил
параметр timeout, как в telebot.

Запуск:
    python3 tests/test_send_location_contact_venue.py
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
from maxibot.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


def sent_response(text, attachments):
    """Ответ POST /messages, как его отдаёт MAX."""
    return {"message": {
        "sender": {"user_id": 7, "name": "bot", "is_bot": True},
        "recipient": {"chat_id": 42, "chat_type": "chat"},
        "timestamp": 1757000000000,
        "body": {"mid": "mid.1", "seq": 1, "text": text, "attachments": attachments or []},
    }}


class RecordingApi:
    def __init__(self):
        self.calls = []
        self.response = None      # если задан — вернуть его из send_message
        self.messages = {}        # msg_id -> сырое сообщение для get_message
        self.chat_info_requests = []

    def get_chat_info(self, chat_id=None, **kwargs):
        self.chat_info_requests.append(chat_id)
        return {"title": "Тестовый чат"}

    def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        if self.response is not None:
            return self.response
        return sent_response(kwargs.get("text"), kwargs.get("attachments"))

    def get_message(self, msg_id=None):
        self.calls.append(("get_message", {"msg_id": msg_id}))
        return self.messages[msg_id]


def make_keyboard():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Кнопка", callback_data="cb"))
    return kb


# 1. Сигнатуры один в один с telebot
for name in ("send_location", "send_contact", "send_venue",
             "edit_message_live_location", "stop_message_live_location"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры всех пяти методов как в telebot")

bot = MaxiBot("t", threaded=False)
bot.api = RecordingApi()

# 2. send_location: location-вложение с координатами на верхнем уровне
msg = bot.send_location(42, 55.75, 37.61)
call_name, kw = bot.api.calls[-1]
assert call_name == "send_message"
assert kw["chat_id"] == "42", kw["chat_id"]
assert kw["text"] is None
assert kw["attachments"] == [{"type": "location", "latitude": 55.75, "longitude": 37.61}], kw["attachments"]
assert kw["notify"] is True
assert kw["link"] is None
assert kw["timeout"] is None
assert isinstance(msg, Message) and msg.message_id == "mid.1"
assert msg.content_type == "location", msg.content_type
print("2 ok: send_location шлёт {type: location, latitude, longitude} без payload")

# 3. send_location: клавиатура, реплай, без звука, таймаут
msg = bot.send_location(42, 1.5, 2.5, reply_to_message_id="mid.0",
                        reply_markup=make_keyboard(), disable_notification=True,
                        timeout=9)
_, kw = bot.api.calls[-1]
assert kw["attachments"][0]["type"] == "location"
assert kw["attachments"][1]["type"] == "inline_keyboard", kw["attachments"][1]
assert kw["notify"] is False
assert kw["link"] == {"type": "reply", "mid": "mid.0"}
assert kw["timeout"] == 9
print("3 ok: reply_markup вторым вложением, notify=False, link reply, timeout")

# 4. live_period игнорируется с предупреждением; reply_parameters.message_id работает
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    bot.send_location(42, 1.0, 2.0, live_period=60)
finally:
    logging.getLogger("maxibot").removeHandler(capture)
assert any("live_period" in w for w in capture.warnings()), capture.warnings()
_, kw = bot.api.calls[-1]
assert kw["attachments"] == [{"type": "location", "latitude": 1.0, "longitude": 2.0}]


class ReplyParams:
    message_id = "mid.9"


bot.send_location(42, 1.0, 2.0, reply_parameters=ReplyParams())
_, kw = bot.api.calls[-1]
assert kw["link"] == {"type": "reply", "mid": "mid.9"}, kw["link"]

# конфликт: reply_parameters важнее устаревшего reply_to_message_id (как в
# telebot), с предупреждением
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    bot.send_location(42, 1.0, 2.0, reply_to_message_id="mid.OLD",
                      reply_parameters=ReplyParams())
finally:
    logging.getLogger("maxibot").removeHandler(capture)
_, kw = bot.api.calls[-1]
assert kw["link"] == {"type": "reply", "mid": "mid.9"}, kw["link"]
assert any("конфликт" in w for w in capture.warnings()), capture.warnings()
print("4 ok: live_period -> предупреждение; reply_parameters важнее "
      "reply_to_message_id, конфликт логируется")

# 5. send_contact: payload {name, vcf_phone[, vcf_info]}, единственное вложение
msg = bot.send_contact(42, "+79990001122", "Иван", last_name="Петров")
_, kw = bot.api.calls[-1]
assert kw["text"] is None
assert kw["attachments"] == [{
    "type": "contact",
    "payload": {"name": "Иван Петров", "vcf_phone": "+79990001122"},
}], kw["attachments"]
assert msg.content_type == "contact", msg.content_type

bot.send_contact(42, "+79990001122", "Иван")
_, kw = bot.api.calls[-1]
assert kw["attachments"][0]["payload"]["name"] == "Иван"

vcard = "BEGIN:VCARD\nVERSION:3.0\nFN:Иван Петров\nTEL:+79990001122\nEND:VCARD"
bot.send_contact(42, "+79990001122", "Иван", vcard=vcard)
_, kw = bot.api.calls[-1]
assert kw["attachments"][0]["payload"]["vcf_info"] == vcard
print("5 ok: контакт — name из имени/фамилии, vcf_phone, vcard -> vcf_info")

# 6. send_contact: reply_markup игнорируется с предупреждением (контакт обязан
#    быть единственным вложением)
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    bot.send_contact(42, "+79990001122", "Иван", reply_markup=make_keyboard())
finally:
    logging.getLogger("maxibot").removeHandler(capture)
assert any("единственным вложением" in w for w in capture.warnings()), capture.warnings()
_, kw = bot.api.calls[-1]
assert len(kw["attachments"]) == 1 and kw["attachments"][0]["type"] == "contact"
print("6 ok: reply_markup у контакта не прикладывается, есть предупреждение")

# 7. send_venue: location-вложение + текст «title\naddress» без разметки
msg = bot.send_venue(42, 55.0, 37.0, "Кафе «Пример»", "Тверская, 1",
                     reply_markup=make_keyboard())
_, kw = bot.api.calls[-1]
assert kw["text"] == "Кафе «Пример»\nТверская, 1"
assert kw["parse_mode"] == "", kw["parse_mode"]
assert kw["attachments"][0] == {"type": "location", "latitude": 55.0, "longitude": 37.0}
assert kw["attachments"][1]["type"] == "inline_keyboard"
assert kw["notify"] is True
print("7 ok: венью — локация + title/address сырым текстом, клавиатура разрешена")

# 8. Api.send_message: notify=false уходит в тело явно, timeout пробрасывается
calls = []


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"success": True}


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return FakeResponse()


real_request = requests.Session.request
requests.Session.request = fake_request
try:
    api = Api("tok")
    api.send_message(chat_id="42", text="привет", notify=False, timeout=7)
    kw = calls[-1]
    assert kw["method"] == "POST"
    assert kw["url"] == "https://platform-api2.max.ru/messages", kw["url"]
    assert kw["params"]["chat_id"] == "42"
    body = json.loads(kw["data"])
    assert body["notify"] is False, body
    assert kw["timeout"] == (7, 7), kw["timeout"]

    api.send_message(chat_id="42", text="привет")
    body = json.loads(calls[-1]["data"])
    assert body["notify"] is True
    assert calls[-1]["timeout"] == (15, 30), calls[-1]["timeout"]
finally:
    requests.Session.request = real_request
print("8 ok: notify=false в теле, timeout до requests, дефолтные таймауты целы")

# 9. MaxiBot.send_message: timeout как в telebot (0 -> «без своего»)
bot.send_message(42, "привет", timeout=5)
_, kw = bot.api.calls[-1]
assert kw["timeout"] == 5
bot.send_message(42, "привет", timeout=0)
_, kw = bot.api.calls[-1]
assert kw["timeout"] is None
print("9 ok: send_message передаёт timeout, 0 означает дефолт")

# 10. edit_message_live_location: PUT с новым location-вложением
bot.api.response = {"success": True}
result = bot.edit_message_live_location(10.0, 20.0, chat_id=42,
                                        message_id="mid.5",
                                        reply_markup=make_keyboard(), timeout=4)
_, kw = bot.api.calls[-1]
assert kw["method"] == "PUT"
assert kw["msg_id"] == "mid.5"
assert kw["attachments"][0] == {"type": "location", "latitude": 10.0, "longitude": 20.0}
assert kw["attachments"][1]["type"] == "inline_keyboard"
assert kw["notify"] is False, kw["notify"]  # переезд пина не шумит в чате
assert kw["timeout"] == 4
assert isinstance(result, Message) and result.message_id == "mid.5"

bot.api.response = {"success": False}
result = bot.edit_message_live_location(10.0, 20.0, chat_id=42, message_id="mid.5")
assert result == {}, result

# инлайн-сообщений в MAX нет: без message_id — понятный ValueError,
# а не UnboundLocalError из недр apihelper
try:
    bot.edit_message_live_location(10.0, 20.0, inline_message_id="i1")
    assert False, "ожидался ValueError"
except ValueError as e:
    assert "message_id" in str(e)
try:
    bot.stop_message_live_location(inline_message_id="i1")
    assert False, "ожидался ValueError"
except ValueError as e:
    assert "message_id" in str(e)

# chat_id можно не передавать: Message собирается без похода в GET /chats/None
bot.api.response = {"success": True}
result = bot.edit_message_live_location(10.0, 20.0, message_id="mid.5")
assert isinstance(result, Message) and result.message_id == "mid.5"
assert result.chat.title is None
assert None not in bot.api.chat_info_requests, bot.api.chat_info_requests
bot.api.response = None
print("10 ok: пин переезжает через PUT без notify, не-успех -> {}, "
      "message_id обязателен, chat_id опционален")

# 11. stop_message_live_location: без клавиатуры — просто вернуть сообщение
bot.api.messages["mid.7"] = {
    "sender": {"user_id": 7, "name": "bot", "is_bot": True},
    "recipient": {"chat_id": 42, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.7", "seq": 7, "text": None,
             "attachments": [{"type": "location", "latitude": 1.0, "longitude": 2.0}]},
}
before = len(bot.api.calls)
result = bot.stop_message_live_location(chat_id=42, message_id="mid.7")
assert isinstance(result, Message) and result.message_id == "mid.7"
sends = [c for c in bot.api.calls[before:] if c[0] == "send_message"]
assert not sends, sends
print("11 ok: stop без клавиатуры ничего не отправляет и возвращает сообщение")

# 12. stop_message_live_location с клавиатурой: PUT сохраняет текст и вложения,
#     старая клавиатура заменяется новой
bot.api.messages["mid.8"] = {
    "sender": {"user_id": 7, "name": "bot", "is_bot": True},
    "recipient": {"chat_id": 42, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.8", "seq": 8, "text": "Кафе\nТверская, 1",
             "attachments": [
                 {"type": "location", "latitude": 1.0, "longitude": 2.0},
                 {"type": "inline_keyboard", "payload": {"buttons": [[{"text": "старая"}]]}},
             ]},
}
bot.api.response = {"success": True}
result = bot.stop_message_live_location(chat_id=42, message_id="mid.8",
                                        reply_markup=make_keyboard())
bot.api.response = None
_, kw = bot.api.calls[-1]
assert kw["method"] == "PUT"
assert kw["msg_id"] == "mid.8"
assert kw["text"] == "Кафе\nТверская, 1"
assert kw["parse_mode"] is None
assert kw["notify"] is False, kw["notify"]  # смена клавиатуры без уведомления
assert kw["attachments"][0]["type"] == "location"
assert kw["attachments"][1]["type"] == "inline_keyboard"
assert kw["attachments"][1]["payload"]["buttons"][0][0]["text"] == "Кнопка", kw["attachments"][1]
assert len(kw["attachments"]) == 2
assert isinstance(result, Message) and result.message_id == "mid.8"
print("12 ok: stop с клавиатурой заменяет только клавиатуру, текст и пин целы")

print("ALL OK")

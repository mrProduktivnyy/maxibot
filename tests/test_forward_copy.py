"""
forward_message(s) и copy_message(s): пересылка в MAX встроена в отправку
(POST /messages с link={"type": "forward", "mid"}), копирование — эмуляция
GET /messages/{messageId} -> новый POST /messages с пересобранными
вложениями (медиа по token, стикер по code, локация по координатам).

Запуск:
    python3 tests/test_forward_copy.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

from maxibot import MaxiBot
from maxibot.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, Message, MessageID,
)
from maxibot.exceptions import MaxApiException


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


def sent_response(mid, text=None, attachments=None):
    return {"message": {
        "sender": {"user_id": 7, "name": "bot", "is_bot": True},
        "recipient": {"chat_id": 42, "chat_type": "chat"},
        "timestamp": 1757000000000,
        "body": {"mid": mid, "seq": 1, "text": text, "attachments": attachments or []},
    }}


class RecordingApi:
    def __init__(self):
        self.calls = []
        self.messages = {}      # mid -> сырое сообщение для get_message
        self.fail_mids = set()  # link.mid из этого множества -> ошибка API
        self.next_mid = 0

    def get_chat_info(self, chat_id=None, **kwargs):
        return {"title": "Тестовый чат"}

    def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        link = kwargs.get("link") or {}
        if link.get("mid") in self.fail_mids:
            raise MaxApiException("message.not.found", "POST /messages", None)
        self.next_mid += 1
        return sent_response(f"new.{self.next_mid}", kwargs.get("text"),
                             kwargs.get("attachments"))

    def get_message(self, msg_id=None):
        self.calls.append(("get_message", {"msg_id": msg_id}))
        if msg_id not in self.messages:
            raise MaxApiException("message.not.found", "GET /messages", None)
        return self.messages[msg_id]


def make_keyboard(text="Кнопка"):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text, callback_data="cb"))
    return kb


# 1. Сигнатуры один в один с telebot
for name in ("forward_message", "forward_messages", "copy_message", "copy_messages"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры всех четырёх методов как в telebot")

bot = MaxiBot("t", threaded=False)
bot.api = RecordingApi()

# 2. forward_message: link forward, пустое тело, chat int -> str
msg = bot.forward_message(42, 777, "mid.5")
name, kw = bot.api.calls[-1]
assert name == "send_message"
assert kw["chat_id"] == "42"
assert kw["text"] is None
assert not kw["attachments"]
assert kw["link"] == {"type": "forward", "mid": "mid.5"}, kw["link"]
assert kw["notify"] is True
assert kw["timeout"] is None
assert isinstance(msg, Message) and msg.message_id == "new.1"
print("2 ok: forward_message — POST /messages с link forward")

# 3. forward_message: без звука и с таймаутом (0 -> дефолт)
bot.forward_message(42, 777, "mid.5", disable_notification=True, timeout=7)
_, kw = bot.api.calls[-1]
assert kw["notify"] is False and kw["timeout"] == 7
bot.forward_message(42, 777, "mid.5", timeout=0)
assert bot.api.calls[-1][1]["timeout"] is None
print("3 ok: notify=False, timeout (0 -> дефолт)")

# 4. forward_messages: не пересланные пропускаются с предупреждением
bot.api.fail_mids = {"mid.bad"}
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    result = bot.forward_messages(42, 777, ["mid.a", "mid.bad", "mid.b"])
finally:
    logging.getLogger("maxibot").removeHandler(capture)
assert len(result) == 2 and all(isinstance(r, MessageID) for r in result), result
assert [r.message_id for r in result] == ["new.4", "new.5"], [r.message_id for r in result]
assert any("mid.bad" in w for w in capture.warnings()), capture.warnings()
bot.api.fail_mids = set()
print("4 ok: forward_messages пропускает не найденные и возвращает MessageID")

# 5. copy_message: пересборка вложений — медиа по token, стикер по code,
#    локация по координатам; клавиатура и share оригинала не копируются
bot.api.messages["mid.src"] = {
    "sender": {"user_id": 1, "name": "u"},
    "recipient": {"chat_id": 1, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.src", "seq": 1, "text": "исходный текст", "attachments": [
        {"type": "image", "payload": {"photo_id": 1, "token": "img-tok", "url": "https://i"}},
        {"type": "video", "payload": {"token": "vid-tok", "url": "https://v"}},
        {"type": "audio", "payload": {"token": "aud-tok", "url": "https://a"}, "transcription": "т"},
        {"type": "file", "payload": {"token": "file-tok", "url": "https://f"}, "filename": "f.txt", "size": 3},
        {"type": "sticker", "payload": {"code": "stk-1", "url": "https://s"}, "width": 128, "height": 128},
        {"type": "location", "latitude": 55.75, "longitude": 37.61},
        {"type": "inline_keyboard", "payload": {"buttons": [[{"text": "старая"}]]}},
        {"type": "share", "payload": {"url": "https://share"}},
    ]},
}
result = bot.copy_message(42, 777, "mid.src")
assert isinstance(result, MessageID) and result.message_id.startswith("new."), result.message_id
_, kw = bot.api.calls[-1]
assert kw["text"] == "исходный текст"
assert kw["parse_mode"] is None  # исходный текст без повторной разметки
assert kw["link"] is None  # копия, не пересылка
assert kw["attachments"] == [
    {"type": "image", "payload": {"token": "img-tok"}},
    {"type": "video", "payload": {"token": "vid-tok"}},
    {"type": "audio", "payload": {"token": "aud-tok"}},
    {"type": "file", "payload": {"token": "file-tok"}},
    {"type": "sticker", "payload": {"code": "stk-1"}},
    {"type": "location", "latitude": 55.75, "longitude": 37.61},
], kw["attachments"]
print("5 ok: copy_message пересобирает вложения, клавиатура и share не копируются")

# 6. copy_message: caption заменяет текст (с parse_mode), reply и клавиатура
#    (источник — фото: без вложений «MUST be the only attachment»)
bot.api.messages["mid.photo"] = {
    "recipient": {"chat_id": 1, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.photo", "seq": 9, "text": "подпись фото", "attachments": [
        {"type": "image", "payload": {"photo_id": 2, "token": "img2-tok", "url": "https://i2"}},
    ]},
}
result = bot.copy_message(42, 777, "mid.photo", caption="новый текст",
                          parse_mode="HTML", reply_to_message_id="mid.r",
                          reply_markup=make_keyboard())
_, kw = bot.api.calls[-1]
assert kw["text"] == "новый текст"
assert kw["parse_mode"] == "html"
assert kw["link"] == {"type": "reply", "mid": "mid.r"}
assert kw["attachments"][-1]["type"] == "inline_keyboard"
assert kw["attachments"][-1]["payload"]["buttons"][0][0]["text"] == "Кнопка"


class ReplyParams:
    message_id = "mid.rp"


bot.copy_message(42, 777, "mid.photo", reply_parameters=ReplyParams())
_, kw = bot.api.calls[-1]
assert kw["link"] == {"type": "reply", "mid": "mid.rp"}
print("6 ok: caption с разметкой, reply, новая клавиатура")

# 7. copy_message: контакт пересобирается из vcf_info и max_info
bot.api.messages["mid.contact"] = {
    "recipient": {"chat_id": 1, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.contact", "seq": 2, "text": None, "attachments": [
        {"type": "contact", "payload": {
            "vcf_info": "BEGIN:VCARD\nEND:VCARD",
            "max_info": {"user_id": 99, "name": "Иван Петров"},
        }},
    ]},
}
bot.copy_message(42, 777, "mid.contact")
_, kw = bot.api.calls[-1]
assert kw["attachments"] == [{"type": "contact", "payload": {
    "name": "Иван Петров", "contact_id": 99, "vcf_info": "BEGIN:VCARD\nEND:VCARD",
}}], kw["attachments"]
print("7 ok: контакт пересобран с name/contact_id/vcf_info")

# 8. copy_messages: remove_caption и пропуск не найденных
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    result = bot.copy_messages(42, 777, ["mid.src", "mid.missing"], remove_caption=True)
finally:
    logging.getLogger("maxibot").removeHandler(capture)
assert len(result) == 1 and isinstance(result[0], MessageID), result
kw = [c[1] for c in bot.api.calls if c[0] == "send_message"][-1]
assert kw["text"] is None  # remove_caption
assert any("mid.missing" in w for w in capture.warnings()), capture.warnings()
print("8 ok: copy_messages без текста, не найденное пропущено")

# 9. Копия пересылки: у чистой пересылки контент лежит в link.message
#    (body по спеке может быть null), у пересылки с комментарием
#    копируется комментарий
bot.api.messages["mid.fwd"] = {
    "recipient": {"chat_id": 1, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": None,
    "link": {"type": "forward", "message": {
        "mid": "mid.orig", "seq": 1, "text": "исходный текст пересылки",
        "attachments": [{"type": "image", "payload": {"photo_id": 1, "token": "fwd-tok", "url": "https://i"}}],
    }},
}
bot.copy_message(42, 777, "mid.fwd")
_, kw = bot.api.calls[-1]
assert kw["text"] == "исходный текст пересылки", kw["text"]
assert kw["attachments"] == [{"type": "image", "payload": {"token": "fwd-tok"}}], kw["attachments"]

bot.api.messages["mid.fwd2"] = {
    "recipient": {"chat_id": 1, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.fwd2", "seq": 2, "text": "комментарий", "attachments": []},
    "link": {"type": "forward", "message": {"mid": "mid.orig", "seq": 1, "text": "оригинал"}},
}
bot.copy_message(42, 777, "mid.fwd2")
_, kw = bot.api.calls[-1]
assert kw["text"] == "комментарий", kw["text"]
print("9 ok: чистая пересылка копируется из link.message, с комментарием — комментарий")

# 10. remove_caption снимает только подпись медиа: чисто текстовое
#     сообщение копируется с текстом (как в telebot)
bot.api.messages["mid.textonly"] = {
    "recipient": {"chat_id": 1, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.textonly", "seq": 3, "text": "просто текст", "attachments": []},
}
result = bot.copy_messages(42, 777, ["mid.textonly"], remove_caption=True)
assert len(result) == 1
kw = [c[1] for c in bot.api.calls if c[0] == "send_message"][-1]
assert kw["text"] == "просто текст", kw["text"]
print("10 ok: remove_caption не трогает чисто текстовые сообщения")

# 11. Клавиатура к копии аудио (MUST be the only attachment) — предупреждение
#     и без клавиатуры
bot.api.messages["mid.audio"] = {
    "recipient": {"chat_id": 1, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.audio", "seq": 4, "text": None, "attachments": [
        {"type": "audio", "payload": {"token": "aud-tok", "url": "https://a"}},
    ]},
}
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    bot.copy_message(42, 777, "mid.audio", reply_markup=make_keyboard())
finally:
    logging.getLogger("maxibot").removeHandler(capture)
_, kw = bot.api.calls[-1]
assert kw["attachments"] == [{"type": "audio", "payload": {"token": "aud-tok"}}], kw["attachments"]
assert any("единственным вложением" in w for w in capture.warnings()), capture.warnings()
print("11 ok: клавиатура к копии аудио игнорируется с предупреждением")

# 12. Контакт со спековым User (first_name/last_name, поля name нет)
bot.api.messages["mid.contact2"] = {
    "recipient": {"chat_id": 1, "chat_type": "chat"},
    "timestamp": 1757000000000,
    "body": {"mid": "mid.contact2", "seq": 5, "text": None, "attachments": [
        {"type": "contact", "payload": {
            "vcf_info": None,
            "max_info": {"user_id": 99, "first_name": "Иван", "last_name": "Петров"},
        }},
    ]},
}
bot.copy_message(42, 777, "mid.contact2")
_, kw = bot.api.calls[-1]
assert kw["attachments"][0]["payload"]["name"] == "Иван Петров", kw["attachments"]
print("12 ok: имя контакта собирается из first_name/last_name спекового User")

# 13. forward_message переживает ответ с body: null (по спеке — сообщение,
#     содержащее только пересылку)
class NullBodyApi(RecordingApi):
    def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        return {"message": {
            "sender": {"user_id": 7, "name": "bot", "is_bot": True},
            "recipient": {"chat_id": 42, "chat_type": "chat"},
            "timestamp": 1757000000000,
            "body": None,
            "link": {"type": "forward", "message": {"mid": "mid.orig", "seq": 1, "text": "x"}},
        }}


bot2 = MaxiBot("t", threaded=False)
bot2.api = NullBodyApi()
msg = bot2.forward_message(42, 777, "mid.5")
assert isinstance(msg, Message)
assert msg.message_id is None  # mid недоступен при body: null
print("13 ok: ответ с body: null не роняет разбор Message")

print("ALL OK")

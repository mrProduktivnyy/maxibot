"""
send_audio и send_voice: родной тип загрузки audio в MAX
(POST /uploads?type=audio — токен сразу в ответе, как у видео),
вложение {"type": "audio", "payload": {"token": ...}}.

send_voice — тонкая обёртка над send_audio: отдельного типа голосовых
в MAX нет. По спеке аудио обязано быть единственным вложением —
reply_markup игнорируется с предупреждением.

Запуск:
    python3 tests/test_send_audio_voice.py
"""
import inspect
import io
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None  # ускоряем ретраи

import requests
import telebot

from maxibot import MaxiBot
from maxibot.apihelper import Api
from maxibot.types import (
    InputMediaAudio, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from maxibot.exceptions import MaxApiHTTPException


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
        "body": {"mid": "mid.123", "seq": 5, "text": "hi", "attachments": [
            {"type": "audio", "payload": {"token": "aud-token"}}
        ]},
    }
}
GET_READY = {"recipient": SEND_OK["message"]["recipient"], "body": SEND_OK["message"]["body"]}


class FakeResponse:
    def __init__(self, status_code, text, reason="Error"):
        self.status_code = status_code
        self.text = text
        self.reason = reason


def not_ready_error():
    return MaxApiHTTPException(
        function_name="POST /messages",
        result=FakeResponse(400, '{"code": "attachment.not.ready"}', "Bad Request")
    )


NOT_READY = object()


class FakeApi:
    """Аудио-вариант: token отдаётся в ответе /uploads, ответ загрузки — пустой."""

    def __init__(self, send_responses=None):
        self.send_responses = list(send_responses or [SEND_OK])
        self.upload_calls = []
        self.load_calls = []
        self.send_kwargs = []

    def get_upload_file_url(self, type_attach):
        self.upload_calls.append(type_attach)
        return {"url": "https://upload", "token": "aud-token"}

    def load_file(self, url, files, content_types=None):
        self.load_calls.append(url)
        return {}  # у аудио, как у видео, токена в ответе загрузки нет

    def send_message(self, **kwargs):
        self.send_kwargs.append(kwargs)
        resp = self.send_responses.pop(0) if self.send_responses else SEND_OK
        if resp is NOT_READY:
            raise not_ready_error()
        return resp

    def get_message(self, mid):
        return GET_READY

    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot(api):
    bot = MaxiBot("t")
    bot.api = api
    bot.send_retry_timeout = 120
    bot.publish_wait_timeout = 10
    return bot


# 1. Сигнатуры один в один с telebot
for name in ("send_audio", "send_voice"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры send_audio и send_voice как в telebot")

# 2. Байты аудио: upload с type=audio, файл загружен, вложение с токеном из /uploads
api = FakeApi()
msg = make_bot(api).send_audio(42, io.BytesIO(b'audio-bytes'))
assert api.upload_calls == ["audio"], api.upload_calls
assert api.load_calls == ["https://upload"], api.load_calls
attachments = api.send_kwargs[0]["attachments"]
assert attachments == [{"type": "audio", "payload": {"token": "aud-token"}}], attachments
assert isinstance(msg, Message) and msg.message_id == "mid.123"
assert msg.content_type == "audio", msg.content_type
print('2 ok: загрузка и вложение {"type": "audio", "payload": {"token": ...}}')

# 3. Api-уровень: POST /uploads?type=audio реально уходит на platform-api2
calls = []


class OkResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"url": "https://upload.example/1", "token": "t"}


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return OkResponse()


real_request = requests.Session.request
requests.Session.request = fake_request
try:
    Api("tok").get_upload_file_url(type_attach="audio")
    kw = calls[-1]
    assert kw["method"] == "POST"
    assert kw["url"] == "https://platform-api2.max.ru/uploads?type=audio", kw["url"]
finally:
    requests.Session.request = real_request
print("3 ok: POST /uploads?type=audio")

# 4. caption/parse_mode; телеботовский позиционный порядок (duration, performer,
#    title принимаются и игнорируются)
api = FakeApi()
make_bot(api).send_audio(42, io.BytesIO(b'a'), "подпись", 180, "Исполнитель",
                         "Название", None, None, "HTML")
kw = api.send_kwargs[0]
assert kw["text"] == "подпись", kw
assert kw["parse_mode"] == "html", kw
print("4 ok: позиционный порядок как в telebot, метаданные игнорируются")

# 5. reply_markup игнорируется с предупреждением (аудио — единственное вложение)
api = FakeApi()
markup = InlineKeyboardMarkup()
markup.add(InlineKeyboardButton("кнопка", callback_data="d"))
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    make_bot(api).send_audio(42, io.BytesIO(b'a'), reply_markup=markup)
finally:
    logging.getLogger("maxibot").removeHandler(capture)
assert any("единственным вложением" in w for w in capture.warnings()), capture.warnings()
attachments = api.send_kwargs[0]["attachments"]
assert len(attachments) == 1 and attachments[0]["type"] == "audio", attachments
print("5 ok: reply_markup у аудио не прикладывается, есть предупреждение")

# 6. reply/notify/timeout доходят до api.send_message через _send_attachments
api = FakeApi()
make_bot(api).send_audio(42, io.BytesIO(b'a'), reply_to_message_id="mid.0",
                         disable_notification=True, timeout=9)
kw = api.send_kwargs[0]
assert kw["link"] == {"type": "reply", "mid": "mid.0"}, kw
assert kw["notify"] is False, kw
assert kw["timeout"] == 9, kw
api = FakeApi()
make_bot(api).send_audio(42, io.BytesIO(b'a'), timeout=0)
assert api.send_kwargs[0]["timeout"] is None, api.send_kwargs[0]


class ReplyParams:
    message_id = "mid.9"


api = FakeApi()
make_bot(api).send_audio(42, io.BytesIO(b'a'), reply_parameters=ReplyParams())
assert api.send_kwargs[0]["link"] == {"type": "reply", "mid": "mid.9"}
print("6 ok: link reply, notify=False, timeout (0 -> дефолт), reply_parameters")

# 7. URL-строка не поддерживается; InputMediaAudio используется напрямую;
#    не-URL строка — токен ранее загруженного аудио (аналог file_id),
#    без повторной загрузки
api = FakeApi()
try:
    make_bot(api).send_audio(42, "https://example.com/a.mp3")
    assert False, "ожидался ValueError"
except ValueError as e:
    assert "URL" in str(e)
api = FakeApi()
make_bot(api).send_audio(42, InputMediaAudio(media=io.BytesIO(b'a')))
assert api.upload_calls == ["audio"]
assert api.send_kwargs[0]["attachments"][0]["type"] == "audio"
api = FakeApi()
make_bot(api).send_audio(42, "старый-токен-аудио")
assert api.upload_calls == [] and api.load_calls == [], (api.upload_calls, api.load_calls)
assert api.send_kwargs[0]["attachments"] == [
    {"type": "audio", "payload": {"token": "старый-токен-аудио"}}
], api.send_kwargs[0]["attachments"]
print("7 ok: URL -> ValueError, InputMediaAudio напрямую, строка -> токен")

# 8. attachment.not.ready ретраится, файл повторно не загружается
api = FakeApi([NOT_READY, SEND_OK])
msg = make_bot(api).send_audio(42, io.BytesIO(b'a'))
assert len(api.send_kwargs) == 2, len(api.send_kwargs)
assert api.load_calls == ["https://upload"], api.load_calls
assert msg.message_id == "mid.123"
print("8 ok: ретраи без повторной загрузки")

# 9. send_voice — обёртка над send_audio с теми же проводами
api = FakeApi()
msg = make_bot(api).send_voice(42, io.BytesIO(b'voice'), caption="подпись",
                               reply_to_message_id="mid.0",
                               disable_notification=True, timeout=3)
assert api.upload_calls == ["audio"]
kw = api.send_kwargs[0]
assert kw["attachments"][0] == {"type": "audio", "payload": {"token": "aud-token"}}
assert kw["text"] == "подпись"
assert kw["link"] == {"type": "reply", "mid": "mid.0"}
assert kw["notify"] is False
assert kw["timeout"] == 3
assert isinstance(msg, Message) and msg.message_id == "mid.123"
print("9 ok: send_voice уходит обычным аудио со всеми параметрами")

# 10. content_types=['voice'] не сработает никогда — message_handler
#     предупреждает и подсказывает 'audio' (тип не переименовывается)
bot = make_bot(FakeApi())
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    @bot.message_handler(content_types=['voice'])
    def _voice_handler(message):
        pass
finally:
    logging.getLogger("maxibot").removeHandler(capture)
warning_text = " ".join(capture.warnings())
assert "voice" in warning_text and "audio" in warning_text, capture.warnings()
assert bot.message_handlers[-1]["filters"]["content_types"] == ["voice"]
print("10 ok: подписка на 'voice' предупреждает и подсказывает 'audio'")

print("ALL OK")

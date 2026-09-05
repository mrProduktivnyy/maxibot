"""
send_animation и send_video_note: отдельных типов в MAX нет — честная
деградация через видеоконвейер (POST /uploads?type=video, вложение
{"type": "video", "payload": {"token": ...}}).

- send_animation: файл — обычным видео; http(s)-ссылка (гифка) —
  вложением {"type": "image", "payload": {"url"}} (MAX скачает сам);
  прочая строка — токен ранее загруженного видео.
- send_video_note: файл — обычным видео (придёт прямоугольным);
  URL — ValueError (как в telebot); duration/length игнорируются.
- Строка у видео теперь всюду токен (file_id-паттерн) — чинит
  и send_video.

Запуск:
    python3 tests/test_send_animation_video_note.py
"""
import inspect
import io
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None  # ускоряем ретраи

import telebot

from maxibot import MaxiBot
from maxibot.types import (
    InputMedia, InputMediaVideo, InlineKeyboardButton, InlineKeyboardMarkup,
    Message,
)


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
            {"type": "video", "payload": {"token": "vid-token"}}
        ]},
    }
}


class FakeApi:
    """Видео-вариант: token отдаётся в ответе /uploads, ответ загрузки — пустой."""

    def __init__(self):
        self.upload_calls = []
        self.load_calls = []
        self.send_kwargs = []

    def get_upload_file_url(self, type_attach):
        self.upload_calls.append(type_attach)
        return {"url": "https://upload", "token": "vid-token"}

    def load_file(self, url, files, content_types=None):
        self.load_calls.append(url)
        return {}

    def send_message(self, **kwargs):
        self.send_kwargs.append(kwargs)
        return SEND_OK

    def get_message(self, mid):
        return {"recipient": SEND_OK["message"]["recipient"],
                "body": SEND_OK["message"]["body"]}

    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot(api):
    bot = MaxiBot("t")
    bot.api = api
    bot.send_retry_timeout = 120
    bot.publish_wait_timeout = 10
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
for name in ("send_animation", "send_video_note"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры send_animation и send_video_note как в telebot")

# 2. Анимация-файл: загрузка type=video, вложение с токеном, content_type "video"
api = FakeApi()
msg = make_bot(api).send_animation(42, io.BytesIO(b'gif-bytes'))
assert api.upload_calls == ["video"], api.upload_calls
assert api.load_calls == ["https://upload"], api.load_calls
kw = api.send_kwargs[0]
assert kw["attachments"] == [{"type": "video", "payload": {"token": "vid-token"}}], kw["attachments"]
assert isinstance(msg, Message) and msg.message_id == "mid.123"
assert msg.content_type == "video", msg.content_type
print("2 ok: файл анимации уходит обычным видео")

# 3. Анимация-URL (гифка): вложение image с url, без загрузки
api = FakeApi()
make_bot(api).send_animation(42, "https://example.com/fun.gif")
assert api.upload_calls == [] and api.load_calls == []
kw = api.send_kwargs[0]
assert kw["attachments"] == [
    {"type": "image", "payload": {"url": "https://example.com/fun.gif"}}
], kw["attachments"]
print("3 ok: URL-гифка уходит картинкой (MAX скачает сам)")

# 4. Анимация-строка (не URL): токен ранее загруженного видео, без загрузки;
#    InputMediaVideo — напрямую
api = FakeApi()
make_bot(api).send_animation(42, "старый-токен-видео")
assert api.upload_calls == [] and api.load_calls == []
assert api.send_kwargs[0]["attachments"] == [
    {"type": "video", "payload": {"token": "старый-токен-видео"}}
], api.send_kwargs[0]["attachments"]
api = FakeApi()
make_bot(api).send_animation(42, InputMediaVideo(media=io.BytesIO(b'v')))
assert api.upload_calls == ["video"]
assert api.send_kwargs[0]["attachments"][0]["type"] == "video"
print("4 ok: строка -> токен видео, InputMediaVideo напрямую")

# 5. Телеботовский позиционный порядок: duration/width/height/thumbnail
#    игнорируются, caption/parse_mode на своих местах
api = FakeApi()
make_bot(api).send_animation(42, io.BytesIO(b'v'), 10, 640, 480, None,
                             "подпись", "HTML")
kw = api.send_kwargs[0]
assert kw["text"] == "подпись", kw
assert kw["parse_mode"] == "html", kw
print("5 ok: позиционный порядок как в telebot, метаданные игнорируются")

# 6. Клавиатура у видео прикладывается (MUST be alone у видео нет)
api = FakeApi()
markup = InlineKeyboardMarkup()
markup.add(InlineKeyboardButton("кнопка", callback_data="d"))
_, warns = capture_warnings(
    lambda: make_bot(api).send_animation(42, io.BytesIO(b'v'), reply_markup=markup)
)
attachments = api.send_kwargs[0]["attachments"]
assert len(attachments) == 2, attachments
assert attachments[0]["type"] == "video" and attachments[1]["type"] == "inline_keyboard", attachments
assert not any("единственным вложением" in w for w in warns), warns
print("6 ok: reply_markup у анимации прикладывается вложением")

# 7. reply/notify/timeout; timeout=0 -> None; reply_parameters важнее
api = FakeApi()
make_bot(api).send_animation(42, io.BytesIO(b'v'), reply_to_message_id="mid.0",
                             disable_notification=True, timeout=9)
kw = api.send_kwargs[0]
assert kw["link"] == {"type": "reply", "mid": "mid.0"}, kw
assert kw["notify"] is False, kw
assert kw["timeout"] == 9, kw
api = FakeApi()
make_bot(api).send_animation(42, io.BytesIO(b'v'), timeout=0)
assert api.send_kwargs[0]["timeout"] is None


class ReplyParams:
    message_id = "mid.9"


api = FakeApi()
_, warns = capture_warnings(
    lambda: make_bot(api).send_animation(42, io.BytesIO(b'v'),
                                         reply_to_message_id="mid.0",
                                         reply_parameters=ReplyParams())
)
assert api.send_kwargs[0]["link"] == {"type": "reply", "mid": "mid.9"}
assert any("send_animation" in w and "конфликт" in w for w in warns), warns
print("7 ok: link reply, notify=False, timeout, reply_parameters важнее")

# 8. Кружок-файл: обычное видео, text None (подписи у кружка нет),
#    duration/length позиционно игнорируются
api = FakeApi()
msg = make_bot(api).send_video_note(42, io.BytesIO(b'note'), 10, 240)
assert api.upload_calls == ["video"]
kw = api.send_kwargs[0]
assert kw["attachments"] == [{"type": "video", "payload": {"token": "vid-token"}}]
assert kw["text"] is None, kw
assert isinstance(msg, Message) and msg.content_type == "video"
print("8 ok: кружок уходит обычным видео, duration/length игнорируются")

# 9. Кружок: URL -> ValueError (как в telebot); строка -> токен;
#    reply/notify/timeout/клавиатура
try:
    make_bot(FakeApi()).send_video_note(42, "https://example.com/note.mp4")
    assert False, "ожидался ValueError"
except ValueError as e:
    assert "URL" in str(e), str(e)
api = FakeApi()
make_bot(api).send_video_note(42, "старый-токен-видео")
assert api.upload_calls == []
assert api.send_kwargs[0]["attachments"] == [
    {"type": "video", "payload": {"token": "старый-токен-видео"}}
]
api = FakeApi()
markup = InlineKeyboardMarkup()
markup.add(InlineKeyboardButton("кнопка", callback_data="d"))
make_bot(api).send_video_note(42, io.BytesIO(b'v'), reply_to_message_id="mid.0",
                              reply_markup=markup, disable_notification=True,
                              timeout=3)
kw = api.send_kwargs[0]
assert kw["link"] == {"type": "reply", "mid": "mid.0"}
assert kw["notify"] is False
assert kw["timeout"] == 3
assert len(kw["attachments"]) == 2 and kw["attachments"][1]["type"] == "inline_keyboard"
print("9 ok: URL -> ValueError, строка -> токен, reply/notify/timeout/клавиатура")

# 10. Строка у send_video — теперь тоже токен (file_id-паттерн, без загрузки)
api = FakeApi()
make_bot(api).send_video(42, "старый-токен-видео")
assert api.upload_calls == [] and api.load_calls == [], (api.upload_calls, api.load_calls)
assert api.send_kwargs[0]["attachments"] == [
    {"type": "video", "payload": {"token": "старый-токен-видео"}}
], api.send_kwargs[0]["attachments"]
print("10 ok: строка у send_video — токен, без повторной загрузки")

# 11. Подписка на content_types=['animation'] / ['video_note'] предупреждает
#     и подсказывает реальный тип (сам тип не переименовывается)
for name in ("animation", "video_note"):
    bot = make_bot(FakeApi())
    _, warns = capture_warnings(lambda: bot.message_handler(content_types=[name])(lambda m: None))
    warning_text = " ".join(warns)
    assert name in warning_text and "video" in warning_text, (name, warns)
    assert bot.message_handlers[-1]["filters"]["content_types"] == [name]
print("11 ok: подписка на 'animation'/'video_note' предупреждает про 'video'")

# 12. URL внутри InputMediaVideo не проскакивает мимо guard'ов —
#     to_dict ловит его сам (телеботовская идиома InputMediaVideo(url))
for method, media in (
    ("send_video", InputMediaVideo(media="https://example.com/v.mp4")),
    ("send_animation", InputMediaVideo(media="https://example.com/v.mp4")),
    ("send_video_note", InputMediaVideo(media="https://example.com/v.mp4")),
):
    api = FakeApi()
    try:
        getattr(make_bot(api), method)(42, media)
        assert False, f"ожидался ValueError у {method}"
    except ValueError as e:
        assert "URL" in str(e), (method, str(e))
    assert api.send_kwargs == [], (method, api.send_kwargs)
print("12 ok: URL внутри InputMediaVideo -> ValueError, на сервер не уходит")

# 13. URL-анимация с очевидным видеорасширением -> ValueError с объяснением
#     (телеботовские анимации часто .mp4); гифка с query-строкой проходит
for bad in ("https://example.com/anim.mp4", "https://example.com/anim.MP4?x=1",
            "https://example.com/anim.webm#t"):
    try:
        make_bot(FakeApi()).send_animation(42, bad)
        assert False, f"ожидался ValueError для {bad}"
    except ValueError as e:
        assert "видеофайл" in str(e), (bad, str(e))
api = FakeApi()
make_bot(api).send_animation(42, "https://example.com/fun.gif?size=big")
assert api.send_kwargs[0]["attachments"] == [
    {"type": "image", "payload": {"url": "https://example.com/fun.gif?size=big"}}
]
print("13 ok: URL-.mp4 у анимации -> ValueError, гифка с query проходит")

print("ALL OK")

"""
Проверка send_video (issue #38).

Сигнатура — как у telebot.send_video: первые позиционные параметры
(chat_id, video, duration, width, height, thumbnail, caption, parse_mode).
На стороне MAX: POST /uploads?type=video возвращает url И token сразу
(в отличие от фото/файлов, где token приходит после загрузки), файл
загружается по url, сообщение уходит с вложением
{"type": "video", "payload": {"token": ...}}.

Запуск:
    python3 tests/test_send_video.py
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None  # ускоряем ретраи

from maxibot import MaxiBot
from maxibot.types import InputMedia, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from maxibot.exceptions import MaxApiHTTPException

SEND_OK = {
    "message": {
        "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.123", "seq": 5, "text": "hi", "attachments": [
            {"type": "video", "payload": {"token": "vid-token"}}
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
    """Видео-вариант: token отдаётся в ответе /uploads, ответ загрузки — пустой."""

    def __init__(self, send_responses=None):
        self.send_responses = list(send_responses or [SEND_OK])
        self.upload_calls = []
        self.load_calls = []
        self.send_kwargs = []

    def get_upload_file_url(self, type_attach):
        self.upload_calls.append(type_attach)
        return {"url": "https://upload", "token": "vid-token"}

    def load_file(self, url, files, content_types=None):
        self.load_calls.append(url)
        return {}  # у видео токена в ответе загрузки нет

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
    bot = MaxiBot("t")  # конструктор сеть не трогает
    bot.api = api
    bot.send_retry_timeout = 120
    bot.publish_wait_timeout = 10
    return bot


# 1. Байты видео: upload с type=video, файл загружен, вложение с токеном из /uploads
api = FakeApi()
msg = make_bot(api).send_video(42, io.BytesIO(b'video-bytes'))
assert api.upload_calls == ["video"], api.upload_calls
assert api.load_calls == ["https://upload"], api.load_calls
attachments = api.send_kwargs[0]["attachments"]
assert attachments == [{"type": "video", "payload": {"token": "vid-token"}}], attachments
assert msg.message_id == "mid.123"
print('1 ok: загрузка и вложение {"type": "video", "payload": {"token": ...}}')

# 2. caption и parse_mode доходят до отправки (parse_mode приводится к нижнему регистру)
api = FakeApi()
make_bot(api).send_video(42, io.BytesIO(b'v'), caption="подпись", parse_mode="HTML")
kw = api.send_kwargs[0]
assert kw["text"] == "подпись", kw
assert kw["parse_mode"] == "html", kw
print('2 ok: caption и parse_mode')

# 3. telebot-порядок позиционных: duration, width, height, thumbnail принимаются и игнорируются
api = FakeApi()
make_bot(api).send_video(42, io.BytesIO(b'v'), 10, 640, 480, None, "подпись", "HTML")
kw = api.send_kwargs[0]
assert kw["text"] == "подпись", kw
assert kw["parse_mode"] == "html", kw
print('3 ok: позиционный порядок как в telebot')

# 4. InputMediaVideo как объект — используется напрямую
api = FakeApi()
make_bot(api).send_video(42, InputMediaVideo(media=io.BytesIO(b'v')))
assert api.upload_calls == ["video"]
assert api.send_kwargs[0]["attachments"][0]["type"] == "video"
print('4 ok: InputMediaVideo')

# 5. reply_markup добавляется вторым вложением
api = FakeApi()
markup = InlineKeyboardMarkup()
markup.add(InlineKeyboardButton("кнопка", callback_data="d"))
make_bot(api).send_video(42, io.BytesIO(b'v'), reply_markup=markup)
attachments = api.send_kwargs[0]["attachments"]
assert len(attachments) == 2 and attachments[1]["type"] == "inline_keyboard", attachments
print('5 ok: reply_markup')

# 6. disable_web_page_preview пробрасывается как disable_link_preview
api = FakeApi()
make_bot(api).send_video(42, io.BytesIO(b'v'), caption="http://x", disable_web_page_preview=True)
assert api.send_kwargs[0]["disable_link_preview"] is True, api.send_kwargs[0]
print('6 ok: disable_web_page_preview')

# 7. attachment.not.ready ретраится, файл повторно не загружается
api = FakeApi([NOT_READY, SEND_OK])
msg = make_bot(api).send_video(42, io.BytesIO(b'v'))
assert len(api.send_kwargs) == 2, len(api.send_kwargs)
assert api.load_calls == ["https://upload"], api.load_calls
assert msg.message_id == "mid.123"
print('7 ok: ретраи без повторной загрузки')

# 8. Регресс compare_types: у InputMedia(type="video") маппинг больше не None
media = InputMedia(type="video")
assert media.compare_types.get(media.type) == "video"
assert InputMedia.compare_types == {"photo": "image", "file": "file", "video": "video"}
print('8 ok: compare_types содержит video')

print('ALL OK')

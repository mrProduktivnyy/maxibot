"""
Файлы: get_file / get_file_url / download_file поверх прямых ссылок
и видео-токенов MAX, MAX-бонус get_video (GET /videos/{videoToken}),
вложения message.video/.audio/.document и телеботовский паттерн
message.photo[-1].file_id.

Запуск:
    python3 tests/test_files.py
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
from maxibot.exceptions import MaxApiHTTPException
from maxibot.types import Audio, Document, File, Message, Video, VideoUrls


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


DETAILS = {
    "token": "vid-tok",
    "urls": {"mp4_720": "https://cdn/v720.mp4", "mp4_144": "https://cdn/v144.mp4",
             "hls": "https://cdn/v.m3u8"},
    "thumbnail": {"url": "https://cdn/thumb.jpg"},
    "width": 640, "height": 480, "duration": 10,
}


class FakeApi:
    def __init__(self, details=None, error=None):
        self.details = details if details is not None else dict(DETAILS)
        self.error = error
        self.video_calls = []
        self.downloads = []

    def get_video(self, video_token, timeout=None):
        self.video_calls.append(video_token)
        if self.error:
            raise self.error
        return self.details

    def download_file(self, url, timeout=None):
        self.downloads.append(url)
        return b"file-bytes"

    def get_chat_info(self, chat_id):
        return {}


def make_bot(api):
    bot = MaxiBot("t")
    bot.api = api
    return bot


class FakeResponse:
    status_code = 404
    reason = "Not Found"
    text = "not found"


MEDIA_UPDATE = {
    "timestamp": 1725000000000,
    "message": {
        "sender": {"user_id": 1, "first_name": "Иван"},
        "recipient": {"chat_id": 10, "chat_type": "chat"},
        "body": {
            "mid": "mid.1", "seq": 1, "text": "подпись",
            "attachments": [
                {"type": "inline_keyboard", "payload": {"buttons": []}},
                {"type": "image",
                 "payload": {"photo_id": 5, "token": "img-tok",
                             "url": "https://cdn/img.jpg"}},
                {"type": "video",
                 "payload": {"token": "vid-tok",
                             "url": "https://max.ru/video/watch"},
                 "width": 640, "height": 480, "duration": 10,
                 "thumbnail": {"url": "https://cdn/thumb.jpg"}},
                {"type": "audio",
                 "payload": {"token": "aud-tok", "url": "https://cdn/a.mp3"},
                 "transcription": "привет"},
                {"type": "file",
                 "payload": {"token": "doc-tok", "url": "https://cdn/d.pdf"},
                 "filename": "d.pdf", "size": 2048},
            ],
        },
    },
}

# 1. Сигнатуры get_file / get_file_url / download_file как в telebot
for name in ("get_file", "get_file_url", "download_file"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры get_file/get_file_url/download_file как в telebot")

# 2. Вложения из сообщения: video/audio/document с телеботовскими полями
msg = Message(update=MEDIA_UPDATE, api=FakeApi())
assert isinstance(msg.video, Video) and msg.video.file_id == "vid-tok"
assert msg.video.width == 640 and msg.video.height == 480 and msg.video.duration == 10
assert msg.video.thumbnail.url == "https://cdn/thumb.jpg"
# превью несёт телеботовские поля PhotoSize и скачивается через file_path
assert msg.video.thumbnail.file_path == "https://cdn/thumb.jpg"
assert msg.video.thumbnail.file_id is None  # у VideoThumbnail токена нет
# устаревший телеботовский алиас .thumb живёт у всех трёх типов
assert msg.video.thumb is msg.video.thumbnail
assert msg.audio.thumb is None and msg.document.thumb is None
# payload.url видео — не прямая ссылка, file_path не подставляется
assert msg.video.file_path is None and msg.video.url == "https://max.ru/video/watch"
assert isinstance(msg.audio, Audio) and msg.audio.file_id == "aud-tok"
assert msg.audio.file_path == "https://cdn/a.mp3"
assert msg.audio.transcription == "привет" and msg.audio.duration is None
assert isinstance(msg.document, Document) and msg.document.file_id == "doc-tok"
assert msg.document.file_name == "d.pdf" and msg.document.file_size == 2048
assert msg.document.file_path == "https://cdn/d.pdf"
# голосовых в MAX нет — voice остаётся None даже при аудио-вложении
assert msg.voice is None
empty = Message(update={"message": {"sender": {}, "recipient": {"chat_id": 10},
                                    "body": {"mid": "m"}},
                        "timestamp": 1}, api=FakeApi())
assert empty.video is None and empty.audio is None and empty.document is None
print("2 ok: message.video/.audio/.document из вложений, voice всегда None")

# 3. message.photo: телеботовский паттерн photo[-1].file_id и прямые поля
assert msg.photo.file_id == "img-tok" and msg.photo.file_path == "https://cdn/img.jpg"
assert msg.photo[-1].file_id == "img-tok" and msg.photo[0] is msg.photo
assert len(msg.photo) == 1 and [p.file_id for p in msg.photo] == ["img-tok"]
try:
    msg.photo[1]
    assert False, "photo[1] должен давать IndexError, как у списка"
except IndexError:
    pass
print("3 ok: message.photo[-1].file_id работает")

# 4. get_file с прямой ссылкой — File без запроса к API
api = FakeApi()
info = make_bot(api).get_file("https://cdn/d.pdf")
assert isinstance(info, File)
assert info.file_path == "https://cdn/d.pdf" and info.file_id == "https://cdn/d.pdf"
assert info.file_unique_id == "https://cdn/d.pdf" and info.file_size is None
assert api.video_calls == []
print("4 ok: get_file(ссылка) — без запроса к API")

# 5. get_file с видео-токеном: GET /videos, лучший mp4 (720 при отсутствии 1080)
api = FakeApi()
info = make_bot(api).get_file("vid-tok")
assert api.video_calls == ["vid-tok"]
assert info.file_id == "vid-tok" and info.file_path == "https://cdn/v720.mp4"
# без mp4 — hls; urls null (видео недоступно) — file_path None
api = FakeApi(details=dict(DETAILS, urls={"hls": "https://cdn/v.m3u8"}))
assert make_bot(api).get_file("vid-tok").file_path == "https://cdn/v.m3u8"
api = FakeApi(details=dict(DETAILS, urls=None))
assert make_bot(api).get_file("vid-tok").file_path is None
print("5 ok: get_file(токен видео) — лучший mp4, hls-фолбэк, недоступное видео")

# 6. get_file: пустой аргумент — ValueError; чужой токен — 404 с подсказкой
try:
    make_bot(FakeApi()).get_file(None)
    assert False, "get_file(None) должен давать ValueError"
except ValueError:
    pass
error = MaxApiHTTPException(function_name="GET /videos/doc-tok",
                            result=FakeResponse())
api = FakeApi(error=error)


def call():
    try:
        make_bot(api).get_file("doc-tok")
        return None
    except MaxApiHTTPException as exc:
        return exc


raised, warns = capture_warnings(call)
assert raised is error, "404 должен пробрасываться дальше"
assert any("file_path" in w for w in warns), warns
print("6 ok: get_file — ValueError на пустом, 404 с предупреждением-подсказкой")

# 7. get_file_url — строка file_path; None у недоступного видео
assert make_bot(FakeApi()).get_file_url("vid-tok") == "https://cdn/v720.mp4"
assert make_bot(FakeApi()).get_file_url("https://cdn/a.mp3") == "https://cdn/a.mp3"
api = FakeApi(details=dict(DETAILS, urls=None))
assert make_bot(api).get_file_url("vid-tok") is None
print("7 ok: get_file_url")

# 8. download_file: байты по ссылке; токен — ValueError с подсказкой;
#    пустой file_path (недоступное видео) — ValueError с причиной
api = FakeApi()
assert make_bot(api).download_file("https://cdn/d.pdf") == b"file-bytes"
assert api.downloads == ["https://cdn/d.pdf"]
try:
    make_bot(FakeApi()).download_file("doc-tok")
    assert False, "download_file(токен) должен давать ValueError"
except ValueError as e:
    assert "get_file" in str(e)
try:
    make_bot(FakeApi()).download_file(None)
    assert False, "download_file(None) должен давать ValueError"
except ValueError as e:
    assert "недоступно" in str(e), e
print("8 ok: download_file — байты по URL, ValueError на токене и пустом пути")

# 9. get_video: types.Video с urls/best/метаданными; не-dict ответ — None
video = make_bot(FakeApi()).get_video("vid-tok")
assert isinstance(video, Video) and video.file_id == "vid-tok"
assert isinstance(video.urls, VideoUrls)
assert video.urls.mp4_720 == "https://cdn/v720.mp4" and video.urls.mp4_1080 is None
assert video.urls.best == "https://cdn/v720.mp4" and video.urls.hls == "https://cdn/v.m3u8"
assert video.file_path == "https://cdn/v720.mp4"
assert video.width == 640 and video.duration == 10
assert video.thumbnail.url == "https://cdn/thumb.jpg"
assert make_bot(FakeApi(details="строка")).get_video("vid-tok") is None
print("9 ok: get_video")

# 10. Wire-уровень: GET /videos/{token} с Authorization, скачивание — без него
calls = []


class OkResponse:
    status_code = 200
    content = b"\x89PNG"

    def raise_for_status(self):
        pass

    def json(self):
        return dict(DETAILS)


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return OkResponse()


real_request = requests.Session.request
requests.Session.request = fake_request
try:
    api = Api("tok")
    api.get_video("vid-tok")
    kw = calls[-1]
    assert kw["method"] == "GET"
    assert kw["url"] == "https://platform-api2.max.ru/videos/vid-tok", kw["url"]
    assert kw["headers"]["Authorization"] == "tok"

    # мусорный «токен» экранируется и не уводит запрос на другой эндпоинт
    api.get_video("../me")
    assert calls[-1]["url"] == "https://platform-api2.max.ru/videos/..%2Fme", calls[-1]["url"]

    data = api.download_file("https://cdn/img.jpg")
    assert data == b"\x89PNG"
    kw = calls[-1]
    assert kw["method"] == "GET" and kw["url"] == "https://cdn/img.jpg"
    # токен бота на CDN не уходит
    assert "Authorization" not in (kw.get("headers") or {}), kw.get("headers")
    assert kw["timeout"] == (15, 30), kw["timeout"]
finally:
    requests.Session.request = real_request
print("10 ok: wire-уровень — GET /videos и скачивание без Authorization")

print("ALL OK")

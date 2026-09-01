"""
Проверка отправки фото по URL (issue #45).

Как в telebot, send_photo принимает строку с http(s)-ссылкой. На стороне
MAX это вложение {"type": "image", "payload": {"url": ...}} — сервер
скачивает изображение сам, POST /uploads не вызывается. Работает только
для изображений: видео и файлы MAX принимает исключительно токеном.

Запуск:
    python3 tests/test_send_photo_url.py
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None

from maxibot import MaxiBot
from maxibot.types import InputMediaPhoto

SEND_OK = {
    "message": {
        "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.123", "seq": 5, "text": "hi", "attachments": [
            {"type": "image", "payload": {"url": "https://x"}}
        ]},
    }
}
GET_READY = {"recipient": SEND_OK["message"]["recipient"], "body": SEND_OK["message"]["body"]}


class FakeApi:
    def __init__(self):
        self.upload_calls = []
        self.load_calls = []
        self.send_kwargs = []

    def get_upload_file_url(self, type_attach):
        self.upload_calls.append(type_attach)
        return {"url": "https://upload"}

    def load_file(self, url, files, content_types=None):
        self.load_calls.append(url)
        return {"photos": {"k": {"token": "t"}}, "token": "t"}

    def send_message(self, **kwargs):
        self.send_kwargs.append(kwargs)
        return SEND_OK

    def get_message(self, mid):
        return GET_READY

    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot():
    bot = MaxiBot.__new__(MaxiBot)
    bot.api = FakeApi()
    bot.send_retry_timeout = 120
    bot.publish_wait_timeout = 10
    return bot


# 1. URL-строка -> payload с url, БЕЗ обращения к POST /uploads
bot = make_bot()
msg = bot.send_photo(42, "https://example.com/pic.jpg", caption="подпись")
attachments = bot.api.send_kwargs[0]["attachments"]
assert attachments[0] == {"type": "image", "payload": {"url": "https://example.com/pic.jpg"}}, attachments
assert bot.api.upload_calls == [] and bot.api.load_calls == []
assert bot.api.send_kwargs[0]["text"] == "подпись"
assert msg.message_id == "mid.123"
print('1 ok: URL уходит в payload без POST /uploads')

# 2. http:// работает так же, как https://
bot = make_bot()
bot.send_photo(42, "http://example.com/pic.jpg")
attachments = bot.api.send_kwargs[0]["attachments"]
assert attachments[0]["payload"] == {"url": "http://example.com/pic.jpg"}
print('2 ok: http-ссылка')

# 3. InputMediaPhoto со строкой-URL -> тоже url-payload
bot = make_bot()
bot.send_photo(42, InputMediaPhoto(media="https://example.com/a.png"))
attachments = bot.api.send_kwargs[0]["attachments"]
assert attachments[0] == {"type": "image", "payload": {"url": "https://example.com/a.png"}}
assert bot.api.upload_calls == []
print('3 ok: InputMediaPhoto с URL')

# 4. Байты по-прежнему загружаются через POST /uploads (регресс)
bot = make_bot()
bot.send_photo(42, io.BytesIO(b'raw-bytes').read())
assert bot.api.upload_calls == ["image"], bot.api.upload_calls
assert bot.api.load_calls == ["https://upload"]
attachments = bot.api.send_kwargs[0]["attachments"]
assert attachments[0]["payload"] == {"token": "t"}, attachments
print('4 ok: байты всё так же через /uploads')

# 5. send_media_group со смесью URL и байтов
bot = make_bot()
bot.send_media_group(42, ["https://example.com/1.jpg", io.BytesIO(b'x').read()], caption="альбом")
attachments = bot.api.send_kwargs[0]["attachments"]
assert attachments[0]["payload"] == {"url": "https://example.com/1.jpg"}
assert attachments[1]["payload"] == {"token": "t"}
assert bot.api.upload_calls == ["image"]  # только для байтов
print('5 ok: send_media_group со смесью URL и байтов')

# 6. Строка не-URL — токен ранее загруженного фото (аналог file_id в telebot)
bot = make_bot()
bot.send_photo(42, "4mtwu/jlqwJwSz5uYMcpHMCcn/5fqR0=")
attachments = bot.api.send_kwargs[0]["attachments"]
assert attachments[0] == {"type": "image", "payload": {"token": "4mtwu/jlqwJwSz5uYMcpHMCcn/5fqR0="}}, attachments
assert bot.api.upload_calls == []  # без повторной загрузки
print('6 ok: строка-токен -> payload с token, как file_id в telebot')

# 7. URL в send_video/send_document — понятный ValueError, а не мусорная загрузка
bot = make_bot()
for method, name in ((bot.send_video, "video"), (bot.send_document, "document")):
    try:
        method(42, "https://example.com/file.bin")
        raise AssertionError(f"send_{name} должен был упасть с ValueError")
    except ValueError as e:
        assert "URL" in str(e), str(e)
assert bot.api.upload_calls == [] and bot.api.send_kwargs == []
print('7 ok: URL в send_video/send_document -> ValueError')

print('ALL OK')

"""
Проверка parse_mode на уровне бота (issue #30).

Как в telebot: MaxiBot(token, parse_mode="html") задаёт разметку всем
методам отправки и редактирования, а parse_mode в самом вызове важнее
общего. Если разметка не задана нигде, поведение методов прежнее:
send_message и edit_message_media размечают текст как markdown, подписи
к вложениям и edit_message_text уходят без разметки.

Запуск:
    python3 tests/test_parse_mode.py
"""
import asyncio
import inspect
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None  # ускоряем ретраи и ожидания

import maxibot
from maxibot import MaxiBot
from maxibot.types import InputMediaPhoto

SEND_OK = {
    "message": {
        "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.1", "seq": 1, "text": "hi", "attachments": []},
    }
}
GET_READY = {
    "sender": SEND_OK["message"]["sender"],
    "recipient": SEND_OK["message"]["recipient"],
    "body": SEND_OK["message"]["body"],
}


class FakeApi:
    """Ловит kwargs отправки; загрузку файлов и чтение сообщений глушит."""

    def __init__(self):
        self.send_kwargs = []
        self.update_params = []

    def send_message(self, **kwargs):
        self.send_kwargs.append(kwargs)
        return SEND_OK

    def get_message(self, msg_id=None):
        return GET_READY

    def get_chat_info(self, chat_id):
        return {"title": "chat"}

    def get_upload_file_url(self, type_attach):
        return {"url": "https://upload", "token": "tok"}

    def load_file(self, url, files, content_types=None):
        return {"photos": {"p": {"token": "tok"}}}

    def get_updates(self, allowed_updates=None, extra=None):
        self.update_params.append(extra)
        if len(self.update_params) == 1:
            return {"updates": [{"update_type": "message_created"}], "marker": 5}
        return {"updates": [], "marker": 6}


def make_bot(**kwargs):
    bot = MaxiBot("t", **kwargs)  # конструктор сеть не трогает
    bot.api = FakeApi()
    return bot


def sent(bot):
    return bot.api.send_kwargs[-1]["parse_mode"]


# 1. Сигнатура и дефолты конструктора — порядок параметров как в telebot
sig = inspect.signature(MaxiBot.__init__)
assert list(sig.parameters) == [
    "self", "token", "parse_mode", "threaded", "skip_pending", "num_threads"
], list(sig.parameters)
assert sig.parameters["parse_mode"].default is None
assert sig.parameters["skip_pending"].default is False
assert MaxiBot("t").parse_mode is None
assert MaxiBot("t", "html").parse_mode == "html"  # второй позиционный, как в telebot
print('1 ok: parse_mode в init, порядок параметров как в telebot')

# 1.1. Старый позиционный вызов MaxiBot(token, threaded) падает громко:
#      иначе False молча снял бы разметку, а True ушёл бы в MAX как format: true
for wrong in (False, True, 4):
    try:
        MaxiBot("t", wrong)
        raise AssertionError(f"должен был упасть с TypeError на parse_mode={wrong!r}")
    except TypeError as e:
        assert "threaded" in str(e) and "parse_mode" in str(e), str(e)
assert MaxiBot("t", threaded=False).threaded is False  # по имени всё работает
print('1.1 ok: нестроковый parse_mode -> TypeError с подсказкой про threaded')

# 2. Разметка бота не задана — прежнее поведение send_message (markdown)
bot = make_bot()
bot.send_message(42, "текст")
assert sent(bot) == "markdown", sent(bot)
print('2 ok: без разметки бота send_message по-прежнему markdown')

# 3. Разметка бота применяется ко всем сообщениям
bot = make_bot(parse_mode="html")
bot.send_message(42, "текст")
assert sent(bot) == "html", sent(bot)
print('3 ok: MaxiBot(parse_mode="html") -> format html')

# 4. parse_mode вызова важнее разметки бота и приводится к нижнему регистру
bot = make_bot(parse_mode="html")
bot.send_message(42, "текст", parse_mode="Markdown")
assert sent(bot) == "markdown", sent(bot)
print('4 ok: parse_mode вызова важнее общего, нижний регистр')

# 5. Пустая строка отключает разметку, даже если у бота она задана
bot = make_bot(parse_mode="html")
bot.send_message(42, "текст *не жирный*", parse_mode="")
assert sent(bot) == "", sent(bot)
assert bot.api.send_kwargs[-1]["text"] == "текст *не жирный*"
print('5 ok: parse_mode="" отключает разметку')

# 6. Подписи к вложениям: без разметки бота — как раньше None, с разметкой — она
bot = make_bot()
bot.send_photo(42, "https://example.com/a.png", caption="подпись")
assert sent(bot) is None, sent(bot)
bot.send_media_group(42, ["https://example.com/a.png"], caption="подпись")
assert sent(bot) is None, sent(bot)

bot = make_bot(parse_mode="HTML")
bot.send_photo(42, "https://example.com/a.png", caption="подпись")
assert sent(bot) == "html", sent(bot)
bot.send_media_group(42, ["https://example.com/a.png"], caption="подпись")
assert sent(bot) == "html", sent(bot)
print('6 ok: send_photo/send_media_group берут разметку бота')

# 7. Файлы и видео — то же самое, явный parse_mode по-прежнему побеждает
bot = make_bot(parse_mode="html")
bot.send_document(42, io.BytesIO(b'file'), caption="подпись")
assert sent(bot) == "html", sent(bot)
bot.send_video(42, io.BytesIO(b'video'), caption="подпись")
assert sent(bot) == "html", sent(bot)
bot.send_video(42, io.BytesIO(b'video'), caption="подпись", parse_mode="markdown")
assert sent(bot) == "markdown", sent(bot)

bot = make_bot()
bot.send_document(42, io.BytesIO(b'file'), caption="подпись")
assert sent(bot) is None, sent(bot)
print('7 ok: send_document/send_video берут разметку бота')

# 8. edit_message_text: без разметки бота — как раньше без format, с ней — она
bot = make_bot()
bot.edit_message_text("новый текст", 42, "mid.1")
assert sent(bot) is None, sent(bot)

bot = make_bot(parse_mode="html")
bot.edit_message_text("новый текст", 42, "mid.1")
assert sent(bot) == "html", sent(bot)
print('8 ok: edit_message_text берёт разметку бота')

# 9. edit_message_media: разметка самого media важнее, затем вызов, затем бот,
#    а без всего — прежний markdown
bot = make_bot()
bot.edit_message_media(InputMediaPhoto(media="https://example.com/a.png", caption="подпись"), 42, "mid.1")
assert sent(bot) == "markdown", sent(bot)

bot = make_bot(parse_mode="html")
bot.edit_message_media(InputMediaPhoto(media="https://example.com/a.png", caption="подпись"), 42, "mid.1")
assert sent(bot) == "html", sent(bot)

bot = make_bot(parse_mode="html")
media = InputMediaPhoto(media="https://example.com/a.png", caption="подпись", parse_mode="markdown")
bot.edit_message_media(media, 42, "mid.1")
assert sent(bot) == "markdown", sent(bot)
print('9 ok: edit_message_media — media > вызов > бот > markdown')

# 10. edit_message_reply_markup: прежний markdown, разметка бота применяется
bot = make_bot()
bot.edit_message_reply_markup(42, "mid.1")
assert sent(bot) == "markdown", sent(bot)

bot = make_bot(parse_mode="html")
bot.edit_message_reply_markup(42, "mid.1")
assert sent(bot) == "html", sent(bot)
print('10 ok: edit_message_reply_markup берёт разметку бота')


class FakePolling:
    def __init__(self, api=None, allowed_updates=None):
        pass

    async def loop(self, handler):
        return


maxibot.Polling = FakePolling

# 11. skip_pending в init: накопленные обновления пропускаются один раз
bot = make_bot(skip_pending=True)
asyncio.run(bot.start())
assert bot.api.update_params == [{"timeout": 0}, {"timeout": 0, "marker": 5}], bot.api.update_params
assert bot.skip_pending is False  # как в telebot: повторный запуск уже не пропускает
bot.is_running = False
asyncio.run(bot.start())
assert len(bot.api.update_params) == 2, bot.api.update_params
print('11 ok: skip_pending в init пропускает обновления один раз')

# 12. Без skip_pending обновления не пропускаются
bot = make_bot()
asyncio.run(bot.start())
assert bot.api.update_params == [], bot.api.update_params
print('12 ok: без skip_pending пропуска нет')

print('ALL OK')

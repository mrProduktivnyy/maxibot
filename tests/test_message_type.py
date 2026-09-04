"""
Тип Message: content_type как в telebot, caption и None-атрибуты.

Документ из MAX приходит вложением type='file' — раньше content_type так и
оставался 'file', и фильтр content_types=['document'] не срабатывал никогда.
Плюс у Message не было атрибутов telebot (caption, sticker, venue, ...) —
переехавший код падал с AttributeError.

Запуск:
    python3 tests/test_message_type.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot
from maxibot.types import Message

USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u", "last_name": None}


class FakeApi:
    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def message_update(text="привет", attachments=None):
    body = {"mid": "mid.1", "seq": 1, "text": text}
    if attachments is not None:
        body["attachments"] = attachments
    return {
        "update_type": "message_created",
        "timestamp": 1751400000000,
        "message": {
            "sender": USER,
            "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
            "timestamp": 1751400000000,
            "body": body,
        },
    }


def make_message(**kwargs):
    return Message(update=message_update(**kwargs), api=FakeApi())


# 1. Документ: вложение 'file' -> content_type 'document', подпись в caption
msg = make_message(text="отчёт", attachments=[{"type": "file", "payload": {"token": "t1"}}])
assert msg.content_type == "document", msg.content_type
assert msg.caption == "отчёт" and msg.text == "отчёт"
assert msg.document is None  # объект появится в issue про файлы
print("1 ok: file -> document, caption заполнен")

# 2. Остальные типы вложений отдают имена как в telebot
for a_type, expected in [
    ("image", "photo"), ("video", "video"), ("audio", "audio"),
    ("sticker", "sticker"), ("location", "location"), ("contact", "contact"),
]:
    msg = make_message(attachments=[{"type": a_type, "payload": {}}])
    assert msg.content_type == expected, (a_type, msg.content_type)
print("2 ok: маппинг image->photo и остальные типы")

# 3. Текстовое сообщение: content_type 'text', caption пустой
msg = make_message(text="просто текст")
assert msg.content_type == "text" and msg.caption is None
print("3 ok: text без caption")

# 4. Клавиатура и share-превью не делают сообщение медиа
msg = make_message(text="выбери", attachments=[
    {"type": "inline_keyboard", "payload": {"buttons": []}},
])
assert msg.content_type == "text", msg.content_type
msg = make_message(text="https://max.ru", attachments=[
    {"type": "share", "payload": {"url": "https://max.ru"}},
])
assert msg.content_type == "text", msg.content_type
msg = make_message(text="фото с кнопками", attachments=[
    {"type": "inline_keyboard", "payload": {"buttons": []}},
    {"type": "image", "payload": {"url": "https://x"}},
])
assert msg.content_type == "photo", msg.content_type
print("4 ok: inline_keyboard/share пропускаются при определении типа")

# 5. Атрибуты telebot существуют и равны None — AttributeError больше нет
msg = make_message()
for attribute in (
    "caption", "audio", "document", "sticker", "video", "video_note", "voice",
    "venue", "animation", "dice", "contact", "location", "reply_markup",
    "media_group_id", "forward_from", "forward_date", "forward_origin",
    "entities", "caption_entities", "sender_chat", "via_bot", "pinned_message",
    "new_chat_members", "left_chat_member", "reply_to_message",
    "user_shared", "new_chat_member",
):
    assert getattr(msg, attribute) is None, attribute
assert msg.html_text == msg.text and msg.html_caption is None
media = make_message(text="подпись", attachments=[{"type": "image", "payload": {}}])
assert media.html_caption == "подпись"
print("5 ok: все атрибуты telebot.Message на месте (None), html_text/html_caption")

# 6. message.json — сырой dict сообщения из апдейта
update = message_update(text="raw")
msg = Message(update=update, api=FakeApi())
assert msg.json is update["message"]
print("6 ok: message.json")

# 7. Диспатч: content_types=['document'] теперь реально срабатывает,
#    а дефолтный text-хендлер документ не перехватывает
bot = MaxiBot("t", threaded=False)
bot.api = FakeApi()
got = []


@bot.message_handler(content_types=["document"])
def on_document(message):
    got.append(("document", message.caption))


@bot.message_handler()
def on_text(message):
    got.append(("text", message.text))


bot._process_update(message_update(text="файл", attachments=[{"type": "file", "payload": {"token": "t"}}]))
bot._process_update(message_update(text="привет"))
assert got == [("document", "файл"), ("text", "привет")], got
print("7 ok: фильтр content_types=['document'] работает")

# 8. Хендлер без content_types получает ТОЛЬКО текст (дефолт telebot) —
#    раньше голый @bot.message_handler() не срабатывал вообще
bot = MaxiBot("t", threaded=False)
bot.api = FakeApi()
got = []


@bot.message_handler()
def bare(message):
    got.append(message.content_type)


bot._process_update(message_update(text="фото", attachments=[{"type": "image", "payload": {}}]))
bot._process_update(message_update(text="текст"))
assert got == ["text"], got
print("8 ok: дефолт content_types=['text'] как в telebot")

# 9. Голый callback_query_handler без фильтров срабатывает
def callback_update(payload="btn_1"):
    upd = message_update()
    upd["update_type"] = "message_callback"
    upd["callback"] = {"timestamp": 1751400000000, "callback_id": "cb1", "payload": payload, "user": USER}
    return upd


bot = MaxiBot("t", threaded=False)
bot.api = FakeApi()
got = []


@bot.callback_query_handler()
def any_callback(call):
    got.append(call.data)


bot._process_update(callback_update())
assert got == ["btn_1"], got
print("9 ok: голый callback_query_handler матчит все колбэки")

# 10. Порядок фильтров как в telebot: content_types раньше func — func,
#     трогающий m.text, не роняет диспатч фото без подписи
bot = MaxiBot("t", threaded=False)
bot.api = FakeApi()
got = []


@bot.message_handler(func=lambda m: m.text.startswith("hi"))
def texty(message):
    got.append("texty")


@bot.message_handler(content_types=["photo"])
def photo_handler(message):
    got.append("photo")


bot._process_update(message_update(text=None, attachments=[{"type": "image", "payload": {}}]))
assert got == ["photo"], got
print("10 ok: func не вызывается для не-текста, фото доходит до своего хендлера")

# 11. Совместимость: content_types=['file'] старых ботов мапится в 'document',
#     commands строкой оборачивается — '/st' не матчит 'start'
bot = MaxiBot("t", threaded=False)
bot.api = FakeApi()
got = []


@bot.message_handler(content_types=["file"])
def old_style(message):
    got.append("file->document")


@bot.message_handler(commands="start")
def cmd(message):
    got.append(message.text)


bot._process_update(message_update(text="док", attachments=[{"type": "file", "payload": {"token": "t"}}]))
bot._process_update(message_update(text="/st"))
bot._process_update(message_update(text="/start"))
assert got == ["file->document", "/start"], got
print("11 ok: content_types=['file'] совместим, commands строкой безопасен")

print("ALL OK")

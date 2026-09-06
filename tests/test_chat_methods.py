"""
Пакет методов чата поверх GET /chats/{chatId} и PATCH /chats/{chatId}:
get_chat, get_chat_member_count (+ устаревший алиас), set_chat_title,
set_chat_description, set_chat_photo, delete_chat_photo.

Типы чатов MAX мапятся в телеботовские везде, где есть chat.type:
dialog -> private, chat -> group, channel -> channel; сырой тип MAX
лежит в chat.max_type.

Запуск:
    python3 tests/test_chat_methods.py
"""
import inspect
import io
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import telebot

from maxibot import MaxiBot
from maxibot.apihelper import Api
from maxibot.types import Chat, Message


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


GROUP_INFO = {
    "chat_id": 100,
    "type": "chat",
    "status": "active",
    "title": "Рабочий чат",
    "icon": {"url": "https://cdn/icon.jpg"},
    "last_event_time": 1751400000000,
    "participants_count": 7,
    "is_public": True,
    "link": "https://max.ru/join/abc",
    "description": "Описание чата",
    "pinned_message": {
        "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
        "recipient": {"chat_id": 100, "chat_type": "chat", "user_id": None},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.pin", "seq": 1, "text": "закреп", "attachments": None},
    },
}

DIALOG_INFO = {
    "chat_id": 200,
    "type": "dialog",
    "status": "active",
    "title": None,
    "icon": None,
    "participants_count": 2,
    "is_public": False,
    "link": None,
    "description": None,
    "dialog_with_user": {
        "user_id": 42, "first_name": "Ваня", "last_name": "Иванов",
        "username": "vanya", "is_bot": False,
    },
}


class FakeApi:
    def __init__(self, chat_info=None):
        self.chat_info = chat_info or GROUP_INFO
        self.patch_calls = []
        self.upload_calls = []
        self.load_calls = []

    def get_chat_info(self, chat_id):
        return self.chat_info

    def edit_chat_info(self, chat_id, patch, timeout=None):
        self.patch_calls.append((chat_id, patch))
        return dict(self.chat_info)

    def get_upload_file_url(self, type_attach):
        self.upload_calls.append(type_attach)
        return {"url": "https://upload"}

    def load_file(self, url, files, content_types=None):
        self.load_calls.append(url)
        return {"photos": {"k": {"token": "icon-tok"}}}


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


# 1. Сигнатуры один в один с telebot (у телеботовского алиаса
#    get_chat_members_count сигнатура искажена decorator'ом deprecated —
#    проверяем только наличие)
for name in ("get_chat", "get_chat_member_count",
             "set_chat_title", "set_chat_description", "set_chat_photo",
             "delete_chat_photo"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
assert callable(getattr(telebot.TeleBot, "get_chat_members_count"))
assert callable(getattr(MaxiBot, "get_chat_members_count"))
print("1 ok: сигнатуры всех семи методов как в telebot")

# 2. get_chat группового чата: тип chat -> group, поля telebot
chat = make_bot(FakeApi()).get_chat(100)
assert isinstance(chat, Chat), type(chat)
assert chat.id == 100 and chat.type == "group", (chat.id, chat.type)
assert chat.title == "Рабочий чат" and chat.description == "Описание чата"
assert chat.photo == "https://cdn/icon.jpg", chat.photo
assert chat.invite_link == "https://max.ru/join/abc", chat.invite_link
assert chat.participants_count == 7 and chat.is_public is True
assert isinstance(chat.pinned_message, Message), type(chat.pinned_message)
assert chat.pinned_message.text == "закреп" and chat.pinned_message.message_id == "mid.pin"
print("2 ok: get_chat группы — type group, photo/invite_link/pinned_message")

# 3. get_chat диалога: type private, собеседник в first_name/last_name/username
chat = make_bot(FakeApi(DIALOG_INFO)).get_chat(200)
assert chat.type == "private", chat.type
assert chat.first_name == "Ваня" and chat.last_name == "Иванов"
assert chat.username == "vanya" and chat.user_id == 42
assert chat.photo is None and chat.pinned_message is None
print("3 ok: get_chat диалога — type private, поля собеседника")

# 4. get_chat_member_count и устаревший алиас с предупреждением
bot = make_bot(FakeApi())
assert bot.get_chat_member_count(100) == 7
count, warns = capture_warnings(lambda: bot.get_chat_members_count(100))
assert count == 7
assert any("устарел" in w for w in warns), warns
print("4 ok: счётчик участников, алиас предупреждает")

# 5. set_chat_title -> PATCH {"title"}; True при успехе
api = FakeApi()
assert make_bot(api).set_chat_title(100, "Новое имя") is True
assert api.patch_calls == [(100, {"title": "Новое имя"})], api.patch_calls
print('5 ok: set_chat_title -> PATCH {"title"}')

# 6. set_chat_description: None -> "" (удаление, как в Telegram), строка — как есть
api = FakeApi()
make_bot(api).set_chat_description(100, "Новое описание")
make_bot(api).set_chat_description(100)
assert api.patch_calls[0] == (100, {"description": "Новое описание"}), api.patch_calls
assert api.patch_calls[1] == (100, {"description": ""}), api.patch_calls
print("6 ok: set_chat_description, None -> пустая строка")

# 7. set_chat_photo: URL -> icon {"url"}; токен-строка -> {"token"};
#    байты -> загрузка type=image -> {"token"} из ответа
api = FakeApi()
make_bot(api).set_chat_photo(100, "https://example.com/pic.jpg")
assert api.patch_calls[-1] == (100, {"icon": {"url": "https://example.com/pic.jpg"}})
make_bot(api).set_chat_photo(100, "старый-токен")
assert api.patch_calls[-1] == (100, {"icon": {"token": "старый-токен"}})
assert api.upload_calls == []
make_bot(api).set_chat_photo(100, io.BytesIO(b'jpg-bytes'))
assert api.upload_calls == ["image"] and api.load_calls == ["https://upload"]
assert api.patch_calls[-1] == (100, {"icon": {"token": "icon-tok"}}), api.patch_calls[-1]
print("7 ok: set_chat_photo — URL/токен/байты")

# 8. delete_chat_photo -> PATCH {"icon": None}
api = FakeApi()
assert make_bot(api).delete_chat_photo(100) is True
assert api.patch_calls == [(100, {"icon": None})], api.patch_calls
print('8 ok: delete_chat_photo -> PATCH {"icon": null}')

# 9. Канал: закреп от имени канала (sender: null по спеке) не роняет
#    get_chat; from_user-поля пустые; date закрепа заполняется;
#    второй GET /chats за тем же чатом не делается
CHANNEL_INFO = {
    "chat_id": 300,
    "type": "channel",
    "status": "active",
    "title": "Канал",
    "icon": None,
    "participants_count": 1000,
    "is_public": True,
    "link": "https://max.ru/ch",
    "description": None,
    "pinned_message": {
        "sender": None,
        "recipient": {"chat_id": 300, "chat_type": "channel", "user_id": None},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.ch", "seq": 3, "text": "пост", "attachments": None},
    },
}


class CountingApi(FakeApi):
    def __init__(self, chat_info):
        super().__init__(chat_info)
        self.get_calls = 0

    def get_chat_info(self, chat_id):
        self.get_calls += 1
        return self.chat_info


api = CountingApi(CHANNEL_INFO)
chat = make_bot(api).get_chat(300)
assert chat.type == "channel"
assert chat.pinned_message.text == "пост" and chat.pinned_message.message_id == "mid.ch"
assert chat.pinned_message.date is not None, "date закрепа потерян"
# с №14 (каналы) у поста от имени канала from_user = None, как в telebot
assert chat.pinned_message.from_user is None
assert api.get_calls == 1, f"лишние GET /chats: {api.get_calls}"
print("9 ok: канальный закреп с sender:null, date есть, GET один")

# 10. Телеботовские атрибуты Chat существуют и равны None; bio диалога —
#     описание профиля собеседника
chat = make_bot(FakeApi()).get_chat(100)
for attr in ("permissions", "is_forum", "sticker_set_name", "linked_chat_id",
             "location", "has_protected_content", "active_usernames"):
    assert getattr(chat, attr) is None, attr
info_with_bio = dict(DIALOG_INFO)
info_with_bio["dialog_with_user"] = dict(DIALOG_INFO["dialog_with_user"],
                                         description="Обо мне")
chat = make_bot(FakeApi(info_with_bio)).get_chat(200)
assert chat.bio == "Обо мне", chat.bio
print("10 ok: телеботовские атрибуты None, bio из dialog_with_user")

# 11. Api-уровень: PATCH реально уходит на platform-api2/chats/{id}
calls = []


class OkResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"chat_id": 100}


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return OkResponse()


real_request = requests.Session.request
requests.Session.request = fake_request
try:
    Api("tok").edit_chat_info(100, {"title": "х"})
    kw = calls[-1]
    assert kw["method"] == "PATCH", kw
    assert kw["url"] == "https://platform-api2.max.ru/chats/100", kw["url"]
    assert json.loads(kw["data"]) == {"title": "х"}, kw
finally:
    requests.Session.request = real_request
print("11 ok: PATCH /chats/{chatId} на platform-api2")

print("ALL OK")

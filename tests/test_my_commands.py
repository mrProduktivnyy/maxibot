"""
Профиль бота поверх GET/PATCH /me: set/get/delete_my_commands,
set/get_my_name, set/get_my_description, set/get_my_short_description
(в MAX одно description) и MAX-бонус set_my_photo.

Запуск:
    python3 tests/test_my_commands.py
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
import telebot.types

from maxibot import MaxiBot
from maxibot.apihelper import Api
from maxibot.types import BotCommand, BotName, BotDescription, BotShortDescription


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


BOT_INFO = {
    "user_id": 7, "first_name": "Макси", "last_name": "Бот",
    "username": "maxibot", "is_bot": True, "last_activity_time": 1,
    "description": "Помощник",
    "commands": [{"name": "start", "description": "Начать"},
                 {"name": "help"}],
}


class FakeApi:
    def __init__(self, info=None):
        self.info = info if info is not None else dict(BOT_INFO)
        self.patches = []
        self.upload_calls = []

    def get_bot_info(self):
        return self.info

    def edit_bot_info(self, patch, timeout=None):
        self.patches.append(patch)
        return dict(self.info)

    def get_upload_file_url(self, type_attach):
        self.upload_calls.append(type_attach)
        return {"url": "https://upload"}

    def load_file(self, url, files, content_types=None):
        return {"photos": {"k": {"token": "avatar-tok"}}}


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


# 1. Сигнатуры один в один с telebot
for name in ("set_my_commands", "get_my_commands", "delete_my_commands",
             "set_my_name", "get_my_name", "set_my_description",
             "get_my_description", "set_my_short_description",
             "get_my_short_description"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры всех девяти методов как в telebot")

# 2. set_my_commands: maxibot.BotCommand, телеботовский BotCommand и dict;
#    ведущий '/' срезается; PATCH {"commands": [...]}
api = FakeApi()
assert make_bot(api).set_my_commands([
    BotCommand("/start", "Начать"),
    telebot.types.BotCommand("help", "Справка"),
    {"command": "/menu", "description": "Меню"},
    {"name": "stop"},
]) is True
assert api.patches == [{"commands": [
    {"name": "start", "description": "Начать"},
    {"name": "help", "description": "Справка"},
    {"name": "menu", "description": "Меню"},
    {"name": "stop"},
]}], api.patches
print("2 ok: set_my_commands — BotCommand/telebot/dict, '/' срезан")

# 3. scope/language_code игнорируются с предупреждением; пустое имя — ValueError
_, warns = capture_warnings(lambda: make_bot(FakeApi()).set_my_commands(
    [BotCommand("start")], scope="все чаты", language_code="ru"))
assert any("скоупов" in w for w in warns), warns
assert any("языковых" in w for w in warns), warns
try:
    make_bot(FakeApi()).set_my_commands([BotCommand("/")])
    assert False, "пустое имя должно давать ValueError"
except ValueError as e:
    assert "пустое имя" in str(e)
# пустое описание = «без описания» (по спеке minLength 1 — "" сервер
# вправе отклонить); None-команды падают TypeError, как в telebot
api = FakeApi()
make_bot(api).set_my_commands([BotCommand("start", "")])
assert api.patches == [{"commands": [{"name": "start"}]}], api.patches
try:
    make_bot(FakeApi()).set_my_commands(None)
    assert False, "commands=None должен падать, как в telebot"
except TypeError:
    pass
print("3 ok: предупреждения, пустое имя/описание, None-команды падают")

# 4. get_my_commands: BotCommand с .command/.description; commands null -> []
commands = make_bot(FakeApi()).get_my_commands()
assert [c.command for c in commands] == ["start", "help"]
assert commands[0].description == "Начать" and commands[1].description is None
info = dict(BOT_INFO, commands=None)
assert make_bot(FakeApi(info)).get_my_commands() == []
print("4 ok: get_my_commands")

# 5. delete_my_commands -> PATCH {"commands": []}
api = FakeApi()
assert make_bot(api).delete_my_commands() is True
assert api.patches == [{"commands": []}], api.patches
print("5 ok: delete_my_commands")

# 6. set_my_name -> PATCH {"first_name"}; None/"" -> ValueError;
#    get_my_name склеивает first_name и last_name
api = FakeApi()
assert make_bot(api).set_my_name("Новое имя") is True
assert api.patches == [{"first_name": "Новое имя"}], api.patches
try:
    make_bot(FakeApi()).set_my_name()
    assert False, "пустое имя должно давать ValueError"
except ValueError as e:
    assert "1–59" in str(e)
name = make_bot(FakeApi()).get_my_name()
assert isinstance(name, BotName) and name.name == "Макси Бот"
info = dict(BOT_INFO, last_name=None)
assert make_bot(FakeApi(info)).get_my_name().name == "Макси"
# language_code предупреждает во всех геттерах (симметрия с get_my_commands)
for getter in ("get_my_name", "get_my_description", "get_my_short_description"):
    _, warns = capture_warnings(
        lambda g=getter: getattr(make_bot(FakeApi()), g)(language_code="ru"))
    assert any("языковых" in w for w in warns), (getter, warns)
print("6 ok: set/get_my_name, предупреждения про language_code в геттерах")

# 7. set_my_description; None -> null (снять); get_my_description ("" при null)
api = FakeApi()
make_bot(api).set_my_description("Новое описание")
make_bot(api).set_my_description()
assert api.patches == [{"description": "Новое описание"},
                       {"description": None}], api.patches
desc = make_bot(FakeApi()).get_my_description()
assert isinstance(desc, BotDescription) and desc.description == "Помощник"
info = dict(BOT_INFO, description=None)
assert make_bot(FakeApi(info)).get_my_description().description == ""
print("7 ok: set/get_my_description")

# 8. set_my_short_description: предупреждение и False, PATCH не зовётся
#    (не затирать основное описание); get_my_short_description из description
api = FakeApi()
result, warns = capture_warnings(lambda: make_bot(api).set_my_short_description("кратко"))
assert result is False and api.patches == [], api.patches
assert any("короткого описания" in w for w in warns), warns
short = make_bot(FakeApi()).get_my_short_description()
assert isinstance(short, BotShortDescription) and short.short_description == "Помощник"
print("8 ok: short_description — заглушка сеттера, геттер из description")

# 9. set_my_photo: URL -> {"photo": {"url"}}; байты -> upload -> token
api = FakeApi()
assert make_bot(api).set_my_photo("https://example.com/a.jpg") is True
assert api.patches[-1] == {"photo": {"url": "https://example.com/a.jpg"}}
make_bot(api).set_my_photo(io.BytesIO(b"jpg"))
assert api.upload_calls == ["image"]
assert api.patches[-1] == {"photo": {"token": "avatar-tok"}}, api.patches[-1]
print("9 ok: set_my_photo — URL и байты")

# 10. Wire-уровень: PATCH https://platform-api2.max.ru/me
calls = []


class OkResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return dict(BOT_INFO)


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return OkResponse()


real_request = requests.Session.request
requests.Session.request = fake_request
try:
    Api("tok").edit_bot_info({"commands": []})
    kw = calls[-1]
    assert kw["method"] == "PATCH"
    assert kw["url"] == "https://platform-api2.max.ru/me", kw["url"]
    assert json.loads(kw["data"]) == {"commands": []}
finally:
    requests.Session.request = real_request
print("10 ok: wire-уровень — PATCH /me")

print("ALL OK")

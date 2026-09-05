"""
Пакет участников и админов поверх блока /chats/{chatId}/members:
get_chat_member, get_chat_administrators, ban_chat_member (+ устаревший
kick_chat_member), unban_chat_member (заглушка), promote_chat_member,
set_chat_administrator_custom_title, export_chat_invite_link и
MAX-бонусы add_chat_members / get_chat_membership.

Статусы MAX мапятся в телеботовские: is_owner -> creator,
is_admin -> administrator, иначе member; нет в чате -> left.

Запуск:
    python3 tests/test_chat_members.py
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
from maxibot.types import ChatMember


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


OWNER = {
    "user_id": 1, "first_name": "Оля", "last_name": "Царёва",
    "username": "olya", "is_bot": False, "last_activity_time": 1,
    "last_access_time": 2, "join_time": 3,
    "is_owner": True, "is_admin": True, "permissions": None, "alias": None,
}

ADMIN = {
    "user_id": 2, "first_name": "Ваня", "last_name": None,
    "username": "vanya", "is_bot": False, "last_activity_time": 1,
    "last_access_time": 2, "join_time": 3,
    "is_owner": False, "is_admin": True,
    "permissions": ["change_chat_info", "pin_message", "add_remove_members"],
    "alias": "Модератор",
}

MEMBER = {
    "user_id": 3, "first_name": "Петя", "last_name": "Быков",
    "username": None, "is_bot": False, "last_activity_time": 1,
    "last_access_time": 2, "join_time": 3,
    "is_owner": False, "is_admin": False, "permissions": None, "alias": None,
    "description": "Обо мне",
}


class FakeApi:
    def __init__(self, members=None, admins=None):
        self.members = members if members is not None else [OWNER, ADMIN, MEMBER]
        self.admins = admins if admins is not None else [OWNER, ADMIN]
        self.calls = []

    def get_chat_members(self, chat_id, user_ids=None, marker=None,
                         count=None, timeout=None):
        self.calls.append(("get_members", chat_id, user_ids))
        wanted = set(user_ids or [])
        return {"members": [m for m in self.members if m["user_id"] in wanted],
                "marker": None}

    def get_chat_admins(self, chat_id, timeout=None):
        self.calls.append(("get_admins", chat_id))
        return {"members": list(self.admins), "marker": None}

    def set_chat_admins(self, chat_id, admins, timeout=None):
        self.calls.append(("set_admins", chat_id, admins))
        return {"success": True}

    def delete_chat_admin(self, chat_id, user_id, timeout=None):
        self.calls.append(("delete_admin", chat_id, user_id))
        return {"success": True}

    def add_chat_members(self, chat_id, user_ids, timeout=None):
        self.calls.append(("add_members", chat_id, user_ids))
        return {"success": True}

    def remove_chat_member(self, chat_id, user_id, block=False, timeout=None):
        self.calls.append(("remove_member", chat_id, user_id, block))
        return {"success": True}

    def get_chat_membership(self, chat_id, timeout=None):
        self.calls.append(("membership", chat_id))
        return dict(ADMIN)

    def get_chat_info(self, chat_id):
        self.calls.append(("chat_info", chat_id))
        return {"chat_id": chat_id, "type": "chat", "link": "https://max.ru/join/abc"}


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


# 1. Сигнатуры один в один с telebot (у телеботовского kick_chat_member
#    сигнатура искажена decorator'ом deprecated — проверяем наличие)
for name in ("get_chat_member", "get_chat_administrators", "ban_chat_member",
             "unban_chat_member", "promote_chat_member",
             "set_chat_administrator_custom_title", "export_chat_invite_link"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
assert callable(getattr(telebot.TeleBot, "kick_chat_member"))
assert callable(getattr(MaxiBot, "kick_chat_member"))
print("1 ok: сигнатуры всех методов как в telebot")

# 2. get_chat_member админа: administrator, custom_title=alias, флаги из прав
api = FakeApi()
member = make_bot(api).get_chat_member(100, 2)
assert isinstance(member, ChatMember), type(member)
assert member.status == "administrator", member.status
assert member.user.id == 2 and member.user.real_id == 2
assert member.user.first_name == "Ваня" and member.user.username == "vanya"
assert member.custom_title == "Модератор"
assert member.can_change_info is True and member.can_pin_messages is True
assert member.can_invite_users is True and member.can_restrict_members is True
assert member.can_promote_members is False and member.can_post_messages is False
assert member.can_manage_chat is True  # телеграмный инвариант админа
assert member.is_member is True and member.until_date is None
assert member.permissions == ["change_chat_info", "pin_message", "add_remove_members"]
assert api.calls[0] == ("get_members", 100, [2]), api.calls
print("2 ok: get_chat_member админа — статус, титул, can_*-флаги")

# 3. Владелец: creator, все мапленные флаги True (permissions null)
member = make_bot(FakeApi()).get_chat_member(100, 1)
assert member.status == "creator"
for flag in ("can_change_info", "can_pin_messages", "can_invite_users",
             "can_restrict_members", "can_promote_members", "can_post_messages",
             "can_edit_messages", "can_delete_messages",
             "can_manage_video_chats", "can_manage_chat"):
    assert getattr(member, flag) is True, flag
print("3 ok: владелец — creator, все флаги True")

# 4. Обычный участник: member, can_*-флаги None (как в telebot у Member),
#    description профиля доступен
member = make_bot(FakeApi()).get_chat_member(100, 3)
assert member.status == "member"
assert member.can_change_info is None and member.can_manage_chat is None
assert member.is_member is True and member.description == "Обо мне"
print("4 ok: обычный участник — member, флаги None")

# 5. Нет в чате: left-заглушка (как в Telegram для вышедших)
member = make_bot(FakeApi()).get_chat_member(100, 999)
assert member.status == "left" and member.is_member is False
assert member.user.id == 999 and member.user.first_name is None
print("5 ok: отсутствующий — left")

# 6. get_chat_administrators: список ChatMember, владелец creator
admins = make_bot(FakeApi()).get_chat_administrators(100)
assert [a.status for a in admins] == ["creator", "administrator"]
assert [a.user.id for a in admins] == [1, 2]
print("6 ok: get_chat_administrators")

# 7. ban: DELETE с block=true; until_date/revoke_messages — предупреждения;
#    kick-алиас предупреждает и банит
api = FakeApi()
assert make_bot(api).ban_chat_member(100, 3) is True
assert api.calls[-1] == ("remove_member", 100, 3, True), api.calls
_, warns = capture_warnings(lambda: make_bot(FakeApi()).ban_chat_member(
    100, 3, until_date=123, revoke_messages=True))
assert any("until_date" in w for w in warns), warns
assert any("revoke_messages" in w for w in warns), warns
api = FakeApi()
result, warns = capture_warnings(lambda: make_bot(api).kick_chat_member(100, 3))
assert result is True and api.calls[-1] == ("remove_member", 100, 3, True)
assert any("устарел" in w for w in warns), warns
print("7 ok: ban с block=true, предупреждения, kick-алиас")

# 8. unban — NotImplementedError (разбана в MAX нет)
try:
    make_bot(FakeApi()).unban_chat_member(100, 3)
    assert False, "unban_chat_member должен бросать"
except NotImplementedError as e:
    assert "разбана" in str(e)
print("8 ok: unban бросает NotImplementedError")

# 9. promote: флаги -> права MAX, дубль add_remove_members схлопывается;
#    все False/None -> DELETE admins (разжалование); флаг без аналога —
#    предупреждение
api = FakeApi()
assert make_bot(api).promote_chat_member(
    100, 3, can_change_info=True, can_invite_users=True,
    can_restrict_members=True, can_promote_members=True,
    can_manage_chat=True, can_manage_video_chats=True) is True
op, chat, admins_body = api.calls[-1]
assert op == "set_admins" and chat == 100
assert admins_body == [{"user_id": 3, "permissions": [
    "change_chat_info", "add_remove_members", "add_admins",
    "read_all_messages", "can_call"]}], admins_body
api = FakeApi()
assert make_bot(api).promote_chat_member(100, 3) is True
assert api.calls[-1] == ("delete_admin", 100, 3), api.calls
_, warns = capture_warnings(lambda: make_bot(FakeApi()).promote_chat_member(
    100, 3, can_pin_messages=True, is_anonymous=True, can_post_stories=True))
assert any("is_anonymous" in w for w in warns), warns
assert any("can_post_stories" in w for w in warns), warns
# только немаппируемые флаги: НЕ разжаловать (DELETE не зовётся) —
# предупреждение и False
api = FakeApi()
result, warns = capture_warnings(lambda: make_bot(api).promote_chat_member(
    100, 3, is_anonymous=True, can_manage_topics=True))
assert result is False
assert api.calls == [], api.calls
assert any("не назначен админом и не разжалован" in w for w in warns), warns
print("9 ok: promote — маппинг прав, разжалование, предупреждения")

# 10. custom_title: читает текущие права и шлёт их с alias; не-админ — ValueError
api = FakeApi()
assert make_bot(api).set_chat_administrator_custom_title(100, 2, "Главный") is True
assert api.calls[0] == ("get_admins", 100)
assert api.calls[1] == ("set_admins", 100, [{
    "user_id": 2,
    "permissions": ["change_chat_info", "pin_message", "add_remove_members"],
    "alias": "Главный"}]), api.calls[1]
try:
    make_bot(FakeApi()).set_chat_administrator_custom_title(100, 3, "х")
    assert False, "не-админ должен давать ValueError"
except ValueError as e:
    assert "promote_chat_member" in str(e)
# владелец: титул не задать (permissions null — пустой набор прав
# по PUT-семантике срезал бы права), API не вызывается
api = FakeApi()
try:
    make_bot(api).set_chat_administrator_custom_title(100, 1, "Босс")
    assert False, "владелец должен давать ValueError"
except ValueError as e:
    assert "владелец" in str(e)
assert all(call[0] != "set_admins" for call in api.calls), api.calls
print("10 ok: custom_title переотправляет права с alias, владелец защищён")

# 11. add_chat_members: одиночный id и список; failed_user_ids -> warning + False
api = FakeApi()
assert make_bot(api).add_chat_members(100, 7) is True
assert api.calls[-1] == ("add_members", 100, [7])
assert make_bot(api).add_chat_members(100, [7, 8]) is True


class FailingAddApi(FakeApi):
    def add_chat_members(self, chat_id, user_ids, timeout=None):
        return {"success": True, "failed_user_ids": [8]}


result, warns = capture_warnings(lambda: make_bot(FailingAddApi()).add_chat_members(100, [7, 8]))
assert result is False
assert any("8" in w for w in warns), warns


# сбой только через failed_user_details: по спеке там плюральный
# user_ids — реальные id и error_code должны попасть в предупреждение
class DetailsOnlyApi(FakeApi):
    def add_chat_members(self, chat_id, user_ids, timeout=None):
        return {"success": True, "failed_user_ids": None,
                "failed_user_details": [
                    {"error_code": "add.participant.privacy", "user_ids": [7, 8]},
                    {"error_code": "add.participant.not.found", "user_ids": [9]},
                ]}


result, warns = capture_warnings(lambda: make_bot(DetailsOnlyApi()).add_chat_members(100, [7, 8, 9]))
assert result is False
assert any("[7, 8, 9]" in w and "add.participant.privacy" in w for w in warns), warns
print("11 ok: add_chat_members, частичные сбои предупреждают с id и кодами")

# 12. get_chat_membership: ChatMember бота
member = make_bot(FakeApi()).get_chat_membership(100)
assert member.status == "administrator" and member.user.id == 2
print("12 ok: get_chat_membership")

# 13. export_chat_invite_link: постоянная ссылка из GET /chats
api = FakeApi()
assert make_bot(api).export_chat_invite_link(100) == "https://max.ru/join/abc"
assert api.calls == [("chat_info", 100)]
print("13 ok: export_chat_invite_link")

# 14. Wire-уровень: user_ids уходит comma-separated, block строкой "true",
#    DELETE admins по правильному пути
calls = []


class OkResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"success": True}


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return OkResponse()


real_request = requests.Session.request
requests.Session.request = fake_request
try:
    api = Api("tok")
    api.get_chat_members(100, user_ids=[1, 2])
    kw = calls[-1]
    assert kw["method"] == "GET"
    assert kw["url"] == "https://platform-api2.max.ru/chats/100/members", kw["url"]
    assert kw["params"] == {"user_ids": "1,2"}, kw["params"]

    api.remove_chat_member(100, 3, block=True)
    kw = calls[-1]
    assert kw["method"] == "DELETE"
    assert kw["params"] == {"user_id": 3, "block": "true"}, kw["params"]

    api.remove_chat_member(100, 3)
    assert calls[-1]["params"] == {"user_id": 3}, calls[-1]["params"]

    api.delete_chat_admin(100, 5)
    kw = calls[-1]
    assert kw["method"] == "DELETE"
    assert kw["url"] == "https://platform-api2.max.ru/chats/100/members/admins/5", kw["url"]

    api.set_chat_admins(100, [{"user_id": 5, "permissions": ["write"]}])
    kw = calls[-1]
    assert kw["method"] == "POST"
    assert json.loads(kw["data"]) == {"admins": [{"user_id": 5, "permissions": ["write"]}]}

    api.add_chat_members(100, [5, 6])
    assert json.loads(calls[-1]["data"]) == {"user_ids": [5, 6]}

    api.get_chat_membership(100)
    assert calls[-1]["url"] == "https://platform-api2.max.ru/chats/100/members/me"
finally:
    requests.Session.request = real_request
print("14 ok: wire-уровень — пути, user_ids строкой, block=true")

print("ALL OK")

"""
События членства: my_chat_member_handler (bot_added/bot_removed/
bot_started/bot_stopped) и chat_member_handler (user_added/user_removed),
синтез телеботовского ChatMemberUpdated.

Запуск:
    python3 tests/test_membership.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

from maxibot import MaxiBot, apihelper
from maxibot.types import ChatMember, ChatMemberUpdated


class FakeApi:
    def __init__(self):
        self.me_calls = 0
        self.chat_info_calls = 0

    def get_bot_info(self):
        self.me_calls += 1
        return {"user_id": 99, "first_name": "Макси", "last_name": "Бот",
                "username": "maxibot", "is_bot": True}

    def get_chat_info(self, chat_id):
        self.chat_info_calls += 1
        return {"title": "chat"}


def make_bot():
    bot = MaxiBot("t", threaded=False)
    bot.api = FakeApi()
    return bot


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def capture_warnings(fn):
    capture = LogCapture()
    logging.getLogger("maxibot").addHandler(capture)
    try:
        result = fn()
    finally:
        logging.getLogger("maxibot").removeHandler(capture)
    return result, [r.getMessage() for r in capture.records
                    if r.levelno == logging.WARNING]


USER = {"user_id": 7, "is_bot": False, "first_name": "Иван", "name": "ivan"}


def membership_update(update_type, **extra):
    upd = {"update_type": update_type, "timestamp": 1751400000000,
           "chat_id": 42, "user": dict(USER)}
    upd.update(extra)
    return upd


# 1. Сигнатуры как в telebot (без **kwargs — кастом-фильтры это №17)
for name in ("my_chat_member_handler", "chat_member_handler",
             "add_my_chat_member_handler", "add_chat_member_handler",
             "register_my_chat_member_handler", "register_chat_member_handler",
             "process_new_my_chat_member", "process_new_chat_member"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = {n: p for n, p in
                   inspect.signature(getattr(telebot.TeleBot, name)).parameters.items()
                   if p.kind is not inspect.Parameter.VAR_KEYWORD}
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры восьми методов как в telebot")

# 2. bot_added -> my_chat_member: left -> member, затронутый — сам бот
bot = make_bot()
got = []


@bot.my_chat_member_handler()
def on_my(member_updated):
    got.append(member_updated)


bot._process_update(membership_update("bot_added", is_channel=False))
# bot_added идёт и в message-пайплайн (как раньше) — Message ходит
# за названием чата; фиксируем базу до bot_removed
calls_after_added = bot.api.chat_info_calls
assert len(got) == 1
cmu = got[0]
assert isinstance(cmu, ChatMemberUpdated)
assert cmu.old_chat_member.status == "left" and cmu.new_chat_member.status == "member"
assert cmu.new_chat_member.user.id == 99  # сам бот, из GET /me
assert cmu.from_user.id == 7 and cmu.from_user.first_name == "Иван"
# chat.type телеботовский (private/group/channel), как у get_chat
assert cmu.chat.id == 42 and cmu.chat.type == "group"
assert cmu.date == 1751400000  # unix-секунды из миллисекунд MAX
assert cmu.invite_link is None and cmu.is_channel is False
# difference — как в telebot: только status (is_member производный)
assert cmu.difference == {"status": ["left", "member"]}, cmu.difference
# GET /me кэшируется: второе событие не ходит в API
bot._process_update(membership_update("bot_removed", is_channel=True))
assert bot.api.me_calls == 1
assert got[1].old_chat_member.status == "member" and got[1].new_chat_member.status == "left"
assert got[1].chat.type == "channel"  # channel в обоих соглашениях
# лёгкий Chat события не ходит за названием чата (у bot_removed бот
# уже удалён из чата) — новых вызовов после bot_added нет
assert bot.api.chat_info_calls == calls_after_added
print("2 ok: bot_added/bot_removed -> ChatMemberUpdated, GET /me кэширован")

# 3. bot_started: и my_chat_member (kicked -> member), и /start-сообщение
bot = make_bot()
got = []


@bot.my_chat_member_handler()
def on_my_started(member_updated):
    got.append(("member", member_updated.old_chat_member.status,
                member_updated.new_chat_member.status))


@bot.message_handler(commands=["start"])
def on_start(message):
    got.append(("start", message.text))


bot._process_update(membership_update("bot_started", payload="ref123"))
assert got[0] == ("member", "kicked", "member"), got
assert got[1][0] == "start" and got[1][1].startswith("/start"), got
assert bot.my_chat_member_handlers  # реестр на месте
# bot_stopped -> member -> kicked; kicked — не участник
got.clear()
bot._process_update(membership_update("bot_stopped"))
assert got == [("member", "member", "kicked")], got
assert ChatMember({"user_id": 1}, status="kicked").is_member is False
print("3 ok: bot_started — событие статуса + /start; bot_stopped -> kicked")

# 4. user_added/user_removed -> chat_member; from_user из inviter/admin
bot = make_bot()
got = []


@bot.chat_member_handler()
def on_member(member_updated):
    got.append(member_updated)


bot._process_update(membership_update("user_added", inviter_id=5, is_channel=False))
bot._process_update(membership_update("user_added", inviter_id=None, is_channel=False))
bot._process_update(membership_update("user_removed", admin_id=6, is_channel=False))
bot._process_update(membership_update("user_removed", admin_id=None, is_channel=False))
assert [c.new_chat_member.status for c in got] == ["member", "member", "left", "left"]
assert got[0].new_chat_member.user.id == 7  # затронутый — из user
assert got[0].from_user.id == 5  # пригласивший
assert got[1].from_user.id == 7  # вошёл по ссылке — сам пользователь
assert got[2].from_user.id == 6  # удалил админ
assert got[3].from_user.id == 7  # сам вышел
assert bot.api.me_calls == 0  # для chat_member данные бота не нужны
# от постороннего инициатора известен только id, а если инициатор —
# сам затронутый, берём его целиком (имя не теряем)
assert got[0].from_user.first_name is None
assert got[1].from_user.first_name == "Иван"
got.clear()
bot._process_update(membership_update("user_added", inviter_id=7, is_channel=False))
assert got[0].from_user.id == 7 and got[0].from_user.first_name == "Иван"
print("4 ok: user_added/user_removed — from_user из inviter_id/admin_id")

# 5. func-фильтр и pass_bot; первый совпавший — единственный
bot = make_bot()
got = []
bot.register_my_chat_member_handler(
    lambda m, bot=None: got.append(("kicked", bot)),
    func=lambda m: m.new_chat_member.status == "kicked", pass_bot=True)
bot.register_my_chat_member_handler(lambda m: got.append(("any", None)))
bot._process_update(membership_update("bot_stopped"))
bot._process_update(membership_update("bot_added", is_channel=False))
assert got == [("kicked", bot), ("any", None)], got
print("5 ok: func-фильтр, pass_bot, первый совпавший")

# 6. Без подписки события членства отбрасываются до разбора; Update
#    несёт телеботовские поля my_chat_member/chat_member (None без событий)
bot = make_bot()
bot._process_update(membership_update("bot_removed", is_channel=False))
bot._process_update(membership_update("user_added", is_channel=False))
assert bot.api.me_calls == 0 and bot.api.chat_info_calls == 0
from maxibot.types import Update
upd = Update({"update_type": "message_removed", "timestamp": 1}, FakeApi())
assert upd.my_chat_member is None and upd.chat_member is None
print("6 ok: без подписки события не разбираются; поля Update на месте")

# 7. Middleware типа события видит update.my_chat_member (объект строится
#    и для одного middleware, без обработчиков)
apihelper.ENABLE_MIDDLEWARE = True
try:
    bot = make_bot()
    got = []

    @bot.middleware_handler(update_types=["bot_removed"])
    def mw(bot_instance, update):
        got.append(update.my_chat_member)

    bot._process_update(membership_update("bot_removed", is_channel=False))
    assert len(got) == 1 and isinstance(got[0], ChatMemberUpdated)
    assert got[0].new_chat_member.status == "left"
finally:
    apihelper.ENABLE_MIDDLEWARE = False
print("7 ok: middleware видит update.my_chat_member")

# 8. process_new_* напрямую; сетевая ошибка GET /me не роняет событие
bot = make_bot()
got = []
bot.add_chat_member_handler(bot._build_handler_dict(lambda m: got.append(m)))
cmu = bot._build_chat_member_updated(membership_update("user_added", is_channel=False))
bot.process_new_chat_member([cmu])
assert got == [cmu]


class ErrApi(FakeApi):
    def get_bot_info(self):
        raise RuntimeError("сеть упала")


bot = make_bot()
bot.api = ErrApi()
got = []
bot.register_my_chat_member_handler(lambda m: got.append(m))
bot._process_update(membership_update("bot_added", is_channel=False))
assert len(got) == 1 and got[0].new_chat_member.user.id is None
assert bot._bot_member_payload is None  # кэш не испорчен, попробуем ещё
print("8 ok: process_new_* и деградация при недоступном GET /me")

# 9. Непонятный payload события членства не отменяет обработку обновления:
#    ошибка логируется, общий middleware и message-ветки работают
apihelper.ENABLE_MIDDLEWARE = True
try:
    bot = make_bot()
    seen, handled = [], []
    bot.register_middleware_handler(lambda b, u: seen.append(u.update_type))
    bot.register_my_chat_member_handler(lambda m: handled.append(m))
    bot._process_update({"update_type": "bot_added", "timestamp": 1751400000000,
                         "chat_id": 42, "user": "строка вместо объекта",
                         "is_channel": False})
    assert seen == ["bot_added"], seen  # middleware получил обновление
    assert handled == []  # событие не построилось, но и не уронило разбор
    # нечисловой timestamp — date None, событие живо
    bot._process_update({"update_type": "bot_removed", "timestamp": "1751400000000",
                         "chat_id": 42, "user": dict(USER), "is_channel": False})
    assert len(handled) == 1 and handled[0].date is None
finally:
    apihelper.ENABLE_MIDDLEWARE = False
print("9 ok: битый payload не роняет обработку обновления")

# 10. Телеботовский middleware update_types=['my_chat_member'] работает
#     и получает ChatMemberUpdated (а не Update/Message)
apihelper.ENABLE_MIDDLEWARE = True
try:
    bot = make_bot()
    got = []

    @bot.middleware_handler(update_types=["my_chat_member"])
    def mw_my(bot_instance, obj):
        got.append(obj)

    @bot.middleware_handler(update_types=["chat_member"])
    def mw_chat(bot_instance, obj):
        got.append(obj)

    bot._process_update(membership_update("bot_stopped"))
    bot._process_update(membership_update("user_added", is_channel=False))
    assert len(got) == 2 and all(isinstance(o, ChatMemberUpdated) for o in got), got
    assert got[0].new_chat_member.status == "kicked"
    assert got[1].new_chat_member.status == "member"
    # общий middleware тоже видит объект в update.my_chat_member
    bot = make_bot()
    seen = []
    bot.register_middleware_handler(lambda b, u: seen.append(u.my_chat_member))
    bot._process_update(membership_update("bot_removed", is_channel=False))
    assert isinstance(seen[0], ChatMemberUpdated), seen
finally:
    apihelper.ENABLE_MIDDLEWARE = False
print("10 ok: middleware my_chat_member/chat_member и общий видят объект")

# 11. language_code из user_locale (bot_started/bot_stopped);
#     инициатор с id 0 не подменяется затронутым пользователем
bot = make_bot()
got = []
bot.register_my_chat_member_handler(lambda m: got.append(m))
bot._process_update(membership_update("bot_started", user_locale="ru-RU"))
assert got[0].from_user.language_code == "ru-RU"
bot = make_bot()
got = []
bot.register_chat_member_handler(lambda m: got.append(m))
bot._process_update(membership_update("user_removed", admin_id=0, is_channel=False))
assert got[0].from_user.id == 0, got[0].from_user.id
print("11 ok: language_code из user_locale, инициатор с id 0")

# 12. Дедупликация bot_added живёт в самом боте — одинаково для
#     поллинга и webhook (оба идут через _process_update)
bot = make_bot()
seen = []
bot.register_my_chat_member_handler(lambda m: seen.append((m.chat.id, m.date)))
dup = membership_update("bot_added", is_channel=False)
bot._process_update(dict(dup))
bot._process_update(dict(dup))          # точный дубль MAX — проглочен
assert len(seen) == 1, seen
# тот же чат, другое время — законное повторное добавление, СРАЗУ
# после дубля (ключ обязан учитывать время, не только чат)
later = membership_update("bot_added", is_channel=False)
later["timestamp"] = 1751400999000
bot._process_update(later)
other = membership_update("bot_added", is_channel=False)
other["chat_id"] = 43
bot._process_update(other)              # другой чат — событие
assert [c for c, _ in seen] == [42, 42, 43], seen
# без chat_id дубль тоже отсекается (раньше ключ None ломал сравнение)
bot = make_bot()
seen = []
bot.register_my_chat_member_handler(lambda m: seen.append(m.chat.id))
blank = {"update_type": "bot_added", "timestamp": 1751400000000,
         "user": dict(USER), "is_channel": False}
bot._process_update(dict(blank))
bot._process_update(dict(blank))
assert len(seen) == 1, seen
# в поллинге своей дедупликации больше нет — транспорт только передаёт
from maxibot.core.network.polling import Polling

assert not hasattr(Polling(api=FakeApi()), "is_prev_add")
print("12 ok: дедупликация bot_added — в боте, для поллинга и webhook")

# 13. Middleware на СЫРОЙ тип MAX (bot_removed/user_added) получает Update
#     с построенным объектом; на bot_added/bot_started — Message, и
#     объект ради него не строится (лишний GET /me не нужен)
apihelper.ENABLE_MIDDLEWARE = True
try:
    for raw_type, field in (("bot_removed", "my_chat_member"),
                            ("user_added", "chat_member"),
                            ("user_removed", "chat_member")):
        bot = make_bot()
        seen = []
        bot.add_middleware_handler(
            lambda b, u, box=seen: box.append(getattr(u, "my_chat_member", None)
                                              or getattr(u, "chat_member", None)),
            update_types=[raw_type])
        bot._process_update(membership_update(raw_type, is_channel=False))
        assert len(seen) == 1 and isinstance(seen[0], ChatMemberUpdated), (raw_type, seen)
    bot = make_bot()
    got = []
    bot.add_middleware_handler(lambda b, obj: got.append(obj),
                               update_types=["bot_added"])
    bot._process_update(membership_update("bot_added", is_channel=False))
    assert len(got) == 1 and not isinstance(got[0], ChatMemberUpdated)
    assert bot.api.me_calls == 0, "GET /me ради невидимого объекта"
finally:
    apihelper.ENABLE_MIDDLEWARE = False
print("13 ok: middleware сырых типов видит объект; bot_added не строит зря")

# 14. Одна функция на 'message' и 'my_chat_member' получает ОБА объекта
#     (в telebot это разные обновления)
apihelper.ENABLE_MIDDLEWARE = True
try:
    bot = make_bot()
    got = []
    bot.register_middleware_handler(lambda b, obj: got.append(type(obj).__name__),
                                    update_types=["message", "my_chat_member"])
    bot._process_update(membership_update("bot_started"))
    assert got == ["Message", "ChatMemberUpdated"], got
finally:
    apihelper.ENABLE_MIDDLEWARE = False
print("14 ok: общая функция на message+my_chat_member получает оба объекта")

# 15. allowed_updates: телеботовские имена разворачиваются в типы MAX,
#     невозможные убираются с предупреждением
normalized = MaxiBot._normalize_allowed_updates(
    ["message", "my_chat_member", "chat_member", "message_created"])
assert normalized == ["message_created", "bot_added", "bot_removed",
                      "bot_started", "bot_stopped", "user_added",
                      "user_removed"], normalized
result, warns = capture_warnings(
    lambda: MaxiBot._normalize_allowed_updates(["poll", "выдумка", "message_created"]))
assert result == ["message_created"], result
assert any("в MAX нет" in w for w in warns) and any("неизвестные" in w for w in warns), warns
assert MaxiBot._normalize_allowed_updates(None) is None
print("15 ok: allowed_updates нормализуется под имена MAX")

# 16. Два бота в одном процессе не делят кэш данных бота
bot_a, bot_b = make_bot(), make_bot()
bot_b.api.get_bot_info = lambda: {"user_id": 100, "first_name": "Другой", "is_bot": True}
got_a, got_b = [], []
bot_a.register_my_chat_member_handler(lambda m: got_a.append(m.new_chat_member.user.id))
bot_b.register_my_chat_member_handler(lambda m: got_b.append(m.new_chat_member.user.id))
bot_a._process_update(membership_update("bot_removed", is_channel=False))
bot_b._process_update(membership_update("bot_removed", is_channel=False))
assert got_a == [99] and got_b == [100], (got_a, got_b)
print("16 ok: кэш данных бота — на экземпляр")

print("ALL OK")

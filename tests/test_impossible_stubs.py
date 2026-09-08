"""
Warn-стабы невозможных в MAX методов telebot: действия бросают
NotImplementedError, регистрация обработчиков предупреждает и не роняет.

Запуск:
    python3 tests/test_impossible_stubs.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

import maxibot
from maxibot import (
    MaxiBot,
    _MAX_DEAD_HANDLER_CALLS,
    _MAX_DEAD_HANDLER_DECORATORS,
    _MAX_IMPOSSIBLE_ACTIONS,
    _MAX_MISSING_FEATURES,
)

ALL_STUBS = {**_MAX_IMPOSSIBLE_ACTIONS, **_MAX_DEAD_HANDLER_DECORATORS,
             **_MAX_DEAD_HANDLER_CALLS}

# 1. Состав: 97 заглушек, все имена — настоящие телеботовские, фичи известны
assert len(ALL_STUBS) == 97, len(ALL_STUBS)
assert len(_MAX_IMPOSSIBLE_ACTIONS) == 57
assert len(_MAX_DEAD_HANDLER_DECORATORS) == 9
assert len(_MAX_DEAD_HANDLER_CALLS) == 31
for name, feature in ALL_STUBS.items():
    assert hasattr(MaxiBot, name), name
    assert hasattr(telebot.TeleBot, name), f"{name} — нет в telebot 4.15.4"
    assert feature in _MAX_MISSING_FEATURES, (name, feature)
print("1 ok: 97 заглушек, имена сверены с telebot")


# 2. Действия: NotImplementedError с именем метода и причиной,
# любые аргументы (не TypeError)
def make_bot():
    return MaxiBot("t", threaded=False)


bot = make_bot()
for name in _MAX_IMPOSSIBLE_ACTIONS:
    try:
        getattr(bot, name)("аргумент", 123, kwarg="да", another=None)
        assert False, f"{name} не бросил"
    except NotImplementedError as e:
        assert str(e).startswith(name + ":"), (name, str(e))
        assert "MAX" in str(e), name
# представительные телеботовские вызовы с настоящими сигнатурами
try:
    bot.send_poll(42, "Вопрос?", ["да", "нет"], is_anonymous=False)
    assert False
except NotImplementedError as e:
    assert "опросов" in str(e)
try:
    bot.create_forum_topic(42, "Тема", icon_color=None)
    assert False
except NotImplementedError as e:
    assert "форумов" in str(e).lower() or "Форумов" in str(e)
print("2 ok: 57 действий бросают NotImplementedError")

# 3. Декораторы обработчиков: warning, функция возвращается как есть,
# бот продолжает работать
records = []
handler = logging.Handler()
handler.emit = records.append
logging.getLogger("maxibot").addHandler(handler)
try:
    bot = make_bot()
    for name in _MAX_DEAD_HANDLER_DECORATORS:
        records.clear()

        @getattr(bot, name)(func=lambda x: True)
        def dead(update):
            raise AssertionError("не должен вызываться")

        assert dead.__name__ == "dead", name                    # вернулась та же функция
        assert len(records) == 1, name
        msg = records[0].getMessage()
        assert name in msg and "никогда не будет вызван" in msg, (name, msg)
finally:
    logging.getLogger("maxibot").removeHandler(handler)
print("3 ok: 9 декораторов предупреждают и не роняют")

# 4. add_/register_/process_new_: warning, None, не бросают
records = []
handler = logging.Handler()
handler.emit = records.append
logging.getLogger("maxibot").addHandler(handler)
try:
    bot = make_bot()
    for name in _MAX_DEAD_HANDLER_CALLS:
        records.clear()
        result = getattr(bot, name)(lambda u: None, func=None, pass_bot=True)
        assert result is None, name
        assert len(records) == 1 and name in records[0].getMessage(), name
finally:
    logging.getLogger("maxibot").removeHandler(handler)
print("4 ok: 31 регистрация/процесс — warn и no-op")

# 5. Бот с телеботовскими регистрациями ЗАПУСКАЕТСЯ и обрабатывает сообщения
bot = make_bot()


class FakeApi:
    def get_chat_info(self, chat_id):
        return {"title": "chat"}


bot.api = FakeApi()
bot.register_poll_handler(lambda p: None, func=None)

@bot.poll_answer_handler()
def on_answer(a):
    pass

fired = []

@bot.message_handler(content_types=["text"])
def on_text(m):
    fired.append(m.text)

bot.process_new_updates([{
    "update_type": "message_created",
    "timestamp": 1751400000000,
    "message": {
        "sender": {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u"},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "m1", "seq": 1, "text": "живой"},
    },
}])
assert fired == ["живой"]
print("5 ok: бот с мёртвыми обработчиками живёт")

# 6. Заглушки не затёрли настоящие методы (инвариант таблиц)
REAL = ("send_message", "send_sticker", "get_chats", "get_chat_history",
        "export_chat_invite_link", "ban_chat_member", "set_my_name",
        "comment_handler", "unban_chat_member", "answer_inline_query",
        "inline_handler")
for name in REAL:
    assert name not in ALL_STUBS, f"{name} попал в таблицу заглушек"
# и у стабов честные docstring с отсылкой к docs
assert "not_in_max.md" in MaxiBot.send_poll.__doc__
assert "not_in_max.md" in MaxiBot.poll_handler.__doc__
assert "not_in_max.md" in MaxiBot.process_new_poll.__doc__
assert os.path.isfile(os.path.join(os.path.dirname(__file__), "..",
                                   "maxibot", "docs", "not_in_max.md"))
print("6 ok: настоящие методы не тронуты, docstring и docs на месте")

# 7. Полнота: у telebot.TeleBot не осталось публичных методов,
# которых нет у MaxiBot (кроме осознанных исключений)
telebot_public = {n for n in dir(telebot.TeleBot) if not n.startswith("_")
                  and callable(getattr(telebot.TeleBot, n))}
ours = {n for n in dir(MaxiBot) if not n.startswith("_")}
missing = sorted(telebot_public - ours)
KNOWN_ABSENT = {
    "setup_middleware",   # телеботовский class-based middleware (BaseMiddleware) не портирован
}
unexpected = [n for n in missing if n not in KNOWN_ABSENT]
assert not unexpected, f"у MaxiBot нет методов telebot: {unexpected}"
print(f"7 ok: паритет поверхности полный (осознанно нет: {sorted(KNOWN_ABSENT)})")

# 8. Попутно закрытые дыры поверхности (эмулируемые, были AttributeError)
records = []
handler = logging.Handler()
handler.emit = records.append
logging.getLogger("maxibot").addHandler(handler)
try:
    MaxiBot.check_commands_input(["start", "help"], "тест")      # ок — тихо
    MaxiBot.check_regexp_input("^да$", "тест")
    assert records == []
    MaxiBot.check_commands_input("не список", "тест")
    MaxiBot.check_commands_input(["start", 42], "тест")          # список, но не строк
    MaxiBot.check_regexp_input(123, "тест")
    assert len(records) == 3 and all(r.levelno == logging.ERROR for r in records)
    assert "тест" in records[0].getMessage()
finally:
    logging.getLogger("maxibot").removeHandler(handler)


class DeleteApi:
    def __init__(self):
        self.deleted = []

    def send_message(self, msg_id=None, method=None, **kw):
        if msg_id == "плохой":
            from maxibot.exceptions import MaxApiHTTPException

            class Resp:
                status_code, reason, text = 404, "Not Found", "{}"
            raise MaxApiHTTPException("DELETE /messages", Resp())
        self.deleted.append((msg_id, method))
        return {}


bot = make_bot()
bot.api = DeleteApi()
assert bot.delete_messages(42, ["m1", "плохой", "m2"]) is True   # плохой пропущен
assert bot.api.deleted == [("m1", "DELETE"), ("m2", "DELETE")]
for name, hint in (("get_user_profile_photos", "avatar_url"),
                   ("restrict_chat_member", "ban_chat_member")):
    try:
        getattr(bot, name)(42, 7)
        assert False, name
    except NotImplementedError as e:
        assert "пока не реализован" in str(e) and hint in str(e), (name, str(e))
print("8 ok: валидаторы, delete_messages циклом, честные «пока не реализован»")

print("ALL OK")

"""
Проверка disable_web_page_preview и clear_step_handler (релиз после 1.0.22).

1. disable_web_page_preview: параметр каждого вызова, как в telebot.
   На уровне Api.send_message превращается в query-параметр
   disable_link_preview="true"/"false" (строго строкой в нижнем регистре),
   только у POST /messages; None — параметр не отправляется вовсе.
2. clear_step_handler(message) / clear_step_handler_by_chat_id(chat_id) —
   сигнатуры один в один с telebot, сбрасывают ожидание register_next_step_handler.

Запуск:
    python3 tests/test_preview_and_steps.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None

from maxibot import MaxiBot
from maxibot.apihelper import Api

SEND_OK = {
    "message": {
        "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.123", "seq": 5, "text": "hi", "attachments": []},
    }
}


# ---------------------------------------------------------------------------
# Часть 1: Api.send_message — формирование query-параметров
# ---------------------------------------------------------------------------

class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path=None, url=None, params=None, data=None, **kw):
        self.calls.append({"method": method, "path": path, "params": params or {}, "data": data or {}})
        return SEND_OK


def make_api():
    api = Api.__new__(Api)
    api.client = FakeClient()
    return api


# 1. True -> params["disable_link_preview"] == "true" (строка, нижний регистр)
api = make_api()
api.send_message(chat_id="42", text="see https://example.com", disable_link_preview=True)
p = api.client.calls[0]["params"]
assert p.get("disable_link_preview") == "true", p
assert isinstance(p["disable_link_preview"], str)
print('1 ok: True -> "true" строкой')

# 2. False -> "false"
api = make_api()
api.send_message(chat_id="42", text="t", disable_link_preview=False)
assert api.client.calls[0]["params"].get("disable_link_preview") == "false"
print('2 ok: False -> "false"')

# 3. None (дефолт) -> параметра нет вовсе
api = make_api()
api.send_message(chat_id="42", text="t")
assert "disable_link_preview" not in api.client.calls[0]["params"]
print('3 ok: None -> параметр не отправляется')

# 4. PUT (редактирование): параметра нет даже при явном True — у PUT /messages его нет в API
api = make_api()
api.send_message(msg_id="mid.1", text="t", method="PUT", disable_link_preview=True)
assert "disable_link_preview" not in api.client.calls[0]["params"]
print('4 ok: PUT — флаг не отправляется')

# 5. answer_callback: флаг уходит в query POST /answers
api = make_api()
api.answer_callback(callback_id="cb1", text="t", disable_link_preview=True)
call = api.client.calls[0]
assert call["path"] == "/answers"
assert call["params"].get("disable_link_preview") == "true"
print('5 ok: answer_callback пробрасывает флаг')

# 6. Bot.send_message: telebot-имя disable_web_page_preview доходит до query
bot = MaxiBot.__new__(MaxiBot)
bot.api = make_api()
bot.send_retry_timeout = 120
bot.publish_wait_timeout = 0
bot.send_message(42, "see https://example.com", disable_web_page_preview=True)
assert bot.api.client.calls[0]["params"].get("disable_link_preview") == "true"
print('6 ok: bot.send_message(disable_web_page_preview=True)')

# 7. Bot.send_message без параметра — query чистый (ничего не ломаем)
bot.api = make_api()
bot.send_message(42, "t")
assert "disable_link_preview" not in bot.api.client.calls[0]["params"]
print('7 ok: без параметра query чистый')


# ---------------------------------------------------------------------------
# Часть 2: clear_step_handler / clear_step_handler_by_chat_id
# ---------------------------------------------------------------------------

class FakeUser:
    def __init__(self, id):
        self.id = id


class FakeChat:
    def __init__(self, id):
        self.id = id


class FakeMessage:
    def __init__(self, user_id, chat_id=None):
        self.from_user = FakeUser(user_id)
        self.chat = FakeChat(chat_id if chat_id is not None else user_id)


def make_bot():
    bot = MaxiBot.__new__(MaxiBot)
    bot._next_steps = {}
    return bot


# 8. register -> clear_step_handler(message) снимает ожидание
bot = make_bot()
msg = FakeMessage(user_id=42)
bot.register_next_step_handler(msg, lambda m: None)
assert 42 in bot._next_steps
bot.clear_step_handler(msg)
assert 42 not in bot._next_steps
print('8 ok: clear_step_handler(message)')

# 9. clear_step_handler_by_chat_id(chat_id) — как в заплатке trim_bot
bot = make_bot()
bot.register_next_step_handler(FakeMessage(user_id=42), lambda m: None)
bot.clear_step_handler_by_chat_id(42)
assert 42 not in bot._next_steps
print('9 ok: clear_step_handler_by_chat_id')

# 10. str/int представления chat_id взаимозаменяемы
bot = make_bot()
bot.register_next_step_handler(FakeMessage(user_id=42), lambda m: None)
bot.clear_step_handler_by_chat_id("42")
assert 42 not in bot._next_steps
print('10 ok: chat_id="42" снимает ключ 42')

# 11. Сброс несуществующего ожидания не падает (идемпотентность)
bot = make_bot()
bot.clear_step_handler_by_chat_id(999)
bot.clear_step_handler(FakeMessage(user_id=999))
print('11 ok: сброс без регистрации не падает')

# 12. Сброс не задевает чужие ожидания
bot = make_bot()
bot.register_next_step_handler(FakeMessage(user_id=1), lambda m: None)
bot.register_next_step_handler(FakeMessage(user_id=2), lambda m: None)
bot.clear_step_handler_by_chat_id(1)
assert 1 not in bot._next_steps and 2 in bot._next_steps
print('12 ok: соседние ожидания не задеты')

print('ALL OK')

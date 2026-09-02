"""
Проверка reply_to и reply_to_message_id (issue #35).

reply_to(message, text, **kwargs) — сигнатура один в один с telebot:
делегирует в send_message(message.chat.id, text,
reply_to_message_id=message.message_id, **kwargs).
На уровне MAX API ответ — это поле link={"type": "reply", "mid": ...}
в теле POST /messages.

Запуск:
    python3 tests/test_reply_to.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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


def make_bot():
    bot = MaxiBot("t")  # конструктор сеть не трогает
    bot.api = make_api()
    return bot


class FakeChat:
    def __init__(self, id):
        self.id = id


class FakeMessage:
    def __init__(self, chat_id, message_id):
        self.chat = FakeChat(chat_id)
        self.message_id = message_id


# 1. Api.send_message(link=...) кладёт link в тело запроса
api = make_api()
api.send_message(chat_id="42", text="t", link={"type": "reply", "mid": "mid.9"})
assert api.client.calls[0]["data"].get("link") == {"type": "reply", "mid": "mid.9"}
print('1 ok: link уходит в тело POST /messages')

# 2. Без link поле не отправляется
api = make_api()
api.send_message(chat_id="42", text="t")
assert "link" not in api.client.calls[0]["data"]
print('2 ok: без link тело чистое')

# 3. Bot.send_message(reply_to_message_id=...) — telebot-имя доходит до link
bot = make_bot()
bot.send_message(42, "t", reply_to_message_id="mid.9")
assert bot.api.client.calls[0]["data"].get("link") == {"type": "reply", "mid": "mid.9"}
print('3 ok: reply_to_message_id -> link type=reply')

# 4. Bot.send_message без параметра — link нет (ничего не ломаем)
bot = make_bot()
bot.send_message(42, "t")
assert "link" not in bot.api.client.calls[0]["data"]
print('4 ok: без параметра link не отправляется')

# 5. reply_to(message, text) — делегат: чат из message.chat.id, mid из message.message_id
bot = make_bot()
msg = FakeMessage(chat_id=42, message_id="mid.777")
result = bot.reply_to(msg, "ответ")
call = bot.api.client.calls[0]
assert call["params"].get("chat_id") == "42", call["params"]
assert call["data"].get("link") == {"type": "reply", "mid": "mid.777"}
assert call["data"].get("text") == "ответ"
assert result.message_id == "mid.123"
print('5 ok: reply_to делегирует в send_message')

# 6. reply_to пробрасывает kwargs в send_message
bot = make_bot()
bot.reply_to(FakeMessage(42, "mid.777"), "т", parse_mode="HTML", disable_web_page_preview=True)
call = bot.api.client.calls[0]
assert call["data"].get("format") == "html"
assert call["params"].get("disable_link_preview") == "true"
print('6 ok: kwargs пробрасываются')

print('ALL OK')

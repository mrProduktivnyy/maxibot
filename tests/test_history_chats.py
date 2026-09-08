"""
История чата и список чатов (MAX-бонус): get_chat_history,
get_messages, get_chats + iter_chats с автопагинацией.

Запуск:
    python3 tests/test_history_chats.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot
from maxibot.apihelper import Api
from maxibot.types import Chat, ChatList


class FakeClient:
    def __init__(self, response=None):
        self.calls = []
        self.response = response if response is not None else {}

    def request(self, method, path, params=None, data=None, timeout=None, **kw):
        self.calls.append({"method": method, "path": path,
                           "params": params, "timeout": timeout})
        return self.response


def make_api(response=None):
    api = Api.__new__(Api)
    api.client = FakeClient(response)
    return api


def raw_message(mid="mid.1", text="привет", ts=1751400000000):
    return {
        "sender": {"user_id": 7, "is_bot": False, "first_name": "Вася", "name": "vasya"},
        "recipient": {"chat_id": 42, "chat_type": "chat", "user_id": None},
        "timestamp": ts,
        "body": {"mid": mid, "seq": 1, "text": text},
    }


# 1. Api.get_messages: путь и все query-параметры, from/to как в спеке
api = make_api({"messages": []})
api.get_messages(chat_id=42, from_time=1751400000000, to_time=1751300000000,
                 count=20, timeout=7)
call = api.client.calls[0]
assert call["method"] == "GET" and call["path"] == "/messages"
assert call["params"] == {"chat_id": 42, "from": 1751400000000,
                          "to": 1751300000000, "count": 20}
assert call["timeout"] == 7
api.get_messages(message_ids=["m1", "m2"])                        # список через запятую
assert api.client.calls[1]["params"] == {"message_ids": "m1,m2"}
api.get_messages(message_ids="m3")                                # строка как есть
assert api.client.calls[2]["params"] == {"message_ids": "m3"}
api.get_messages()
assert api.client.calls[3]["params"] == {}                        # None не уходят
print("1 ok: Api.get_messages")

# 2. Api.get_chats: count/marker
api = make_api({"chats": [], "marker": None})
api.get_chats(count=30, marker=777, timeout=5)
call = api.client.calls[0]
assert call["method"] == "GET" and call["path"] == "/chats"
assert call["params"] == {"count": 30, "marker": 777} and call["timeout"] == 5
api.get_chats()
assert api.client.calls[1]["params"] == {}
print("2 ok: Api.get_chats")


# 3. bot.get_chat_history -> List[Message], свежие первыми (порядок сервера)
class HistoryApi:
    def __init__(self):
        self.calls = []

    def get_messages(self, **kw):
        self.calls.append(kw)
        return {"messages": [raw_message("mid.new", "новое", 1751400000000),
                             raw_message("mid.old", "старое", 1751300000000)]}

    def get_chat_info(self, chat_id):
        return {"title": "Чат"}


bot = MaxiBot("t", threaded=False)
bot.api = HistoryApi()
history = bot.get_chat_history(42, count=2, from_time=111, to_time=22)
assert bot.api.calls[0] == {"chat_id": 42, "from_time": 111, "to_time": 22,
                            "count": 2, "timeout": None}
assert [m.message_id for m in history] == ["mid.new", "mid.old"]
assert history[0].text == "новое" and history[0].chat.id == 42
assert isinstance(history[0].date, datetime)                      # timestamp пророс в date
assert history[0].date > history[1].date                          # свежее первым
bot.get_chat_history(42)
assert bot.api.calls[1]["count"] == 50                            # дефолт 50, как у сервера
print("3 ok: get_chat_history")

# 4. bot.get_messages по списку id (и одиночной строкой)
bot = MaxiBot("t", threaded=False)
bot.api = HistoryApi()
msgs = bot.get_messages(["mid.new", "mid.old"])
assert bot.api.calls[0] == {"message_ids": ["mid.new", "mid.old"], "timeout": None}
assert len(msgs) == 2 and msgs[1].text == "старое"
bot.get_messages("mid.new", timeout=9)
assert bot.api.calls[1] == {"message_ids": "mid.new", "timeout": 9}
# кривой ответ не роняет
bot.api.get_messages = lambda **kw: "не словарь"
assert bot.get_messages("x") == []
print("4 ok: get_messages")


# 5. bot.get_chats -> ChatList: объекты Chat, маркер, поведение списка
def raw_chat(chat_id, chat_type="chat", title="Группа"):
    return {"chat_id": chat_id, "type": chat_type, "title": title,
            "status": "active", "participants_count": 3}


class ChatsApi:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get_chats(self, **kw):
        self.calls.append(kw)
        return self.pages.pop(0)

    def get_chat_info(self, chat_id):
        return {"title": "Чат"}


bot = MaxiBot("t", threaded=False)
bot.api = ChatsApi([{"chats": [raw_chat(1, "dialog", "Вася"),
                               raw_chat(2, "channel", "Канал")], "marker": 999}])
page = bot.get_chats(count=2)
assert isinstance(page, ChatList) and page.marker == 999
assert bot.api.calls[0] == {"count": 2, "marker": None, "timeout": None}
assert len(page) == 2 and isinstance(page[0], Chat)
assert page[0].id == 1 and page[0].type == "private"              # dialog -> private
assert page[1].type == "channel" and page[1].title == "Канал"
assert [c.id for c in page] == [1, 2]                             # итерация
print("5 ok: get_chats -> ChatList")

# 6. iter_chats: автопагинация по marker до конца
bot = MaxiBot("t", threaded=False)
bot.api = ChatsApi([
    {"chats": [raw_chat(1), raw_chat(2)], "marker": 111},
    {"chats": [raw_chat(3)], "marker": None},
])
seen = [c.id for c in bot.iter_chats(count=2)]
assert seen == [1, 2, 3]
assert [c.get("marker") for c in bot.api.calls] == [None, 111]    # маркер пробрасывается
assert all(c.get("count") == 2 for c in bot.api.calls)
# защита от вечного цикла: пустая страница с ненулевым marker
bot.api = ChatsApi([{"chats": [], "marker": 5}, {"chats": [], "marker": 5}])
assert list(bot.iter_chats()) == []
assert len(bot.api.calls) == 1                                    # второй раз не пошли
print("6 ok: iter_chats")

# 7. ChatList устойчив к кривому ответу
empty = ChatList("не словарь", api=None)
assert len(empty) == 0 and empty.marker is None
empty = ChatList({"chats": [raw_chat(1), "мусор"]}, api=None)
assert len(empty) == 1                                            # не-dict пропущен
print("7 ok: ChatList устойчив")

print("ALL OK")

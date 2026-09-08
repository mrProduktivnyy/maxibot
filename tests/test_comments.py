"""
Комментарии к постам каналов (MAX-бонус): 5 эндпоинтов
/messages/{messageId}/comments и обработчики
comment_created/comment_edited/comment_removed.

Запуск:
    python3 tests/test_comments.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot
from maxibot.apihelper import Api
from maxibot.types import CommentRemoved, Update
from maxibot.util import update_types


class FakeClient:
    """Подменный сетевой клиент: пишет запросы, отдаёт заготовку."""

    def __init__(self, response=None):
        self.calls = []
        self.response = response if response is not None else {}

    def request(self, method, path, params=None, data=None, timeout=None, **kw):
        self.calls.append({"method": method, "path": path,
                           "params": params, "data": data, "timeout": timeout})
        return self.response


def make_api(response=None):
    api = Api.__new__(Api)                       # без сети и токена
    api.client = FakeClient(response)
    return api


COMMENT = {
    "sender": {"user_id": 7, "is_bot": False, "first_name": "Вася", "name": "vasya"},
    "recipient": {"chat_id": 42, "chat_type": "channel", "user_id": None},
    "timestamp": 1751400000000,
    "link": {"type": "reply", "message": {"mid": "mid.post", "seq": 1, "text": "пост"}},
    "body": {"mid": "cmid.1", "seq": 5, "text": "первый!"},
}


# 1. Api.get_comments: путь, все query-параметры, список id через запятую
api = make_api({"messages": []})
api.get_comments("mid.post", count=10, before=111, after=222,
                 comment_ids=["c1", "c2"], timeout=9)
call = api.client.calls[0]
assert call["method"] == "GET" and call["path"] == "/messages/mid.post/comments"
assert call["params"] == {"count": 10, "before": 111, "after": 222, "comment_ids": "c1,c2"}
assert call["timeout"] == 9
api.get_comments("mid.post")
assert api.client.calls[1]["params"] == {}                       # None не уходит
api.get_comments("mid.post", comment_ids="c3")                   # строка — как есть
assert api.client.calls[2]["params"] == {"comment_ids": "c3"}
print("1 ok: Api.get_comments")

# 2. Api.get_comment / send_comment / edit_comment / delete_comment — HTTP-обвязка
api = make_api()
api.get_comment("mid.post", "cmid.1")
assert api.client.calls[0]["method"] == "GET"
assert api.client.calls[0]["path"] == "/messages/mid.post/comments/cmid.1"

api.send_comment("mid.post", text="привет", link={"type": "reply", "mid": "cmid.0"},
                 format="markdown", disable_link_preview=True)
call = api.client.calls[1]
assert call["method"] == "POST" and call["path"] == "/messages/mid.post/comments"
assert call["params"] == {"disable_link_preview": "true"}        # строкой, не True
assert call["data"] == {"text": "привет",
                        "link": {"type": "reply", "mid": "cmid.0"},
                        "format": "markdown"}
api.send_comment("mid.post", text="без превью", disable_link_preview=False)
assert api.client.calls[2]["params"] == {"disable_link_preview": "false"}
api.send_comment("mid.post", link={"type": "forward", "mid": "x"}, format="html")
assert api.client.calls[3]["data"] == {"link": {"type": "forward", "mid": "x"}}  # format только с текстом

api.edit_comment("mid.post", "cmid.1", text="новый", format="html")
call = api.client.calls[4]
assert call["method"] == "PUT" and call["path"] == "/messages/mid.post/comments"
assert call["params"] == {"message_id": "mid.post", "comment_id": "cmid.1"}
assert call["data"] == {"text": "новый", "format": "html"}

api.delete_comment("mid.post", "cmid.1")
call = api.client.calls[5]
assert call["method"] == "DELETE" and call["path"] == "/messages/mid.post/comments"
assert call["params"] == {"comment_id": "cmid.1"}
print("2 ok: обвязка get_comment/send/edit/delete")


# 3. Бот: get_comments/get_comment оборачивают в Message
class FakeBotApi:
    def __init__(self):
        self.chat_info_calls = 0

    def get_chat_info(self, chat_id):
        self.chat_info_calls += 1
        return {"title": "Канал"}

    def get_comments(self, message_id, **kw):
        return {"messages": [COMMENT]}

    def get_comment(self, message_id, comment_id, **kw):
        return dict(COMMENT)

    def send_comment(self, message_id, **kw):
        self.sent = {"message_id": message_id, **kw}
        return {"message": COMMENT}

    def edit_comment(self, message_id, comment_id, **kw):
        self.edited = {"message_id": message_id, "comment_id": comment_id, **kw}
        return {"success": True}

    def delete_comment(self, message_id, comment_id, **kw):
        return {"success": False}


def make_bot():
    bot = MaxiBot("t", threaded=False)
    bot.api = FakeBotApi()
    return bot


bot = make_bot()
comments = bot.get_comments("mid.post")
assert len(comments) == 1 and comments[0].text == "первый!"
assert comments[0].message_id == "cmid.1"
assert comments[0].chat.id == 42 and comments[0].chat.type == "channel"
assert comments[0].reply_to_message.message_id == "mid.post"     # на что отвечает
one = bot.get_comment("mid.post", "cmid.1")
assert one.text == "первый!" and one.message_id == "cmid.1"
print("3 ok: get_comments/get_comment -> Message")

# 4. Бот: send_comment (parse_mode бота), edit_comment/delete_comment -> bool
bot = make_bot()
sent = bot.send_comment("mid.post", "привет", disable_link_preview=True)
assert sent.text == "первый!"                                    # обёртка ответа
assert bot.api.sent["format"] == "markdown"                      # дефолт как у send_message
assert bot.api.sent["disable_link_preview"] is True
bot2 = MaxiBot("t", threaded=False, parse_mode="html")
bot2.api = FakeBotApi()
bot2.send_comment("mid.post", "привет")
assert bot2.api.sent["format"] == "html"                         # разметка бота уважается
assert bot.edit_comment("mid.post", "cmid.1", text="новый") is True
assert bot.api.edited["comment_id"] == "cmid.1"
assert bot.api.edited["format"] is None                          # как edit_message_text: без дефолта
assert bot.delete_comment("mid.post", "cmid.1") is False         # success: false -> False
bot.api.edit_comment = lambda *a, **k: {"success": False}
assert bot.edit_comment("mid.post", "cmid.1", text="x") is False
try:
    bot.send_comment("mid.post", "х" * 4001)
    assert False, "ожидался ValueError"
except ValueError:
    pass
print("4 ok: send/edit/delete_comment на боте")


# 5. Диспатч comment_created: только comment_handler, message_handler молчит
def comment_update(update_type="comment_created", text="первый!"):
    comment = dict(COMMENT)
    comment["body"] = dict(COMMENT["body"], text=text)
    return {"update_type": update_type, "timestamp": 1751400000000, "message": comment}


bot = make_bot()
fired = []

@bot.message_handler(content_types=["text"])
def on_message(m):
    fired.append(("message", m.text))

@bot.comment_handler(content_types=["text"])
def on_comment(m):
    fired.append(("comment", m.text))

@bot.edited_comment_handler(content_types=["text"])
def on_edited(m):
    fired.append(("edited", m.text))

bot.process_new_updates([comment_update()])
assert fired == [("comment", "первый!")], fired
bot.process_new_updates([comment_update("comment_edited", "правка")])
assert fired[-1] == ("edited", "правка")
print("5 ok: comment_created/comment_edited диспатчатся отдельно")

# 6. comment_removed -> CommentRemoved в removed_comment_handler; func-фильтр
bot = make_bot()
removed = []

@bot.removed_comment_handler(func=lambda r: r.post_id == "mid.post")
def on_removed(r):
    removed.append(r)

bot.process_new_updates([{
    "update_type": "comment_removed", "timestamp": 1751400000001,
    "message_id": "cmid.1", "chat_id": 42, "user_id": 7, "post_id": "mid.post",
}])
bot.process_new_updates([{
    "update_type": "comment_removed", "timestamp": 1751400000002,
    "message_id": "cmid.2", "chat_id": 42, "user_id": 7, "post_id": "другой",
}])
assert len(removed) == 1
event = removed[0]
assert isinstance(event, CommentRemoved)
assert (event.message_id, event.chat_id, event.user_id, event.post_id) == \
       ("cmid.1", 42, 7, "mid.post")
assert event.timestamp == 1751400000001
print("6 ok: comment_removed -> CommentRemoved")

# 7. Гейт: без обработчиков комментарий не строится (нет похода в API)
bot = make_bot()
bot.process_new_updates([comment_update()])
assert bot.api.chat_info_calls == 0                              # Message не строился
bot.register_comment_handler(lambda m: None, content_types=["text"])
bot.process_new_updates([comment_update()])
assert bot.api.chat_info_calls > 0
print("7 ok: без подписки объекты не строятся")

# 8. register_-варианты и pass_bot; фильтры content_types/func работают
bot = make_bot()
got = []
bot.register_comment_handler(
    lambda m, bot: got.append(("c", m.text, bot)), content_types=["text"], pass_bot=True)
bot.register_edited_comment_handler(
    lambda m: got.append(("e", m.text)), func=lambda m: "да" in m.text)
bot.register_removed_comment_handler(
    lambda r, bot: got.append(("r", r.message_id, bot)), pass_bot=True)
bot.process_new_updates([comment_update()])
assert got[0][:2] == ("c", "первый!") and got[0][2] is bot
bot.process_new_updates([comment_update("comment_edited", "нет")])
bot.process_new_updates([comment_update("comment_edited", "да, правка")])
assert [g for g in got if g[0] == "e"] == [("e", "да, правка")]
bot.process_new_updates([{"update_type": "comment_removed", "timestamp": 1,
                          "message_id": "cmid.9", "chat_id": 42, "user_id": 7,
                          "post_id": None}])
assert got[-1] == ("r", "cmid.9", bot)
# register_ без content_types матчит комментарий ЛЮБОГО типа
# (дефолт ['text'] подставляют только декораторы)
bot = make_bot()
any_type = []
bot.register_comment_handler(lambda m: any_type.append(m.content_type))
photo_comment = comment_update()
photo_comment["message"]["body"]["attachments"] = [
    {"type": "image", "payload": {"photo_id": 1, "token": "t", "url": "http://x/i.jpg"}}
]
bot.process_new_updates([photo_comment])
assert any_type == ["photo"], any_type
print("8 ok: register_-варианты, pass_bot, без content_types — все типы")

# 9. Middleware сырого типа видит Update с построенным .comment
import maxibot.apihelper as m_apihelper
old_flag = m_apihelper.ENABLE_MIDDLEWARE
m_apihelper.ENABLE_MIDDLEWARE = True
try:
    bot = make_bot()
    seen = []

    @bot.middleware_handler(update_types=["comment_created"])
    def mw(bot_instance, update):
        seen.append(update)

    bot.process_new_updates([comment_update()])
    assert len(seen) == 1 and isinstance(seen[0], Update)
    assert seen[0].comment is not None and seen[0].comment.text == "первый!"
    assert seen[0].removed_comment is None
finally:
    m_apihelper.ENABLE_MIDDLEWARE = old_flag
print("9 ok: middleware comment_created")

# 10. Типы обновлений: UpdateType и util.update_types согласованы
from maxibot.types import UpdateType
assert UpdateType.COMMENT_CREATED == "comment_created"
assert UpdateType.COMMENT_EDITED == "comment_edited"
assert UpdateType.COMMENT_REMOVED == "comment_removed"
for t in ("comment_created", "comment_edited", "comment_removed"):
    assert t in update_types
print("10 ok: типы обновлений на месте")

print("ALL OK")

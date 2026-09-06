"""
Каналы: channel_post_handler / edited_channel_post_handler и
маршрутизация — посты каналов (message_created/message_edited с
chat_type='channel') попадают только в канальные обработчики,
у поста от имени канала from_user = None.

Запуск:
    python3 tests/test_channel_posts.py
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

from maxibot import MaxiBot
from maxibot.types import Message, Update
from maxibot.util import get_edit_message_data


class FakeApi:
    def __init__(self):
        self.chat_info_calls = 0

    def get_chat_info(self, chat_id):
        self.chat_info_calls += 1
        return {"title": "Канал"}


def make_bot():
    bot = MaxiBot("t", threaded=False)
    bot.api = FakeApi()
    return bot


USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u"}


def post_update(text="пост", update_type="message_created", sender=None,
                chat_type="channel", attachments=None):
    body = {"mid": "mid.1", "seq": 1, "text": text}
    if attachments is not None:
        body["attachments"] = attachments
    message = {
        "recipient": {"chat_id": 100, "chat_type": chat_type},
        "timestamp": 1751400000000,
        "body": body,
    }
    if sender is not None:
        message["sender"] = sender
    return {
        "update_type": update_type,
        "timestamp": 1751400000000,
        "message": message,
    }


# 1. Сигнатуры как в telebot (вместе с **kwargs под кастом-фильтры)
for name in ("channel_post_handler", "edited_channel_post_handler",
             "add_channel_post_handler", "add_edited_channel_post_handler",
             "register_channel_post_handler", "register_edited_channel_post_handler",
             "process_new_channel_posts", "process_new_edited_channel_posts"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = inspect.signature(getattr(telebot.TeleBot, name)).parameters
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры восьми методов как в telebot")

# 2. Пост канала (sender null) парсится: from_user None, chat.type channel
upd = Update(post_update(), FakeApi())
assert upd.message is not None, "пост канала должен парситься"
assert upd.message.from_user is None
assert upd.message.chat.type == "channel" and upd.message.text == "пост"
# подписанный пост (sender есть) — from_user заполнен
upd = Update(post_update(sender=USER), FakeApi())
assert upd.message.from_user is not None and upd.message.from_user.real_id == 7
print("2 ok: пост канала парсится, from_user None (подписанный — заполнен)")

# 3. Маршрутизация: пост -> только channel_post_handler, не message_handler
bot = make_bot()
got = []


@bot.channel_post_handler(func=lambda m: True)
def on_post(message):
    got.append(("post", message.text, message.from_user))


@bot.message_handler(func=lambda m: True)
def on_message(message):
    got.append(("message", message.text, message.from_user))


bot._process_update(post_update(text="в канал"))
bot._process_update(post_update(text="в личку", sender=USER, chat_type="dialog"))
assert got[0][:2] == ("post", "в канал") and got[0][2] is None, got
assert got[1][0] == "message" and got[1][1] == "в личку", got
print("3 ok: посты каналов не попадают в message_handler и наоборот")

# 4. Правка поста -> только edited_channel_post_handler
bot = make_bot()
got = []


@bot.edited_channel_post_handler(func=lambda m: True)
def on_post_edit(message):
    got.append("channel-edit")


@bot.edited_message_handler(func=lambda m: True)
def on_edit(message):
    got.append("edit")


bot._process_update(post_update(text="правка", update_type="message_edited"))
bot._process_update(post_update(text="правка", update_type="message_edited",
                                sender=USER, chat_type="chat"))
assert got == ["channel-edit", "edit"], got
print("4 ok: правки постов каналов отдельно от правок сообщений")

# 5. Дефолт ['text'] у декоратора; register_ без content_types матчит всё
bot = make_bot()
got = []


@bot.channel_post_handler()
def on_text_post(message):
    got.append("text")


bot.register_channel_post_handler(lambda m: got.append(m.content_type))
bot._process_update(post_update(
    text=None,
    attachments=[{"type": "image", "payload": {"token": "t", "url": "https://u"}}],
))
assert got == ["photo"], got  # декоратор с ['text'] пропустил, register поймал
assert bot.channel_post_handlers[-1]["filters"] == {}
print("5 ok: декоратор — только текст по умолчанию, register_ — все типы")

# 6. pass_bot у register_channel_post_handler
bot = make_bot()
got = []
bot.register_channel_post_handler(
    lambda m, bot=None: got.append(bot), pass_bot=True)
bot._process_update(post_update())
assert got == [bot], got
print("6 ok: pass_bot")

# 7. next_step не съедает пост канала и не падает на from_user=None
bot = make_bot()
got = []
fake_message = Message(
    update=post_update(text="x", sender=USER, chat_type="dialog"), api=FakeApi())
bot.register_next_step_handler(fake_message, lambda m: got.append("step"))
bot.add_channel_post_handler(bot._build_handler_dict(
    lambda m: got.append("post"), content_types=["text"]))
bot._process_update(post_update(text="пост"))
assert got == ["post"], got
bot._process_update(post_update(text="ответ", sender=USER, chat_type="dialog"))
assert got == ["post", "step"], got
print("7 ok: next_step переживает посты каналов и остаётся ждать")

# 8. process_new_channel_posts / process_new_edited_channel_posts напрямую
bot = make_bot()
got = []
bot.add_channel_post_handler(bot._build_handler_dict(
    lambda m: got.append(("post", m.text)), content_types=["text"]))
bot.add_edited_channel_post_handler(bot._build_handler_dict(
    lambda m: got.append(("edit", m.text)), content_types=["text"]))
msg = Update(post_update(text="привет"), FakeApi()).message
bot.process_new_channel_posts([msg])
bot.process_new_edited_channel_posts([msg])
assert got == [("post", "привет"), ("edit", "привет")], got
print("8 ok: публичные process_new_*")

# 9. Экономный гейт правок: без edited-обработчиков правка не разбирается,
#    с одним лишь канальным edited-обработчиком — разбирается
bot = make_bot()
bot._process_update(post_update(update_type="message_edited"))
assert bot.api.chat_info_calls == 0
bot.add_edited_channel_post_handler(bot._build_handler_dict(
    lambda m: None, content_types=["text"]))
bot._process_update(post_update(update_type="message_edited"))
assert bot.api.chat_info_calls > 0
print("9 ok: гейт правок учитывает канальные обработчики")

# 10. Синтетический sender {} у результатов edit_*-методов по-прежнему
#     даёт from_user (регрессию поймали скептики: falsy-чек ловил и его)
edited = Message(update=get_edit_message_data(
    text="новый текст", chat_id=123, message_id="mid.9",
    attachments=[], timestamp=1751400000000), api=FakeApi())
assert edited.from_user is not None and edited.from_user.id == 123
# а канальный закреп (sender: null в самом сообщении) — from_user None
pin_msg = Message(update={"message": {
    "recipient": {"chat_id": 100, "chat_type": "channel"},
    "sender": None,
    "body": {"mid": "mid.pin", "seq": 1, "text": "закреп"},
}, "timestamp": 1751400000000}, api=FakeApi())
assert pin_msg.from_user is None
print("10 ok: sender {} -> from_user есть, sender null -> None")

# 11. Телеботовские поля Update.channel_post/edited_channel_post существуют
#     и всегда None — мигрантский `if update.channel_post:` не падает
upd = Update(post_update(), FakeApi())
assert upd.channel_post is None and upd.edited_channel_post is None
assert upd.message is not None  # пост канала лежит в message
print("11 ok: Update.channel_post существует и равен None")

# 12. next_step ключуется по chat.id (как в telebot): регистрация на
#     канальном посте (from_user=None) не падает, а senderless-сообщение
#     вне канала доходит до message_handlers
bot = make_bot()
channel_msg = Update(post_update(), FakeApi()).message
bot.register_next_step_handler(channel_msg, lambda m: None)  # не падает
bot.clear_step_handler(channel_msg)
got = []


@bot.message_handler(func=lambda m: True)
def on_any(message):
    got.append(message.from_user)


bot._process_update(post_update(chat_type="chat"))  # sender null вне канала
assert got == [None], got
print("12 ok: next_step по chat.id, senderless-сообщение доходит до обработчиков")

print("ALL OK")

"""
next_step по chat_id, накопление обработчиков, персистентность
(FileHandlerBackend) и реестр reply-хендлеров.

Запуск:
    python3 tests/test_next_step_reply.py
"""
import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot
import telebot.handler_backends as telebot_backends

import maxibot
from maxibot import Handler, MaxiBot, apihelper
from maxibot.handler_backends import (
    FileHandlerBackend,
    HandlerBackend,
    MemoryHandlerBackend,
)
from maxibot.types import Update


class FakeApi:
    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot(**kwargs):
    bot = MaxiBot("t", threaded=False, **kwargs)
    bot.api = FakeApi()
    return bot


USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u"}


def message_update(text="привет", chat_id=42, mid="mid.1"):
    return {
        "update_type": "message_created",
        "timestamp": 1751400000000,
        "message": {
            "sender": USER,
            "recipient": {"chat_id": chat_id, "chat_type": "dialog", "user_id": 7},
            "timestamp": 1751400000000,
            "body": {"mid": mid, "seq": 1, "text": text},
        },
    }


def reply_update(link_type="reply", link_mid="mid.orig", text="ответ", chat_id=42):
    upd = message_update(text=text, chat_id=chat_id, mid="mid.2")
    upd["message"]["link"] = {
        "type": link_type,
        "message": {"mid": link_mid, "seq": 1, "text": "исходное"},
    }
    return upd


# именованные функции уровня модуля — только такие переживают pickle
SAVED_CALLS = []


def saved_step_cb(message, tag="step"):
    SAVED_CALLS.append((tag, message.text))


def saved_reply_cb(message):
    SAVED_CALLS.append(("reply", message.text))


# 1. Сигнатуры и состав — как в telebot
for name in ("register_next_step_handler", "register_next_step_handler_by_chat_id",
             "clear_step_handler", "clear_step_handler_by_chat_id",
             "enable_save_next_step_handlers", "disable_save_next_step_handlers",
             "load_next_step_handlers",
             "register_for_reply", "register_for_reply_by_message_id",
             "clear_reply_handlers", "clear_reply_handlers_by_message_id",
             "enable_save_reply_handlers", "disable_save_reply_handlers",
             "load_reply_handlers"):
    ours = inspect.signature(getattr(MaxiBot, name))
    theirs = inspect.signature(getattr(telebot.TeleBot, name))
    assert list(ours.parameters) == list(theirs.parameters), name
    for p_name, p in theirs.parameters.items():
        assert ours.parameters[p_name].default == p.default, (name, p_name)
# бэкенды: телеботовский набор публичных методов
for ours_cls, theirs_cls in (
    (HandlerBackend, telebot_backends.HandlerBackend),
    (MemoryHandlerBackend, telebot_backends.MemoryHandlerBackend),
    (FileHandlerBackend, telebot_backends.FileHandlerBackend),
):
    missing = [m for m in dir(theirs_cls)
               if not m.startswith("_") and not hasattr(ours_cls, m)]
    assert not missing, (ours_cls.__name__, missing)
# конструктор: next_step_backend и reply_backend на телеботовских местах
params = list(inspect.signature(MaxiBot.__init__).parameters)
t_params = list(inspect.signature(telebot.TeleBot.__init__).parameters)
assert params.index("next_step_backend") == t_params.index("next_step_backend") == 6
assert params.index("reply_backend") == t_params.index("reply_backend") == 7
assert hasattr(apihelper, "CUSTOM_SERIALIZER") and apihelper.CUSTOM_SERIALIZER is None
assert maxibot.Handler is Handler
assert Handler(len, 1, x=2)["callback"] is len          # доступ по ключу, как в telebot
print("1 ok: сигнатуры, бэкенды, места в конструкторе")

# 2. Несколько next_step на чат копятся и забирают сообщение все разом
bot = make_bot()
fired = []
bot.register_next_step_handler_by_chat_id(42, lambda m, tag: fired.append((tag, m.text)), "первый")
bot.register_next_step_handler_by_chat_id(42, lambda m, tag=None: fired.append((tag, m.text)), tag="второй")

@bot.message_handler(content_types=["text"])
def h_rest(m):
    fired.append(("handler", m.text))

bot.process_new_updates([message_update(text="раз")])
assert fired == [("первый", "раз"), ("второй", "раз")]   # оба, обработчик молчит
bot.process_new_updates([message_update(text="два")])
assert fired[-1] == ("handler", "два")                   # ожидание снято
print("2 ok: обработчики копятся, сообщение забирают все разом")

# 3. register_next_step_handler — делегат by_chat_id (ключ chat.id)
bot = make_bot()
fired = []
first = Update(message_update(text="старт"), FakeApi()).message
bot.register_next_step_handler(first, lambda m, x, y=None: fired.append((x, y, m.text)), 1, y=2)
assert list(bot.next_step_backend.handlers) == [42]
bot.process_new_updates([message_update(text="ответ")])
assert fired == [(1, 2, "ответ")]
print("3 ok: register_next_step_handler и args/kwargs")

# 4. clear_step_handler_by_chat_id снимает всё, int/str подчищаются оба
bot = make_bot()
bot.register_next_step_handler_by_chat_id(42, lambda m: None)
bot.register_next_step_handler_by_chat_id(42, lambda m: None)
bot.clear_step_handler_by_chat_id("42")
assert bot.next_step_backend.handlers == {}
bot.register_next_step_handler_by_chat_id("77", lambda m: None)
bot.clear_step_handler_by_chat_id(77)
assert bot.next_step_backend.handlers == {}
print("4 ok: clear_step_handler_by_chat_id")

# 5. Reply: диспатч по mid исходного, сообщение идёт дальше, ожидание разовое
bot = make_bot()
fired = []
bot.register_for_reply_by_message_id("mid.orig", lambda m, tag: fired.append((tag, m.text)), "жду")

@bot.message_handler(content_types=["text"])
def h_all(m):
    fired.append(("handler", m.text))

listener_got = []
bot.set_update_listener(lambda msgs: listener_got.append(msgs[0].text))
bot.process_new_updates([reply_update(text="это ответ")])
# порядок telebot: reply -> слушатель -> message_handler
assert fired == [("жду", "это ответ"), ("handler", "это ответ")], fired
assert listener_got == ["это ответ"]
bot.process_new_updates([reply_update(text="ещё ответ")])
assert fired[-1] == ("handler", "ещё ответ")             # ожидание было разовым
print("5 ok: reply-обработчик разовый, сообщение идёт дальше")

# 6. Пересылка исходного сообщения ответом не считается
bot = make_bot()
fired = []
bot.register_for_reply_by_message_id("mid.orig", lambda m: fired.append("reply"))
bot.process_new_updates([reply_update(link_type="forward")])
assert fired == []
assert bot.reply_backend.handlers != {}                  # ожидание осталось
bot.process_new_updates([reply_update(link_type="reply")])
assert fired == ["reply"]
print("6 ok: forward не срабатывает, reply срабатывает")

# 7. register_for_reply/clear_reply_handlers — от объекта сообщения
bot = make_bot()
fired = []
orig = Update(message_update(mid="mid.orig"), FakeApi()).message
bot.register_for_reply(orig, lambda m: fired.append("r"))
assert "mid.orig" in bot.reply_backend.handlers
bot.clear_reply_handlers(orig)
assert bot.reply_backend.handlers == {}
bot.register_for_reply(orig, lambda m: fired.append("r"))
bot.clear_reply_handlers_by_message_id("mid.orig")
assert bot.reply_backend.handlers == {}
print("7 ok: register_for_reply/clear от сообщения")

# 8. Link.message_id заполнен (раньше был всегда None)
msg = Update(reply_update(), FakeApi()).message
assert msg.reply_to_message.message_id == "mid.orig"
assert msg.reply_to_message.type == "reply"
print("8 ok: reply_to_message.message_id заполняется")

# 9. next_step съедает сообщение раньше reply (порядок telebot)
bot = make_bot()
fired = []
bot.register_next_step_handler_by_chat_id(42, lambda m: fired.append("step"))
bot.register_for_reply_by_message_id("mid.orig", lambda m: fired.append("reply"))
bot.process_new_updates([reply_update()])
assert fired == ["step"]                                 # reply не получил
assert bot.reply_backend.handlers != {}                  # и ждёт дальше
print("9 ok: next_step раньше reply")

# 10. Персистентность next_step: enable_save -> рестарт -> load -> работает
tmp = tempfile.mkdtemp()
step_file = os.path.join(tmp, "saves", "step.save")
SAVED_CALLS.clear()
bot = make_bot()
bot.enable_save_next_step_handlers(delay=0, filename=step_file)
bot.register_next_step_handler_by_chat_id(42, saved_step_cb, tag="из файла")
assert os.path.isfile(step_file)                         # delay=0 — запись сразу
bot2 = make_bot()                                        # «рестарт процесса»
bot2.enable_save_next_step_handlers(delay=0, filename=step_file)
bot2.load_next_step_handlers(step_file)
assert not os.path.exists(step_file)                     # del_file_after_loading=True
bot2.process_new_updates([message_update(text="после рестарта")])
assert SAVED_CALLS == [("из файла", "после рестарта")]
print("10 ok: next_step переживает рестарт")

# 11. Персистентность reply: то же самое
reply_file = os.path.join(tmp, "saves", "reply.save")
SAVED_CALLS.clear()
bot = make_bot()
bot.enable_save_reply_handlers(delay=0, filename=reply_file)
bot.register_for_reply_by_message_id("mid.orig", saved_reply_cb)
bot2 = make_bot()
bot2.enable_save_reply_handlers(delay=0, filename=reply_file)
bot2.load_reply_handlers(reply_file, del_file_after_loading=False)
assert os.path.isfile(reply_file)                        # файл попросили оставить
bot2.process_new_updates([reply_update(text="ответ после рестарта")])
assert SAVED_CALLS == [("reply", "ответ после рестарта")]
print("11 ok: reply переживает рестарт")

# 12. Как в telebot: load без enable_save (память) — NotImplementedError,
# disable_save переносит накопленное обратно в память
bot = make_bot()
try:
    bot.load_next_step_handlers("нет-файла")
    assert False, "ожидался NotImplementedError"
except NotImplementedError:
    pass
bot.enable_save_next_step_handlers(delay=300, filename=os.path.join(tmp, "x.save"))
bot.register_next_step_handler_by_chat_id(42, saved_step_cb)
assert isinstance(bot.next_step_backend, FileHandlerBackend)
bot.disable_save_next_step_handlers()
assert isinstance(bot.next_step_backend, MemoryHandlerBackend)
assert 42 in bot.next_step_backend.handlers              # накопленное переехало
print("12 ok: load на памяти и disable_save — как в telebot")

# 13. Файл без папки в пути не создаёт паразитную папку (телеботовский rsplit)
cwd = os.getcwd()
os.chdir(tmp)
try:
    FileHandlerBackend.dump_handlers({1: []}, "bare.save")
    assert os.path.isfile("bare.save") and not os.path.isdir("bare.save")
finally:
    os.chdir(cwd)
print("13 ok: dump_handlers с голым именем файла")

# 14. Свой бэкенд в конструктор — на телеботовском месте
custom = MemoryHandlerBackend({99: [Handler(saved_step_cb)]})
bot = make_bot(next_step_backend=custom, reply_backend=MemoryHandlerBackend())
assert bot.next_step_backend is custom
SAVED_CALLS.clear()
bot.process_new_updates([message_update(chat_id=99)])
assert SAVED_CALLS == [("step", "привет")]
print("14 ok: свои бэкенды принимаются")

print("ALL OK")

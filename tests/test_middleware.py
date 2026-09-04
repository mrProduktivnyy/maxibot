"""
Проверка middleware_handler (issue #29).

Как в telebot: после apihelper.ENABLE_MIDDLEWARE = True декоратор
@bot.middleware_handler(update_types=[...]) регистрирует функцию, которую
бот вызывает для каждого обновления до обработчиков — в потоке приёма
обновлений и с тем же объектом, который потом получит обработчик. Без
update_types middleware получает Update целиком и вызывается для всех
обновлений. Исключение в middleware логируется, обновление пропускается.

Запуск:
    python3 tests/test_middleware.py
"""
import inspect
import io
import logging
import os
import sys
import threading
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot, apihelper
from maxibot.types import Message, CallbackQuery, Update
from maxibot.util import update_types


class FakeApi:
    """Message/Chat при разборе обновления ходят за названием чата — считаем эти вызовы."""

    def __init__(self):
        self.chat_info_calls = 0

    def get_chat_info(self, chat_id):
        self.chat_info_calls += 1
        return {"title": "chat"}


def make_bot(**kwargs):
    kwargs.setdefault("threaded", False)  # обработчики синхронно — порядок вызовов детерминирован
    bot = MaxiBot("t", **kwargs)  # конструктор сеть не трогает
    bot.api = FakeApi()
    return bot


USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u", "last_name": None}


def message_update(text="привет", update_type="message_created"):
    return {
        "update_type": update_type,
        "timestamp": 1751400000000,
        "message": {
            "sender": USER,
            "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
            "timestamp": 1751400000000,
            "body": {"mid": "mid.1", "seq": 1, "text": text, "attachments": []},
        },
    }


def callback_update(payload="btn_1"):
    upd = message_update()
    upd["update_type"] = "message_callback"
    upd["callback"] = {"timestamp": 1751400000000, "callback_id": "cb1", "payload": payload, "user": USER}
    return upd


def bot_started_update():
    return {"update_type": "bot_started", "timestamp": 1751400000000, "chat_id": 42, "user": USER}


def bot_added_update():
    return {"update_type": "bot_added", "timestamp": 1751400000000, "chat_id": 42, "user": USER, "is_channel": False}


def bot_stopped_update():
    return {"update_type": "bot_stopped", "timestamp": 1751400000000, "chat_id": 42, "user": USER}


# 1. Сигнатуры один в один с telebot, флаг по умолчанию выключен
sig = inspect.signature(MaxiBot.middleware_handler)
assert list(sig.parameters) == ["self", "update_types"] and sig.parameters["update_types"].default is None
sig = inspect.signature(MaxiBot.add_middleware_handler)
assert list(sig.parameters) == ["self", "handler", "update_types"] and sig.parameters["update_types"].default is None
sig = inspect.signature(MaxiBot.register_middleware_handler)
assert list(sig.parameters) == ["self", "callback", "update_types"] and sig.parameters["update_types"].default is None
assert apihelper.ENABLE_MIDDLEWARE is False
print('1 ok: сигнатуры как в telebot, ENABLE_MIDDLEWARE по умолчанию False')

# 2. Без apihelper.ENABLE_MIDDLEWARE регистрация падает, как в telebot
bot = make_bot()
for register in (
    lambda f: bot.middleware_handler()(f),
    lambda f: bot.register_middleware_handler(f),
    lambda f: bot.add_middleware_handler(f, update_types=['message_created']),
):
    try:
        register(lambda b, u: None)
        raise AssertionError("должен был упасть без ENABLE_MIDDLEWARE")
    except RuntimeError as e:
        assert "ENABLE_MIDDLEWARE" in str(e), str(e)
assert bot.default_middleware_handlers == [] and bot.typed_middleware_handlers["message_created"] == []
print('2 ok: без apihelper.ENABLE_MIDDLEWARE регистрация -> RuntimeError')

apihelper.ENABLE_MIDDLEWARE = True

# 3. Типизированный middleware вызывается до обработчика с тем же Message
bot = make_bot()
calls = []


@bot.middleware_handler(update_types=['message_created'])
def add_lang(bot_instance, message):
    assert bot_instance is bot
    assert isinstance(message, Message)
    message.lang = "ru"
    calls.append(("middleware", message))


assert add_lang.__name__ == "add_lang"  # декоратор возвращает функцию как есть


@bot.message_handler(func=lambda m: True)
def handle(message):
    calls.append(("handler", message, message.lang))


bot._process_update(message_update())
assert [c[0] for c in calls] == ["middleware", "handler"], calls
assert calls[0][1] is calls[1][1]  # тот же объект Message
assert calls[1][2] == "ru"
print('3 ok: middleware вызывается до обработчика с тем же Message')

# 4. Общий middleware получает Update для всех типов, даже без обработчиков
bot = make_bot()
seen = []


@bot.middleware_handler()
def log_update(bot_instance, update):
    seen.append(update)


bot._process_update(message_update())
bot._process_update(callback_update())
bot._process_update(bot_stopped_update())
assert [u.update_type for u in seen] == ["message_created", "message_callback", "bot_stopped"], seen
assert all(isinstance(u, Update) for u in seen)
assert isinstance(seen[0].message, Message) and seen[0].edited_message is None and seen[0].callback_query is None
assert seen[0].message.text == "привет" and seen[0].timestamp == 1751400000000
assert seen[1].message is None and isinstance(seen[1].callback_query, CallbackQuery)
assert seen[1].callback_query.data == "btn_1"
assert seen[2].message is None and seen[2].callback_query is None and seen[2].json["chat_id"] == 42
print('4 ok: общий middleware получает Update для всех типов обновлений')

# 5. Типизированный middleware получает объект своего типа:
#    CallbackQuery (тот же, что и обработчик), Message для message_edited и
#    bot_started, Update — для типов без своего объекта
bot = make_bot()
got = []


@bot.middleware_handler(update_types=['message_callback', 'message_edited', 'bot_started', 'bot_stopped'])
def typed(bot_instance, obj):
    got.append(obj)


@bot.callback_query_handler(func=lambda cb: True)
def on_cb(callback):
    got.append(("handler", callback))


bot._process_update(callback_update())
bot._process_update(message_update(update_type="message_edited"))
bot._process_update(bot_started_update())
bot._process_update(bot_stopped_update())
assert isinstance(got[0], CallbackQuery) and got[1] == ("handler", got[0])
assert isinstance(got[2], Message) and got[2].update_type == "message_edited" and got[2].text == "привет"
assert isinstance(got[3], Message) and got[3].update_type == "bot_started" and got[3].text.startswith("/start")
assert isinstance(got[4], Update) and got[4].update_type == "bot_stopped"
print('5 ok: типизированный middleware получает CallbackQuery/Message/Update по типу')

# 6. Телеботовские имена типов переводятся в типы MAX, а не становятся общими
bot = make_bot()


@bot.middleware_handler(update_types=['message', 'edited_message', 'callback_query'])
def ported(bot_instance, obj):
    pass


assert bot.typed_middleware_handlers["message_created"] == [ported]
assert bot.typed_middleware_handlers["message_edited"] == [ported]
assert bot.typed_middleware_handlers["message_callback"] == [ported]
assert bot.default_middleware_handlers == []
print('6 ok: телеботовские message/edited_message/callback_query -> типы MAX')

# 7. Типы telebot, которых в MAX нет, пропускаются с предупреждением (бот
#    запускается, как с inline_handler); незнакомое имя -> ValueError; в обоих
#    случаях ничего лишнего не регистрируется
bot = make_bot()
records = []


class Grab(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


logging.getLogger("maxibot").addHandler(Grab())
bot.register_middleware_handler(lambda b, u: None, update_types=['message_created', 'channel_post'])
assert len(bot.typed_middleware_handlers["message_created"]) == 1
assert "channel_post" in records[-1], records
bot.register_middleware_handler(lambda b, u: None, update_types=['inline_query'])
assert "никогда не будет вызван" in records[-1], records
assert bot.default_middleware_handlers == []  # не стал общим, как сделал бы telebot
try:
    bot.register_middleware_handler(lambda b, u: None, update_types=['message_created', 'message_creatd'])
    raise AssertionError("должен был упасть на опечатке")
except ValueError as e:
    assert "message_creatd" in str(e) and "message_removed" in str(e), str(e)
assert len(bot.typed_middleware_handlers["message_created"]) == 1  # опечатка ничего не добавила
# строка вместо списка — частая ошибка, принимается как один тип; алиас и
# имя MAX в одном списке — одна регистрация
bot.register_middleware_handler(lambda b, u: None, update_types='message_edited')
assert len(bot.typed_middleware_handlers["message_edited"]) == 1
bot.register_middleware_handler(lambda b, u: None, update_types=['message', 'message_created'])
assert len(bot.typed_middleware_handlers["message_created"]) == 2
print('7 ok: типы telebot без аналога — предупреждение, опечатка — ValueError')

# 8. Порядок как в telebot: middleware своего типа, общие, обработчик
bot = make_bot()
order = []
bot.register_middleware_handler(lambda b, u: order.append("default"))
bot.register_middleware_handler(lambda b, m: order.append("typed"), update_types=['message_created'])


@bot.message_handler(func=lambda m: True)
def handle_order(message):
    order.append("handler")


bot._process_update(message_update())
assert order == ["typed", "default", "handler"], order
print('8 ok: порядок — типизированные, общие, обработчик')

# 9. Исключение в middleware логируется, обновление пропускается, бот жив
bot = make_bot()
handled = []


@bot.middleware_handler(update_types=['message_created'])
def guard(bot_instance, message):
    if message.text == "плохо":
        raise RuntimeError("авария в middleware")


@bot.message_handler(func=lambda m: True)
def handle_guarded(message):
    handled.append(message.text)


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


capture = _LogCapture()
maxi_logger = logging.getLogger("maxibot")
maxi_logger.addHandler(capture)
buf = io.StringIO()
with redirect_stdout(buf):
    bot._process_update(message_update(text="плохо"))
    bot._process_update(message_update(text="хорошо"))
assert handled == ["хорошо"], handled
logged = "\n".join(r.getMessage() for r in capture.records)
assert "авария в middleware" in logged and "guard" in logged, logged
assert "update skipped" in logged  # именно ветка process_middlewares, а не общий except
assert buf.getvalue() == "", buf.getvalue()  # ошибка уходит в логгер, а не print в stdout
assert bot.process_middlewares(Update(message_update(text="плохо"), bot.api)) is False
assert bot.process_middlewares(Update(message_update(text="хорошо"), bot.api)) is True
maxi_logger.removeHandler(capture)
print('9 ok: исключение в middleware логируется, обновление пропускается')

# 10. threaded=True: middleware в потоке приёма обновлений, обработчик в пуле
#     видит его изменения
bot = make_bot(threaded=True)
done = threading.Event()
threads = {}


@bot.middleware_handler(update_types=['message_created'])
def mark(bot_instance, message):
    threads["middleware"] = threading.current_thread().name
    message.marked = True


@bot.message_handler(func=lambda m: True)
def handle_threaded(message):
    threads["handler"] = (threading.current_thread().name, getattr(message, "marked", False))
    done.set()


bot._process_update(message_update())
assert done.wait(5), "обработчик не выполнился"
assert threads["middleware"] == threading.current_thread().name, threads
assert threads["handler"][0].startswith("maxibot-worker") and threads["handler"][1] is True, threads
print('10 ok: middleware в потоке поллинга, обработчик в пуле видит его изменения')

# 11. Без middleware необрабатываемые типы не строят объекты и не ходят в API
bot = make_bot()
bot._process_update(message_update(update_type="message_edited"))
bot._process_update(bot_stopped_update())
assert bot.api.chat_info_calls == 0, bot.api.chat_info_calls
bot.register_middleware_handler(lambda b, m: None, update_types=['message_edited'])
bot._process_update(message_update(update_type="message_edited"))
assert bot.api.chat_info_calls == 1, bot.api.chat_info_calls
print('11 ok: без middleware необрабатываемые типы не ходят в API')

# 12. Middleware выполняется и перед next_step-обработчиком
bot = make_bot()
steps = []


@bot.middleware_handler(update_types=['message_created'])
def before_step(bot_instance, message):
    steps.append("middleware")


def step(message):
    steps.append("step")


@bot.message_handler(commands=['ask'])
def ask(message):
    steps.append("ask")
    bot.register_next_step_handler(message, step)


bot._process_update(message_update(text="/ask"))
bot._process_update(message_update(text="ответ"))
assert steps == ["middleware", "ask", "middleware", "step"], steps
print('12 ok: middleware выполняется и перед next_step-обработчиком')

# 13. Ключи typed_middleware_handlers — все типы обновлений MAX из
#     maxibot.util.update_types (сам список сверен с документацией в
#     tests/test_update_types.py)
assert set(MaxiBot("t").typed_middleware_handlers) == set(update_types) and len(update_types) == 18
print('13 ok: middleware принимает все типы обновлений MAX')

# 14. Как в telebot: middleware для message_created (телеботовское 'message')
#     получает каждое сообщение, которое дойдёт до обработчиков, — bot_started
#     (кнопка «Начать») и bot_added тоже; функция, зарегистрированная и на
#     message_created, и на bot_started, вызывается один раз
bot = make_bot()
seen_start = []


@bot.middleware_handler(update_types=['message'])
def load_user(bot_instance, message):
    message.user_profile = "loaded"


@bot.middleware_handler(update_types=['message_created', 'bot_started'])
def count(bot_instance, message):
    seen_start.append(message.update_type)


@bot.message_handler(commands=['start'])
def on_start(message):
    seen_start.append(("start", message.update_type, getattr(message, "user_profile", None)))


# хендлер без content_types получает только text (дефолт telebot);
# bot_added ловится явной подпиской content_types=['bot_added']
@bot.message_handler(func=lambda m: True, content_types=["text", "bot_added"])
def on_any(message):
    seen_start.append(("any", message.update_type, getattr(message, "user_profile", None)))


bot._process_update(bot_started_update())
bot._process_update(bot_added_update())
assert seen_start == [
    "bot_started", ("start", "bot_started", "loaded"),
    "bot_added", ("any", "bot_added", "loaded"),
], seen_start
print('14 ok: middleware message_created получает bot_started/bot_added, как обработчики')

# 15. message_created без message (нарушение схемы MAX): middleware своего типа
#     пропускаются, как в telebot, общий получает Update с message=None
bot = make_bot()
typed_calls, default_calls = [], []
bot.register_middleware_handler(lambda b, m: typed_calls.append(m), update_types=['message_created'])
bot.register_middleware_handler(lambda b, u: default_calls.append(u))
bot._process_update({"update_type": "message_created", "timestamp": 1751400000000})
assert typed_calls == [] and len(default_calls) == 1 and default_calls[0].message is None
print('15 ok: без объекта своего типа middleware типа пропускаются')

# 16. Payload, который парсер не понял (пост канала без sender): общий
#     middleware всё равно получает Update с сырым json, ошибка логируется,
#     до обработчиков обновление не доходит — как и раньше
bot = make_bot()
default_calls, handled = [], []
bot.register_middleware_handler(lambda b, u: default_calls.append(u))


@bot.message_handler(func=lambda m: True)
def on_any_16(message):
    handled.append(message)


channel_post = message_update()
del channel_post["message"]["sender"]
capture = _LogCapture()
maxi_logger.addHandler(capture)
bot._process_update(channel_post)
maxi_logger.removeHandler(capture)
assert len(default_calls) == 1 and default_calls[0].message is None
assert default_calls[0].json is channel_post and handled == []
logged = "\n".join(r.getMessage() for r in capture.records)
assert "Error while parsing update message_created" in logged, logged
print('16 ok: непонятный payload — общий middleware получает Update, ошибка логируется')

print('ALL OK')

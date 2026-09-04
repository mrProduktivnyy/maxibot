"""
ExceptionHandler: перехват ошибок обработчиков, middleware, фильтров,
поллинга и webhook — как telebot.ExceptionHandler.

Раньше все ошибки уходили в print(traceback) — перехватить их (Sentry,
алерты, своё логирование) было нельзя. Теперь MaxiBot(exception_handler=...)
получает каждое исключение; не обработано (handle вернул falsy) —
logger.error в логгер 'maxibot', traceback на уровне DEBUG. print в stdout
больше нет.

Запуск:
    python3 tests/test_exception_handler.py
"""
import asyncio
import io
import json
import logging
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from maxibot import ExceptionHandler, MaxiBot, apihelper
import maxibot.core.network.polling as polling_mod
from maxibot.core.network.webhook import WebhookServer

USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u", "last_name": None}


class FakeApi:
    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def message_update(text="привет"):
    return {
        "update_type": "message_created",
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


class Recorder(ExceptionHandler):
    """Копит исключения; handled задаёт, что вернёт handle()."""

    def __init__(self, handled=True):
        self.exceptions = []
        self.handled = handled

    def handle(self, exception):
        self.exceptions.append(exception)
        return self.handled


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def errors(self):
        return [r.getMessage() for r in self.records if r.levelno >= logging.ERROR]

    def debugs(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.DEBUG]

    def clear(self):
        self.records = []


capture = LogCapture()
maxi_logger = logging.getLogger("maxibot")
# логгер настроен при импорте, как в telebot: свой stderr-хендлер и уровень
# WARNING (у telebot ERROR, но предупреждения совместимости maxibot должны
# быть видны) — ошибки видны из коробки, traceback'и включает DEBUG
assert maxi_logger.level == logging.WARNING, maxi_logger.level
assert any(
    isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stderr
    for h in maxi_logger.handlers
), maxi_logger.handlers
maxi_logger.addHandler(capture)
maxi_logger.setLevel(logging.DEBUG)


def make_bot(**kwargs):
    kwargs.setdefault("threaded", False)
    bot = MaxiBot("t", **kwargs)
    bot.api = FakeApi()
    return bot


# 1. База: handle() по умолчанию возвращает False, у бота обработчика нет
assert ExceptionHandler().handle(ValueError("x")) is False
assert make_bot().exception_handler is None
print("1 ok: ExceptionHandler.handle по умолчанию False")

# 2. Без exception_handler ошибка обработчика логируется (не print) и не
#    останавливает диспатч следующих обновлений
bot = make_bot()
got = []


@bot.message_handler(commands=["boom"])
def boom(message):
    raise RuntimeError("авария в обработчике")


@bot.message_handler(func=lambda m: True)
def ok_handler(message):
    got.append(message.text)


capture.clear()
buf = io.StringIO()
with redirect_stdout(buf):
    bot._process_update(message_update(text="/boom"))
    bot._process_update(message_update(text="дальше"))
assert got == ["дальше"], got
assert buf.getvalue() == "", buf.getvalue()
assert any("авария в обработчике" in m for m in capture.errors()), capture.errors()
assert any("Traceback" in m for m in capture.debugs()), "traceback должен уйти в DEBUG"
print("2 ok: без exception_handler — logger.error, stdout чист, диспатч жив")

# 3. handle() вернул True — ошибка обработана: в логах тишина
rec = Recorder(handled=True)
bot = make_bot(exception_handler=rec)


@bot.message_handler(commands=["boom"])
def boom2(message):
    raise RuntimeError("перехвати меня")


capture.clear()
bot._process_update(message_update(text="/boom"))
assert len(rec.exceptions) == 1 and str(rec.exceptions[0]) == "перехвати меня"
assert isinstance(rec.exceptions[0], RuntimeError)
assert capture.errors() == [], capture.errors()
print("3 ok: handle() -> True: исключение у обработчика, логи молчат")

# 4. handle() вернул False — и обработчик получил, и logger.error сработал
rec = Recorder(handled=False)
bot = make_bot(exception_handler=rec)


@bot.message_handler(commands=["boom"])
def boom3(message):
    raise RuntimeError("не перехвачено")


capture.clear()
bot._process_update(message_update(text="/boom"))
assert len(rec.exceptions) == 1
assert any("не перехвачено" in m for m in capture.errors()), capture.errors()
print("4 ok: handle() -> False: исключение и у обработчика, и в логгере")

# 5. Ошибка middleware уходит в exception_handler, обновление пропускается
apihelper.ENABLE_MIDDLEWARE = True
rec = Recorder(handled=True)
bot = make_bot(exception_handler=rec)
handled_messages = []


@bot.middleware_handler(update_types=["message_created"])
def guard(bot_instance, message):
    raise ValueError("авария в middleware")


@bot.message_handler(func=lambda m: True)
def after_guard(message):
    handled_messages.append(message.text)


capture.clear()
bot._process_update(message_update(text="не дойдёт"))
assert handled_messages == [], handled_messages
assert len(rec.exceptions) == 1 and isinstance(rec.exceptions[0], ValueError)
assert capture.errors() == [], capture.errors()
apihelper.ENABLE_MIDDLEWARE = False
print("5 ok: ошибка middleware — в exception_handler, обновление пропущено")

# 6. Ошибка func-фильтра (Message): обработчик считается несовпавшим,
#    следующий обработчик получает сообщение, исключение — в exception_handler
rec = Recorder(handled=True)
bot = make_bot(exception_handler=rec)
got = []


@bot.message_handler(func=lambda m: 1 / 0)
def broken_filter(message):
    got.append("broken")


@bot.message_handler(func=lambda m: True)
def healthy(message):
    got.append("healthy")


bot._process_update(message_update(text="привет"))
assert got == ["healthy"], got
assert len(rec.exceptions) == 1 and isinstance(rec.exceptions[0], ZeroDivisionError)
print("6 ok: ошибка func-фильтра не роняет диспатч, уходит в exception_handler")

# 7. Ошибка func-фильтра у callback_query_handler — то же самое
rec = Recorder(handled=True)
bot = make_bot(exception_handler=rec)
got = []


@bot.callback_query_handler(func=lambda call: 1 / 0)
def broken_callback_filter(call):
    got.append("broken")


@bot.callback_query_handler(func=lambda call: True)
def healthy_callback(call):
    got.append(call.data)


bot._process_update(callback_update())
assert got == ["btn_1"], got
assert len(rec.exceptions) == 1 and isinstance(rec.exceptions[0], ZeroDivisionError)
print("7 ok: ошибка func-фильтра колбэка — в exception_handler, диспатч жив")

# 8. threaded=True: ошибка обработчика в потоке пула тоже доходит
rec = Recorder(handled=True)
bot = make_bot(threaded=True, num_threads=1, exception_handler=rec)


@bot.message_handler(func=lambda m: True)
def boom_threaded(message):
    raise RuntimeError("авария в пуле")


capture.clear()
bot._process_update(message_update(text="в пул"))
bot._worker_pool._queue.join()
assert len(rec.exceptions) == 1 and str(rec.exceptions[0]) == "авария в пуле"
assert capture.errors() == [], capture.errors()
print("8 ok: threaded=True — ошибка из потока пула в exception_handler")

# 9. Поллинг: сетевая ошибка get_updates и ошибка обработки апдейта уходят
#    в exception_handler бота, цикл продолжает работать
rec = Recorder(handled=True)
bot = make_bot(exception_handler=rec)


class FlakyApi:
    def __init__(self):
        self.calls = 0

    def get_updates(self, allowed_updates, extra=None):
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("сеть упала")
        if self.calls >= 3:
            poll.stop()
            return {}
        return {"updates": [{"update_type": "message_created"}], "marker": 1}


def bad_handler(update):
    raise RuntimeError("авария при обработке")


poll = polling_mod.Polling(api=FlakyApi(), allowed_updates=None, on_error=bot._report_exception)
real_async_sleep = asyncio.sleep


async def fake_async_sleep(seconds):
    if len(rec.exceptions) > 10:
        poll.stop()


asyncio.sleep = fake_async_sleep
try:
    asyncio.run(poll.loop(bad_handler))
finally:
    asyncio.sleep = real_async_sleep
kinds = [type(e).__name__ for e in rec.exceptions]
assert kinds == ["ConnectionError", "RuntimeError"], kinds
print("9 ok: ошибки поллинга (сеть и обработка) — в exception_handler, цикл жив")

# 10. Упавший handle() не роняет бот: логируются и его ошибка, и исходная
class BrokenHandler(ExceptionHandler):
    def handle(self, exception):
        raise TypeError("сломанный exception_handler")


bot = make_bot(exception_handler=BrokenHandler())


@bot.message_handler(commands=["boom"])
def boom4(message):
    raise RuntimeError("исходная ошибка")


capture.clear()
bot._process_update(message_update(text="/boom"))
errors = capture.errors()
assert any("Error in exception handler" in m and "сломанный exception_handler" in m for m in errors), errors
assert any("исходная ошибка" in m for m in errors), errors
print("10 ok: упавший handle() логируется, исходная ошибка не теряется")

# 11. Обработчик можно назначить и после создания бота (как в telebot)
bot = make_bot()
rec = Recorder(handled=True)
bot.exception_handler = rec


@bot.message_handler(commands=["boom"])
def boom5(message):
    raise RuntimeError("после создания")


capture.clear()
bot._process_update(message_update(text="/boom"))
assert len(rec.exceptions) == 1 and capture.errors() == []
print("11 ok: bot.exception_handler = ... работает и после создания")

# 12. Webhook: ошибки обработчика и кривой JSON уходят в exception_handler;
#     403 при неверном секрете отдаётся чисто (тело дочитано, без RST);
#     гигантский или кривой Content-Length отбивается до чтения тела
rec = Recorder(handled=True)
bot = make_bot(exception_handler=rec)


def exploding_handler(update):
    raise RuntimeError("авария в webhook")


def raw_status(port, request_bytes):
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request_bytes)
        sock.settimeout(5)
        return sock.recv(4096).decode(errors="replace").split("\r\n")[0]


server = WebhookServer(host="127.0.0.1", port=0, secret="s3cret", on_error=bot._report_exception)
capture.clear()
server.start(handler=exploding_handler)
port = server._server.server_address[1]
try:
    url = f"http://127.0.0.1:{port}/"
    ok = requests.post(url, data=b"{}", headers={"X-Max-Bot-Api-Secret": "s3cret"}, timeout=5)
    assert ok.status_code == 200, ok.status_code
    bad_json = requests.post(url, data="не json".encode(), headers={"X-Max-Bot-Api-Secret": "s3cret"}, timeout=5)
    assert bad_json.status_code == 200, bad_json.status_code
    forbidden = requests.post(url, data=b"{}", timeout=5)
    assert forbidden.status_code == 403, forbidden.status_code
    too_big = raw_status(port, (
        "POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 999999999999\r\n\r\n"
    ).encode())
    assert " 413 " in too_big, too_big
    broken_length = raw_status(port, (
        "POST / HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n"
    ).encode())
    assert " 400 " in broken_length, broken_length
finally:
    server.stop()
kinds = [type(e).__name__ for e in rec.exceptions]
assert kinds == ["RuntimeError", "JSONDecodeError"], kinds
assert capture.errors() == [], capture.errors()
print("12 ok: ошибки webhook — в exception_handler, секрет и кап тела работают")

maxi_logger.removeHandler(capture)
print("ALL OK")

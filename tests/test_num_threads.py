"""
Проверка threaded/num_threads в MaxiBot.__init__ (issue #34).

Как в telebot: MaxiBot(token, threaded=True, num_threads=2). При
threaded=True обработчики выполняются в пуле потоков (медленный
обработчик не блокирует остальных), при threaded=False — синхронно,
как раньше. Фильтры всегда проверяются в потоке поллинга.

Запуск:
    python3 tests/test_num_threads.py
"""
import inspect
import io
import os
import sys
import threading
import time
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot


class FakeApi:
    """Message/Chat при разборе обновления ходят за названием чата — глушим сеть."""

    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot(**kwargs):
    bot = MaxiBot("t", **kwargs)
    bot.api = FakeApi()
    return bot


def make_update(user_id=7, text="привет"):
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "is_bot": False, "first_name": "u", "name": "u", "last_name": None},
            "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": user_id},
            "timestamp": 1751400000000,
            "body": {"mid": "mid.1", "seq": 1, "text": text, "attachments": []},
        },
    }


# 1. Сигнатура и дефолты — как в telebot (threaded=True, num_threads=2)
sig = inspect.signature(MaxiBot.__init__)
params = list(sig.parameters)
assert params == [
    "self", "token", "parse_mode", "threaded", "skip_pending", "num_threads",
    "exception_handler",
], params
assert sig.parameters["threaded"].default is True
assert sig.parameters["num_threads"].default == 2
bot = MaxiBot("t")  # без фейка: конструктор сеть не трогает
assert bot.threaded is True and bot.num_threads == 2 and bot._worker_pool is not None
# демон-потоки, как WorkerThread в telebot: Ctrl+C завершает процесс сразу,
# не дожидаясь зависших или очередных обработчиков
assert len(bot._worker_pool._threads) == 2
assert all(t.daemon for t in bot._worker_pool._threads)
print('1 ok: сигнатура и дефолты telebot, воркеры — демоны')

# 2. threaded=True: обработчик выполняется в потоке пула, поллинг не блокируется
bot = make_bot()
done = threading.Event()
seen_threads = []

@bot.message_handler(func=lambda m: True)
def handle(message):
    seen_threads.append(threading.current_thread().name)
    done.set()

bot._process_update(make_update())
assert done.wait(5), "обработчик не выполнился"
assert seen_threads[0].startswith("maxibot-worker"), seen_threads
print('2 ok: threaded=True выполняет обработчик в пуле')

# 3. threaded=False: синхронно в текущем потоке, как раньше
bot = make_bot(threaded=False)
assert bot._worker_pool is None
sync_threads = []

@bot.message_handler(func=lambda m: True)
def handle_sync(message):
    sync_threads.append(threading.current_thread().name)

bot._process_update(make_update())
assert sync_threads == [threading.current_thread().name], sync_threads  # уже выполнен, тот же поток
print('3 ok: threaded=False — синхронная обработка')

# 4. num_threads=2: два обработчика реально работают параллельно
bot = make_bot(num_threads=2)
barrier = threading.Barrier(2)
results = []

@bot.message_handler(func=lambda m: True)
def handle_parallel(message):
    try:
        barrier.wait(timeout=5)  # дождаться второго — при последовательной обработке тут таймаут
        results.append("ok")
    except threading.BrokenBarrierError:
        results.append("timeout")

bot._process_update(make_update(user_id=1))
bot._process_update(make_update(user_id=2))
deadline = time.monotonic() + 6
while len(results) < 2 and time.monotonic() < deadline:
    time.sleep(0.05)
assert results == ["ok", "ok"], results
print('4 ok: два обработчика работают параллельно')

# 5. Исключение в обработчике не роняет бота и логируется, а не теряется в Future
import logging


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


capture = _LogCapture()
maxi_logger = logging.getLogger("maxibot")
maxi_logger.addHandler(capture)
bot = make_bot()
crashed = threading.Event()

@bot.message_handler(func=lambda m: True)
def handle_crash(message):
    crashed.set()
    raise RuntimeError("авария в обработчике")

def logged():
    return "\n".join(r.getMessage() for r in capture.records)

buf = io.StringIO()
with redirect_stdout(buf):
    bot._process_update(make_update())
    assert crashed.wait(5)
    deadline = time.monotonic() + 5
    while "авария в обработчике" not in logged() and time.monotonic() < deadline:
        time.sleep(0.05)
maxi_logger.removeHandler(capture)
assert "авария в обработчике" in logged(), logged()
assert "Error in handler" in logged(), logged()
assert buf.getvalue() == "", buf.getvalue()  # ошибка уходит в логгер, а не print
print('5 ok: исключение в пуле логируется, бот жив')

# 6. next_step-обработчики тоже уходят в пул
bot = make_bot()
step_done = threading.Event()
step_threads = []

def step(message, extra=None):
    step_threads.append((threading.current_thread().name, extra))
    step_done.set()

first = threading.Event()

@bot.message_handler(func=lambda m: True)
def ask(message):
    bot.register_next_step_handler(message, step, extra="данные")
    first.set()

bot._process_update(make_update())
assert first.wait(5)
bot._process_update(make_update(text="ответ"))
assert step_done.wait(5)
assert step_threads[0][0].startswith("maxibot-worker") and step_threads[0][1] == "данные", step_threads
print('6 ok: next_step-обработчик в пуле, kwargs доходят')

print('ALL OK')

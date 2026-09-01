"""
Проверка infinity_polling (issue #47).

Сигнатура — как у telebot.infinity_polling: polling оборачивается в
бесконечный цикл с перехватом исключений, выход — bot.stop() или
KeyboardInterrupt. skip_pending прокручивает очередь обновлений
запросами GET /updates с timeout=0. Дополнительно: пауза в except-ветке
Polling.loop, чтобы обрыв сети не превращался в горячий цикл.

Запуск:
    python3 tests/test_infinity_polling.py
"""
import asyncio
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None  # ускоряем паузы между рестартами

from maxibot import MaxiBot
import maxibot.core.network.polling as polling_mod


def make_bot():
    bot = MaxiBot.__new__(MaxiBot)
    bot.is_running = False
    return bot


# 1. Нормальный выход: stop() во время polling -> без рестарта
bot = make_bot()
calls = []

def fake_polling(allowed_updates=None):
    calls.append(allowed_updates)
    bot.is_running = True   # так делает start()
    bot.is_running = False  # эмуляция bot.stop() из хендлера

bot.polling = fake_polling
bot.infinity_polling()
assert len(calls) == 1, calls
print('1 ok: stop() завершает infinity_polling без рестарта')

# 2. Исключения ретраятся, is_running сбрасывается перед рестартом
bot = make_bot()
states_at_entry = []
attempts = []

def flaky_polling(allowed_updates=None):
    states_at_entry.append(bot.is_running)
    attempts.append(1)
    bot.is_running = True
    if len(attempts) < 3:
        raise ConnectionError("сеть упала")
    bot.is_running = False

bot.polling = flaky_polling
bot.infinity_polling(logger_level=None)
assert len(attempts) == 3, attempts
# перед каждым рестартом is_running сброшен, иначе start() отказался бы запускаться
assert states_at_entry == [False, False, False], states_at_entry
print('2 ok: исключения ретраятся, is_running сбрасывается')

# 3. KeyboardInterrupt не перехватывается (Ctrl+C останавливает бота)
bot = make_bot()

def interrupted_polling(allowed_updates=None):
    raise KeyboardInterrupt

bot.polling = interrupted_polling
try:
    bot.infinity_polling()
    raise AssertionError('KeyboardInterrupt должен был пробраться наружу')
except KeyboardInterrupt:
    print('3 ok: KeyboardInterrupt пробрасывается')

# 4. skip_pending: очередь прокручивается с timeout=0 и маркером до опустошения
bot = make_bot()
get_updates_calls = []

class FakeApi:
    def get_updates(self, allowed_updates, extra=None):
        get_updates_calls.append(dict(extra or {}))
        n = len(get_updates_calls)
        if n == 1:
            return {"updates": [{"u": 1}], "marker": 101}
        if n == 2:
            return {"updates": [{"u": 2}], "marker": 202}
        return {"updates": [], "marker": 202}

bot.api = FakeApi()
bot.polling = fake_polling  # из теста 1: сразу останавливается

def stop_polling(allowed_updates=None):
    bot.is_running = False

bot.polling = stop_polling
bot.infinity_polling(skip_pending=True)
assert len(get_updates_calls) == 3, get_updates_calls
assert all(c.get("timeout") == 0 for c in get_updates_calls), get_updates_calls
assert "marker" not in get_updates_calls[0]
assert get_updates_calls[1]["marker"] == 101
assert get_updates_calls[2]["marker"] == 202
print('4 ok: skip_pending прокручивает очередь с timeout=0')

# 5. allowed_updates пробрасывается в polling
bot = make_bot()
received = []

def record_polling(allowed_updates=None):
    received.append(allowed_updates)
    bot.is_running = False

bot.polling = record_polling
bot.infinity_polling(allowed_updates=["message_created"])
assert received == [["message_created"]], received
print('5 ok: allowed_updates пробрасывается')

# 6. Пауза в Polling.loop при ошибке get_updates (горячего цикла нет)
sleep_calls = []
real_async_sleep = asyncio.sleep

class FailingApi:
    def get_updates(self, allowed_updates, extra=None):
        raise ConnectionError("сеть упала")

poll = polling_mod.Polling(api=FailingApi(), allowed_updates=None)

async def fake_async_sleep(seconds):
    sleep_calls.append(seconds)
    if len(sleep_calls) >= 2:
        poll.stop()

asyncio.sleep = fake_async_sleep
try:
    asyncio.run(poll.loop(lambda u: None))
finally:
    asyncio.sleep = real_async_sleep
assert sleep_calls == [3, 3], sleep_calls
print('6 ok: ошибки get_updates ретраятся с паузой')

# 7. На успешном пути паузы нет (обычный поллинг не замедлен)
sleep_calls = []
handled = []

class OkApi:
    def __init__(self):
        self.calls = 0

    def get_updates(self, allowed_updates, extra=None):
        self.calls += 1
        if self.calls >= 3:
            poll.stop()
        return {"updates": [{"update_type": "message_created"}], "marker": self.calls}

poll = polling_mod.Polling(api=OkApi(), allowed_updates=None)
asyncio.sleep = fake_async_sleep
try:
    asyncio.run(poll.loop(lambda u: handled.append(u)))
finally:
    asyncio.sleep = real_async_sleep
assert sleep_calls == [], sleep_calls
assert len(handled) == 3, handled
print('7 ok: успешный путь без пауз')

print('ALL OK')

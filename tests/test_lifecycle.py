"""
Лайфсайкл-алиасы: stop_polling, stop_bot, remove_webhook, run_webhooks,
bot.token; нормализация allowed_updates в set_webhook.

Запуск:
    python3 tests/test_lifecycle.py
"""
import inspect
import logging
import os
import string
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

from maxibot import MaxiBot


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def warnings(self):
        return [r.getMessage() for r in self.records if r.levelno == logging.WARNING]


def capture_warnings(fn):
    capture = LogCapture()
    logging.getLogger("maxibot").addHandler(capture)
    try:
        result = fn()
    finally:
        logging.getLogger("maxibot").removeHandler(capture)
    return result, capture.warnings()


class FakeApi:
    def __init__(self, subscriptions=None):
        self.subscriptions = subscriptions
        self.deleted = []
        self.set_calls = []

    def get_webhook_info(self):
        return self.subscriptions

    def delete_webhook(self, url):
        self.deleted.append(url)
        return {"success": True}

    def set_webhook(self, url, update_types=None, secret=None):
        self.set_calls.append({"url": url, "update_types": update_types,
                               "secret": secret})
        return {"success": True}


def make_bot(api=None):
    bot = MaxiBot("токен-бота", threaded=False)
    bot.api = api or FakeApi()
    return bot


# 1. Сигнатуры и bot.token — как в telebot
for name in ("stop_polling", "stop_bot", "remove_webhook", "run_webhooks"):
    ours = inspect.signature(getattr(MaxiBot, name))
    theirs = inspect.signature(getattr(telebot.TeleBot, name))
    assert list(ours.parameters) == list(theirs.parameters), name
    for p_name, p in theirs.parameters.items():
        assert ours.parameters[p_name].default == p.default, (name, p_name)
assert make_bot().token == "токен-бота"          # как telebot.TeleBot.token
print("1 ok: сигнатуры и bot.token")

# 2. stop_polling и stop_bot останавливают бота
class FakePoll:
    def __init__(self):
        self.stopped = 0

    def stop(self):
        self.stopped += 1


for method in ("stop_polling", "stop_bot"):
    bot = make_bot()
    bot.poll = FakePoll()
    bot.is_running = True
    getattr(bot, method)()
    assert bot.is_running is False and bot.poll.stopped == 1, method
    getattr(bot, method)()                        # повторно — тихий no-op
    assert bot.poll.stopped == 1, method
print("2 ok: stop_polling/stop_bot")

# 3. remove_webhook: снимает каждую подписку, пустота и мусор не роняют
api = FakeApi({"subscriptions": [
    {"url": "https://a.example/hook", "time": 1},
    {"url": "https://b.example/hook", "time": 2},
    {"time": 3},                                  # подписка без url — пропуск
]})
bot = make_bot(api)
assert bot.remove_webhook() is True
assert api.deleted == ["https://a.example/hook", "https://b.example/hook"]
assert make_bot(FakeApi({"subscriptions": []})).remove_webhook() is True
assert make_bot(FakeApi(None)).remove_webhook() is True
assert make_bot(FakeApi("мусор")).remove_webhook() is True
print("3 ok: remove_webhook")

# 4. run_webhooks: делегат start_webhook, секрет генерируется
bot = make_bot()
calls = []
bot.start_webhook = lambda **kw: calls.append(kw)
_, warns = capture_warnings(lambda: bot.run_webhooks(
    listen="0.0.0.0", port=8443, allowed_updates=["message"]))
assert len(calls) == 1
call = calls[0]
assert call["host"] == "0.0.0.0" and call["port"] == 8443
assert call["allowed_updates"] == ["message"]
# секрет: 20 символов из ВЕРХНЕГО регистра и цифр, как в telebot
secret = call["secret"]
assert len(secret) == 20
assert set(secret) <= set(string.ascii_uppercase + string.digits)
# webhook_url собран из listen:port и токена; протокол http без сертификата
assert call["webhook_url"] == "http://0.0.0.0:8443/токен-бота/"
assert warns == []                                # ничего не игнорировалось
print("4 ok: run_webhooks делегирует start_webhook")

# 5. run_webhooks: свой webhook_url и секрет уходят как есть, слэш дописывается
bot = make_bot()
calls = []
bot.start_webhook = lambda **kw: calls.append(kw)
bot.run_webhooks(secret_token="СЕКРЕТ-123", webhook_url="https://ex.ru/hook")
assert calls[0]["webhook_url"] == "https://ex.ru/hook"
assert calls[0]["secret"] == "СЕКРЕТ-123"
bot.run_webhooks(url_path="myhook")               # без завершающего слэша
assert calls[1]["webhook_url"] == "http://127.0.0.1:443/myhook/"
bot.run_webhooks(secret_token=None, secret_token_length=5)
assert len(calls[2]["secret"]) == 5
print("5 ok: свои webhook_url/секрет/url_path")

# 6. run_webhooks: сертификат — https и предупреждение про TLS,
# неподдерживаемые параметры — предупреждение
bot = make_bot()
calls = []
bot.start_webhook = lambda **kw: calls.append(kw)
_, warns = capture_warnings(lambda: bot.run_webhooks(
    certificate="/tmp/cert.pem", certificate_key="/tmp/key.pem",
    max_connections=40, timeout=30))
assert calls[0]["webhook_url"].startswith("https://127.0.0.1:443/")
assert any("TLS" in w for w in warns), warns
assert any("max_connections" in w and "timeout" in w for w in warns), warns
assert not any("ip_address" in w for w in warns)   # не передан — не поминается
print("6 ok: сертификат и игнорируемые параметры предупреждают")

# 7. set_webhook нормализует телеботовские имена типов (как polling)
api = FakeApi()
bot = make_bot(api)
bot.set_webhook("https://ex.ru/hook", allowed_updates=["message", "channel_post"])
sent = api.set_calls[0]["update_types"]
assert sent == ["message_created"], sent           # оба типа — message_created
bot.set_webhook("https://ex.ru/hook", allowed_updates=["my_chat_member"])
sent = api.set_calls[1]["update_types"]
assert "bot_added" in sent and "bot_started" in sent, sent
bot.set_webhook("https://ex.ru/hook")
assert api.set_calls[2]["update_types"] is None    # None — все, как раньше
print("7 ok: set_webhook нормализует allowed_updates")

print("ALL OK")

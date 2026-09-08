"""
maxibot.util: quick_markup, extract_arguments, antiflood, escape,
user_link, split_string — дифференциально против telebot.util.

Запуск:
    python3 tests/test_util.py
"""
import inspect
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot.util

from maxibot import util
from maxibot.exceptions import MaxApiHTTPException
from maxibot.types import InlineKeyboardMarkup, Update

# 1. Сигнатуры — как в telebot (имена параметров и дефолты)
for name in ("quick_markup", "extract_arguments", "antiflood", "escape",
             "user_link", "split_string"):
    ours = inspect.signature(getattr(util, name))
    theirs = inspect.signature(getattr(telebot.util, name))
    assert list(ours.parameters) == list(theirs.parameters), name
    for p_name, p in theirs.parameters.items():
        assert ours.parameters[p_name].default == p.default, (name, p_name)
print("1 ok: сигнатуры")

# 2. escape — дифференциально (включая порядок замен: & раньше < и >)
for text in (None, "", "чистый текст", "a&<>b", "&amp; уже экранированный",
             "<b>жирный & точка</b>", "кавычки 'не' \"трогаем\""):
    assert util.escape(text) == telebot.util.escape(text), text
assert util.escape("a&<>b") == "a&amp;&lt;&gt;b"
print("2 ok: escape")

# 3. split_string — дифференциально (пустая строка, ровное и неровное деление)
for text, n in (("", 5), ("абв", 5), ("абвгд", 5), ("абвгде", 5),
                ("слово " * 100, 7), ("х" * 25, 10)):
    assert util.split_string(text, n) == telebot.util.split_string(text, n), (text[:20], n)
print("3 ok: split_string")

# 4. extract_arguments — дифференциально + None-безопасность (у telebot краш)
for text in ("/get name", "/get", "/get@botName name", "/get@botName",
             "/cmd  два   аргумента ", "не команда", "", "/",
             "/картошка по-русски"):
    assert util.extract_arguments(text) == telebot.util.extract_arguments(text), repr(text)
assert util.extract_arguments(None) is None
assert util.extract_arguments("/get") == ""          # команда без аргументов — '' (не None)
assert util.extract_arguments("привет") is None      # не команда — None
print("4 ok: extract_arguments")

# 5. quick_markup — раскладка рядов как у telebot, наши кнопки/attachment
values = {
    "Twitter": {"url": "https://twitter.com"},
    "Facebook": {"url": "https://facebook.com"},
    "Назад": {"callback_data": "whatever"},
}
markup = util.quick_markup(values)
t_markup = telebot.util.quick_markup(values)
assert isinstance(markup, InlineKeyboardMarkup)
assert [len(r) for r in markup.keyboard] == [len(r) for r in t_markup.keyboard] == [2, 1]
assert [[b.text for b in r] for r in markup.keyboard] == [["Twitter", "Facebook"], ["Назад"]]
payload = markup.to_attachment()["payload"]["buttons"]
assert payload[0][0] == {"type": "link", "text": "Twitter", "url": "https://twitter.com"}
assert payload[1][0] == {"type": "callback", "text": "Назад", "payload": "whatever"}
# row_width уважается (и дефолт 2 — не 3, как у самой клавиатуры)
markup = util.quick_markup({str(i): {"callback_data": str(i)} for i in range(5)}, row_width=3)
assert [len(r) for r in markup.keyboard] == [3, 2]
assert inspect.signature(util.quick_markup).parameters["row_width"].default == 2
# web_app и телеботовские игнорируемые kwargs проходят
markup = util.quick_markup({"Мини-апп": {"web_app": "https://app.example"},
                            "Кнопка": {"callback_data": "x", "pay": None}})
assert markup.to_attachment()["payload"]["buttons"][0][0]["type"] == "open_app"
print("5 ok: quick_markup")


# 6. antiflood: пережидает только 429, паузу берёт из Retry-After (иначе 1с)
class FakeResp:
    def __init__(self, status=429, headers=None):
        self.status_code = status
        self.reason = "Too Many Requests"
        self.text = "{}"
        self.headers = headers or {}


def flaky(fails, headers=None, status=429):
    calls = []

    def func(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) <= fails:
            raise MaxApiHTTPException("GET /x", FakeResp(status, headers))
        return ("ок", args, kwargs)

    func.calls = calls
    return func


slept = []
_orig_sleep = time.sleep
time.sleep = slept.append
try:
    f = flaky(2, headers={"Retry-After": "2.5"})
    assert util.antiflood(f, 1, x=2) == ("ок", (1,), {"x": 2})
    assert len(f.calls) == 3 and slept == [2.5, 2.5]

    slept.clear()
    f = flaky(1)                                     # заголовка нет — пауза 1с
    assert util.antiflood(f)[0] == "ок"
    assert slept == [1.0]

    slept.clear()
    f = flaky(99, status=500)                        # не 429 — сразу наружу
    try:
        util.antiflood(f)
        assert False, "ожидался MaxApiHTTPException"
    except MaxApiHTTPException as ex:
        assert ex.status_code == 500 and len(f.calls) == 1 and slept == []

    f = flaky(99)                                    # попытки кончились —
    try:                                             # последняя без страховки
        util.antiflood(f, number_retries=3)
        assert False, "ожидался MaxApiHTTPException"
    except MaxApiHTTPException:
        assert len(f.calls) == 3 and slept == [1.0, 1.0]
finally:
    time.sleep = _orig_sleep
print("6 ok: antiflood")

# 7. user_link: real_id (а не id чата), escape имени, include_id
USER = {"user_id": 7, "is_bot": False, "first_name": "Вася <'&> Пупкин", "name": "vasya"}


def message_update(sender=USER):
    return {
        "update_type": "message_created",
        "timestamp": 1751400000000,
        "message": {
            "sender": sender,
            "recipient": {"chat_id": 42, "chat_type": "chat", "user_id": 7},
            "timestamp": 1751400000000,
            "body": {"mid": "mid.1", "seq": 1, "text": "привет"},
        },
    }


class FakeApi:
    def get_chat_info(self, chat_id):
        return {"title": "chat"}


user = Update(message_update(), FakeApi()).message.from_user
assert user.id == 42 and user.real_id == 7           # квирк: id — это чат
link = util.user_link(user)
assert link == "<a href='max://user/7'>Вася &lt;'&amp;&gt; Пупкин</a>", link
link = util.user_link(user, include_id=True)
assert link.endswith("</a> (<pre>7</pre>)"), link
# пост от имени канала: sender пустой, real_id нет — fallback на id
channel_user = Update(message_update(sender={}), FakeApi()).message.from_user
assert channel_user.real_id is None
assert "max://user/42" in util.user_link(channel_user)
print("7 ok: user_link")

print("ALL OK")

"""
Проверка WebAppInfo и web_app в InlineKeyboardButton (issue #41).

Сигнатуры как в telebot: WebAppInfo(url) и InlineKeyboardButton(text, url,
callback_data, web_app, ...). В MAX кнопка с web_app — это кнопка
{"type": "open_app"}: она открывает мини-приложение бота, чей username
или ссылка переданы в url; contact_id и payload — поля MAX. Кнопка
open_app, как и link, ограничивает ряд тремя кнопками. web_app работает
и на reply-кнопке (KeyboardButton), как в telebot. Телеграмный адрес
приложения в url — предупреждение в лог: MAX открывает приложение,
настроенное в самом боте.

Запуск:
    python3 tests/test_web_app.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot
from maxibot.apihelper import Api
from maxibot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

records = []


class Grab(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


logging.getLogger("maxibot").addHandler(Grab())

SEND_OK = {
    "message": {
        "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.123", "seq": 5, "text": "hi", "attachments": []},
    }
}


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path=None, url=None, params=None, data=None, **kw):
        self.calls.append({"method": method, "path": path, "params": params or {}, "data": data or {}})
        return SEND_OK


def make_bot():
    api = Api.__new__(Api)
    api.client = FakeClient()
    bot = MaxiBot("t")  # конструктор сеть не трогает
    bot.api = api
    return bot


def must_fail(make, what):
    try:
        make()
    except ValueError:
        return
    raise AssertionError(f"должно было упасть с ValueError: {what}")


# 1. Сигнатуры как в telebot: web_app на своём месте, остальные параметры
#    telebot приняты; WebAppInfo(url) — первый позиционный url
params = list(inspect.signature(InlineKeyboardButton.__init__).parameters)
assert params == [
    "self", "text", "url", "callback_data", "web_app", "switch_inline_query",
    "switch_inline_query_current_chat", "switch_inline_query_chosen_chat",
    "callback_game", "pay", "login_url",
], params
params = list(inspect.signature(WebAppInfo.__init__).parameters)
assert params[:2] == ["self", "url"], params
assert WebAppInfo("https://max.ru/mybot").url == "https://max.ru/mybot"
print('1 ok: сигнатуры как в telebot')

# 2. web_app -> {"type": "open_app", "web_app": url}; пустых полей нет
btn = InlineKeyboardButton("Открыть", web_app=WebAppInfo("https://max.ru/mybot"))
assert btn.to_dict() == {"type": "open_app", "text": "Открыть", "web_app": "https://max.ru/mybot"}, btn.to_dict()
print('2 ok: web_app -> open_app без пустых полей')

# 3. contact_id и payload — поля MAX; без url можно, если есть contact_id
btn = InlineKeyboardButton("Открыть", web_app=WebAppInfo("mybot", contact_id=123, payload="promo"))
assert btn.to_dict() == {
    "type": "open_app", "text": "Открыть", "web_app": "mybot", "contact_id": 123, "payload": "promo",
}, btn.to_dict()
assert InlineKeyboardButton("x", web_app=WebAppInfo(None, contact_id=123)).to_dict() == \
    {"type": "open_app", "text": "x", "contact_id": 123}
must_fail(lambda: WebAppInfo(None), "WebAppInfo без url и contact_id")
must_fail(lambda: WebAppInfo(""), "WebAppInfo с пустым url")
must_fail(lambda: WebAppInfo(None, payload="promo"), "WebAppInfo только с payload — нет ни url, ни contact_id")
assert WebAppInfo(None, contact_id=123, payload="promo").to_dict() == {"contact_id": 123, "payload": "promo"}
assert WebAppInfo("@mybot").url == "mybot"  # telebot-привычка: ведущий @ отбрасывается
print('3 ok: contact_id и payload')

# 4. Строка вместо WebAppInfo — username или ссылка на бота
assert InlineKeyboardButton("x", web_app="mybot").to_dict() == \
    InlineKeyboardButton("x", web_app=WebAppInfo("mybot")).to_dict()
print('4 ok: web_app строкой')

# 5. Ровно один вид кнопки: любая пара и тройка — ValueError, как раньше url+callback_data
app = WebAppInfo("mybot")
for kwargs in (
    {},
    {"url": "https://a", "callback_data": "cb"},
    {"url": "https://a", "web_app": app},
    {"callback_data": "cb", "web_app": app},
    {"url": "https://a", "callback_data": "cb", "web_app": app},
):
    must_fail(lambda: InlineKeyboardButton("x", **kwargs), kwargs)
assert InlineKeyboardButton("x", url="https://a").to_dict() == {"type": "link", "text": "x", "url": "https://a"}
assert InlineKeyboardButton("x", callback_data="cb").to_dict() == {"type": "callback", "text": "x", "payload": "cb"}
must_fail(lambda: InlineKeyboardButton("x", url="h" * 2049), "url длиннее 2048")
print('5 ok: ровно один из url / callback_data / web_app')

# 6. Telegram-only параметры telebot принимаются и игнорируются
btn = InlineKeyboardButton(
    "x", callback_data="cb", switch_inline_query="q", switch_inline_query_current_chat="q",
    switch_inline_query_chosen_chat=object(), callback_game=object(), pay=True, login_url=object(),
)
assert btn.to_dict() == {"type": "callback", "text": "x", "payload": "cb"}
must_fail(lambda: InlineKeyboardButton("x", switch_inline_query="q"), "кнопка только со switch_inline_query")
try:
    InlineKeyboardButton("Оплатить", pay=True)
    raise AssertionError("кнопка только с pay должна отклоняться")
except ValueError as e:
    assert "pay" in str(e) and "MAX" in str(e), str(e)  # ошибка называет виновника
try:
    InlineKeyboardButton("Поделиться", switch_inline_query="")  # в telebot пустая строка значима
    raise AssertionError("кнопка только со switch_inline_query='' должна отклоняться")
except ValueError as e:
    assert "switch_inline_query" in str(e), str(e)
print('6 ok: switch_inline_query/callback_game/pay/login_url игнорируются')

# 7. is_special: open_app и link ограничивают ряд, callback — нет
assert InlineKeyboardButton("x", web_app=app).is_special()
assert InlineKeyboardButton("x", url="https://a").is_special()
assert not InlineKeyboardButton("x", callback_data="cb").is_special()
print('7 ok: is_special')


# 8. Лимит ряда: с open_app не больше 3 кнопок, без спец-кнопок — 7
def app_btn(i):
    return InlineKeyboardButton(f"a{i}", web_app=WebAppInfo(f"bot{i}"))


def cb_btn(i):
    return InlineKeyboardButton(f"c{i}", callback_data=f"cb{i}")


markup = InlineKeyboardMarkup()
markup.row(app_btn(1), app_btn(2), app_btn(3))
markup.to_attachment()

markup = InlineKeyboardMarkup()
markup.row(app_btn(1), cb_btn(1), cb_btn(2), cb_btn(3))
try:
    markup.to_attachment()
    raise AssertionError("4 кнопки в ряду с open_app должны отклоняться")
except ValueError as e:
    assert "4" in str(e) and "3" in str(e) and "open_app" in str(e), str(e)

markup = InlineKeyboardMarkup()
markup.row(*[cb_btn(i) for i in range(7)])
markup.to_attachment()

markup = InlineKeyboardMarkup()
markup.row(*[cb_btn(i) for i in range(8)])
try:
    markup.to_attachment()
    raise AssertionError("8 обычных кнопок в ряду должны отклоняться")
except ValueError as e:
    assert "8" in str(e) and "7" in str(e), str(e)  # сообщение об ошибке не пустое

# add() с row_width — как раскладка из examples/test_bot.py
markup = InlineKeyboardMarkup(row_width=2)
markup.add(cb_btn(1), cb_btn(2), InlineKeyboardButton("l", url="https://max.ru"), app_btn(1))
assert [[b["type"] for b in r] for r in markup.to_attachment()["payload"]["buttons"]] == \
    [["callback", "callback"], ["link", "open_app"]]
markup = InlineKeyboardMarkup(row_width=3)
markup.add(*[app_btn(i) for i in range(6)])
assert [[b["text"] for b in r] for r in markup.to_attachment()["payload"]["buttons"]] == \
    [["a0", "a1", "a2"], ["a3", "a4", "a5"]]
markup = InlineKeyboardMarkup()
markup.add(app_btn(1), cb_btn(1), cb_btn(2), cb_btn(3), row_width=4)
try:
    markup.to_attachment()
    raise AssertionError("ряд из 4 кнопок с open_app должен отклоняться")
except ValueError as e:
    assert "3" in str(e), str(e)

# лимиты всей клавиатуры
assert (InlineKeyboardMarkup.MAX_ROWS, InlineKeyboardMarkup.MAX_BUTTONS,
        InlineKeyboardMarkup.MAX_ROW_REGULAR, InlineKeyboardMarkup.MAX_ROW_SPECIAL) == (30, 210, 7, 3)
markup = InlineKeyboardMarkup(row_width=7)
markup.add(*[cb_btn(i) for i in range(210)])
markup.to_attachment()  # 30 рядов по 7 — ровно лимит
markup = InlineKeyboardMarkup(row_width=7)
markup.add(*[cb_btn(i) for i in range(211)])
try:
    markup.to_attachment()
    raise AssertionError("211 кнопок должны отклоняться")
except ValueError as e:
    assert "210" in str(e), str(e)
markup = InlineKeyboardMarkup()
for i in range(31):
    markup.row(cb_btn(i))
try:
    markup.to_attachment()
    raise AssertionError("31 ряд должен отклоняться")
except ValueError as e:
    assert "30" in str(e), str(e)
print('8 ok: лимиты рядов и клавиатуры, add() с row_width')

# 9. Интеграция: bot.send_message(reply_markup=...) кладёт open_app в attachments
bot = make_bot()
markup = InlineKeyboardMarkup()
markup.add(InlineKeyboardButton("Открыть", web_app=WebAppInfo("https://max.ru/mybot", payload="promo")))
bot.send_message(42, "t", reply_markup=markup)
call = bot.api.client.calls[0]
attachments = call["data"]["attachments"]
assert len(attachments) == 1 and attachments[0]["type"] == "inline_keyboard", attachments
assert attachments[0]["payload"]["buttons"] == [[
    {"type": "open_app", "text": "Открыть", "web_app": "https://max.ru/mybot", "payload": "promo"},
]], attachments
print('9 ok: open_app уходит в POST /messages')

# 10. Телеграмный адрес приложения в url — предупреждение в лог (кнопка не откроется:
#     MAX открывает приложение, настроенное в самом боте); username и max.ru — без шума
records.clear()
WebAppInfo("https://my-app.example.com/page")
assert len(records) == 1 and "dev.max.ru" in records[0] and "my-app.example.com" in records[0], records
records.clear()
WebAppInfo("mybot")
WebAppInfo("@mybot")
WebAppInfo("https://max.ru/mybot")
WebAppInfo("https://web.max.ru/mybot")
assert records == [], records
print('10 ok: предупреждение о телеграмном адресе приложения')

# 11. web_app на reply-кнопке — open_app, как в telebot (Keyboard Button Mini Apps)
kb = KeyboardButton("Открыть", web_app=WebAppInfo("mybot", payload="promo"))
assert kb.to_dict() == {"type": "open_app", "text": "Открыть", "web_app": "mybot", "payload": "promo"}, kb.to_dict()
assert kb.is_special()
assert KeyboardButton("Открыть", web_app="mybot").to_dict()["type"] == "open_app"
# приоритет request-флагов сохранён; мусор в web_app по-прежнему игнорируется
assert KeyboardButton("к", request_contact=True, web_app=WebAppInfo("mybot")).to_dict()["type"] == "request_contact"
assert KeyboardButton("т", web_app=object()).to_dict() == {"type": "message", "text": "т"}
markup = ReplyKeyboardMarkup()
markup.add(KeyboardButton("Открыть", web_app=WebAppInfo("mybot")))
assert markup.to_attachment()["payload"]["buttons"] == [[
    {"type": "open_app", "text": "Открыть", "web_app": "mybot"},
]]
print('11 ok: KeyboardButton(web_app=...) -> open_app')


# 12. Объект telebot.types.WebAppInfo (утиная типизация по .url) принимается
class TelebotWebAppInfo:  # как telebot.types.WebAppInfo: только .url и свой to_dict
    def __init__(self, url):
        self.url = url

    def to_dict(self):
        return {"url": self.url}


btn = InlineKeyboardButton("x", web_app=TelebotWebAppInfo("https://max.ru/mybot"))
assert btn.to_dict() == {"type": "open_app", "text": "x", "web_app": "https://max.ru/mybot"}, btn.to_dict()
assert KeyboardButton("x", web_app=TelebotWebAppInfo("mybot")).to_dict() == \
    {"type": "open_app", "text": "x", "web_app": "mybot"}
print('12 ok: телеботовский WebAppInfo принимается')

print('ALL OK')

"""
Проверка KeyboardButton (issue #39) и ReplyKeyboardMarkup (issue #40).

Сигнатуры один в один с telebot. В MAX нет системной reply-клавиатуры,
поэтому ReplyKeyboardMarkup отправляется как inline-клавиатура:
текстовая кнопка -> {"type": "message"} (по нажатию текст уходит в чат),
request_contact -> {"type": "request_contact"},
request_location -> {"type": "request_geo_location"}.

Запуск:
    python3 tests/test_reply_keyboard.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot
from maxibot.apihelper import Api
from maxibot.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup

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


# 1. Текстовая кнопка -> message (текст кнопки уходит в чат по нажатию)
assert KeyboardButton("Привет").to_dict() == {"type": "message", "text": "Привет"}
print('1 ok: текстовая кнопка -> {"type": "message"}')

# 2. request_contact / request_location -> спец-кнопки MAX; contact приоритетнее
assert KeyboardButton("Контакт", request_contact=True).to_dict() == \
    {"type": "request_contact", "text": "Контакт"}
assert KeyboardButton("Гео", request_location=True).to_dict() == \
    {"type": "request_geo_location", "text": "Гео"}
assert KeyboardButton("Оба", request_contact=True, request_location=True).to_dict() == \
    {"type": "request_contact", "text": "Оба"}
print('2 ok: request_contact и request_location')

# 3. Неподдерживаемые MAX параметры telebot принимаются и игнорируются
btn = KeyboardButton("х", request_poll=object(), web_app=object(),
                     request_user=object(), request_chat=object(), request_users=object())
assert btn.to_dict() == {"type": "message", "text": "х"}
print('3 ok: request_poll/web_app/request_user/request_chat/request_users игнорируются')

# 4. is_special: контакт и гео ограничивают ряд, текстовая — нет
assert KeyboardButton("к", request_contact=True).is_special()
assert KeyboardButton("г", request_location=True).is_special()
assert not KeyboardButton("т").is_special()
print('4 ok: is_special')

# 5. add() со строками и row_width, дефолт row_width=3 — как в telebot
markup = ReplyKeyboardMarkup()
markup.add("A", "B", "C", "D")
buttons = markup.to_attachment()["payload"]["buttons"]
assert [[b["text"] for b in row] for row in buttons] == [["A", "B", "C"], ["D"]], buttons
assert all(b["type"] == "message" for row in buttons for b in row)

markup = ReplyKeyboardMarkup(row_width=2)
markup.add("A", "B", "C")
buttons = markup.to_attachment()["payload"]["buttons"]
assert [[b["text"] for b in row] for row in buttons] == [["A", "B"], ["C"]], buttons
print('5 ok: add() разбивает на ряды по row_width')

# 6. Кнопкой может быть строка, bytes или KeyboardButton — как в telebot
markup = ReplyKeyboardMarkup(row_width=3)
markup.add("строка", "байты".encode("utf-8"), KeyboardButton("объект", request_contact=True))
row = markup.to_attachment()["payload"]["buttons"][0]
assert row[0] == {"type": "message", "text": "строка"}
assert row[1] == {"type": "message", "text": "байты"}
assert row[2] == {"type": "request_contact", "text": "объект"}
print('6 ok: строки, bytes и KeyboardButton')

# 7. row() кладёт все кнопки в один ряд, цепочка вызовов работает
markup = ReplyKeyboardMarkup(row_width=1)
markup.row("A", "B").row("C")
buttons = markup.to_attachment()["payload"]["buttons"]
assert [[b["text"] for b in row] for row in buttons] == [["A", "B"], ["C"]], buttons
print('7 ok: row() и цепочка вызовов')

# 8. Атрибут вложения — inline_keyboard (reply эмулируется через inline)
markup = ReplyKeyboardMarkup()
markup.add("Да")
attachment = markup.to_attachment()
assert attachment["type"] == "inline_keyboard", attachment
assert isinstance(markup, InlineKeyboardMarkup)  # send_message подхватит дак-тайпингом
print('8 ok: to_attachment -> inline_keyboard')

# 9. Интеграция: bot.send_message(reply_markup=...) кладёт клавиатуру в attachments
bot = make_bot()
markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
markup.add("Да", "Нет")
bot.send_message(42, "Продолжаем?", reply_markup=markup)
call = bot.api.client.calls[0]
attachments = call["data"]["attachments"]
assert len(attachments) == 1 and attachments[0]["type"] == "inline_keyboard", attachments
texts = [b["text"] for b in attachments[0]["payload"]["buttons"][0]]
assert texts == ["Да", "Нет"], texts
print('9 ok: send_message(reply_markup=ReplyKeyboardMarkup)')

# 10. Параметры telebot принимаются и не мешают, лимиты MAX проверяются
markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, selective=True,
                             input_field_placeholder="...", is_persistent=True)
markup.add("ок")
assert markup.to_attachment()["type"] == "inline_keyboard"

markup = ReplyKeyboardMarkup()
markup.row("1", "2", "3", "4", "5", "6", "7", "8")  # больше лимита MAX (7 в ряду)
try:
    markup.to_attachment()
    raise AssertionError("должен был упасть по лимиту ряда")
except ValueError:
    pass

markup = ReplyKeyboardMarkup()
markup.row(KeyboardButton("1", request_contact=True), KeyboardButton("2", request_contact=True),
           KeyboardButton("3", request_contact=True), KeyboardButton("4", request_contact=True))
try:
    markup.to_attachment()
    raise AssertionError("должен был упасть: спец-кнопок больше 3 в ряду")
except ValueError:
    pass
print('10 ok: telebot-параметры принимаются, лимиты MAX работают')

print('ALL OK')

"""
Публичный пайплайн: get_updates, process_new_updates,
process_new_messages / process_new_edited_messages /
process_new_callback_query, set_update_listener и Update.de_json.

Запуск:
    python3 tests/test_pipeline.py
"""
import inspect
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot

from maxibot import MaxiBot
from maxibot.types import Message, Update


class FakeApi:
    def __init__(self, responses=None):
        self.chat_info_calls = 0
        self.update_calls = []
        self.responses = list(responses or [])

    def get_chat_info(self, chat_id):
        self.chat_info_calls += 1
        return {"title": "Чат"}

    def get_updates(self, allowed_updates, extra=None):
        self.update_calls.append((allowed_updates, dict(extra or {})))
        if self.responses:
            return self.responses.pop(0)
        return {"updates": [], "marker": None}


def make_bot(responses=None):
    bot = MaxiBot("t", threaded=False)
    bot.api = FakeApi(responses)
    return bot


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def capture_warnings(fn):
    capture = LogCapture()
    logging.getLogger("maxibot").addHandler(capture)
    try:
        result = fn()
    finally:
        logging.getLogger("maxibot").removeHandler(capture)
    return result, [r.getMessage() for r in capture.records
                    if r.levelno == logging.WARNING]


USER = {"user_id": 7, "is_bot": False, "first_name": "Иван", "name": "ivan"}


def message_update(text="привет", update_type="message_created", chat_id=42,
                   chat_type="dialog", mid="mid.1"):
    return {
        "update_type": update_type,
        "timestamp": 1751400000000,
        "message": {
            "sender": dict(USER),
            "recipient": {"chat_id": chat_id, "chat_type": chat_type,
                          "user_id": 7 if chat_type == "dialog" else None},
            "timestamp": 1751400000000,
            "body": {"mid": mid, "seq": 1, "text": text},
        },
    }


def callback_update(payload="yes"):
    return {
        "update_type": "message_callback",
        "timestamp": 1751400000000,
        "callback": {
            "timestamp": 1751400000000,
            "callback_id": "cb.1",
            "payload": payload,
            "user": dict(USER),
        },
        "message": {
            "sender": dict(USER),
            "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
            "timestamp": 1751400000000,
            "body": {"mid": "mid.1", "seq": 1, "text": "меню"},
        },
    }


# 1. Сигнатуры как в telebot
for name in ("get_updates", "process_new_updates", "process_new_messages",
             "process_new_edited_messages", "process_new_callback_query",
             "set_update_listener"):
    maxi_params = inspect.signature(getattr(MaxiBot, name)).parameters
    tele_params = {n: p for n, p in
                   inspect.signature(getattr(telebot.TeleBot, name)).parameters.items()
                   if p.kind is not inspect.Parameter.VAR_KEYWORD}
    assert list(maxi_params) == list(tele_params), (name, list(maxi_params), list(tele_params))
    for param in tele_params:
        assert maxi_params[param].default == tele_params[param].default, (name, param)
print("1 ok: сигнатуры шести методов пайплайна как в telebot")

# 2. get_updates: параметры уходят в MAX, возвращаются Update, маркер сохраняется
bot = make_bot([{"updates": [message_update()], "marker": 555}])
updates = bot.get_updates(limit=50, long_polling_timeout=30, allowed_updates=["message"])
assert len(updates) == 1 and isinstance(updates[0], Update)
assert updates[0].message.text == "привет"
allowed, params = bot.api.update_calls[0]
# телеботовское имя типа переведено в имя MAX (см. _normalize_allowed_updates)
assert allowed == ["message_created"], allowed
assert params == {"limit": 50, "timeout": 30}, params
assert bot.last_update_id == 555
# длительность long polling задаёт long_polling_timeout, как в telebot
# (там timeout — таймаут соединения)
bot.api.responses.append({"updates": [], "marker": 555})
bot.get_updates(timeout=5, long_polling_timeout=60)
assert bot.api.update_calls[1][1]["timeout"] == 60, bot.api.update_calls[1]
print("2 ok: get_updates отдаёт Update и запоминает маркер MAX")

# 3. Следующий вызов без offset продолжает с сохранённого маркера
bot.api.responses.append({"updates": [], "marker": 556})
bot.get_updates()
assert bot.api.update_calls[2][1]["marker"] == 555, bot.api.update_calls[2]
assert bot.last_update_id == 556
# ответ без маркера не сбрасывает сохранённый
bot.api.responses.append({"updates": []})
bot.get_updates()
assert bot.last_update_id == 556
# marker=0 — валидное значение MAX, а не «маркера нет»: он сохраняется
# и уходит в следующий запрос
bot.api.responses.extend([{"updates": [], "marker": 0}, {"updates": [], "marker": 9}])
bot.get_updates()
bot.get_updates()
assert bot.api.update_calls[5][1]["marker"] == 0, bot.api.update_calls[5]
print("3 ok: маркер продолжается сам, нулевой маркер не теряется")

# 4. Телеботовская привычка offset = last_update_id + 1 не пропускает обновление
bot = make_bot([{"updates": [], "marker": 900}, {"updates": [], "marker": 901}])
# первый вызов на свежем боте: маркера ещё нет, offset=0+1 не должен уйти в MAX
_, warnings = capture_warnings(lambda: bot.get_updates(offset=bot.last_update_id + 1))
assert "marker" not in bot.api.update_calls[0][1], bot.api.update_calls[0]
assert any("update_id + 1" in w for w in warnings), warnings
# и на следующих итерациях того же цикла
_, warnings = capture_warnings(lambda: bot.get_updates(offset=bot.last_update_id + 1))
assert bot.api.update_calls[1][1]["marker"] == 900, bot.api.update_calls[1]
assert any("update_id + 1" in w for w in warnings), warnings
# явный чужой маркер уходит как есть, без предупреждения
bot.api.responses.append({"updates": [], "marker": 902})
_, warnings = capture_warnings(lambda: bot.get_updates(offset=123))
assert bot.api.update_calls[2][1]["marker"] == 123
assert not warnings, warnings
print("4 ok: offset = last_update_id + 1 исправляется с первого же вызова")

# 5. offset=0 — «без offset», offset=-1 — телеботовский пропуск накопленного
bot = make_bot([{"updates": [], "marker": 10}, {"updates": [], "marker": 11}])
bot.get_updates()
bot.get_updates(offset=0)
assert bot.api.update_calls[1][1]["marker"] == 10, bot.api.update_calls[1]
bot = make_bot([{"updates": [message_update()], "marker": 20},
                {"updates": [], "marker": 21}, {"updates": [], "marker": 21}])
result, warnings = capture_warnings(lambda: bot.get_updates(offset=-1))
assert result == [], result
assert any("offset=-1" in w for w in warnings), warnings
# накопленное подтверждено маркером, запросы шли с timeout=0
assert bot.api.update_calls[0][1] == {"timeout": 0}, bot.api.update_calls[0]
assert bot.last_update_id == 20 and bot._updates_marker == 20
print("5 ok: offset 0 и -1 обрабатываются по-телеботовски")

# 6. limit и timeout вне диапазона MAX обрезаются, не-число отбрасывается
bot = make_bot()
_, warnings = capture_warnings(lambda: bot.get_updates(limit=5000, long_polling_timeout=300))
assert bot.api.update_calls[0][1] == {"limit": 1000, "timeout": 90}, bot.api.update_calls[0]
assert len(warnings) == 2, warnings
# timeout=0 (вернуть сразу) — валидное значение MAX, но в telebot 0
# означал дефолт, поэтому предупреждаем про горячий цикл
_, warnings = capture_warnings(lambda: bot.get_updates(long_polling_timeout=0, limit=1))
assert bot.api.update_calls[1][1] == {"limit": 1, "timeout": 0}
assert any("отключает long polling" in w for w in warnings), warnings
# строка и float приводятся к числу: '300' иначе доехал бы до клиента
# и раздул таймаут чтения до пяти минут
_, warnings = capture_warnings(lambda: bot.get_updates(long_polling_timeout="300", limit=50.0))
assert bot.api.update_calls[2][1] == {"limit": 50, "timeout": 90}, bot.api.update_calls[2]
assert any("вне диапазона" in w for w in warnings), warnings
# совсем не число — параметр не отправляем
_, warnings = capture_warnings(lambda: bot.get_updates(long_polling_timeout="скоро", limit=None))
assert bot.api.update_calls[3][1] == {}, bot.api.update_calls[3]
assert any("не число" in w for w in warnings), warnings
print("6 ok: limit и timeout приводятся к числу и клэмпятся")

# 7. allowed_updates без единого типа MAX = подписка на всё, и это громко
bot = make_bot()
_, warnings = capture_warnings(lambda: bot.get_updates(allowed_updates=["poll", "inline_query"]))
assert bot.api.update_calls[0][0] == [], bot.api.update_calls[0]
assert any("ВСЕ обновления" in w for w in warnings), warnings
print("7 ok: пустой после нормализации allowed_updates предупреждает о полной подписке")

# 8. process_new_updates со словарями (кастомный webhook) — обычный пайплайн
bot = make_bot()
seen = []
bot.message_handlers = []


@bot.message_handler(func=lambda m: True)
def on_message(message):
    seen.append(message)


bot.process_new_updates([message_update("один"), message_update("два", mid="mid.2")])
assert [m.text for m in seen] == ["один", "два"], [m.text for m in seen]
print("8 ok: process_new_updates принимает словари обновлений MAX")

# 9. Update из get_updates не разбирается второй раз
bot = make_bot([{"updates": [message_update("готовое")], "marker": 1}])
seen = []


@bot.message_handler(func=lambda m: True)
def on_ready(message):
    seen.append(message)


updates = bot.get_updates()
calls_after_get = bot.api.chat_info_calls
assert calls_after_get > 0  # Message ходил за названием чата один раз
bot.process_new_updates(updates)
assert bot.api.chat_info_calls == calls_after_get, "обновление разобрано повторно"
assert len(seen) == 1 and seen[0] is updates[0].message, "обработчику ушёл другой объект"
print("9 ok: готовый Update не пересобирается — лишних запросов в API нет")

# 10. Сырой Update.de_json (без api) бот разбирает сам
bot = make_bot()
seen = []


@bot.message_handler(func=lambda m: True)
def on_raw(message):
    seen.append(message)


raw_update = Update.de_json(json.dumps(message_update("из вебхука")))
assert raw_update.message is None, "без api объекты строиться не должны"
assert raw_update.update_type == "message_created" and raw_update.api is None
bot.process_new_updates([raw_update])
assert [m.text for m in seen] == ["из вебхука"], [m.text for m in seen]
print("10 ok: сырой Update.de_json разбирается ботом при обработке")

# 11. Update.de_json: словарь, bytes, None и мусор
assert Update.de_json(None) is None
assert Update.de_json(message_update()).update_type == "message_created"
assert Update.de_json(json.dumps(message_update()).encode()).update_type == "message_created"
try:
    Update.de_json(42)
except TypeError as exc:
    assert "de_json" in str(exc), exc
else:
    raise AssertionError("de_json(42) должен бросать TypeError")
print("11 ok: Update.de_json принимает словарь, строку и bytes")

# 12. Мусор в списке пропускается с предупреждением, остальные обрабатываются
bot = make_bot()
seen = []


@bot.message_handler(func=lambda m: True)
def on_mixed(message):
    seen.append(message)


_, warnings = capture_warnings(
    lambda: bot.process_new_updates([42, message_update("живое")])
)
assert [m.text for m in seen] == ["живое"], [m.text for m in seen]
assert any("de_json" in w for w in warnings), warnings
print("12 ok: непонятный элемент списка не отменяет остальные обновления")

# 13. set_update_listener: слушатель получает СПИСОК сообщений до обработчиков
bot = make_bot()
order = []


def listener(messages):
    assert isinstance(messages, list), type(messages)
    order.append(("listener", [m.text for m in messages]))


bot.set_update_listener(listener)


@bot.message_handler(func=lambda m: True)
def on_listened(message):
    order.append(("handler", message.text))


bot.process_new_updates([message_update("эй")])
assert order == [("listener", ["эй"]), ("handler", "эй")], order
print("13 ok: set_update_listener получает список Message до обработчиков")

# 14. Сообщение, забранное next_step, не доходит ни до слушателя, ни до обработчика
bot = make_bot()
order = []
bot.set_update_listener(lambda messages: order.append(("listener", len(messages))))


@bot.message_handler(func=lambda m: True)
def on_after_step(message):
    order.append(("handler", message.text))


first = Update(message_update("первое"), bot.api).message
bot.register_next_step_handler(first, lambda m: order.append(("step", m.text)))
bot.process_new_updates([message_update("второе", mid="mid.2")])
assert order == [("step", "второе")], order
# следующее сообщение уже идёт обычным путём
bot.process_new_updates([message_update("третье", mid="mid.3")])
assert order == [("step", "второе"), ("listener", 1), ("handler", "третье")], order
print("14 ok: next_step забирает сообщение до слушателей и обработчиков")

# 15. Правки и коллбэки — через публичные точки
bot = make_bot()
edited, callbacks = [], []


@bot.edited_message_handler(func=lambda m: True)
def on_edited(message):
    edited.append(message.text)


@bot.callback_query_handler(func=lambda c: True)
def on_callback(callback):
    callbacks.append(callback.data)


bot.process_new_updates([message_update("правка", update_type="message_edited"),
                         callback_update("yes")])
assert edited == ["правка"], edited
assert callbacks == ["yes"], callbacks
# те же точки вызываются напрямую, как в telebot
bot.process_new_edited_messages([Update(message_update("вручную",
                                                       update_type="message_edited"),
                                        bot.api).edited_message])
assert edited == ["правка", "вручную"], edited
bot.process_new_callback_query([Update(callback_update("no"), bot.api).callback_query])
assert callbacks == ["yes", "no"], callbacks
print("15 ok: правки и коллбэки идут через публичные точки пайплайна")

# 16. Посты каналов из process_new_updates — только в канальные обработчики
bot = make_bot()
posts, messages = [], []


@bot.channel_post_handler(func=lambda m: True)
def on_post(message):
    posts.append(message.text)


@bot.message_handler(func=lambda m: True)
def on_plain(message):
    messages.append(message.text)


bot.process_new_updates([message_update("пост", chat_type="channel", chat_id=100)])
assert posts == ["пост"] and messages == [], (posts, messages)
print("16 ok: посты каналов маршрутизируются и в публичном пайплайне")

# 17. Битое обновление не отменяет следующие
bot = make_bot()
seen = []


@bot.message_handler(func=lambda m: True)
def on_survivor(message):
    seen.append(message.text)


broken = {"update_type": "message_created", "timestamp": 1751400000000,
          "message": {"sender": dict(USER), "body": {"mid": "m", "seq": 1, "text": "битое"}}}
bot.process_new_updates([broken, message_update("целое", mid="mid.9")])
assert seen == ["целое"], seen
print("17 ok: обновление с битым payload не отменяет остальные")

# 18. Пустой список и None — без ошибок и без запросов
bot = make_bot()
bot.process_new_updates([])
bot.process_new_updates(None)
assert bot.api.chat_info_calls == 0
print("18 ok: пустой список обновлений обрабатывается молча")

# 19. Слушателей может быть несколько, и они не мешают друг другу
bot = make_bot()
calls = []
bot.set_update_listener(lambda messages: calls.append("a"))
bot.set_update_listener(lambda messages: calls.append("b"))
assert len(bot.update_listener) == 2
bot.process_new_messages([Update(message_update("раз"), bot.api).message])
assert calls == ["a", "b"], calls
print("19 ok: слушателей может быть несколько")

# 20. Сырой Update дозаполняется на месте, с api — сразу
bot = make_bot()
raw = Update.de_json(message_update("обратно"))
bot.process_new_updates([raw])
assert raw.message is not None and raw.message.text == "обратно", "объекты не вернулись в Update"
assert raw.api is bot.api
ready = Update.de_json(message_update("сразу"), bot.api)
assert ready.message is not None and ready.message.text == "сразу"
print("20 ok: de_json без api дозаполняется ботом, с api — сразу")

# 21. У Update есть update_id (всегда None) — мигрантский код не падает
upd = Update(message_update(), make_bot().api)
assert upd.update_id is None and not upd.update_id
print("21 ok: Update.update_id есть и равен None")

# 22. Middleware работает и на пути process_new_updates с готовым Update
from maxibot import apihelper  # noqa: E402  (ENABLE_MIDDLEWARE — как в telebot)

apihelper.ENABLE_MIDDLEWARE = True
try:
    bot = make_bot([{"updates": [message_update("через middleware")], "marker": 1}])
    trace = []

    @bot.middleware_handler()
    def common_mw(bot_instance, update):
        trace.append(("common", update.update_type))

    @bot.middleware_handler(update_types=["message"])
    def typed_mw(bot_instance, message):
        trace.append(("typed", message.text))

    @bot.message_handler(func=lambda m: True)
    def on_mw(message):
        trace.append(("handler", message.text))

    bot.process_new_updates(bot.get_updates())
    assert trace == [("typed", "через middleware"), ("common", "message_created"),
                     ("handler", "через middleware")], trace

    # упавший middleware отменяет обновление и на этом пути
    bot = make_bot()
    reached = []

    @bot.middleware_handler()
    def broken_mw(bot_instance, update):
        raise RuntimeError("боль")

    @bot.message_handler(func=lambda m: True)
    def never(message):
        reached.append(message.text)

    bot.process_new_updates([Update(message_update("не дойдёт"), bot.api)])
    assert reached == [], reached
finally:
    apihelper.ENABLE_MIDDLEWARE = False
print("22 ok: middleware отрабатывает и на готовых Update")

# 23. Гейт «нет обработчиков» работает и на пути process_new_updates
bot = make_bot()
raw_edit = Update.de_json(message_update("правка", update_type="message_edited"))
bot.process_new_updates([raw_edit])
# без edited_message_handlers объект не строится: в API не ходили
assert bot.api.chat_info_calls == 0, bot.api.chat_info_calls
assert raw_edit.edited_message is None


@bot.edited_message_handler(func=lambda m: True)
def on_edit_gate(message):
    pass


bot.process_new_updates([Update.de_json(message_update("правка", update_type="message_edited"))])
assert bot.api.chat_info_calls == 1, bot.api.chat_info_calls
print("23 ok: без подписки объект не строится даже в публичном пайплайне")

# 24. Упавший слушатель не отменяет ни соседей, ни обработчик
bot = make_bot()
trace = []
bot.set_update_listener(lambda messages: trace.append("first"))


def boom(messages):
    trace.append("boom")
    raise RuntimeError("слушатель упал")


bot.set_update_listener(boom)
bot.set_update_listener(lambda messages: trace.append("last"))


@bot.message_handler(func=lambda m: True)
def after_boom(message):
    trace.append("handler")


bot.process_new_updates([message_update("живём дальше")])
assert trace == ["first", "boom", "last", "handler"], trace
print("24 ok: исключение слушателя изолировано, как у обработчиков")

# 25. Пачка обновлений: слушатель вызывается на каждое сообщение отдельно
bot = make_bot()
sizes = []
bot.set_update_listener(lambda messages: sizes.append([m.text for m in messages]))
bot.process_new_updates([message_update("а"), message_update("б", mid="mid.2"),
                         message_update("в", mid="mid.3")])
# отличие от telebot (там один вызов со всей пачкой) — задокументировано
assert sizes == [["а"], ["б"], ["в"]], sizes
print("25 ok: обновления обрабатываются по одному — слушателю приходит по сообщению")

# 26. Любой отрицательный offset — телеботовский пропуск накопленного
bot = make_bot([{"updates": [message_update()], "marker": 30}, {"updates": [], "marker": 31}])
result, warnings = capture_warnings(lambda: bot.get_updates(offset=-5))
assert result == [] and bot.last_update_id == 30, (result, bot.last_update_id)
assert all("marker" not in params or params["marker"] > 0
           for _, params in bot.api.update_calls), bot.api.update_calls
assert any("offset=-5" in w for w in warnings), warnings
print("26 ok: отрицательный offset не уходит в MAX маркером")

# 27. limit=0 не отправляем, дробный таймаут не превращается в 0, inf не роняет
bot = make_bot()
bot.get_updates(limit=0, long_polling_timeout=0.9)
assert bot.api.update_calls[0][1] == {"timeout": 1}, bot.api.update_calls[0]
_, warnings = capture_warnings(lambda: bot.get_updates(long_polling_timeout=float("inf")))
assert bot.api.update_calls[1][1] == {}, bot.api.update_calls[1]
assert any("не число" in w for w in warnings), warnings
print("27 ok: ложный limit, дробный и бесконечный таймаут обработаны")

# 28. Ответ с marker=null не ломает телеботовский цикл offset+1
bot = make_bot([{"updates": [], "marker": None}, {"updates": [], "marker": 5}])
bot.get_updates()
assert bot.last_update_id == 0 and bot._updates_marker is None
bot.get_updates(offset=bot.last_update_id + 1)  # не должен падать с TypeError
assert "marker" not in bot.api.update_calls[1][1], bot.api.update_calls[1]
print("28 ok: marker=null не ломает цикл с last_update_id + 1")

# 29. Предупреждения не повторяются на каждой итерации цикла
bot = make_bot()
_, warnings = capture_warnings(
    lambda: [bot.get_updates(allowed_updates=["poll"], limit=5000) for _ in range(3)]
)
assert len(warnings) == 3, warnings  # по одному на каждый повод, а не девять
print("29 ok: повторные предупреждения в цикле не дублируются")

# 30. Забытые скобки в вебхуке: одно обновление вместо списка
bot = make_bot()
seen = []


@bot.message_handler(func=lambda m: True)
def on_single(message):
    seen.append(message.text)


_, warnings = capture_warnings(lambda: bot.process_new_updates(message_update("без скобок")))
assert seen == ["без скобок"], seen
assert any("оберните в список" in w for w in warnings), warnings
print("30 ok: одиночное обновление обрабатывается с подсказкой про список")

# 31. process_new_messages со смешанной пачкой: слушателю — только остаток
bot = make_bot()
got = []
bot.set_update_listener(lambda messages: got.append([m.text for m in messages]))


@bot.message_handler(func=lambda m: True)
def on_rest(message):
    got.append(("handler", message.text))


with_step = Update(message_update("шаг", chat_id=1), bot.api).message
plain = Update(message_update("обычное", chat_id=2, mid="mid.2"), bot.api).message
bot.register_next_step_handler(with_step, lambda m: got.append(("step", m.text)))
batch = [with_step, plain]
bot.process_new_messages(batch)
assert got == [("step", "шаг"), ["обычное"], ("handler", "обычное")], got
assert len(batch) == 2, "переданный список не должен изменяться (в telebot он мутирует)"
print("31 ok: слушатель получает пачку без забранных next_step сообщений")

print("ALL OK")

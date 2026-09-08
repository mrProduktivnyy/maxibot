"""
maxibot.formatting (диалекты MAX), maxibot.callback_data (CallbackData)
и телеботовские алиасы исключений — дифференциально против telebot.

Запуск:
    python3 tests/test_formatting_callback.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot.apihelper
import telebot.callback_data
import telebot.formatting

import maxibot
from maxibot import callback_data, exceptions, formatting
from maxibot import apihelper as m_apihelper

# 1. Состав и сигнатуры — все телеботовские имена на месте
t_public = [n for n in dir(telebot.formatting)
            if not n.startswith("_") and callable(getattr(telebot.formatting, n))
            and getattr(telebot.formatting, n).__module__ == "telebot.formatting"]
for name in t_public:
    ours = getattr(formatting, name, None)
    assert ours is not None, name
    sig, t_sig = inspect.signature(ours), inspect.signature(getattr(telebot.formatting, name))
    assert list(sig.parameters) == list(t_sig.parameters), name
    for p_name, p in t_sig.parameters.items():
        assert sig.parameters[p_name].default == p.default, (name, p_name)
assert callable(formatting.mmark) and callable(formatting.hmark)   # бонусы MAX
# голый import maxibot экспонирует formatting (как telebot; callback_data — нет)
assert maxibot.formatting is formatting
print(f"1 ok: сигнатуры ({len(t_public)} телеботовских + mmark/hmark)")

# 2. HTML-функции — байт в байт с telebot (диалект совпадает)
SAMPLES = ("обычный", "спец <i> & 'знаки'", "")
for name in ("hbold", "hitalic", "hunderline", "hstrikethrough", "hcode", "hcite"):
    for text in SAMPLES:
        for esc in (True, False):
            assert getattr(formatting, name)(text, escape=esc) == \
                   getattr(telebot.formatting, name)(text, escape=esc), (name, text, esc)
assert formatting.hlink("Доки", "https://dev.max.ru?a=1&b=2") == \
       telebot.formatting.hlink("Доки", "https://dev.max.ru?a=1&b=2")
assert formatting.hpre("code < here", language="python") == \
       telebot.formatting.hpre("code < here", language="python")
assert formatting.hide_link("https://x.y/i.png") == telebot.formatting.hide_link("https://x.y/i.png")
assert formatting.format_text("а", "б", separator=" | ") == \
       telebot.formatting.format_text("а", "б", separator=" | ")
assert formatting.escape_html("<болт & гайка>") == telebot.formatting.escape_html("<болт & гайка>")
print("2 ok: h-функции байт в байт с telebot")

# 3. Маркдаун — диалект MAX (не телеграмный!)
assert formatting.mbold("жирный") == "**жирный**"                 # telebot: *жирный* (в MAX это курсив)
assert formatting.mitalic("курсив") == "_курсив_"                 # без телеграмного \r
assert not formatting.mitalic("курсив").endswith("\r")
assert formatting.munderline("низ") == "++низ++"                  # telebot: __низ__ (в MAX это жирный)
assert formatting.mstrikethrough("зачёркнуто") == "~~зачёркнуто~~"  # telebot: ~зачёркнуто~
assert formatting.mmark("важно") == "^^важно^^"
assert formatting.hmark("важно") == "<mark>важно</mark>"
# mcode и mcite — как у telebot
for text in ("print(1)", "многострочная\nцитата"):
    assert formatting.mcode(text) == telebot.formatting.mcode(text)
    assert formatting.mcode(text, language="python") == telebot.formatting.mcode(text, language="python")
    assert formatting.mcite(text) == telebot.formatting.mcite(text)
print("3 ok: маркдаун — диалект MAX")

# 4. escape_markdown: телеботовский набор + ^ (маркер выделения MAX)
tricky = r"_*[]()~`>#+-=|{}.!\ и текст"
assert formatting.escape_markdown(tricky) == telebot.formatting.escape_markdown(tricky)
assert formatting.escape_markdown("5^2") == r"5\^2"               # у telebot ^ не экранируется
assert telebot.formatting.escape_markdown("5^2") == "5^2"
assert formatting.mbold("2*2=4") == r"**2\*2\=4**"                # делимитеры не ломаются
print("4 ok: escape_markdown с ^")

# 5. mlink: escape=True как telebot; телеботовский баг escape=False починен
assert formatting.mlink("текст", "https://max.ru") == telebot.formatting.mlink("текст", "https://max.ru")
assert formatting.mlink("текст", "https://max.ru", escape=False) == "[текст](https://max.ru)"
# guard: в telebot 4.15.4 ветка escape=False подставляет content вместо url;
# если тут упало — telebot починили, обновить комментарии в formatting.py
assert telebot.formatting.mlink("текст", "https://max.ru", escape=False) == "[текст](текст)"
print("5 ok: mlink (баг telebot починен)")

# 6. Спойлера в MAX нет: текст без обёртки + предупреждение
records = []
handler = logging.Handler()
handler.emit = records.append
logging.getLogger("maxibot").addHandler(handler)
try:
    assert formatting.mspoiler("тайна!") == r"тайна\!"            # экранирован, не обёрнут
    assert formatting.hspoiler("<тайна>") == "&lt;тайна&gt;"
    assert formatting.mspoiler("тайна", escape=False) == "тайна"
    assert len(records) == 3 and all("спойлера в MAX нет" in r.getMessage() for r in records)
finally:
    logging.getLogger("maxibot").removeHandler(handler)
print("6 ok: mspoiler/hspoiler предупреждают")

# 7. CallbackData — дифференциально с telebot (new/parse/filter)
ours_f = callback_data.CallbackData("cmd", "id", prefix="products")
theirs_f = telebot.callback_data.CallbackData("cmd", "id", prefix="products")
for build in (lambda f: f.new("buy", 5), lambda f: f.new(cmd="buy", id=5),
              lambda f: f.new("buy", id="5")):
    assert build(ours_f) == build(theirs_f) == "products:buy:5"
assert ours_f.parse("products:buy:5") == theirs_f.parse("products:buy:5") == \
       {"@": "products", "cmd": "buy", "id": "5"}
for factory in (ours_f, theirs_f):
    for bad_call in (lambda: factory.parse("other:buy:5"),      # чужой префикс
                     lambda: factory.parse("products:buy"),     # не то число частей
                     lambda: factory.new("a:b", 1),             # разделитель в значении
                     lambda: factory.new("buy"),                # значение не передано
                     lambda: factory.filter(nope=1)):           # нет такой части
        try:
            bad_call()
            assert False, (factory, bad_call)
        except ValueError:
            pass
    try:
        factory.new("buy", 5, 7)
        assert False
    except TypeError:
        pass
try:
    callback_data.CallbackData("id", prefix="a:b")
    assert False
except ValueError:
    pass
try:
    callback_data.CallbackData("id", prefix=7)
    assert False
except TypeError:
    pass
print("7 ok: CallbackData дифференциально")


# 8. CallbackDataFilter.check по CallbackQuery.data
class FakeQuery:
    def __init__(self, data):
        self.data = data


flt = ours_f.filter(cmd="buy")
assert flt.check(FakeQuery("products:buy:5")) is True
assert flt.check(FakeQuery("products:sell:5")) is False
assert flt.check(FakeQuery("мусор без префикса")) is False        # ValueError -> False
assert ours_f.filter(cmd=["buy", "sell"]).check(FakeQuery("products:sell:1")) is True
assert ours_f.filter(cmd=["buy", "sell"]).check(FakeQuery("products:del:1")) is False
assert ours_f.filter().check(FakeQuery("products:x:y")) is True   # пустой конфиг — только префикс
# скаляр сверяется равенством, не подстрокой (и как у telebot)
assert ours_f.filter(cmd="buys").check(FakeQuery("products:buy:5")) is False
assert theirs_f.filter(cmd="buys").check(FakeQuery("products:buy:5")) is False
print("8 ok: CallbackDataFilter.check")

# 9. Лимит payload — 1024 по спеке MAX (не телеграмные 64 байта)
long_factory = callback_data.CallbackData("blob", prefix="p")
t_long_factory = telebot.callback_data.CallbackData("blob", prefix="p")
mid = "x" * 500                                                   # > 64, < 1024
assert long_factory.new(blob=mid)                                 # у нас проходит
try:
    t_long_factory.new(blob=mid)                                  # у telebot — уже нет
    assert False, "telebot стал принимать > 64 байт?"
except ValueError:
    pass
try:
    long_factory.new(blob="x" * 1025)
    assert False, "ожидался ValueError"
except ValueError:
    pass
assert callback_data.MAX_PAYLOAD_LEN == 1024
print("9 ok: лимит 1024")

# 10. Алиасы исключений — телеботовские имена из telebot.apihelper
for name in ("ApiException", "ApiHTTPException", "ApiInvalidJSONException", "ApiTelegramException"):
    assert hasattr(telebot.apihelper, name), name                 # имя действительно телеботовское
    assert hasattr(m_apihelper, name) and hasattr(exceptions, name), name
assert m_apihelper.ApiException is exceptions.MaxApiException
assert m_apihelper.ApiHTTPException is exceptions.MaxApiHTTPException
assert m_apihelper.ApiInvalidJSONException is exceptions.MaxApiInvalidJSONException
assert m_apihelper.ApiTelegramException is exceptions.MaxApiException


class FakeResp:
    status_code = 429
    reason = "Too Many Requests"
    text = "{}"


# `except ApiTelegramException` обязан ловить ОБА вида ошибок MAX:
# HTTP-статусом (как шлёт MAX) и code в теле
for exc in (exceptions.MaxApiHTTPException("GET /x", FakeResp()),
            exceptions.MaxApiRequestException("GET /x", FakeResp(), {"code": "err", "message": "m"})):
    try:
        raise exc
    except m_apihelper.ApiTelegramException:
        pass
# а конкретные алиасы остаются конкретными
try:
    raise exceptions.MaxApiRequestException("GET /x", FakeResp(), {"code": "err", "message": "m"})
except m_apihelper.ApiHTTPException:
    assert False, "ApiHTTPException не должен ловить ошибку из тела"
except m_apihelper.ApiException:
    pass
print("10 ok: алиасы исключений")

print("ALL OK")

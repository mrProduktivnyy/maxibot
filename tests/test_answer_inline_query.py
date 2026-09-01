"""
Проверка заглушек инлайн-режима (issue #37).

Инлайн-режима в MAX Bot API нет (ни метода, ни типа обновления
inline_query), поэтому всё ради совместимости с telebot:
answer_inline_query принимает telebot-параметры и бросает
NotImplementedError с объяснением, а декораторы inline_handler /
chosen_inline_handler (и register_*-варианты) регистрируются без
ошибки — перенесённый бот запускается, — но пишут предупреждение,
что обработчик никогда не будет вызван.

Запуск:
    python3 tests/test_answer_inline_query.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot import MaxiBot


def make_bot():
    return MaxiBot.__new__(MaxiBot)


# 1. Вызов всегда бросает NotImplementedError с объяснением про MAX
bot = make_bot()
try:
    bot.answer_inline_query("query1", [])
    raise AssertionError("должен был упасть с NotImplementedError")
except NotImplementedError as e:
    assert "MAX" in str(e), str(e)
    assert "inline" in str(e).lower(), str(e)
print('1 ok: NotImplementedError с объяснением')

# 2. Все параметры telebot принимаются (по имени), до броска дело доходит одинаково
try:
    bot.answer_inline_query(
        "query1", [{"r": 1}], cache_time=300, is_personal=True,
        next_offset="10", switch_pm_text="t", switch_pm_parameter="p", button=object()
    )
    raise AssertionError("должен был упасть с NotImplementedError")
except NotImplementedError:
    pass
print('2 ok: все параметры telebot принимаются')

# 3. Порядок и имена параметров — один в один с telebot.answer_inline_query
params = list(inspect.signature(MaxiBot.answer_inline_query).parameters)
assert params == [
    "self", "inline_query_id", "results", "cache_time", "is_personal",
    "next_offset", "switch_pm_text", "switch_pm_parameter", "button",
], params
print('3 ok: сигнатура telebot')


class WarningCollector(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


collector = WarningCollector()
maxibot_logger = logging.getLogger("maxibot")
maxibot_logger.addHandler(collector)
maxibot_logger.setLevel(logging.WARNING)

# 4. @bot.inline_handler(...) не роняет перенесённый код, функция не подменяется
bot = make_bot()

@bot.inline_handler(lambda query: True)
def handle_inline(query):
    return "результат"

assert handle_inline(None) == "результат"  # декоратор вернул функцию нетронутой
assert len(collector.records) == 1
assert "inline" in collector.records[0].getMessage().lower()
assert "handle_inline" in collector.records[0].getMessage()
print('4 ok: inline_handler регистрируется с предупреждением')

# 5. chosen_inline_handler — так же
collector.records.clear()

@bot.chosen_inline_handler(func=lambda result: True)
def handle_chosen(result):
    return "выбор"

assert handle_chosen(None) == "выбор"
assert len(collector.records) == 1
print('5 ok: chosen_inline_handler регистрируется с предупреждением')

# 6. register_*-варианты принимают telebot-параметры и не падают
collector.records.clear()
bot.register_inline_handler(handle_inline, func=lambda q: True, pass_bot=True)
bot.register_chosen_inline_handler(handle_chosen, func=lambda r: True)
assert len(collector.records) == 2
print('6 ok: register_inline_handler и register_chosen_inline_handler')

maxibot_logger.removeHandler(collector)

print('ALL OK')

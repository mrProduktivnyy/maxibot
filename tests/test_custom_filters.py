"""
Кастом-фильтры: add_custom_filter, модуль maxibot.custom_filters,
**kwargs у обработчиков, нормализация chat_types и телеботовские
имена типов чата у message.chat.

Запуск:
    python3 tests/test_custom_filters.py
"""
import inspect
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot
from telebot import custom_filters as telebot_filters

from maxibot import MaxiBot
from maxibot import custom_filters
from maxibot.custom_filters import (
    AdvancedCustomFilter,
    ChatFilter,
    ForwardFilter,
    IsAdminFilter,
    IsDigitFilter,
    IsReplyFilter,
    LanguageFilter,
    SimpleCustomFilter,
    TextContainsFilter,
    TextFilter,
    TextMatchFilter,
    TextStartsFilter,
)
from maxibot.types import CallbackQuery, Message, Update


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
    def __init__(self, members=None):
        self.chat_info_calls = 0
        self.member_calls = []
        self.members = members or []

    def get_chat_info(self, chat_id):
        self.chat_info_calls += 1
        return {"title": "chat"}

    def get_chat_members(self, chat_id, user_ids=None, **kwargs):
        self.member_calls.append((chat_id, tuple(user_ids or ())))
        return {"members": self.members}


def make_bot(api=None):
    bot = MaxiBot("t", threaded=False)
    bot.api = api or FakeApi()
    return bot


USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u"}


def message_update(text="привет", chat_type="dialog", link=None,
                   attachments=None, user_locale=None, sender=USER):
    body = {"mid": "mid.1", "seq": 1, "text": text}
    if attachments is not None:
        body["attachments"] = attachments
    message = {
        "sender": sender,
        "recipient": {"chat_id": 42, "chat_type": chat_type, "user_id": 7},
        "timestamp": 1751400000000,
        "body": body,
    }
    if link is not None:
        message["link"] = link
    update = {
        "update_type": "message_created",
        "timestamp": 1751400000000,
        "message": message,
    }
    if user_locale is not None:
        update["user_locale"] = user_locale
    return update


def callback_update(payload="ok"):
    return {
        "update_type": "message_callback",
        "timestamp": 1751400000000,
        "callback": {"callback_id": "cb.1", "payload": payload, "user": USER},
        "message": {
            "sender": USER,
            "recipient": {"chat_id": 42, "chat_type": "chat", "user_id": 7},
            "timestamp": 1751400000000,
            "body": {"mid": "mid.1", "seq": 1, "text": "кнопки", "attachments": []},
        },
    }


def make_message(**kwargs):
    return Update(message_update(**kwargs), FakeApi()).message


# 1. Сигнатуры и состав модуля как в telebot
assert (list(inspect.signature(MaxiBot.add_custom_filter).parameters)
        == list(inspect.signature(telebot.TeleBot.add_custom_filter).parameters))
# _check_filter — внутренний метод: сверяем только число аргументов
# (имя третьего у нас context, как во всём диспатче maxibot)
assert (len(inspect.signature(MaxiBot._check_filter).parameters)
        == len(inspect.signature(telebot.TeleBot._check_filter).parameters))
for name in ("SimpleCustomFilter", "AdvancedCustomFilter", "TextFilter",
             "TextMatchFilter", "TextContainsFilter", "TextStartsFilter",
             "ChatFilter", "ForwardFilter", "IsReplyFilter", "LanguageFilter",
             "IsAdminFilter", "IsDigitFilter"):
    assert hasattr(custom_filters, name), name
    assert (getattr(custom_filters, name).key if name.endswith("Filter")
            and name not in ("TextFilter", "SimpleCustomFilter", "AdvancedCustomFilter")
            else True)
for name in ("TextMatchFilter", "TextContainsFilter", "TextStartsFilter",
             "ChatFilter", "ForwardFilter", "IsReplyFilter", "LanguageFilter",
             "IsAdminFilter", "IsDigitFilter"):
    assert (getattr(custom_filters, name).key
            == getattr(telebot_filters, name).key), name
assert list(inspect.signature(TextFilter.__init__).parameters) == list(
    inspect.signature(telebot_filters.TextFilter.__init__).parameters)
print("1 ok: add_custom_filter/_check_filter и ключи фильтров как в telebot")

# 2. Simple-фильтр: значение СРАВНИВАЕТСЯ с результатом check (как в telebot)
bot = make_bot()
bot.add_custom_filter(IsDigitFilter())
got = []


@bot.message_handler(is_digit=True)
def digits(message):
    got.append(("digit", message.text))


@bot.message_handler(is_digit=False)
def not_digits(message):
    got.append(("text", message.text))


bot._process_update(message_update(text="42"))
bot._process_update(message_update(text="сорок два"))
assert got == [("digit", "42"), ("text", "сорок два")], got
print("2 ok: SimpleCustomFilter — is_digit=True/False")

# 3. Advanced-фильтр получает значение из обработчика
bot = make_bot()
bot.add_custom_filter(TextStartsFilter())
got = []


@bot.message_handler(text_startswith="сэр")
def sir(message):
    got.append(message.text)


bot._process_update(message_update(text="сэр, извольте"))
bot._process_update(message_update(text="мадам"))
assert got == ["сэр, извольте"], got
print("3 ok: AdvancedCustomFilter получает значение фильтра")

# 4. Незарегистрированный ключ: обработчик НЕ срабатывает + предупреждение
bot = make_bot()
got = []


@bot.message_handler(is_digit=True)
def unregistered(message):
    got.append(message.text)


_, warnings = capture_warnings(lambda: bot._process_update(message_update(text="42")))
assert got == [], got
assert any("не зарегистрирован" in w for w in warnings), warnings
print("4 ok: незнакомый фильтр не пропускает обработчик и пишет в лог")

# 5. Кастом-фильтры работают у callback_query_handler (раньше игнорировались)
bot = make_bot()
bot.add_custom_filter(TextMatchFilter())
got = []


@bot.callback_query_handler(text="нет")
def wrong(call):
    got.append("нет")


@bot.callback_query_handler(text="ok")
def right(call):
    got.append("ok")


bot._process_update(callback_update(payload="ok"))
assert got == ["ok"], got
print("5 ok: кастом-фильтр у callback_query_handler (data берётся из payload)")

# 6. Кастом-фильтры работают у обработчиков членства
bot = make_bot()


class IsChannelFilter(SimpleCustomFilter):
    key = "is_channel_event"

    def check(self, event):
        return bool(getattr(event, "is_channel", False))


bot.add_custom_filter(IsChannelFilter())
got = []


@bot.my_chat_member_handler(is_channel_event=True)
def channel_only(event):
    got.append(event.chat.id)


bot._process_update({"update_type": "bot_removed", "timestamp": 1751400000000,
                     "chat_id": 42, "user": USER, "is_channel": False})
assert got == [], got
bot._process_update({"update_type": "bot_removed", "timestamp": 1751400001000,
                     "chat_id": 43, "user": USER, "is_channel": True})
assert got == [43], got
print("6 ok: кастом-фильтр у my_chat_member_handler")

# 7. Ошибка внутри фильтра не роняет диспатч — обработчик просто не совпал
bot = make_bot()


class BoomFilter(SimpleCustomFilter):
    key = "boom"

    def check(self, message):
        raise RuntimeError("бум")


bot.add_custom_filter(BoomFilter())
reported = []
bot.exception_handler = type("H", (), {"handle": lambda self, e: reported.append(e) or True})()
got = []


@bot.message_handler(boom=True)
def boom(message):
    got.append(message.text)


@bot.message_handler(func=lambda m: True)
def fallback(message):
    got.append(("fallback", message.text))


bot._process_update(message_update(text="привет"))
assert got == [("fallback", "привет")], got
assert len(reported) == 1 and isinstance(reported[0], RuntimeError)
print("7 ok: исключение фильтра уходит в exception_handler, диспатч живёт")

# 8. add_custom_filter: класс вместо экземпляра и фильтр без key
bot = make_bot()
_, warnings = capture_warnings(lambda: bot.add_custom_filter(IsDigitFilter))
assert any("экземпляр" in w for w in warnings), warnings


class NoKeyFilter(SimpleCustomFilter):
    def check(self, message):
        return True


_, warnings = capture_warnings(lambda: bot.add_custom_filter(NoKeyFilter()))
assert any("нет key" in w for w in warnings), warnings
assert None not in bot.custom_filters and "" not in bot.custom_filters
print("8 ok: add_custom_filter предупреждает про класс и фильтр без key")

# 9. Фильтр не того базового класса регистрируется, но не вызывается (telebot)
bot = make_bot()


class Duck:
    key = "duck"

    def check(self, message):
        return True


_, warnings = capture_warnings(lambda: bot.add_custom_filter(Duck()))
assert any("не наследует" in w for w in warnings), warnings
assert "duck" in bot.custom_filters
got = []


@bot.message_handler(duck=True)
def duck(message):
    got.append(message.text)


bot._process_update(message_update(text="кря"))
assert got == [], got
print("9 ok: фильтр не того типа зарегистрирован, но не срабатывает")

# 10. chat.type — телеботовское имя, сырой тип MAX в max_type
message = make_message(chat_type="dialog")
assert message.chat.type == "private" and message.chat.max_type == "dialog"
message = make_message(chat_type="chat")
assert message.chat.type == "group" and message.chat.max_type == "chat"
message = make_message(chat_type="channel")
assert message.chat.type == "channel" and message.chat.max_type == "channel"
print("10 ok: message.chat.type телеботовский, max_type — сырой MAX")

# 11. chat_types: телеботовские имена, supergroup и сырые имена MAX
bot = make_bot()
got = []
bot.message_handler(chat_types=["supergroup"], func=lambda m: True)(
    lambda m: got.append("supergroup"))
bot._process_update(message_update(chat_type="chat"))
assert got == ["supergroup"], got

bot = make_bot()
got = []
bot.message_handler(chat_types=["private"], func=lambda m: True)(
    lambda m: got.append("private"))
bot._process_update(message_update(chat_type="dialog"))
assert got == ["private"], got

handler_dict = MaxiBot._build_handler_dict(lambda m: None,
                                           chat_types=["dialog", "chat", "supergroup"])
assert handler_dict["filters"]["chat_types"] == ["private", "group"], handler_dict
print("11 ok: chat_types принимает оба словаря имён, дубли схлопываются")

# 12. Незнакомый тип чата — предупреждение, обработчик не срабатывает
bot = make_bot()
got = []
_, warnings = capture_warnings(
    lambda: bot.message_handler(chat_types=["личка"], func=lambda m: True)(
        lambda m: got.append("да")))
assert any("неизвестные типы" in w for w in warnings), warnings
bot._process_update(message_update(chat_type="dialog"))
assert got == [], got

_, warnings = capture_warnings(
    lambda: MaxiBot._build_handler_dict(lambda m: None, chat_types="private"))
assert any("обернул строку" in w for w in warnings), warnings
print("12 ok: неизвестный chat_types предупреждает, строка оборачивается")

# 13. TextFilter: equals/contains/starts_with/ends_with и ignore_case
message = make_message(text="Аккаунт заблокирован")
assert TextFilter(equals="Аккаунт заблокирован").check(message)
assert not TextFilter(equals="аккаунт заблокирован").check(message)
assert TextFilter(equals="аккаунт заблокирован", ignore_case=True).check(message)
assert TextFilter(contains=["Счёт", "аккаунт"], ignore_case=True).check(message)
assert TextFilter(starts_with="Аккаунт").check(message)
assert TextFilter(ends_with=["заблокирован"]).check(message)
assert not TextFilter(starts_with="Счёт").check(message)
# equals не совпал, но задан contains — проверка продолжается
assert TextFilter(equals="нет", contains=["блок"]).check(message)
# ignore_case снимает регистр со всех условий, в отличие от telebot
assert TextFilter(equals="нет", contains=["АККАУНТ"], ignore_case=True).check(message)
assert not telebot_filters.TextFilter(
    equals="нет", contains=["АККАУНТ"], ignore_case=True).check(message)
# фильтр не портится между проверками
text_filter = TextFilter(equals="АККАУНТ ЗАБЛОКИРОВАН", ignore_case=True)
assert text_filter.check(message) and text_filter.equals == "АККАУНТ ЗАБЛОКИРОВАН"
assert TextFilter(ends_with=["ЗАБЛОКИРОВАН"], ignore_case=True).check(message)
assert TextContainsFilter().check(message, ["нет", "блок"])
assert TextContainsFilter().check(message, "Аккаунт")
# список у TextStartsFilter — расширение относительно telebot
assert TextStartsFilter().check(message, ["Счёт", "Аккаунт"])
assert not TextStartsFilter().check(message, ["Счёт", "Платёж"])
try:
    TextFilter()
    raise AssertionError("ожидался ValueError")
except ValueError:
    pass
print("13 ok: TextFilter, ignore_case чинит телеботовский elif")

# 14. Текстовые фильтры не падают на сообщении без текста
message = make_message(text=None, attachments=[{"type": "image",
                                                "payload": {"url": "u", "token": "t"}}])
assert message.content_type == "photo" and message.text is None
assert not TextFilter(equals="привет").check(message)
assert not TextMatchFilter().check(message, "привет")
assert not TextContainsFilter().check(message, "прив")
assert not TextStartsFilter().check(message, "прив")
assert not IsDigitFilter().check(message)
print("14 ok: текстовые фильтры на сообщении без текста дают False")

# 15. Подпись медиа: текстовые фильтры видят caption
message = make_message(text="подпись", attachments=[
    {"type": "image", "payload": {"url": "u", "token": "t"}}])
assert message.content_type == "photo" and message.caption == "подпись"
assert TextMatchFilter().check(message, "подпись")
print("15 ok: у медиа фильтры работают по подписи")

# 16. is_reply / is_forwarded различают типы link MAX
reply = make_message(link={"type": "reply", "message": {"mid": "mid.0", "seq": 0}})
forward = make_message(link={"type": "forward", "chat_id": 9,
                             "message": {"mid": "mid.0", "seq": 0}})
plain = make_message()
assert IsReplyFilter().check(reply) and not IsReplyFilter().check(forward)
assert ForwardFilter().check(forward) and not ForwardFilter().check(reply)
assert not IsReplyFilter().check(plain) and not ForwardFilter().check(plain)
# у пересылки reply_to_message тоже заполнен — телеботовская проверка
# "is not None" тут дала бы ложное срабатывание
assert forward.reply_to_message is not None
print("16 ok: is_reply и is_forwarded по link.type, а не по reply_to_message")

# 17. ChatFilter и LanguageFilter, в том числе у callback
message = make_message()
assert ChatFilter().check(message, [42]) and not ChatFilter().check(message, [1])
_, warnings = capture_warnings(lambda: ChatFilter().check(message, 42))
assert any("обернул" in w for w in warnings), warnings
call = CallbackQuery(callback_update(), FakeApi())
assert ChatFilter().check(call, [42])
assert not LanguageFilter().check(message, ["ru"])
message = make_message(user_locale="ru")
assert LanguageFilter().check(message, ["ru"]) and LanguageFilter().check(message, "ru")
print("17 ok: ChatFilter (в том числе у callback) и LanguageFilter")

# 18. IsAdminFilter ходит в API за статусом участника
api = FakeApi(members=[{"user_id": 7, "is_owner": True, "first_name": "u"}])
bot = make_bot(api)
message = Update(message_update(chat_type="chat"), api).message
assert IsAdminFilter(bot).check(message)
assert api.member_calls == [(42, (7,))], api.member_calls
api = FakeApi(members=[{"user_id": 7, "first_name": "u"}])
bot = make_bot(api)
message = Update(message_update(chat_type="chat"), api).message
assert not IsAdminFilter(bot).check(message)
print("18 ok: IsAdminFilter — get_chat_member, creator/administrator")

# 19. Фильтры у callback_query_handler проверяются ВСЕ, а не только data
bot = make_bot()
got = []


@bot.callback_query_handler(data="ok", func=lambda c: False)
def never(call):
    got.append("never")


@bot.callback_query_handler(data="ok")
def always(call):
    got.append("always")


bot._process_update(callback_update(payload="ok"))
assert got == ["always"], got
print("19 ok: у callback data и func проверяются вместе")

# 20. chat_types у callback берётся из сообщения с кнопкой
bot = make_bot()
got = []


@bot.callback_query_handler(data="ok", chat_types=["group"])
def in_group(call):
    got.append("group")


bot._process_update(callback_update(payload="ok"))
assert got == ["group"], got
print("20 ok: chat_types у callback смотрит на чат сообщения")

# 21. Сообщения без фильтров и с None-фильтрами не задевают кастом-путь
bot = make_bot()
got = []
bot.message_handler(func=None, commands=None)(lambda m: got.append(m.text))
_, warnings = capture_warnings(lambda: bot._process_update(message_update(text="привет")))
assert got == ["привет"], got
assert not any("не зарегистрирован" in w for w in warnings), warnings
print("21 ok: None-фильтры не считаются незнакомыми ключами")

# 22. Предупреждение о незнакомом фильтре не спамит в цикле
bot = make_bot()
bot.message_handler(unknown_key=True)(lambda m: None)
_, warnings = capture_warnings(
    lambda: [bot._process_update(message_update(text="раз")),
             bot._process_update(message_update(text="два"))])
# стартовая проверка ключей и ленивое предупреждение из диспатча —
# каждое по одному разу на четыре обновления
assert len([w for w in warnings if w.startswith("фильтры ")]) == 1, warnings
assert len([w for w in warnings if w.startswith("фильтр ")]) == 1, warnings
print("22 ok: предупреждения о незнакомом фильтре — по одному разу")

# 23. Фильтры по чату и админству работают на событиях членства
api = FakeApi(members=[{"user_id": 9, "is_admin": True, "first_name": "a"}])
bot = make_bot(api)
bot.add_custom_filter(ChatFilter())
bot.add_custom_filter(IsAdminFilter(bot))
got = []


@bot.chat_member_handler(chat_id=[42], is_chat_admin=True)
def added_by_admin(event):
    got.append((event.chat.id, event.from_user.real_id))


bot._process_update({"update_type": "user_added", "timestamp": 1751400000000,
                     "chat_id": 42, "user": USER, "inviter_id": 9})
assert got == [(42, 9)], got
assert api.member_calls == [(42, (9,))], api.member_calls
print("23 ok: chat_id и is_chat_admin работают на ChatMemberUpdated")

# 24. Статус 'administrator' (не только владелец) пускает IsAdminFilter
api = FakeApi(members=[{"user_id": 7, "is_admin": True, "first_name": "u"}])
bot = make_bot(api)
message = Update(message_update(chat_type="chat"), api).message
assert bot.get_chat_member(42, 7).status == "administrator"
assert IsAdminFilter(bot).check(message)
print("24 ok: администратор чата, а не только владелец")

# 25. Предупреждение ChatFilter об одиночном id — один раз на значение
bot = make_bot()
bot.add_custom_filter(ChatFilter())
bot.message_handler(chat_id=42)(lambda m: None)
_, warnings = capture_warnings(
    lambda: [bot._process_update(message_update(text=str(i))) for i in range(5)])
assert len([w for w in warnings if "обернул" in w]) == 1, warnings
print("25 ok: обёртка одиночного chat_id предупреждает один раз")

# 26. На старте бот проверяет ключи фильтров всех обработчиков
bot = make_bot()
bot.message_handler(is_digit=True)(lambda m: None)
bot.callback_query_handler(data="ok", text="привет")(lambda c: None)
bot.edited_message_handler(k_edited=True)(lambda m: None)
bot.channel_post_handler(k_post=True)(lambda m: None)
bot.edited_channel_post_handler(k_edited_post=True)(lambda m: None)
bot.my_chat_member_handler(k_my=True)(lambda e: None)
bot.chat_member_handler(k_member=True)(lambda e: None)
_, warnings = capture_warnings(bot._warn_unknown_filter_keys)
assert len(warnings) == 1, warnings
for key in ("'is_digit'", "'text'", "'k_edited'", "'k_post'",
            "'k_edited_post'", "'k_my'", "'k_member'"):
    assert key in warnings[0], (key, warnings)
# перезапуск поллинга (infinity_polling зовёт start в цикле) не должен
# повторять ту же строку — иначе на обрыве сети лог зальёт
bot = make_bot()
bot.message_handler(is_digit=True)(lambda m: None)
_, warnings = capture_warnings(lambda: [bot._warn_unknown_filter_keys(),
                                        bot._warn_unknown_filter_keys(),
                                        bot._warn_unknown_filter_keys()])
assert len(warnings) == 1, warnings

# после регистрации всех ключей предупреждать не о чем
bot = make_bot()
bot.message_handler(is_digit=True)(lambda m: None)
bot.callback_query_handler(data="ok", text="привет")(lambda c: None)
bot.add_custom_filter(IsDigitFilter())
bot.add_custom_filter(TextMatchFilter())
_, warnings = capture_warnings(bot._warn_unknown_filter_keys)
assert warnings == [], warnings
# проверка ключей должна стоять на обоих стартах — и в поллинге,
# и в вебхуке (иначе половина ботов диагностику не увидит)
for starter in (MaxiBot.start, MaxiBot.start_webhook):
    assert "_warn_unknown_filter_keys" in inspect.getsource(starter), starter.__name__

# у своего цикла (get_updates + process_new_updates) и своей
# webhook-интеграции старта нет — проверка должна случиться лениво
bot = make_bot()
bot.message_handler(func=lambda m: True)(lambda m: None)
bot.message_handler(is_digit=True)(lambda m: None)
_, warnings = capture_warnings(
    lambda: bot.process_new_updates([message_update(text="раз"),
                                     message_update(text="два")]))
assert len([w for w in warnings if w.startswith("фильтры ")]) == 1, warnings
# регистрация фильтра после старта — повод проверить ключи заново
bot = make_bot()
bot.message_handler(is_digit=True)(lambda m: None)
bot._warn_unknown_filter_keys()
bot.add_custom_filter(IsDigitFilter())
assert bot._filter_keys_checked is False
_, warnings = capture_warnings(
    lambda: bot.process_new_updates([message_update(text="1")]))
assert not any(w.startswith("фильтры ") for w in warnings), warnings
print("26 ok: незарегистрированные ключи видны на старте и на первом обновлении")

# 27. Фильтр со значением None пропускается (handler_dict руками)
bot = make_bot()
got = []
bot.add_channel_post_handler({"function": lambda m: got.append(m.text),
                              "pass_bot": False,
                              "filters": {"func": None, "unknown_key": None}})
_, warnings = capture_warnings(
    lambda: bot._process_update(message_update(text="пост", chat_type="channel")))
assert got == ["пост"], got
assert not any("не зарегистрирован" in w for w in warnings), warnings
print("27 ok: None-значение фильтра пропускается, а не считается ключом")

# 28. bot_added: тип чата берётся из is_channel, а не остаётся None
message = Update({"update_type": "bot_added", "timestamp": 1751400000000,
                  "chat_id": 42, "user": USER, "is_channel": True}, FakeApi()).message
assert message.chat.type == "channel" and message.chat.max_type == "channel"
message = Update({"update_type": "bot_added", "timestamp": 1751400000000,
                  "chat_id": 42, "user": USER, "is_channel": False}, FakeApi()).message
assert message.chat.type == "group" and message.chat.max_type == "chat"
# добавление бота в канал — не пост канала: Message идёт обычным
# путём, в message_handler (иначе приветствие бота молча пропало бы)
bot = make_bot()
got = []
bot.message_handlers.append(MaxiBot._build_handler_dict(
    lambda m: got.append(("message", m.chat.type))))
bot.add_channel_post_handler(MaxiBot._build_handler_dict(
    lambda m: got.append(("channel_post", m.chat.type))))
bot._process_update({"update_type": "bot_added", "timestamp": 1751400000000,
                     "chat_id": 42, "user": USER, "is_channel": True})
assert got == [("message", "channel")], got
# а настоящий пост канала по-прежнему только в канальные обработчики
bot._process_update(message_update(text="пост", chat_type="channel"))
assert got[-1] == ("channel_post", "channel"), got
print("28 ok: bot_added знает тип чата по is_channel и не считается постом")

# 29. Результат edit_*: тип чата неизвестен, а не выдуманный 'private'
from maxibot.util import get_edit_message_data

edited = Message(update=get_edit_message_data("новый текст", 42, "mid.1", [],
                                             1751400000000), api=FakeApi())
assert edited.chat.type is None and edited.chat.max_type is None
assert edited.from_user.language_code is None
print("29 ok: у результата edit_* тип чата и локаль None, а не выдуманные")

# 30. content_types строкой не роняет обновление и не матчит по подстроке
bot = make_bot()
got = []
bot.callback_query_handler(data="ok", content_types="text")(
    lambda c: got.append("callback"))
_, warnings = capture_warnings(
    lambda: bot._process_update(callback_update(payload="ok")))
assert got == [], got
assert not any("Error" in w for w in warnings), warnings
handler = {"function": lambda m: got.append("msg"), "pass_bot": False,
           "filters": {"content_types": "text_and_more"}}
bot.message_handlers.append(handler)
bot._process_update(message_update(text="привет"))
assert got == [], got
print("30 ok: строковый content_types не роняет обновление и не матчит подстрокой")

# 31. add_custom_filter: занятый встроенный ключ, нестроковый ключ, замена
bot = make_bot()


class FuncKeyFilter(SimpleCustomFilter):
    key = "func"

    def check(self, message):
        return True


_, warnings = capture_warnings(lambda: bot.add_custom_filter(FuncKeyFilter()))
assert any("занят встроенным" in w for w in warnings), warnings


class IntKeyFilter(SimpleCustomFilter):
    key = 42

    def check(self, message):
        return True


_, warnings = capture_warnings(lambda: bot.add_custom_filter(IntKeyFilter()))
assert any("должен быть строкой" in w for w in warnings), warnings
assert 42 not in bot.custom_filters

bot = make_bot()
bot.add_custom_filter(IsDigitFilter())
_, warnings = capture_warnings(lambda: bot.add_custom_filter(IsDigitFilter()))
assert any("уже занят фильтром" in w for w in warnings), warnings
same = IsDigitFilter()
bot.add_custom_filter(same)
_, warnings = capture_warnings(lambda: bot.add_custom_filter(same))
assert not any("уже занят" in w for w in warnings), warnings
print("31 ok: add_custom_filter предупреждает о занятом и нестроковом ключе")

# 32. Фильтр не того типа сообщает о себе один раз, а не на каждое обновление
bot = make_bot()


class Duck2:
    key = "duck2"

    def check(self, message):
        return True


capture_warnings(lambda: bot.add_custom_filter(Duck2()))
bot.message_handler(duck2=True)(lambda m: None)
capture = LogCapture()
logging.getLogger("maxibot").addHandler(capture)
try:
    for _ in range(3):
        bot._process_update(message_update(text="кря"))
finally:
    logging.getLogger("maxibot").removeHandler(capture)
messages = [r.getMessage() for r in capture.records if "не наследует" in r.getMessage()]
assert len(messages) == 1, messages
assert "'duck2'" in messages[0] and "Duck2" in messages[0], messages
print("32 ok: фильтр не того типа сообщает о себе один раз и по имени")

print("ALL OK")

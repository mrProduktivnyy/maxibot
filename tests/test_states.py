"""
FSM-состояния: State/StatesGroup, хранилища maxibot.storage,
методы set_state/get_state/delete_state/add_data/retrieve_data/
reset_data/enable_saving_states и StateFilter.

Запуск:
    python3 tests/test_states.py
"""
import inspect
import logging
import os
import pickle
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import telebot
import telebot.storage as telebot_storage
from telebot.handler_backends import State as TState, StatesGroup as TStatesGroup
from telebot.custom_filters import StateFilter as TStateFilter

import maxibot
from maxibot import MaxiBot
from maxibot import custom_filters
from maxibot.custom_filters import StateFilter
from maxibot.handler_backends import State, StatesGroup
from maxibot.storage import (
    StateContext,
    StateMemoryStorage,
    StatePickleStorage,
    StateRedisStorage,
    StateStorageBase,
)
from maxibot.types import Update


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
    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot(**kwargs):
    bot = MaxiBot("t", threaded=False, **kwargs)
    bot.api = FakeApi()
    return bot


USER = {"user_id": 7, "is_bot": False, "first_name": "u", "name": "u"}


def message_update(text="привет", chat_type="dialog"):
    return {
        "update_type": "message_created",
        "timestamp": 1751400000000,
        "message": {
            "sender": USER,
            "recipient": {"chat_id": 42, "chat_type": chat_type, "user_id": 7},
            "timestamp": 1751400000000,
            "body": {"mid": "mid.1", "seq": 1, "text": text},
        },
    }


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


# 1. Сигнатуры методов бота и состав пакета как в telebot
for name in ("set_state", "get_state", "delete_state", "add_data",
             "retrieve_data", "reset_data", "enable_saving_states"):
    ours = inspect.signature(getattr(MaxiBot, name))
    theirs = inspect.signature(getattr(telebot.TeleBot, name))
    assert list(ours.parameters) == list(theirs.parameters), name
    for p_name, p in theirs.parameters.items():
        assert ours.parameters[p_name].default == p.default, (name, p_name)
assert "state_storage" in inspect.signature(MaxiBot.__init__).parameters
# верхний уровень — как у telebot (State и хранилища), StatesGroup бонусом
for name in ("State", "StateMemoryStorage", "StatePickleStorage",
             "StateStorageBase"):
    assert hasattr(telebot, name) and hasattr(maxibot, name), name
assert maxibot.State is State and maxibot.StatesGroup is StatesGroup
# у хранилищ есть все публичные методы соответствующих классов telebot
for ours_cls, theirs_cls in (
    (StateMemoryStorage, telebot_storage.StateMemoryStorage),
    (StatePickleStorage, telebot_storage.StatePickleStorage),
    (StateRedisStorage, telebot_storage.StateRedisStorage),
    (StateStorageBase, telebot_storage.StateStorageBase),
    (StateContext, telebot_storage.StateContext),
):
    missing = [m for m in dir(theirs_cls)
               if not m.startswith("_") and not hasattr(ours_cls, m)]
    assert not missing, (ours_cls.__name__, missing)
assert StateFilter.key == TStateFilter.key == "state"
assert (list(inspect.signature(StateFilter.check).parameters)
        == list(inspect.signature(TStateFilter.check).parameters))
print("1 ok: сигнатуры и состав как в telebot")


# 2. State/StatesGroup: имена — дифференциально против telebot
class MyStates(StatesGroup):
    name = State()
    age = State()


class TheirStates(TStatesGroup):
    name = TState()
    age = TState()


assert MyStates.name.name == "MyStates:name"
assert TheirStates.name.name == "TheirStates:name"
assert MyStates.age.name == "MyStates:age" and TheirStates.age.name == "TheirStates:age"
assert str(MyStates.name) == "MyStates:name"
assert MyStates.name.group is MyStates
assert MyStates._state_list == [MyStates.name, MyStates.age]
assert State().name is None
print("2 ok: State/StatesGroup именуются как в telebot")

# 3. Память: одинаковая последовательность операций против telebot
ours, theirs = StateMemoryStorage(), telebot_storage.StateMemoryStorage()
script = [
    ("get_state", (1, 2)),
    ("set_state", (1, 2, "a")),
    ("get_state", (1, 2)),
    ("set_state", (1, 2, MyStates.name)),      # State → его имя
    ("get_state", (1, 2)),
    ("set_state", (1, 2, 5)),                  # число хранится числом
    ("get_state", (1, 2)),
    ("set_data", (1, 2, "k", "v")),
    ("get_data", (1, 2)),
    ("set_state", (1, 2, "дальше")),           # смена состояния данные не трёт
    ("get_data", (1, 2)),
    ("reset_data", (1, 2)),
    ("get_data", (1, 2)),
    ("delete_state", (1, 2)),
    ("get_state", (1, 2)),
    ("delete_state", (1, 2)),                  # повторно — False
    ("set_state", (3, 3, "x")),                # chat_id == user_id
    ("delete_state", (3, 3)),
    ("reset_data", (9, 9)),                    # записи нет — False
]
for method, args in script:
    a = getattr(ours, method)(*args)
    b = getattr(theirs, method)(*args)
    assert a == b, (method, args, a, b)
assert ours.data == theirs.data
# set_data без записи — RuntimeError у обоих
for st in (ours, theirs):
    try:
        st.set_data(8, 8, "k", "v")
        assert False, "ожидался RuntimeError"
    except RuntimeError:
        pass
# save без записи — KeyError у обоих
for st in (ours, theirs):
    try:
        st.save(8, 8, {"k": "v"})
        assert False, "ожидался KeyError"
    except KeyError:
        pass
print("3 ok: память — операция в операцию с telebot")

# 4. Методы бота: дефолт chat_id=user_id, State→строка, add_data/reset_data
bot = make_bot()
assert bot.get_state(7) is None
bot.set_state(7, MyStates.name)
assert bot.get_state(7) == "MyStates:name"
assert bot.get_state(7, 7) == "MyStates:name"       # (7) и (7, 7) — одна запись
assert bot.get_state(7, 42) is None                 # другой чат — другая запись
bot.set_state(7, "шаг2", 42)
assert bot.get_state(7, 42) == "шаг2"
bot.add_data(7, 42, name="Ася", age=3)
with bot.retrieve_data(7, 42) as data:
    assert data == {"name": "Ася", "age": 3}
bot.reset_data(7, 42)
with bot.retrieve_data(7, 42) as data:
    assert data == {}
bot.delete_state(7, 42)
assert bot.get_state(7, 42) is None
assert bot.get_state(7) == "MyStates:name"          # личка не задета
bot.add_data(7, marker="жив")
bot.set_state(7, MyStates.age)                       # переход состояния
assert bot.get_state(7) == "MyStates:age"
with bot.retrieve_data(7) as data:
    assert data == {"marker": "жив"}                 # данные пережили переход
bot.reset_data(7)                                    # одноаргументная форма
with bot.retrieve_data(7) as data:
    assert data == {}
bot.delete_state(7)                                  # одноаргументная форма
assert bot.get_state(7) is None
try:
    bot.add_data(100, x=1)                           # состояния нет
    assert False, "ожидался RuntimeError"
except RuntimeError:
    pass
print("4 ok: методы бота работают по паре (chat_id, user_id)")

# 5. retrieve_data: копия на входе, запись на выходе, изоляция
bot = make_bot()
bot.set_state(7, "s")
bot.add_data(7, tags=["a"])
with bot.retrieve_data(7) as data:
    data["tags"].append("b")
    data["n"] = 1
    # до выхода из блока хранилище не тронуто (deepcopy, как в telebot)
    assert bot.current_states.get_data(7, 7) == {"tags": ["a"]}
assert bot.current_states.get_data(7, 7) == {"tags": ["a", "b"], "n": 1}
# записи нет — data None, выход из блока падает (как в telebot)
try:
    with bot.retrieve_data(999) as data:
        assert data is None
    assert False, "ожидался KeyError"
except KeyError:
    pass
print("5 ok: retrieve_data — контекст-менеджер с копией")

# 6. Pickle: переживает пересоздание, файл без папки, конвертация старого
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "sub", "states.pkl")
st = StatePickleStorage(file_path=path)
st.set_state(1, 2, MyStates.age)
st.set_data(1, 2, "k", "v")
st.set_state(1, 2, "дальше")                       # переход не трёт данные
st2 = StatePickleStorage(file_path=path)
assert st2.get_state(1, 2) == "дальше"
assert st2.get_data(1, 2) == {"k": "v"}
cwd = os.getcwd()
os.chdir(tmp)
try:
    bare = StatePickleStorage(file_path="bare.pkl")   # в telebot тут makedirs('')
    bare.set_state(5, 5, "x")
    assert StatePickleStorage(file_path="bare.pkl").get_state(5, 5) == "x"
finally:
    os.chdir(cwd)
old_path = os.path.join(tmp, "old.pkl")
with open(old_path, "wb") as f:
    pickle.dump({1: {"state": "start", "data": {"n": "J"}}}, f)
st3 = StatePickleStorage(file_path=old_path)
st3.convert_old_to_new()
assert st3.get_state(1, 1) == "start" and st3.get_data(1, 1) == {"n": "J"}
print("6 ok: pickle-хранилище")

# 7. enable_saving_states подменяет хранилище на pickle
bot = make_bot()
assert isinstance(bot.current_states, StateMemoryStorage)
bot.enable_saving_states(os.path.join(tmp, "enab", "st.pkl"))
assert isinstance(bot.current_states, StatePickleStorage)
bot.set_state(7, "x")
assert StatePickleStorage(os.path.join(tmp, "enab", "st.pkl")).get_state(7, 7) == "x"
print("7 ok: enable_saving_states")

# 8. Дефолтное хранилище у каждого бота своё (в telebot — одно на всех)
b1, b2 = make_bot(), make_bot()
b1.set_state(7, "x")
assert b2.get_state(7) is None
assert b1.current_states is not b2.current_states
t_default = inspect.signature(telebot.TeleBot.__init__).parameters["state_storage"].default
assert isinstance(t_default, telebot_storage.StateMemoryStorage)  # у telebot — общий объект
custom = StateMemoryStorage()
b3 = make_bot(state_storage=custom)
assert b3.current_states is custom
print("8 ok: хранилище на экземпляр, свой state_storage принимается")

# 9. StateFilter через диспатч: State/строка/список/число/'*'
bot = make_bot()
bot.add_custom_filter(StateFilter(bot))
fired = []

@bot.message_handler(state=MyStates.name)
def h_name(m):
    fired.append("name")

@bot.message_handler(state=[MyStates.age, "другое"])
def h_list(m):
    fired.append("list")

@bot.message_handler(state=5)
def h_int(m):
    fired.append("int")

@bot.message_handler(state="*")
def h_star(m):
    fired.append("star")

@bot.message_handler(content_types=["text"])
def h_rest(m):
    fired.append("rest")

def push():
    fired.clear()
    bot.process_new_updates([message_update()])
    return list(fired)

# состояния нет: State/список/число мимо, '*' совпадает
assert push() == ["star"]
# канонический телеботовский паттерн: from_user.id и chat.id (оба 42)
bot.set_state(42, MyStates.name, 42)
assert push() == ["name"]
bot.set_state(42, MyStates.age, 42)
assert push() == ["list"]
bot.set_state(42, "другое", 42)
assert push() == ["list"]
bot.set_state(42, 5, 42)
assert push() == ["int"]
bot.set_state(42, "не то", 42)
assert push() == ["star"]
bot.delete_state(42, 42)
assert push() == ["star"]
print("9 ok: StateFilter — State, список, число, '*'")

# 10. state=None — фильтр выключен (как в telebot None-kwargs отпадают)
bot = make_bot()
bot.add_custom_filter(StateFilter(bot))
fired = []

@bot.message_handler(state=None)
def h_none(m):
    fired.append("none")

bot.process_new_updates([message_update()])
assert fired == ["none"]
print("10 ok: state=None не фильтрует")

# 11. StateFilter на CallbackQuery: чат из сообщения, пользователь из колбэка
bot = make_bot()
bot.add_custom_filter(StateFilter(bot))
fired = []

@bot.callback_query_handler(func=lambda c: True, state="жду")
def h_cb(c):
    fired.append("cb")

bot.process_new_updates([callback_update()])
assert fired == []
bot.set_state(42, "".join(["ж", "д", "у"]), 42)   # рантайм-строка: == а не is
bot.process_new_updates([callback_update()])
assert fired == ["cb"]
print("11 ok: StateFilter на колбэке")

# 12. Чужой контекст: у telebot падал UnboundLocalError, у нас False; '*' — True
f = StateFilter(make_bot())
assert f.check(object(), "x") is False
assert f.check(object(), "*") is True                 # как в telebot: '*' до всего
cb_no_msg = Update(callback_update(), FakeApi()).callback_query
cb_no_msg.message = None
assert f.check(cb_no_msg, "x") is False
# пост от имени канала: from_user нет — фильтр не совпадает, не падает
post = message_update(chat_type="channel")
post["message"]["sender"] = None
channel_msg = Update(post, FakeApi()).message
assert channel_msg.from_user is None
assert f.check(channel_msg, "x") is False
assert f.check(channel_msg, "*") is True
print("12 ok: не-Message контекст и пост канала не роняют фильтр")

# 13. Ключ state без add_custom_filter — предупреждение, обработчик молчит
bot = make_bot()
fired = []

@bot.message_handler(state="x")
def h_unreg(m):
    fired.append("bad")

_, warns = capture_warnings(lambda: bot.process_new_updates([message_update()]))
assert fired == []
assert any("state" in w for w in warns), warns
print("13 ok: незарегистрированный state предупреждает")

# 14. Redis-хранилище на поддельном клиенте: строковые user_id внутри
import maxibot.storage.redis_storage as redis_module


class FakeRedis:
    store = {}

    def __init__(self, connection_pool=None):
        pass

    def get(self, key):
        return FakeRedis.store.get(key)

    def set(self, key, value):
        FakeRedis.store[key] = value

    def delete(self, key):
        FakeRedis.store.pop(key, None)

    def close(self):
        pass


class FakeConnectionPool:
    def __init__(self, **kwargs):
        pass

    @classmethod
    def from_url(cls, url):
        return cls()


redis_module.redis_installed, redis_module.Redis, redis_module.ConnectionPool = (
    True, FakeRedis, FakeConnectionPool)
rs = StateRedisStorage(prefix="t_")
assert rs.get_state(1, 2) is None
rs.set_state(1, 2, MyStates.name)
assert rs.get_state(1, 2) == "MyStates:name"
assert "t_1" in FakeRedis.store                       # ключ — префикс + chat_id
rs.set_data(1, 2, "k", "v")
assert rs.get_data(1, 2) == {"k": "v"}
assert rs.get_value(1, 2, "k") == "v" and rs.get_value(1, 2, "нет") is None
assert rs.set_data(9, 9, "k", "v") is False           # без записи — False, не ошибка
rs.reset_data(1, 2)
assert rs.get_data(1, 2) == {}
with rs.get_interactive_data(1, 2) as data:
    data["a"] = 1
assert rs.get_data(1, 2) == {"a": 1}
# исключение внутри with НЕ глотается (в telebot redis-save возвращал
# True из __exit__ и глотал)
try:
    with rs.get_interactive_data(1, 2) as data:
        raise ValueError("боль")
    assert False, "ожидался ValueError"
except ValueError:
    pass
assert rs.delete_state(1, 2) is True and rs.get_state(1, 2) is None
rs.set_state(3, 3, "x")
assert rs.delete_state(3, 3) is True and "t_3" not in FakeRedis.store
bot_r = make_bot(state_storage=StateRedisStorage())
bot_r.set_state(7, "через бота")
assert bot_r.get_state(7) == "через бота"
print("14 ok: redis-хранилище на поддельном клиенте")

# 15. Хранилище в группе: у всех участников from_user.id == chat.id —
# состояние общее на чат (задокументированное отличие от telebot)
bot = make_bot()
bot.add_custom_filter(StateFilter(bot))
fired = []

@bot.message_handler(state="опрос")
def h_poll(m):
    fired.append(m.from_user.id)

@bot.message_handler(content_types=["text"])
def h_other(m):
    fired.append("мимо")

bot.set_state(42, "опрос", 42)
bot.process_new_updates([message_update(chat_type="chat")])
other_user = dict(USER, user_id=8, first_name="v")
upd = message_update(chat_type="chat")
upd["message"]["sender"] = other_user
bot.process_new_updates([upd])
assert fired == [42, 42]                              # оба участника в одном состоянии
print("15 ok: в группе состояние на чат (см. docs/states.md)")

print("ALL OK")

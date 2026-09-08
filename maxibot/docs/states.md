# Состояния FSM

Машина состояний — как в telebot: `State`/`StatesGroup` из
`maxibot.handler_backends`, хранилища из `maxibot.storage`, методы
`set_state`/`get_state`/`delete_state`/`add_data`/`retrieve_data`/
`reset_data` у бота и фильтр `state=` через
`maxibot.custom_filters.StateFilter`. Телеботовский код переезжает
заменой импортов.

## Быстрый пример (анкета в личке)

```python
from maxibot import MaxiBot
from maxibot import custom_filters
from maxibot.handler_backends import State, StatesGroup

bot = MaxiBot(TOKEN)
bot.add_custom_filter(custom_filters.StateFilter(bot))  # не забыть, как и в telebot
bot.add_custom_filter(custom_filters.IsDigitFilter())   # для is_digit ниже

class Form(StatesGroup):
    name = State()
    age = State()

@bot.message_handler(commands=['start'])
def start(message):
    bot.set_state(message.from_user.id, Form.name, message.chat.id)
    bot.send_message(message.chat.id, "Как вас зовут?")

@bot.message_handler(state=Form.name)
def got_name(message):
    bot.add_data(message.from_user.id, message.chat.id, name=message.text)
    bot.set_state(message.from_user.id, Form.age, message.chat.id)
    bot.send_message(message.chat.id, "Сколько вам лет?")

@bot.message_handler(state=Form.age, is_digit=True)
def got_age(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        bot.send_message(message.chat.id, f"{data['name']}, {message.text} — записал")
    bot.delete_state(message.from_user.id, message.chat.id)
```

## Хранилища (maxibot.storage)

* **StateMemoryStorage** — по умолчанию, живёт до рестарта процесса.
* **StatePickleStorage** (`file_path='./.state-save/states.pkl'`) —
  каждая запись сразу на диск, состояния переживают рестарт. Включается
  через `MaxiBot(state_storage=StatePickleStorage())` либо
  `bot.enable_saving_states()` (второе подменяет хранилище на лету —
  уже накопленные состояния прежнего теряются, как в telebot).
* **StateRedisStorage** (`host/port/db/password/prefix` или
  `redis_url`) — нужен `pip install redis`. Внутри записи user_id
  строковый (наследие telebot), а `set_data` без записи возвращает
  False вместо RuntimeError других хранилищ — тоже как в telebot.
* **StateStorageBase** — база для своего хранилища: реализовать
  set_state/get_state/delete_state/set_data/get_data/reset_data/
  get_interactive_data/save.

Запись ключуется парой **(chat_id, user_id)**; методы бота без
`chat_id` берут `chat_id = user_id` — «состояние в личке».

## Чем maxibot отличается от telebot

* **Хранилище по умолчанию — своё у каждого бота.** В telebot дефолт —
  изменяемый аргумент в сигнатуре: один StateMemoryStorage на все
  экземпляры TeleBot процесса, два бота видят и трут состояния друг
  друга. В maxibot каждый MaxiBot получает собственное хранилище.
* **В группе состояние общее на чат.** В maxibot
  `message.from_user.id` — это id ЧАТА (настоящий id пользователя — в
  `from_user.real_id`), поэтому канонический паттерн
  `set_state(message.from_user.id, ..., message.chat.id)` в группе
  ключует запись парой (чат, чат): одно состояние на всех участников.
  В личках — ровно как в telebot (там тоже chat.id == from_user.id).
  Раздельные состояния участников группы стандартным StateFilter не
  сделать — проверяйте вручную (`func=`) по `from_user.real_id`.
* **Исключение внутри `with retrieve_data(...)` не глотается.** В
  telebot с Redis-хранилищем `save` возвращал True из `__exit__`, и
  ошибка в блоке молча пропадала.
* **`StatePickleStorage('states.pkl')` без папки в пути работает** —
  в telebot падал `makedirs('')`.
* **StateFilter на событии членства просто не совпадает** — в telebot
  падал UnboundLocalError.

## StateFilter

Значение `state=` — State, строка, число, список таких или `'*'`
(совпадает всегда, даже когда состояния нет). `state=None` — фильтра
нет. Работает у всех обработчиков с кастом-фильтрами: сообщения,
правки, посты каналов, колбэки (чат берётся из сообщения с
клавиатурой). Без `bot.add_custom_filter(StateFilter(bot))` ключ
`state` не работает — maxibot напишет об этом в лог (telebot молчал).

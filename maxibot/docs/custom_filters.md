# Custom filters
## Модуль maxibot.custom_filters
Кастом-фильтры — как `telebot.custom_filters`. Фильтр это класс с полем `key` и методом `check`; зарегистрированный через `bot.add_custom_filter(...)` ключ пишется именованным аргументом обработчика (`@bot.message_handler(is_digit=True)`). Ничего не регистрируется само — как в telebot, нужный фильтр включает сам бот:
```python
from maxibot import MaxiBot
from maxibot.custom_filters import IsDigitFilter, TextStartsFilter

bot = MaxiBot("TOKEN")
bot.add_custom_filter(IsDigitFilter())
bot.add_custom_filter(TextStartsFilter())

@bot.message_handler(is_digit=True)
def digits(message):
    bot.reply_to(message, "это число")

@bot.message_handler(text_startswith="куп")
def buy(message):
    bot.reply_to(message, "оформляем")
```
Незарегистрированный ключ обработчик не пропустит, и maxibot скажет об этом в лог (в telebot такой обработчик молча не срабатывал). Кастом-фильтры работают у всех обработчиков: сообщений, правок, постов каналов, коллбэков и событий членства. Ошибка внутри фильтра не роняет диспатч — она уходит в `exception_handler`, обработчик считается несовпавшим (как у `func`).

**Базовые классы:**
* **SimpleCustomFilter** - `check(message)` возвращает bool, который СРАВНИВАЕТСЯ со значением из обработчика: `is_digit=False` матчит нечисловые сообщения  
* **AdvancedCustomFilter** - `check(message, value)` получает значение фильтра из обработчика  

**Готовые фильтры (ключ = имя аргумента обработчика):**
* **TextMatchFilter** (`text`) - Текст совпадает со строкой, входит в список или проходит `TextFilter`  
* **TextContainsFilter** (`text_contains`) - Текст содержит строку (или любую из списка)  
* **TextStartsFilter** (`text_startswith`) - Текст начинается со строки (или с любой из списка — расширение относительно telebot, где только строка)  
* **ChatFilter** (`chat_id`) - Идентификатор чата в списке; одиночный id оборачивается в список с предупреждением (в telebot падал TypeError)  
* **ForwardFilter** (`is_forwarded`) - Сообщение переслано: в MAX это `link.type == 'forward'` (телеботовского `forward_date` у сообщения нет)  
* **IsReplyFilter** (`is_reply`) - Сообщение — ответ: `link.type == 'reply'`. Проверять `reply_to_message is not None`, как в telebot, нельзя: в MAX ответ и пересылка лежат в одном поле  
* **LanguageFilter** (`language_code`) - Язык пользователя (в MAX приходит в `user_locale` и есть не у всех событий)  
* **IsAdminFilter** (`is_chat_admin`) - Пользователь — владелец или админ чата. Создаётся с ботом: `IsAdminFilter(bot)`. Каждая проверка — запрос к API, и участники в MAX видны только администраторам: если бот не админ, запрос упадёт и обработчик не сработает  
* **IsDigitFilter** (`is_digit`) - Текст состоит только из цифр  

**TextFilter** (`equals`, `contains`, `starts_with`, `ends_with`, `ignore_case`) — значение для `text=`: `@bot.message_handler(text=TextFilter(contains=['счёт', 'аккаунт'], ignore_case=True))`. Отличия от telebot: `ignore_case` снимает регистр со ВСЕХ заданных условий (в telebot из-за `elif` — только с первого) и не портит сам фильтр; сообщение без текста даёт False, а не AttributeError.

Текст берётся так же, как в telebot: у сообщения — `text`, а если его нет, `caption` (у медиа MAX подпись лежит в обоих полях), у callback — `data`. Сообщение без текста (стикер, файл без подписи) текстовые фильтры не роняют — они просто не совпадают.

**Свой фильтр:**
```python
from maxibot.custom_filters import SimpleCustomFilter

class IsGroupFilter(SimpleCustomFilter):
    key = 'is_group'

    def check(self, message):
        return message.chat.type == 'group'

bot.add_custom_filter(IsGroupFilter())

@bot.message_handler(is_group=True, commands=['stats'])
def stats(message):
    ...
```

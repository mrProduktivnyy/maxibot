# CallbackData
## module maxibot.callback_data
Фабрика callback data — как `telebot.callback_data`, переезжает заменой слова: `from maxibot.callback_data import CallbackData`. Payload колбэка в MAX — тоже строка, фабрика работает без изменений; лимит длины — **1024 символа** по спеке MAX (`CallbackButton.payload maxLength`) против телеграмных 64 байт (константа `MAX_PAYLOAD_LEN`).

```python
from maxibot.callback_data import CallbackData

products_factory = CallbackData('product_id', prefix='products')

data = products_factory.new(product_id=1)   # 'products:1'
parsed = products_factory.parse(data)       # {'@': 'products', 'product_id': '1'}
```

## class CallbackData(*parts, prefix, sep=':')
* **new** (`*args`, `**kwargs`) - Сборка callback data из значений частей; `ValueError` при разделителе в значении, пропущенной части или длине больше лимита, `TypeError` при лишних аргументах
* **parse** (`callback_data`) - Разбор строки обратно в словарь (`префикс — под ключом '@'`); `ValueError` при чужом префиксе или не том числе частей
* **filter** (`**config`) - Собирает `CallbackDataFilter` по значениям частей (значение-список — «любое из»); `ValueError` при неизвестном имени части

## class CallbackDataFilter(factory, config)
* **check** (`query`) - `True`, если `query.data` разбирается фабрикой и части совпадают с config (скаляры — равенством, списки — вхождением)

Подключение к обработчикам — через кастом-фильтр, как в telebot:
```python
from maxibot import MaxiBot
from maxibot.custom_filters import AdvancedCustomFilter

class ProductsCallbackFilter(AdvancedCustomFilter):
    key = 'config'
    def check(self, call, config):
        return config.check(query=call)

bot.add_custom_filter(ProductsCallbackFilter())

@bot.callback_query_handler(func=None, config=products_factory.filter(product_id='1'))
def product_one(call):
    ...
```

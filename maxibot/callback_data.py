"""
Фабрика callback data — как telebot.callback_data: телеботовский импорт
переезжает заменой одного слова:

.. code-block:: python3

    from maxibot.callback_data import CallbackData

    products_factory = CallbackData('product_id', prefix='products')
    data = products_factory.new(product_id=1)       # 'products:1'
    parsed = products_factory.parse(data)           # {'@': 'products', 'product_id': '1'}

Payload колбэка в MAX — тоже строка (CallbackButton.payload), так что
фабрика портируется без изменений; отличается только лимит длины:
у MAX это 1024 символа против телеграмных 64 байт.
"""

# Код телеботовского telebot/callback_data.py (сам скопирован в telebot
# из aiogram); уведомление об авторских правах — по лицензии оригинала:
#
# Copyright (c) 2017-2018 Alex Root Junior
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the
# following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies
# or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
# PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
# OR OTHER DEALINGS IN THE SOFTWARE.

import typing

# лимит CallbackButton.payload по спеке MAX (maxLength: 1024);
# у Telegram callback_data ограничен 64 байтами - здесь просторнее
MAX_PAYLOAD_LEN = 1024


class CallbackDataFilter:
    """
    Фильтр для CallbackData — проверяет callback.data по заданным
    значениям частей. Используется в связке с кастом-фильтром
    (AdvancedCustomFilter с key='config'), как в telebot.
    """

    def __init__(self, factory, config: typing.Dict[str, str]):
        self.config = config
        self.factory = factory

    def check(self, query) -> bool:
        """
        Проверяет, подходит ли query.data под указанный config

        :param query: Колбэк
        :type query: maxibot.types.CallbackQuery

        :return: True, если query.data соответствует config
        :rtype: bool
        """
        try:
            data = self.factory.parse(query.data)
        except ValueError:
            return False

        for key, value in self.config.items():
            if isinstance(value, (list, tuple, set, frozenset)):
                if data.get(key) not in value:
                    return False
            elif data.get(key) != value:
                return False
        return True


class CallbackData:
    """
    Фабрика callback data — собирает и разбирает payload
    callback-кнопок по схеме 'prefix:часть1:часть2:...'.
    """

    def __init__(self, *parts, prefix: str, sep=':'):
        if not isinstance(prefix, str):
            raise TypeError(f'Prefix must be instance of str not {type(prefix).__name__}')
        if not prefix:
            raise ValueError("Prefix can't be empty")
        if sep in prefix:
            raise ValueError(f"Separator {sep!r} can't be used in prefix")

        self.prefix = prefix
        self.sep = sep

        self._part_names = parts

    def new(self, *args, **kwargs) -> str:
        """
        Собирает callback data из значений частей

        :param args: Значения частей по порядку
        :param kwargs: Значения частей по именам
        :return: str
        """
        args = list(args)

        data = [self.prefix]

        for part in self._part_names:
            value = kwargs.pop(part, None)
            if value is None:
                if args:
                    value = args.pop(0)
                else:
                    raise ValueError(f'Value for {part!r} was not passed!')

            if value is not None and not isinstance(value, str):
                value = str(value)

            if self.sep in value:
                raise ValueError(f"Symbol {self.sep!r} is defined as the separator and can't be used in parts' values")

            data.append(value)

        if args or kwargs:
            raise TypeError('Too many arguments were passed!')

        callback_data = self.sep.join(data)

        if len(callback_data.encode()) > MAX_PAYLOAD_LEN:
            raise ValueError('Resulted callback data is too long!')

        return callback_data

    def parse(self, callback_data: str) -> typing.Dict[str, str]:
        """
        Разбирает callback data обратно в словарь частей

        :param callback_data: Строка из CallbackQuery.data
        :return: Словарь частей (префикс — под ключом '@')
        """
        prefix, *parts = callback_data.split(self.sep)
        if prefix != self.prefix:
            raise ValueError("Passed callback data can't be parsed with that prefix.")
        elif len(parts) != len(self._part_names):
            raise ValueError('Invalid parts count!')

        result = {'@': prefix}
        result.update(zip(self._part_names, parts))
        return result

    def filter(self, **config) -> CallbackDataFilter:
        """
        Собирает фильтр по значениям частей

        :param config: Именованные части для сверки с CallbackQuery.data
        :return: CallbackDataFilter
        """
        for key in config.keys():
            if key not in self._part_names:
                raise ValueError(f'Invalid field name {key!r}')
        return CallbackDataFilter(self, config)

"""
Кастом-фильтры — как `telebot.custom_filters`.

Фильтр это класс с полем `key` и методом `check`. Зарегистрированный
через `bot.add_custom_filter(...)` ключ можно писать именованным
аргументом обработчика:

.. code-block:: python3

    from maxibot.custom_filters import IsDigitFilter

    bot.add_custom_filter(IsDigitFilter())

    @bot.message_handler(is_digit=True)
    def digits(message):
        bot.reply_to(message, "число")

Незарегистрированный ключ обработчик не пропустит: maxibot напишет
об этом в лог (в telebot он молча не срабатывал).
"""
import logging
from abc import ABC
from typing import Optional, Union

from maxibot import types

logger = logging.getLogger("maxibot")


def _get_text(obj) -> Optional[str]:
    """
    Текст объекта для текстовых фильтров: у сообщения — text, а если
    его нет, подпись (как в telebot: `message.text or message.caption`;
    у медиа MAX подпись лежит в обоих полях), у callback — data.

    :return: Текст или None, если текста у объекта нет
    """
    if isinstance(obj, types.CallbackQuery):
        return obj.data
    if isinstance(obj, types.Message):
        return obj.text if obj.text is not None else obj.caption
    return None


def _get_message(obj):
    """
    Объект, у которого спрашивают чат: у callback это сообщение
    с кнопкой (как в telebot), у остальных — он сам. ChatMemberUpdated
    сюда тоже приходит: у него есть и chat, и from_user, и фильтры
    по чату на нём работают, как в telebot
    """
    if isinstance(obj, types.CallbackQuery):
        return obj.message
    return obj


def _user_id(obj) -> Optional[int]:
    """
    Настоящий id пользователя MAX: у message.from_user в поле id
    исторически лежит id чата, а сам пользователь — в real_id
    (см. types.User). Для запросов к API нужен real_id
    """
    from_user = getattr(obj, "from_user", None)
    real_id = getattr(from_user, "real_id", None)
    if real_id is not None:
        return real_id
    return getattr(from_user, "id", None)


def _link_type(obj) -> Optional[str]:
    """
    Тип связи сообщения MAX: 'reply' у ответа, 'forward'
    у пересланного, None — сообщение само по себе
    """
    message = _get_message(obj)
    # Link лежит в reply_to_message: у пересылки это тоже он
    # (одно поле link на оба типа связи в MAX)
    link = getattr(message, "reply_to_message", None)
    return getattr(link, "type", None)


class SimpleCustomFilter(ABC):
    """
    Простой кастом-фильтр — как `telebot.custom_filters.SimpleCustomFilter`.
    Наследник задаёт `key` и метод `check(message) -> bool`; результат
    сравнивается со значением, написанным в обработчике.

    .. code-block:: python3

        class IsPrivateFilter(SimpleCustomFilter):
            key = 'is_private'

            def check(self, message):
                return message.chat.type == 'private'
    """

    key: str = None

    def check(self, message):
        """
        Выполнить проверку

        :param message: Сообщение, callback или событие членства
        """
        pass


class AdvancedCustomFilter(ABC):
    """
    Кастом-фильтр со значением — как
    `telebot.custom_filters.AdvancedCustomFilter`. Наследник задаёт
    `key` и метод `check(message, value) -> bool`, куда приходит
    значение из обработчика.

    .. code-block:: python3

        class TextStartsFilter(AdvancedCustomFilter):
            key = 'text_startswith'

            def check(self, message, text):
                return message.text.startswith(text)
    """

    key: str = None

    def check(self, message, text):
        """
        Выполнить проверку

        :param message: Сообщение, callback или событие членства
        :param text: Значение фильтра из обработчика
        """
        pass


class TextFilter:
    """
    Текстовый фильтр для TextMatchFilter — как
    `telebot.custom_filters.TextFilter`: проверяет текст сообщения,
    подпись, data callback'а.

    :param equals: Текст совпадает со строкой
    :type equals: :obj:`str`

    :param contains: Текст содержит любую из строк
    :type contains: :obj:`list` или :obj:`tuple`

    :param starts_with: Текст начинается с любой из строк
    :type starts_with: :obj:`str`, :obj:`list` или :obj:`tuple`

    :param ends_with: Текст заканчивается любой из строк
    :type ends_with: :obj:`str`, :obj:`list` или :obj:`tuple`

    :param ignore_case: Не учитывать регистр (по умолчанию False)
    :type ignore_case: :obj:`bool`

    :raises ValueError: Не задано ни одного условия
    """

    def __init__(self,
                 equals: Optional[str] = None,
                 contains: Optional[Union[list, tuple]] = None,
                 starts_with: Optional[Union[str, list, tuple]] = None,
                 ends_with: Optional[Union[str, list, tuple]] = None,
                 ignore_case: bool = False):
        if not any(pattern is not None for pattern in (equals, contains, starts_with, ends_with)):
            raise ValueError('None of the check modes was specified')

        self.equals = equals
        self.contains = self._check_iterable(contains, filter_name='contains')
        self.starts_with = self._check_iterable(starts_with, filter_name='starts_with')
        self.ends_with = self._check_iterable(ends_with, filter_name='ends_with')
        self.ignore_case = ignore_case

    @staticmethod
    def _check_iterable(iterable, filter_name: str):
        if not iterable:
            return iterable
        if isinstance(iterable, str):
            return [iterable]
        if isinstance(iterable, (list, tuple)):
            return [item for item in iterable if isinstance(item, str)]
        raise ValueError("Incorrect value of %r" % filter_name)

    def check(self, obj) -> bool:
        """
        :meta private:
        """
        text = _get_text(obj)
        if text is None:
            # у сообщения нет текста (стикер, файл без подписи) —
            # фильтр не совпал. В telebot тут падал AttributeError
            return False

        equals, contains = self.equals, self.contains
        starts_with, ends_with = self.starts_with, self.ends_with
        if self.ignore_case:
            # регистр снимается со ВСЕХ условий (в telebot из-за
            # elif — только с первого заданного) и с копий: сам
            # фильтр остаётся неизменным и переиспользуется
            text = text.lower()
            equals = equals.lower() if equals else equals
            contains = [item.lower() for item in contains] if contains else contains
            starts_with = [item.lower() for item in starts_with] if starts_with else starts_with
            ends_with = [item.lower() for item in ends_with] if ends_with else ends_with

        if equals:
            if equals == text:
                return True
            if not any((contains, starts_with, ends_with)):
                return False

        if contains:
            if any(item in text for item in contains):
                return True
            if not any((starts_with, ends_with)):
                return False

        if starts_with:
            if any(text.startswith(item) for item in starts_with):
                return True
            if not ends_with:
                return False

        if ends_with:
            return any(text.endswith(item) for item in ends_with)

        return False


class TextMatchFilter(AdvancedCustomFilter):
    """
    Фильтр по тексту сообщения (ключ `text`) — как в telebot.
    Значением может быть строка, список строк или TextFilter.

    .. code-block:: python3

        @bot.message_handler(text=['аккаунт'])
    """

    key = 'text'

    def check(self, message, text):
        """
        :meta private:
        """
        if isinstance(text, TextFilter):
            return text.check(message)
        value = _get_text(message)
        if isinstance(text, (list, tuple)):
            return value in text
        return text == value


class TextContainsFilter(AdvancedCustomFilter):
    """
    Фильтр «текст содержит» (ключ `text_contains`) — как в telebot.

    .. code-block:: python3

        @bot.message_handler(text_contains=['аккаунт'])
    """

    key = 'text_contains'

    def check(self, message, text):
        """
        :meta private:
        """
        if not isinstance(text, (str, list, tuple)):
            raise ValueError("Incorrect text_contains value")
        if isinstance(text, str):
            text = [text]
        else:
            text = [item for item in text if isinstance(item, str)]

        value = _get_text(message)
        if value is None:
            return False
        return any(item in value for item in text)


class TextStartsFilter(AdvancedCustomFilter):
    """
    Фильтр «текст начинается с» (ключ `text_startswith`) — как
    в telebot; значением может быть строка или список строк.

    .. code-block:: python3

        @bot.message_handler(text_startswith='сэр')
    """

    key = 'text_startswith'

    def check(self, message, text):
        """
        :meta private:
        """
        value = _get_text(message)
        if value is None:
            return False
        if isinstance(text, (list, tuple)):
            return any(value.startswith(item) for item in text)
        return value.startswith(text)


class ChatFilter(AdvancedCustomFilter):
    """
    Фильтр по идентификатору чата (ключ `chat_id`) — как в telebot.

    .. code-block:: python3

        @bot.message_handler(chat_id=[99999])
    """

    key = 'chat_id'

    def __init__(self):
        # значения, о которых уже предупреждали: check вызывается
        # на каждое обновление, и повтор одной строки утопил бы
        # в логе настоящие ошибки (ср. MaxiBot._warn_once)
        self._warned = set()

    def check(self, message, text):
        """
        :meta private:
        """
        target = _get_message(message)
        chat_id = getattr(getattr(target, "chat", None), "id", None)
        if chat_id is None:
            return False
        if not isinstance(text, (list, tuple, set, frozenset)):
            # в telebot одиночный id падал с TypeError - у нас
            # обёртка с предупреждением, как у content_types
            if repr(text) not in self._warned:
                self._warned.add(repr(text))
                logger.warning(
                    "chat_id: ожидается список идентификаторов, обернул %r", text)
            text = [text]
        return chat_id in text


class ForwardFilter(SimpleCustomFilter):
    """
    Сообщение переслано (ключ `is_forwarded`) — как в telebot.
    В MAX пересылка видна по link.type == 'forward' (телеботовского
    forward_date у сообщения нет).

    .. code-block:: python3

        @bot.message_handler(is_forwarded=True)
    """

    key = 'is_forwarded'

    def check(self, message):
        """
        :meta private:
        """
        return _link_type(message) == "forward"


class IsReplyFilter(SimpleCustomFilter):
    """
    Сообщение — ответ на другое (ключ `is_reply`) — как в telebot.
    В MAX ответ и пересылка лежат в одном поле link, поэтому фильтр
    сверяет link.type == 'reply' (у пересылки reply_to_message тоже
    заполнен).

    .. code-block:: python3

        @bot.message_handler(is_reply=True)
    """

    key = 'is_reply'

    def check(self, message):
        """
        :meta private:
        """
        return _link_type(message) == "reply"


class LanguageFilter(AdvancedCustomFilter):
    """
    Фильтр по языку пользователя (ключ `language_code`) — как
    в telebot. В MAX язык приходит в user_locale и есть не у всех
    событий: там, где его нет, language_code = None.

    .. code-block:: python3

        @bot.message_handler(language_code=['ru'])
    """

    key = 'language_code'

    def check(self, message, text):
        """
        :meta private:
        """
        language_code = getattr(getattr(message, "from_user", None), "language_code", None)
        if isinstance(text, (list, tuple, set, frozenset)):
            return language_code in text
        return language_code == text


class IsAdminFilter(SimpleCustomFilter):
    """
    Пользователь — администратор или владелец чата (ключ
    `is_chat_admin`) — как в telebot. Каждая проверка это запрос
    к API (GET /chats/{chatId}/members), и список участников в MAX
    виден только администраторам: если бот не админ, запрос упадёт
    и обработчик не сработает. Пользователь берётся из
    from_user.real_id — в from_user.id у сообщений MAX лежит id чата.

    .. code-block:: python3

        @bot.message_handler(chat_types=['group'], is_chat_admin=True)
    """

    key = 'is_chat_admin'

    def __init__(self, bot):
        self._bot = bot

    def check(self, message):
        """
        :meta private:
        """
        target = _get_message(message)
        chat_id = getattr(getattr(target, "chat", None), "id", None)
        user_id = _user_id(message)
        if chat_id is None or user_id is None:
            return False
        return self._bot.get_chat_member(chat_id, user_id).status in ('creator', 'administrator')


class IsDigitFilter(SimpleCustomFilter):
    """
    Текст состоит только из цифр (ключ `is_digit`) — как в telebot.

    .. code-block:: python3

        @bot.message_handler(is_digit=True)
    """

    key = 'is_digit'

    def check(self, message):
        """
        :meta private:
        """
        text = _get_text(message)
        # в telebot сообщение без текста роняло фильтр AttributeError
        return bool(text) and text.isdigit()

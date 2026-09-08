import re
from io import BytesIO
from typing import Union, List, Dict, Any, Callable, Optional

try:
    # noinspection PyPackageRequirements
    from PIL import Image
    pil_imported = True
except ImportError:
    pil_imported = False


MAX_MESSAGE_LENGTH = 4000

# Все типы обновлений MAX Bot API (объект Update в документации) — аналог
# telebot.util.update_types; именно их принимает bot.middleware_handler
update_types = [
    "message_created", "message_edited", "message_removed", "message_callback",
    "bot_added", "bot_removed", "bot_started", "bot_stopped",
    "user_added", "user_removed", "chat_title_changed",
    "dialog_cleared", "dialog_muted", "dialog_unmuted", "dialog_removed",
    "comment_created", "comment_edited", "comment_removed",
]


def is_command(text: str) -> bool:
    """
    Проверка, является ли строка командой

    :param text: строка
    :type text: str
    :return: Флаг, является ли строка командой
    :rtype: bool
    """
    if text is None:
        return False
    return text.startswith('/')


def extract_command(text: str) -> Union[str, None]:
    """
    Вытаскивает команду из текста сообщения

    :param text: Description
    :type text: str
    :return: Description
    :rtype: Union[str, None]
    """
    if text is None:
        return None
    return text.split()[0].split('@')[0][1:] if is_command(text) else None


def extract_arguments(text: str) -> Union[str, None]:
    """
    Возвращает аргументы после команды — парный к extract_command,
    как telebot.util.extract_arguments.

    .. code-block:: python3
        :caption: Примеры:

        extract_arguments("/get name"): 'name'
        extract_arguments("/get"): ''
        extract_arguments("/get@botName name"): 'name'

    :param text: Текст сообщения
    :type text: str

    :return: Аргументы, если text — команда (по is_command), иначе None
    :rtype: Union[str, None]
    """
    if text is None:
        # telebot на None падает TypeError; наши is_command/extract_command
        # None-безопасны — эта пара такая же
        return None
    regexp = re.compile(r"/\w*(@\w*)*\s*([\s\S]*)", re.IGNORECASE)
    result = regexp.match(text)
    return result.group(2) if is_command(text) else None


def is_pil_image(var) -> bool:
    """
    Returns True if the given object is a PIL.Image.Image object.

    :param var: object to be checked
    :type var: :obj:`object`

    :return: True if the given object is a PIL.Image.Image object.
    :rtype: :obj:`bool`
    """
    return pil_imported and isinstance(var, Image.Image)


def pil_image_to_bytes(image, extension='JPEG', quality='web_low') -> bool:
    """
    Returns True if the given object is a PIL.Image.Image object.

    :param var: object to be checked
    :type var: :obj:`object`

    :return: True if the given object is a PIL.Image.Image object.
    :rtype: :obj:`bool`
    """
    if pil_imported:
        photoBuffer = BytesIO()
        image.convert('RGB').save(photoBuffer, extension, quality=quality)
        photoBuffer.seek(0)
        return photoBuffer
    else:
        raise RuntimeError('PIL module is not imported')


def get_text(media):
    """
    Метод получения текста из media

    :param media: Объект медиа
    """
    try:
        text = media.caption
    except Exception:
        text = None
    finally:
        return text


def get_parse_mode(media, parse_mode: str):
    """
    Метод получения parse_mode из media

    :param media: Объект медиа
    :param parse_mode: Тип парсинга раметки
    """
    try:
        parse_mode_res = media.parse_mode.lower()
    except Exception:
        parse_mode_res = parse_mode.lower()
    finally:
        return parse_mode_res


def smart_split(text: str, chars_per_string: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """
    Разбивает одну строку на несколько строк с максимальным количеством символов chars_per_string на строку.
    Полезно для разбиения одного большого сообщения на несколько.
    Если chars_per_string > 4096: chars_per_string = 4096.
    Разбиение выполняется по '\n', '. ' или ' ', именно в таком порядке приоритета.

    :param text: Текст для разбиения
    :type text: str

    :param chars_per_string: Максимальное количество символов на одну часть, на которую разбивается текст.
    :type chars_per_string: int

    :return: Разбитый текст в виде списка строк.
    :rtype: List из str
    """

    def _text_before_last(substr: str) -> str:
        return substr.join(part.split(substr)[:-1]) + substr

    if chars_per_string > MAX_MESSAGE_LENGTH: chars_per_string = MAX_MESSAGE_LENGTH

    parts = []
    while True:
        if len(text) < chars_per_string:
            parts.append(text)
            return parts

        part = text[:chars_per_string]

        if "\n" in part:
            part = _text_before_last("\n")
        elif ". " in part:
            part = _text_before_last(". ")
        elif " " in part:
            part = _text_before_last(" ")

        parts.append(part)
        text = text[len(part):]


def split_string(text: str, chars_per_string: int) -> List[str]:
    """
    Разбивает строку на части не длиннее chars_per_string символов —
    как telebot.util.split_string. Режет по количеству символов, не
    глядя на слова; чтобы не рвать слова — smart_split.

    :param text: Текст для разбиения
    :type text: str

    :param chars_per_string: Максимальное количество символов на часть
    :type chars_per_string: int

    :return: Разбитый текст в виде списка строк
    :rtype: List[str]
    """
    return [text[i:i + chars_per_string] for i in range(0, len(text), chars_per_string)]


def escape(text: str) -> Optional[str]:
    """
    Экранирует HTML-символы: '&' → '&amp;', '<' → '&lt;', '>' → '&gt;' —
    как telebot.util.escape. Для parse_mode='HTML'.

    :param text: Текст для экранирования
    :type text: str

    :return: Экранированный текст (None — если пришёл None)
    :rtype: Optional[str]
    """
    chars = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
    if text is None:
        return None
    for old, new in chars.items():
        text = text.replace(old, new)
    return text


def user_link(user, include_id: bool = False) -> str:
    """
    HTML-ссылка на пользователя (упоминание) — как telebot.util.user_link.
    Не забудьте parse_mode='HTML'!

    .. code-block:: python3
        :caption: Пример:

        bot.send_message(chat_id, user_link(message.from_user) + ' запустил бота!', parse_mode='HTML')

    Ссылка строится по схеме MAX ``max://user/%user_id%`` (упоминание
    без username). Берётся user.real_id — настоящий id пользователя:
    from_user.id в maxibot всегда равен id ЧАТА (даже в диалоге это
    id диалога, а не пользователя), и ссылка по нему вела бы в никуда.

    :param user: Пользователь (объект maxibot.types.User, не user_id)
    :type user: :class:`maxibot.types.User`

    :param include_id: Дописать id пользователя после ссылки
    :type include_id: bool

    :return: HTML-ссылка
    :rtype: str
    """
    user_id = getattr(user, "real_id", None)
    if user_id is None:
        # у поста от имени канала sender пустой (real_id нет) —
        # хоть какой-то id лучше, чем 'None' в ссылке
        user_id = user.id
    name = escape(user.first_name)
    return (f"<a href='max://user/{user_id}'>{name}</a>"
            + (f" (<pre>{user_id}</pre>)" if include_id else ""))


def quick_markup(values: Dict[str, Dict[str, Any]], row_width: int = 2) -> 'InlineKeyboardMarkup':
    """
    Собирает InlineKeyboardMarkup из словаря {'текст': kwargs} — как
    telebot.util.quick_markup. Избавляет от вечных
    'btn1 = InlineKeyboardButton(...)' 'btn2 = InlineKeyboardButton(...)'.

    .. code-block:: python3
        :caption: Пример:

        from maxibot.util import quick_markup

        markup = quick_markup({
            'Twitter': {'url': 'https://twitter.com'},
            'Facebook': {'url': 'https://facebook.com'},
            'Назад': {'callback_data': 'whatever'}
        }, row_width=2)
        # клавиатура 2x1: Twitter и Facebook в ряд, «Назад» — ниже

    В kwargs то же, что принимает maxibot.types.InlineKeyboardButton:
    'url', 'callback_data' или 'web_app' (телеботовские
    switch_inline_query, pay и прочие без аналога в MAX принимаются
    и игнорируются, см. InlineKeyboardButton).

    :param values: Словарь кнопок в формате {текст: kwargs}
    :type values: Dict[str, Dict[str, Any]]

    :param row_width: Кнопок в ряду
    :type row_width: int

    :return: Собранная клавиатура
    :rtype: :class:`maxibot.types.InlineKeyboardMarkup`
    """
    # импорт отложенный: maxibot.types сам импортирует maxibot.util
    from maxibot.types import InlineKeyboardButton, InlineKeyboardMarkup

    markup = InlineKeyboardMarkup(row_width=row_width)
    buttons = [
        InlineKeyboardButton(text=text, **kwargs)
        for text, kwargs in values.items()
    ]
    markup.add(*buttons)
    return markup


def antiflood(function: Callable, *args, number_retries=5, **kwargs):
    """
    Вызывает function, пережидая лимит запросов (HTTP 429) — как
    telebot.util.antiflood. Для вызовов в цикле.

    .. code-block:: python3
        :caption: Пример:

        from maxibot.util import antiflood

        for chat_id in chat_id_list:
            msg = antiflood(bot.send_message, chat_id, text)

    Отличие от telebot: Telegram присылает в 429 поле retry_after,
    MAX — нет, поэтому пауза берётся из HTTP-заголовка Retry-After,
    а без него — 1 секунда.

    :param function: Функция для вызова
    :type function: Callable

    :param number_retries: Всего попыток (не дополнительных)
    :type number_retries: int

    :param args: Позиционные аргументы function
    :param kwargs: Именованные аргументы function

    :return: Результат function
    """
    # импорт отложенный — как у telebot с apihelper (и чтобы maxibot.util
    # оставался лёгким для импорта)
    from time import sleep

    from maxibot.exceptions import MaxApiHTTPException

    for _ in range(number_retries - 1):
        try:
            return function(*args, **kwargs)
        except MaxApiHTTPException as ex:
            if ex.status_code == 429:
                retry_after = (getattr(ex.result, "headers", None) or {}).get("Retry-After")
                try:
                    pause = float(retry_after)
                except (TypeError, ValueError):
                    pause = 1.0
                sleep(pause)
            else:
                raise
    else:
        # последняя попытка — без страховки, как в telebot
        return function(*args, **kwargs)


def get_edit_message_data(
    text: Optional[str],
    chat_id: Union[str, int],
    message_id: str,
    attachments: List[Dict[str, Any]],
    timestamp: int
) -> Dict[str, Any]:
    """
    Формирует структуру данных сообщения для метода редактирования сообщения.

    Создаёт словарь с форматом, аналогичным ответу MAX API при получении сообщения,
    чтобы объект Message мог корректно инициализироваться из этих данных.

    :param text: Новый текст сообщения. Может быть None, если текст не изменяется
    :type text: Optional[str]

    :param chat_id: Идентификатор чата
    :type chat_id: Union[str, int]

    :param message_id: Идентификатор сообщения (mid)
    :type message_id: str

    :param attachments: Список вложений сообщения (клавиатуры, медиа и т.д.)
    :type attachments: List[Dict[str, Any]]

    :param timestamp: Временная метка в миллисекундах (Unix timestamp * 1000)
    :type timestamp: int

    :return: Структура данных сообщения в формате MAX API
    :rtype: Dict[str, Any]
    """
    return {
        "message": {
            "recipient": {
                "chat_id": int(chat_id) if isinstance(chat_id, str) and chat_id.isdigit() else chat_id,
                # тип чата в ответе на правку не приходит, а выдумывать
                # его нельзя: 'dialog' у сообщения из группы означал бы
                # chat.type == 'private' и увёл бы проверку не в ту ветку
                "chat_type": None,
                "user_id": None
            },
            "timestamp": timestamp,
            "body": {
                "mid": message_id,
                "seq": 0,
                "text": text,
                "attachments": attachments
            },
            "sender": {}
        },
        "timestamp": timestamp,
        # локаль в ответе на правку не приходит — выдуманное "ru"
        # означало бы from_user.language_code == "ru" у любого
        # пользователя (и ложное срабатывание LanguageFilter)
        "user_locale": None,
        "update_type": "message_edited"
    }

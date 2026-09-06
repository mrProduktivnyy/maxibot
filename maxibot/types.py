# from dataclasses import dataclass
import logging
import traceback
from datetime import datetime
from urllib.parse import urlsplit
from typing import List, Dict, Any, Optional

from maxibot.apihelper import Api
from maxibot.util import is_pil_image, pil_image_to_bytes

logger = logging.getLogger("maxibot")


class JsonDeserializable(object):
    def __str__(self):
        d = {
            x: y.__dict__ if hasattr(y, '__dict__') else y
            for x, y in self.__dict__.items()
        }
        return str(d)


class UpdateType:
    """
    Типы обновлений, которые можно получать от MAX API (объект Update в
    документации; тот же список строк — maxibot.util.update_types)
    """
    MESSAGE_CREATED = "message_created"
    MESSAGE_CALLBACK = "message_callback"
    MESSAGE_EDITED = "message_edited"
    MESSAGE_REMOVED = "message_removed"
    MESSAGE_DELETED = MESSAGE_REMOVED  # прежнее имя: "message_deleted" MAX не присылает
    BOT_STARTED = "bot_started"
    BOT_STOPPED = "bot_stopped"
    BOT_ADDED = "bot_added"
    BOT_REMOVED = "bot_removed"
    USER_ADDED = "user_added"
    USER_REMOVED = "user_removed"
    CHAT_TITLE_CHANGED = "chat_title_changed"
    DIALOG_CLEARED = "dialog_cleared"
    DIALOG_MUTED = "dialog_muted"
    DIALOG_UNMUTED = "dialog_unmuted"
    DIALOG_REMOVED = "dialog_removed"
    COMMENT_CREATED = "comment_created"
    COMMENT_EDITED = "comment_edited"
    COMMENT_REMOVED = "comment_removed"


class WebAppInfo:
    """
    Мини-приложение для кнопки InlineKeyboardButton(web_app=...).
    Сигнатура как у telebot.types.WebAppInfo(url).

    В Telegram web_app открывает произвольную страницу по URL. В MAX кнопка
    open_app открывает мини-приложение бота, а адрес самого приложения
    задаётся в настройках бота. Поэтому url здесь — публичное имя
    (username) бота или ссылка на него (https://max.ru/<username>), чьё
    мини-приложение надо открыть; это поле web_app кнопки open_app.

    Пример, один в один с telebot:

        markup.add(InlineKeyboardButton("Открыть", web_app=WebAppInfo("https://max.ru/mybot")))

    :param url: Публичное имя (username) бота (ведущий @ отбрасывается)
        или ссылка на него — поле web_app кнопки open_app. None допустим,
        если задан contact_id. Адрес самого приложения сюда не подходит:
        для такого url будет предупреждение в лог
    :type url: Optional[str]

    :param contact_id: ID бота, чьё мини-приложение надо открыть — поле
        contact_id кнопки open_app (только в MAX)
    :type contact_id: Optional[int]

    :param payload: Параметр запуска, который попадёт в initData
        мини-приложения — поле payload кнопки open_app (только в MAX)
    :type payload: Optional[str]
    """

    def __init__(
            self,
            url: Optional[str],
            contact_id: Optional[int] = None,
            payload: Optional[str] = None,
    ):
        if isinstance(url, str) and url.startswith("@"):
            url = url[1:]  # telebot-привычка: @username
        self.url = url
        self.contact_id = contact_id
        self.payload = payload

        if not url and contact_id is None:
            raise ValueError("нужен url (username или ссылка на бота) или contact_id")
        if url:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            if parts.scheme in ("http", "https") and \
                    host != "max.ru" and not host.endswith(".max.ru"):
                logger.warning(
                    "WebAppInfo(%r): в MAX кнопка open_app открывает мини-приложение "
                    "бота, настроенное на dev.max.ru, — url должен быть username бота "
                    "или https://max.ru/<username>, а не адрес приложения, как в Telegram",
                    url,
                )

    def to_dict(self) -> Dict[str, Any]:
        """
        Поля кнопки open_app для MAX API: web_app, contact_id, payload.
        Незаданные поля в словарь не попадают

        :return: Словарь с полями кнопки open_app
        :rtype: Dict[str, Any]
        """
        result: Dict[str, Any] = {}
        if self.url:
            result["web_app"] = self.url
        if self.contact_id is not None:
            result["contact_id"] = self.contact_id
        if self.payload is not None:
            result["payload"] = self.payload
        return result


class InlineKeyboardButton:
    """
    Класс для создания inline-кнопок в сообщениях. Сигнатура один в один
    с telebot.InlineKeyboardButton: text, url, callback_data, web_app.

    Кнопка должна быть ровно одного вида:

    * url — {"type": "link"}: открывает ссылку;
    * callback_data — {"type": "callback"}: по нажатию бот получает
      message_callback с этими данными (callback_query_handler);
    * web_app — {"type": "open_app"}: открывает мини-приложение бота,
      см. WebAppInfo.

    Кнопки link и open_app — специальные: в ряду с ними не больше
    3 кнопок (у обычных — 7).

    :param text: Текст на кнопке
    :type text: str

    :param url: URL ссылка для кнопки типа "link"
    :type url: Optional[str]

    :param callback_data: Данные для callback-кнопки
    :type callback_data: Optional[str]

    :param web_app: Мини-приложение для кнопки типа "open_app": WebAppInfo
        или строка — username бота или ссылка на него
    :type web_app: Optional[WebAppInfo]

    Параметры telebot без аналога в MAX (switch_inline_query, callback_game,
    pay, login_url и т.п.) принимаются и игнорируются, но кнопка только
    с таким параметром не собирается — ValueError с его именем.

    :param switch_inline_query: Принимается для совместимости с telebot и
        игнорируется — inline-режима в MAX нет
    :type switch_inline_query: Optional[Any]

    :param switch_inline_query_current_chat: Принимается для совместимости
        с telebot и игнорируется
    :type switch_inline_query_current_chat: Optional[Any]

    :param switch_inline_query_chosen_chat: Принимается для совместимости
        с telebot и игнорируется
    :type switch_inline_query_chosen_chat: Optional[Any]

    :param callback_game: Принимается для совместимости с telebot и
        игнорируется — игр в MAX нет
    :type callback_game: Optional[Any]

    :param pay: Принимается для совместимости с telebot и игнорируется —
        платежей в MAX Bot API нет
    :type pay: Optional[Any]

    :param login_url: Принимается для совместимости с telebot и
        игнорируется
    :type login_url: Optional[Any]
    """
    MAX_URL_LEN = 2048

    def __init__(
            self,
            text: str,
            url: Optional[str] = None,
            callback_data: Optional[str] = None,
            web_app: Optional[WebAppInfo] = None,
            switch_inline_query: Optional[Any] = None,
            switch_inline_query_current_chat: Optional[Any] = None,
            switch_inline_query_chosen_chat: Optional[Any] = None,
            callback_game: Optional[Any] = None,
            pay: Optional[Any] = None,
            login_url: Optional[Any] = None,
    ):
        if isinstance(web_app, str) and web_app:
            web_app = WebAppInfo(web_app)
        elif web_app is not None and not isinstance(web_app, WebAppInfo):
            telebot_url = getattr(web_app, "url", None)  # telebot.types.WebAppInfo
            if isinstance(telebot_url, str) and telebot_url:
                web_app = WebAppInfo(telebot_url)
        self.text = text
        self.url = url
        self.callback_data = callback_data
        self.web_app = web_app
        self.switch_inline_query = switch_inline_query
        self.switch_inline_query_current_chat = switch_inline_query_current_chat
        self.switch_inline_query_chosen_chat = switch_inline_query_chosen_chat
        self.callback_game = callback_game
        self.pay = pay
        self.login_url = login_url

        kinds = [name for name, value in (("url", url), ("callback_data", callback_data), ("web_app", web_app)) if value]
        if not kinds:
            telebot_only = [name for name, value in (
                ("switch_inline_query", switch_inline_query),
                ("switch_inline_query_current_chat", switch_inline_query_current_chat),
                ("switch_inline_query_chosen_chat", switch_inline_query_chosen_chat),
                ("callback_game", callback_game),
                ("pay", pay),
                ("login_url", login_url),
            ) if value is not None]
            if telebot_only:
                raise ValueError(
                    f"кнопка только с {', '.join(telebot_only)}: аналога в MAX нет "
                    f"(inline-режима, игр и платежей нет) — нужен url, callback_data или web_app")
            raise ValueError("url, callback_data или web_app обязан быть")
        if len(kinds) > 1:
            raise ValueError(f"укажите что-то одно: {' и '.join(kinds)}")
        if url and len(url) > self.MAX_URL_LEN:
            raise ValueError(f"url не может быть длиннее {self.MAX_URL_LEN} символов")

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует кнопку в словарь для отправки в MAX API

        :return: Словарь с данными кнопки в формате MAX API
        :rtype: Dict[str, Any]
        """
        if self.url:
            return {"type": "link", "text": self.text, "url": self.url}
        if self.web_app:
            return {"type": "open_app", "text": self.text, **self.web_app.to_dict()}
        return {
            "type": "callback",
            "text": self.text,
            "payload": self.callback_data
        }

    def is_special(self) -> bool:
        """
        Проверяет, является ли кнопка специальной (ограничивает ряд до 3 кнопок)

        :return: True если кнопка link или open_app, False если обычная (callback)
        :rtype: bool
        """
        return bool(self.url or self.web_app)


class InlineKeyboardMarkup:
    """
    Класс для создания inline-клавиатур в сообщениях. Сигнатура один
    в один с telebot.InlineKeyboardMarkup: (keyboard=None, row_width=3).

    :param keyboard: Готовая клавиатура — список рядов кнопок
        InlineKeyboardButton
    :type keyboard: Optional[List[List[InlineKeyboardButton]]]

    :param row_width: Ширина ряда по умолчанию для add()
        (сколько кнопок в ряду), как в telebot — 3
    :type row_width: int
    """
    MAX_ROWS = 30
    MAX_BUTTONS = 210
    MAX_ROW_REGULAR = 7
    MAX_ROW_SPECIAL = 3

    def __init__(
            self,
            keyboard: Optional[List[List[InlineKeyboardButton]]] = None,
            row_width: int = 3,
    ):
        self.row_width = row_width
        self.keyboard: List[List[InlineKeyboardButton]] = keyboard if keyboard else []

    def add(self, *args: InlineKeyboardButton, row_width=None) -> 'InlineKeyboardMarkup':
        """
        Добавляет кнопки в клавиатуру, автоматически разбивая на ряды

        :param args: Кнопки для добавления
        :type args: InlineKeyboardButton

        :param row_width: Ширина ряда для этих кнопок (если не указано, используется self.row_width)
        :type row_width: Optional[int]

        :return: Текущий объект клавиатуры (для цепочки вызовов)
        :rtype: InlineKeyboardMarkup
        """
        width = row_width or self.row_width
        row = []
        for btn in args:
            row.append(btn)
            if len(row) == width:
                self._append_row(row)
                row = []
        if row:
            self._append_row(row)
        return self

    def row(self, *args: InlineKeyboardButton) -> 'InlineKeyboardMarkup':
        """
        Добавляет ряд кнопок в клавиатуру

        :param args: Кнопки для добавления в ряд
        :type args: InlineKeyboardButton

        :return: Текущий объект клавиатуры (для цепочки вызовов)
        :rtype: InlineKeyboardMarkup
        """
        if args:
            self._append_row(list(args))
        return self

    def to_attachment(self) -> Dict[str, Any]:
        """
        Преобразует клавиатуру в attachment для отправки в сообщении

        :return: Словарь с данными клавиатуры в формате MAX API
        :rtype: Dict[str, Any]
        """
        self._validate()
        return {
            "type": "inline_keyboard",
            "payload": {"buttons": [[btn.to_dict() for btn in row] for row in self.keyboard]},
        }

    def _append_row(self, row: List[InlineKeyboardButton]):
        """
        Метод для добавления ряда кнопок

        :param row: Ряд кнопок для добавления
        :type row: List[InlineKeyboardButton]
        """
        self.keyboard.append(row)

    def _validate(self):
        """
        Метод для валидации клавиатуры

        :raises ValueError: Если превышены лимиты на количество кнопок или рядов
        """
        total = sum(len(r) for r in self.keyboard)
        if total > self.MAX_BUTTONS:
            raise ValueError(f"Максимум {self.MAX_BUTTONS} кнопок")
        if len(self.keyboard) > self.MAX_ROWS:
            raise ValueError(f"Максимум {self.MAX_ROWS} рядов")

        for row in self.keyboard:
            special_in_row = any(btn.is_special() for btn in row)
            limit = self.MAX_ROW_SPECIAL if special_in_row else self.MAX_ROW_REGULAR
            if len(row) > limit:
                reason = " (в ряду есть кнопка link, open_app, request_contact или request_geo_location)" \
                    if special_in_row else ""
                raise ValueError(f"Ряд содержит {len(row)} кнопок, но максимум {limit}{reason}")


class KeyboardButton:
    """
    Кнопка reply-клавиатуры. Сигнатура один в один с telebot.KeyboardButton.

    В MAX нет системной reply-клавиатуры, поэтому кнопка превращается
    в кнопку inline-клавиатуры:

    * обычная текстовая — {"type": "message"}: по нажатию отправляет
      текст кнопки в чат, как reply-кнопка в Telegram;
    * request_contact=True — {"type": "request_contact"}: запрашивает
      контакт и номер телефона пользователя;
    * request_location=True — {"type": "request_geo_location"}:
      запрашивает местоположение пользователя;
    * web_app=WebAppInfo(...) — {"type": "open_app"}: открывает
      мини-приложение бота, как в telebot (см. WebAppInfo).

    Приоритет, если задано несколько: request_contact, затем
    request_location, затем web_app.

    :param text: Текст кнопки (у обычной кнопки он же отправляется в чат)
    :type text: str

    :param request_contact: Если True, по нажатию бот получит контакт
        пользователя
    :type request_contact: Optional[bool]

    :param request_location: Если True, по нажатию бот получит
        местоположение пользователя
    :type request_location: Optional[bool]

    :param request_poll: Принимается для совместимости с telebot и
        игнорируется — опросов в MAX Bot API нет, кнопка станет обычной
        текстовой
    :type request_poll: Optional[Any]

    :param web_app: WebAppInfo или строка (username бота или ссылка
        на него) — кнопка станет кнопкой open_app и откроет
        мини-приложение бота, как в telebot. Другие значения
        принимаются для совместимости и игнорируются — кнопка
        останется обычной текстовой
    :type web_app: Optional[Any]

    :param request_user: Принимается для совместимости с telebot и
        игнорируется
    :type request_user: Optional[Any]

    :param request_chat: Принимается для совместимости с telebot и
        игнорируется
    :type request_chat: Optional[Any]

    :param request_users: Принимается для совместимости с telebot и
        игнорируется
    :type request_users: Optional[Any]
    """

    def __init__(
            self,
            text: str,
            request_contact: Optional[bool] = None,
            request_location: Optional[bool] = None,
            request_poll: Optional[Any] = None,
            web_app: Optional[Any] = None,
            request_user: Optional[Any] = None,
            request_chat: Optional[Any] = None,
            request_users: Optional[Any] = None,
    ):
        if isinstance(web_app, str) and web_app:
            web_app = WebAppInfo(web_app)
        elif web_app is not None and not isinstance(web_app, WebAppInfo):
            telebot_url = getattr(web_app, "url", None)  # telebot.types.WebAppInfo
            if isinstance(telebot_url, str) and telebot_url:
                web_app = WebAppInfo(telebot_url)
        self.text = text
        self.request_contact = request_contact
        self.request_location = request_location
        self.request_poll = request_poll
        self.web_app = web_app
        self.request_user = request_user
        self.request_chat = request_chat
        self.request_users = request_users

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует кнопку в словарь для отправки в MAX API

        :return: Словарь с данными кнопки в формате MAX API
        :rtype: Dict[str, Any]
        """
        if self.request_contact:
            return {"type": "request_contact", "text": self.text}
        if self.request_location:
            return {"type": "request_geo_location", "text": self.text}
        if isinstance(self.web_app, WebAppInfo):
            return {"type": "open_app", "text": self.text, **self.web_app.to_dict()}
        return {"type": "message", "text": self.text}

    def is_special(self) -> bool:
        """
        Проверяет, является ли кнопка специальной (ограничивает ряд до 3 кнопок)

        :return: True если кнопка запрашивает контакт или местоположение
            либо открывает мини-приложение
        :rtype: bool
        """
        return bool(self.request_contact or self.request_location
                    or isinstance(self.web_app, WebAppInfo))


class ReplyKeyboardMarkup(InlineKeyboardMarkup):
    """
    Reply-клавиатура. Сигнатура один в один с telebot.ReplyKeyboardMarkup:
    add() и row() принимают строки, bytes и KeyboardButton.

    В MAX нет системной reply-клавиатуры, поэтому она отправляется как
    inline-клавиатура с кнопками типа "message" — по нажатию текст кнопки
    уходит в чат, и бот получает его обычным сообщением, как в Telegram.
    Клавиатура при этом прикреплена к сообщению, а не к полю ввода.

    Пример, один в один с telebot:

        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("Да", "Нет")
        bot.send_message(chat_id, "Продолжаем?", reply_markup=markup)

    :param resize_keyboard: Принимается для совместимости с telebot и
        игнорируется — в MAX клавиатура прикреплена к сообщению, размер
        задаёт клиент
    :type resize_keyboard: Optional[bool]

    :param one_time_keyboard: Принимается для совместимости с telebot и
        игнорируется
    :type one_time_keyboard: Optional[bool]

    :param selective: Принимается для совместимости с telebot и
        игнорируется
    :type selective: Optional[bool]

    :param row_width: Ширина ряда по умолчанию (сколько кнопок в ряду)
    :type row_width: int

    :param input_field_placeholder: Принимается для совместимости с
        telebot и игнорируется — поля ввода с плейсхолдером в MAX нет
    :type input_field_placeholder: Optional[str]

    :param is_persistent: Принимается для совместимости с telebot и
        игнорируется
    :type is_persistent: Optional[bool]
    """
    max_row_keys = 12  # атрибут telebot, оставлен для совместимости

    def __init__(
            self,
            resize_keyboard: Optional[bool] = None,
            one_time_keyboard: Optional[bool] = None,
            selective: Optional[bool] = None,
            row_width: int = 3,
            input_field_placeholder: Optional[str] = None,
            is_persistent: Optional[bool] = None,
    ):
        super().__init__(row_width=row_width)
        self.resize_keyboard = resize_keyboard
        self.one_time_keyboard = one_time_keyboard
        self.selective = selective
        self.input_field_placeholder = input_field_placeholder
        self.is_persistent = is_persistent

    def add(self, *args, row_width=None) -> 'ReplyKeyboardMarkup':
        """
        Добавляет кнопки в клавиатуру, автоматически разбивая на ряды.
        Как в telebot, кнопкой может быть строка, bytes или KeyboardButton.

        :param args: Кнопки для добавления
        :type args: Union[str, bytes, KeyboardButton]

        :param row_width: Ширина ряда для этих кнопок (если не указано,
            используется self.row_width)
        :type row_width: Optional[int]

        :return: Текущий объект клавиатуры (для цепочки вызовов)
        :rtype: ReplyKeyboardMarkup
        """
        buttons = [self._normalize_button(button) for button in args]
        super().add(*buttons, row_width=row_width)
        return self

    def row(self, *args) -> 'ReplyKeyboardMarkup':
        """
        Добавляет ряд кнопок в клавиатуру.
        Как в telebot, кнопкой может быть строка, bytes или KeyboardButton.

        :param args: Кнопки для добавления в ряд
        :type args: Union[str, bytes, KeyboardButton]

        :return: Текущий объект клавиатуры (для цепочки вызовов)
        :rtype: ReplyKeyboardMarkup
        """
        buttons = [self._normalize_button(button) for button in args]
        super().row(*buttons)
        return self

    @staticmethod
    def _normalize_button(button) -> KeyboardButton:
        """
        Приводит строку/bytes к KeyboardButton (как это делает telebot)

        :param button: Кнопка в любом поддерживаемом виде
        :type button: Union[str, bytes, KeyboardButton]

        :return: Объект кнопки
        :rtype: KeyboardButton
        """
        if isinstance(button, KeyboardButton):
            return button
        if isinstance(button, bytes):
            return KeyboardButton(button.decode("utf-8"))
        return KeyboardButton(str(button))


class ImagePayload(JsonDeserializable):
    """
    Класс для хранения данных изображения

    :param payload: Словарь с данными изображения
    :type payload: Dict[str, Any]
    """

    def __init__(self, payload: Dict[str, Any]):
        self.photo_id = payload.get("photo_id")
        self.token = payload.get("token")
        self.url = payload.get("url")
        # телеботовские поля PhotoSize — объект живёт и как
        # message.video.thumbnail, где telebot-код ждёт file_id;
        # file_path — прямая ссылка для download_file
        self.file_id = self.token
        self.file_unique_id = self.token
        self.file_path = self.url
        self.file_size = None
        self.width = None
        self.height = None


class ImageAttachment(JsonDeserializable):
    """
    Класс для работы с вложениями типа "image"

    :param attach: Словарь с данными вложения
    :type attach: Dict[str, Any]
    """

    def __init__(self, attach: Dict[str, Any]):
        self.payload = ImagePayload(payload=attach.get("payload"))
        self.type = attach.get("type")
        # телеботовские поля PhotoSize: file_id — токен вложения (им же
        # фото переотправляется через send_photo), file_path — прямая
        # ссылка для download_file; размеров у image-вложения MAX нет
        self.file_id = self.payload.token
        self.file_unique_id = self.payload.token
        self.file_size = None
        self.width = None
        self.height = None
        self.file_path = self.payload.url

    # в telebot message.photo — список PhotoSize; в MAX размер один,
    # поэтому канонические photo[-1]/photo[0] возвращают само вложение
    def __getitem__(self, index):
        return (self,)[index]

    def __len__(self):
        return 1

    def __iter__(self):
        return iter((self,))

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует объект в словарь

        :return: Словарь с данными изображения
        :rtype: Dict[str, Any]
        """
        return {
            "payload": {
                "photo_id": self.payload.photo_id,
                "token": self.payload.token,
                "url": self.payload.url
            },
            "type": self.type
        }


class File(JsonDeserializable):
    """
    Файл, готовый к скачиванию, — как telebot.types.File, но file_path
    в MAX — это ПОЛНЫЙ URL (в Telegram — относительный путь на сервере
    файлов), а роль file_id играет токен вложения либо сама ссылка.
    Канонический паттерн переносится без правок:

        file_info = bot.get_file(message.document.file_id)
        data = bot.download_file(file_info.file_path)
    """

    def __init__(self, file_id: Optional[str] = None,
                 file_path: Optional[str] = None,
                 file_size: Optional[int] = None):
        self.file_id = file_id
        self.file_unique_id = file_id
        self.file_size = file_size
        self.file_path = file_path


class VideoUrls(JsonDeserializable):
    """
    Ссылки воспроизведения видео из GET /videos/{videoToken}:
    mp4_1080 … mp4_144 (обычные файлы, любая может быть None)
    и hls (плейлист трансляции — не скачиваемый файл)
    """

    _QUALITY_ORDER = ("mp4_1080", "mp4_720", "mp4_480", "mp4_360",
                      "mp4_240", "mp4_144")

    def __init__(self, urls: Optional[Dict[str, Any]]):
        for key in self._QUALITY_ORDER + ("hls",):
            setattr(self, key, (urls or {}).get(key))

    @property
    def best(self) -> Optional[str]:
        """Лучший доступный mp4; если mp4 нет вовсе — hls"""
        for key in self._QUALITY_ORDER:
            url = getattr(self, key)
            if url:
                return url
        return self.hls


class Video(JsonDeserializable):
    """
    Видео — атрибуты telebot.types.Video (file_id/width/height/duration…)
    поверх видео-вложения MAX. file_id — токен вложения; file_path
    у вложения из сообщения всегда None: payload.url видео — НЕ прямая
    ссылка, скачиваемые ссылки отдаёт только GET /videos/{videoToken}
    (bot.get_file(токен) или bot.get_video(токен))
    """

    def __init__(self, attach: Dict[str, Any]):
        payload = attach.get("payload") or {}
        self.token = payload.get("token")
        self.url = payload.get("url")
        self.file_id = self.token
        self.file_unique_id = self.token
        self.width = attach.get("width")
        self.height = attach.get("height")
        self.duration = attach.get("duration")
        thumbnail = attach.get("thumbnail")
        self.thumbnail = ImagePayload(payload=thumbnail) if thumbnail else None
        self.file_name = None
        self.mime_type = None
        self.file_size = None
        self.urls: Optional[VideoUrls] = None
        self.file_path: Optional[str] = None

    @property
    def thumb(self):
        """Устаревший алиас thumbnail — как в telebot"""
        return self.thumbnail

    @classmethod
    def from_details(cls, details: Dict[str, Any]) -> "Video":
        """
        Видео из ответа GET /videos/{videoToken}
        (VideoAttachmentDetails): токен, ссылки, размеры, длительность
        """
        video = cls({
            "payload": {"token": details.get("token")},
            "width": details.get("width"),
            "height": details.get("height"),
            "duration": details.get("duration"),
            "thumbnail": details.get("thumbnail"),
        })
        # urls null — видео недоступно, тогда и file_path остаётся None
        urls = details.get("urls")
        if urls is not None:
            video.urls = VideoUrls(urls)
            video.file_path = video.urls.best
        return video


class Audio(JsonDeserializable):
    """
    Аудио — атрибуты telebot.types.Audio поверх аудио-вложения MAX.
    file_id — токен вложения, file_path — прямая ссылка для
    download_file; длительности/исполнителя/названия у аудио-вложения
    MAX нет. transcription — расшифровка речи (расширение MAX)
    """

    def __init__(self, attach: Dict[str, Any]):
        payload = attach.get("payload") or {}
        self.token = payload.get("token")
        self.url = payload.get("url")
        self.file_id = self.token
        self.file_unique_id = self.token
        self.duration = None
        self.performer = None
        self.title = None
        self.file_name = None
        self.mime_type = None
        self.file_size = None
        self.thumbnail = None
        self.transcription = attach.get("transcription")
        self.file_path = self.url

    @property
    def thumb(self):
        """Устаревший алиас thumbnail — как в telebot"""
        return self.thumbnail


class Document(JsonDeserializable):
    """
    Документ — атрибуты telebot.types.Document поверх file-вложения
    MAX. file_id — токен вложения, file_path — прямая ссылка для
    download_file, file_name/file_size — из вложения
    """

    def __init__(self, attach: Dict[str, Any]):
        payload = attach.get("payload") or {}
        self.token = payload.get("token")
        self.url = payload.get("url")
        self.file_id = self.token
        self.file_unique_id = self.token
        self.file_name = attach.get("filename")
        self.file_size = attach.get("size")
        self.mime_type = None
        self.thumbnail = None
        self.file_path = self.url

    @property
    def thumb(self):
        """Устаревший алиас thumbnail — как в telebot"""
        return self.thumbnail


class Recipient(JsonDeserializable):
    """
    Класс получателя сообщения

    :param rec: Словарь recipient из ответа MAX API
    :type rec: Dict[str, Any]
    """

    def __init__(self, rec: Dict[str, Any]):
        self.chat_id = rec.get("chat_id")
        self.chat_type = rec.get("chat_type")
        self.user_id = rec.get("user_id")


class Body(JsonDeserializable):
    """
    Класс тела сообщения

    :param body: Словарь body из ответа MAX API
    :type body: Dict[str, Any]
    """

    def __init__(self, body: Dict[str, Any]):
        self.mid = body.get("mid")
        self.seq = body.get("seq")
        self.text = body.get("text")
        self.attachments = body.get("attachments")


class User(JsonDeserializable):
    """
    Класс пользователя

    :param update: Обновление от MAX API
    :type update: Dict[str, Any]
    """

    def __init__(self, update: Dict[str, Any]):
        if not isinstance(update, dict):
            pass
        elif update.get("callback"):
            self.id = update.get("message").get("recipient").get("chat_id")
            self.real_id = update.get("callback").get("user").get("user_id")
            self.is_bot = update.get("callback").get("user").get("is_bot")
            self.first_name = update.get("callback").get("user").get("first_name")
            self.username = update.get("callback").get("user").get("name")
            self.last_name = update.get("callback").get("user").get("last_name")
            self.language_code = update.get("user_locale")
        elif update.get("update_type") == UpdateType.BOT_STARTED or update.get("update_type") == UpdateType.BOT_ADDED:
            self.id = update.get("chat_id")
            self.real_id = update.get("user").get("user_id")
            self.is_bot = update.get("user").get("is_bot")
            self.first_name = update.get("user").get("first_name")
            self.username = update.get("user").get("name")
            self.last_name = update.get("user").get("last_name")
            self.language_code = update.get("user_locale")
        else:
            # sender по спеке nullable — у поста от имени канала его нет
            sender = update.get("message").get("sender") or {}
            self.id = update.get("message").get("recipient").get("chat_id")
            self.real_id = sender.get("user_id")
            self.is_bot = sender.get("is_bot")
            self.first_name = sender.get("first_name")
            self.username = sender.get("name")
            self.last_name = sender.get("last_name")
            self.language_code = update.get("user_locale")


class _PreloadedChatInfoApi:
    """
    Обёртка Api с предзагруженным ответом GET /chats/{chatId}: сборка
    pinned_message в Chat.from_chat_info не должна ходить в сеть за
    чатом, который уже в руках (Chat.get_chat_title дергает
    get_chat_info на каждое построение). Остальные вызовы делегируются
    настоящему Api.
    """

    def __init__(self, api, chat_info):
        self._api = api
        self._chat_info = chat_info

    def get_chat_info(self, chat_id):
        if chat_id == self._chat_info.get("chat_id"):
            return self._chat_info
        return self._api.get_chat_info(chat_id=chat_id)

    def __getattr__(self, name):
        return getattr(self._api, name)


class Chat(JsonDeserializable):
    """
    Класс чата

    :param update: Обновление от MAX API
    :type update: Dict[str, Any]
    """

    def __init__(self, update: Dict[str, Any], api: Api):
        self.api = api
        if update.get("update_type") == UpdateType.BOT_STARTED:
            self.id = update.get("chat_id")
            self.title = self.get_chat_title(chat_id=self.id)
            self.type = "dialog"
            self.user_id = None
        elif update.get("update_type") == UpdateType.BOT_ADDED:
            self.id = update.get("chat_id")
            self.title = self.get_chat_title(chat_id=self.id)
            self.type = None
            self.user_id = None
        else:
            self.id = update.get("message").get("recipient").get("chat_id")
            self.title = self.get_chat_title(chat_id=self.id)
            self.type = update.get("message").get("recipient").get("chat_type")
            self.user_id = update.get("message").get("recipient").get("user_id")

    def get_chat_title(self, chat_id: str):
        """
        Получение заголовка чата

        :param chat_id: айди чата
        :type chat_id: Dict[str, Any]
        """
        if chat_id is None:
            # синтетическое сообщение без chat_id (например, результат PUT,
            # когда вызывающий его не передал) — не ходить в GET /chats/None
            return None
        info = self.api.get_chat_info(chat_id=chat_id)
        return info.get("title")

    # маппинг типов чата MAX -> имена telebot (channel совпадает)
    _CHAT_TYPE_MAP = {"dialog": "private", "chat": "group"}

    # атрибуты telebot.types.Chat 4.15.4 — у результата get_chat
    # выставляются в None до заполнения реальных полей, чтобы
    # перенесённый код не падал с AttributeError (прецедент —
    # Message._TELEBOT_ATTRIBUTES)
    _TELEBOT_ATTRIBUTES = (
        "id", "type", "title", "username", "first_name", "last_name",
        "photo", "bio", "has_private_forwards", "description",
        "invite_link", "pinned_message", "permissions", "slow_mode_delay",
        "message_auto_delete_time", "has_protected_content",
        "sticker_set_name", "can_set_sticker_set", "linked_chat_id",
        "location", "join_to_send_messages", "join_by_request",
        "has_restricted_voice_and_video_messages", "is_forum",
        "active_usernames", "emoji_status_custom_emoji_id",
        "has_hidden_members", "has_aggressive_anti_spam_enabled",
        "emoji_status_expiration_date", "available_reactions",
        "accent_color_id", "background_custom_emoji_id",
        "profile_accent_color_id", "profile_background_custom_emoji_id",
        "has_visible_history",
    )

    @classmethod
    def from_chat_info(cls, info: Dict[str, Any], api: Api) -> "Chat":
        """
        Строит Chat из ответа GET /chats/{chatId} (для bot.get_chat) —
        в отличие от конструктора, который собирает чат из обновления.

        Поля как в telebot: id, type (типы MAX мапятся в телеботовские:
        dialog -> private, chat -> group, channel -> channel), title,
        description, photo (URL иконки чата — строка, а не ChatPhoto),
        pinned_message (Message или None), invite_link; для диалогов —
        first_name/last_name/username и bio (описание профиля)
        собеседника из dialog_with_user. Остальные атрибуты
        telebot.types.Chat существуют и равны None (permissions,
        is_forum и т.п.). Дополнительно поля MAX: status,
        participants_count, is_public.

        Отличие от message.chat: там type — сырой тип MAX
        ("dialog"/"chat"/"channel"), исторически.
        """
        chat = cls.__new__(cls)
        # сначала все телеботовские атрибуты None, реальные значения
        # перекрывают их ниже
        for attribute in cls._TELEBOT_ATTRIBUTES:
            setattr(chat, attribute, None)
        chat.api = api
        chat.id = info.get("chat_id")
        raw_type = info.get("type")
        chat.type = cls._CHAT_TYPE_MAP.get(raw_type, raw_type)
        chat.title = info.get("title")
        chat.description = info.get("description")
        icon = info.get("icon") or {}
        chat.photo = icon.get("url")
        chat.invite_link = info.get("link")
        chat.user_id = None
        dialog_with_user = info.get("dialog_with_user") or {}
        if dialog_with_user:
            chat.user_id = dialog_with_user.get("user_id")
            chat.first_name = dialog_with_user.get("first_name")
            chat.last_name = dialog_with_user.get("last_name")
            chat.username = dialog_with_user.get("username")
            # телеботовский bio приватного чата — описание профиля
            # собеседника (UserWithPhoto.description)
            chat.bio = dialog_with_user.get("description")
        pinned = info.get("pinned_message")
        if pinned:
            pinned_update = {
                # sender по спеке может быть null (пост от имени
                # канала) — Message тогда даёт from_user=None, как
                # в telebot
                "message": pinned,
                # timestamp закрепа — на верхний уровень, где его ждёт
                # Message._get_msg_timestamp (иначе date был бы None)
                "timestamp": pinned.get("timestamp"),
            }
            # сборка Message тянет Chat.get_chat_title -> GET того же
            # чата; ответ уже в руках — подсовываем его без сети
            chat.pinned_message = Message(
                update=pinned_update, api=_PreloadedChatInfoApi(api, info)
            )
        # поля MAX без телеботовских аналогов
        chat.status = info.get("status")
        chat.participants_count = info.get("participants_count")
        chat.is_public = info.get("is_public")
        return chat


class ChatMember(JsonDeserializable):
    """
    Класс участника чата — результат bot.get_chat_member,
    bot.get_chat_administrators и bot.get_chat_membership. Собирается
    из объекта ChatMember MAX (GET /chats/{chatId}/members).

    Поля как в telebot: status ('creator' у владельца, 'administrator'
    у админа, иначе 'member'; 'left' — если пользователя нет в чате),
    user (телеботовский User; здесь user.id — НАСТОЯЩИЙ id
    пользователя, в отличие от message.from_user.id, где исторически
    лежит id чата), custom_title (alias админа), is_member и can_*-флаги,
    собранные из прав MAX. Все остальные атрибуты telebot.types.ChatMember
    существуют и равны None. Дополнительно сырые поля MAX:
    is_owner, is_admin, permissions (список прав как пришёл),
    alias, last_access_time, join_time, description (описание профиля),
    avatar_url, full_avatar_url.

    :param member: Объект ChatMember из ответа MAX API
    :type member: Dict[str, Any]

    :param status: Готовый телеботовский статус — используется для
        заглушки 'left', когда пользователя в чате нет
    :type status: Optional[str]
    """

    # атрибуты telebot.types.ChatMember 4.15.4 — существуют всегда,
    # чтобы перенесённый код не падал с AttributeError (прецедент —
    # Chat._TELEBOT_ATTRIBUTES)
    _TELEBOT_ATTRIBUTES = (
        "user", "status", "custom_title", "is_anonymous", "can_be_edited",
        "can_post_messages", "can_edit_messages", "can_delete_messages",
        "can_restrict_members", "can_promote_members", "can_change_info",
        "can_invite_users", "can_pin_messages", "is_member",
        "can_send_messages", "can_send_audios", "can_send_documents",
        "can_send_photos", "can_send_videos", "can_send_video_notes",
        "can_send_voice_notes", "can_send_polls", "can_send_other_messages",
        "can_add_web_page_previews", "can_manage_chat",
        "can_manage_video_chats", "until_date", "can_manage_topics",
        "can_post_stories", "can_edit_stories", "can_delete_stories",
    )

    # права MAX (enum ChatAdminPermission) -> телеботовские can_*-флаги.
    # add_remove_members закрывает и приглашения, и удаления, поэтому
    # взводит оба флага; у edit_link и view_stats телеботовского флага
    # нет — они видны только в сыром .permissions
    _PERMISSION_FLAGS = {
        "change_chat_info": ("can_change_info",),
        "pin_message": ("can_pin_messages",),
        "add_remove_members": ("can_invite_users", "can_restrict_members"),
        "add_admins": ("can_promote_members",),
        "write": ("can_post_messages",),
        "edit": ("can_edit_messages",),
        "delete": ("can_delete_messages",),
        "can_call": ("can_manage_video_chats",),
    }

    def __init__(self, member: Dict[str, Any], status: Optional[str] = None):
        member = member if isinstance(member, dict) else {}
        # сначала все телеботовские атрибуты None, реальные значения
        # перекрывают их ниже
        for attribute in self._TELEBOT_ATTRIBUTES:
            setattr(self, attribute, None)

        # телеботовский User: id здесь — настоящий id пользователя
        # (сравнения вида member.user.id == user_id работают)
        user = User.__new__(User)
        user.id = member.get("user_id")
        user.real_id = member.get("user_id")
        user.is_bot = member.get("is_bot")
        user.first_name = member.get("first_name")
        user.last_name = member.get("last_name")
        # в объектах участников MAX публичный username; в обновлениях
        # вместо него display-имя name — берём что есть
        user.username = member.get("username") or member.get("name")
        user.language_code = None
        self.user = user

        if status is not None:
            self.status = status
        elif member.get("is_owner"):
            self.status = "creator"
        elif member.get("is_admin"):
            self.status = "administrator"
        else:
            self.status = "member"

        # kicked (заблокировал бота / забанен) — тоже не участник
        self.is_member = self.status not in ("left", "kicked")
        self.custom_title = member.get("alias")

        if self.status == "creator":
            # владелец может всё — как в Telegram, где у creator нет
            # ограничений; permissions MAX у него может быть и null
            for flags in self._PERMISSION_FLAGS.values():
                for flag in flags:
                    setattr(self, flag, True)
            self.can_manage_chat = True
        elif self.status == "administrator":
            # у админа флаги честные: True по правам MAX, False — нет права
            for flags in self._PERMISSION_FLAGS.values():
                for flag in flags:
                    setattr(self, flag, False)
            for permission in member.get("permissions") or []:
                for flag in self._PERMISSION_FLAGS.get(permission, ()):
                    setattr(self, flag, True)
            # телеграмный инвариант: у администратора can_manage_chat
            # всегда True («implied by any other administrator privilege»)
            self.can_manage_chat = True

        # сырые поля MAX без телеботовских аналогов
        self.is_owner = member.get("is_owner")
        self.is_admin = member.get("is_admin")
        self.permissions = member.get("permissions")
        self.alias = member.get("alias")
        self.last_access_time = member.get("last_access_time")
        self.join_time = member.get("join_time")
        self.description = member.get("description")
        self.avatar_url = member.get("avatar_url")
        self.full_avatar_url = member.get("full_avatar_url")


class ChatMemberUpdated(JsonDeserializable):
    """
    Изменение статуса участника чата — как telebot.types.ChatMemberUpdated.
    В maxibot синтезируется из обновлений членства MAX:

    - my_chat_member (статус самого бота): bot_added (left -> member),
      bot_removed (member -> left), bot_started (kicked -> member —
      аналог разблокировки в Telegram), bot_stopped (member -> kicked —
      аналог блокировки бота пользователем);
    - chat_member (другие участники): user_added (left -> member),
      user_removed (member -> left).

    from_user — инициатор события (кто добавил/удалил; у user_added
    по ссылке и user_removed «сам вышел» — сам пользователь);
    old_chat_member/new_chat_member — ChatMember затронутого
    (у my_chat_member это сам бот). date — unix-время в секундах,
    как в telebot. invite_link/via_chat_folder_invite_link всегда None
    (таких сущностей в MAX нет). Дополнительно: is_channel (флаг MAX)
    и json — сырое обновление (deep-link кнопки «Начать» — в
    json['payload']).
    """

    def __init__(self, chat, from_user, date, old_chat_member,
                 new_chat_member, invite_link=None,
                 via_chat_folder_invite_link=None):
        self.chat = chat
        self.from_user = from_user
        self.date = date
        self.old_chat_member = old_chat_member
        self.new_chat_member = new_chat_member
        self.invite_link = invite_link
        self.via_chat_folder_invite_link = via_chat_folder_invite_link
        self.is_channel = None
        self.json = None

    @property
    def difference(self) -> Dict[str, List]:
        """
        Разница old_chat_member/new_chat_member в формате telebot:
        {'параметр': [старое, новое]}, например
        {'status': ['left', 'member']}
        """
        old = self.old_chat_member.__dict__
        new = self.new_chat_member.__dict__
        dif = {}
        for key in new:
            # is_member — производное от status (в telebot его в разнице
            # не бывает); user пропускает и telebot
            if key in ("user", "is_member"):
                continue
            if new[key] != old[key]:
                dif[key] = [old[key], new[key]]
        return dif


class BotCommand(JsonDeserializable):
    """
    Команда бота — как telebot.types.BotCommand.

    :param command: Имя команды; ведущий '/' при отправке срезается
        (лимит MAX — 64 символа)
    :type command: str

    :param description: Описание команды — в отличие от telebot
        необязательно (лимит MAX — 128 символов)
    :type description: Optional[str]
    """

    def __init__(self, command: str, description: Optional[str] = None):
        self.command = command
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """
        Преобразует команду в объект BotCommand MAX ({"name",
        "description"}); ведущие '/' срезаются.

        :return: Словарь с данными команды
        :rtype: Dict[str, Any]
        """
        name = (self.command or "").lstrip("/")
        data = {"name": name}
        # пустая строка — как «без описания»: description по спеке
        # nullable, но с minLength 1 — "" сервер вправе отклонить
        if self.description:
            data["description"] = self.description
        return data

    @classmethod
    def from_max(cls, data: Dict[str, Any]) -> "BotCommand":
        """Строит BotCommand из объекта MAX ({"name", "description"})."""
        data = data if isinstance(data, dict) else {}
        return cls(command=data.get("name"), description=data.get("description"))


class BotName(JsonDeserializable):
    """Имя бота — как telebot.types.BotName (результат get_my_name)."""

    def __init__(self, name: str):
        self.name = name


class BotDescription(JsonDeserializable):
    """Описание бота — как telebot.types.BotDescription
    (результат get_my_description)."""

    def __init__(self, description: str):
        self.description = description


class BotShortDescription(JsonDeserializable):
    """Короткое описание бота — как telebot.types.BotShortDescription
    (результат get_my_short_description). Отдельного короткого описания
    в MAX нет — заполняется из единственного description."""

    def __init__(self, short_description: str):
        self.short_description = short_description


class ChatLink(JsonDeserializable):
    """
    Класс ссылки на чат

    :param update: Обновление от MAX API
    :type update: Dict[str, Any]
    """

    def __init__(self, update: Dict[str, Any]):
        self.id = update.get("chat_id")


class Link(JsonDeserializable):
    """
    Класс ссылки на сообщение

    :param link: Словарь с данными ссылки
    :type link: Dict[str, Any]
    """

    def __init__(self, link: Dict[str, Any]):
        if link:
            self.type = link.get("type")
            self.message_id: str = None
            self.from_user: Optional[User] = None
            self.chat: ChatLink = ChatLink(update=link)


class Photo(JsonDeserializable):
    """
    Класс для работы с фотографиями

    :param update: Обновление от MAX API
    :type update: Dict[str, Any]
    """

    def __init__(self, update: Dict[str, Any]):
        # body по спеке может быть null (сообщение-пересылка без комментария) —
        # цепочка .get(..., {}) от явного null не защищает
        attach = ((update.get("message") or {}).get("body") or {}).get("attachments")
        if attach:
            for att in attach:
                if att.get("type") == "image":
                    self.file_id = att.get("payload").get("photo_id")
                    self.token: str = att.get("payload").get("token")
                    self.url: str = att.get("payload").get("url")


class InputMedia(JsonDeserializable):
    """
    Класс формирования объекта attachments для отправки медиа

    :param type: Тип медиа (photo/file/video/audio)
    :type type: str

    :param media: Байты медиа; для фото — также строка: прямая
        http(s)-ссылка на изображение (MAX скачает его сам) или токен
        ранее загруженного изображения (аналог file_id); для аудио и
        видео — строка-токен ранее загруженного вложения
    :type media: Union[bytes, str]

    :param caption: Подпись к медиа
    :type caption: Optional[str]

    :param parse_mode: Режим парсинга текста (markdown/html)
    :type parse_mode: Optional[str]
    """
    compare_types = {
        "photo": "image",
        "file": "file",
        "video": "video",
        "audio": "audio"
    }

    def __init__(self, type: str = None, media: bytes = None, caption: str = None, parse_mode: str = None):
        self.type = type if type else "photo"
        self.media = media
        self.caption = caption
        self.parse_mode = parse_mode
        self.api = None

    def _get_upload_url(self, type_attach: str = "photo") -> Dict[str, Any]:
        """
        Шаг 1. Получение URL для загрузки файла

        :param type_attach: Тип вложения
        :type type_attach: str

        :return: Ответ API с URL для загрузки
        :rtype: Dict[str, Any]
        """
        return self.api.get_upload_file_url(type_attach=self.compare_types.get(type_attach))

    def _load_file_to_max(self, url: str, file_name: str = None) -> Dict[str, Any]:
        """
        Шаг 2. Загрузка файла на сервер MAX API

        :param url: URL для загрузки
        :type url: str

        :param file_name: Имя файла
        :type file_name: Optional[str]

        :return: Ответ API после загрузки
        :rtype: Dict[str, Any]
        """
        if file_name:
            files = {"data": (file_name, self.media, "text/plain")}
            return self.api.load_file(url=url, files=files, content_types=None)
        else:
            files = {"data": self.media}
            return self.api.load_file(url=url, files=files)

    def to_dict(self, api: Api, file_name: str = None) -> Dict[str, Any]:
        """
        Формирование attachments для отправки медиа

        :param api: Объект API
        :type api: Api

        :param file_name: Имя файла
        :type file_name: Optional[str]

        :return: Словарь с данными вложения
        :rtype: Dict[str, Any]
        """
        self.api = api
        if self.type == "photo" and isinstance(self.media, str):
            # Строка — как в telebot: http(s)-ссылка или токен ранее
            # загруженного изображения (аналог file_id, лежит в
            # message.photo.payload.token). Оба варианта MAX принимает
            # без POST /uploads, но только для изображений: видео, аудио
            # и файлы MAX принимает исключительно токеном загрузки
            if self.media.startswith(("http://", "https://")):
                return {"type": "image", "payload": {"url": self.media}}
            return {"type": "image", "payload": {"token": self.media}}
        if self.type == "audio" and isinstance(self.media, str):
            # строка — токен ранее загруженного аудио (аналог file_id, лежит
            # во входящем вложении payload.token); URL для аудио MAX не
            # принимает — send_audio отрезает его раньше с ValueError
            return {"type": "audio", "payload": {"token": self.media}}
        if self.type == "video" and isinstance(self.media, str):
            # строка — токен ранее загруженного видео (аналог file_id);
            # голые строки-URL send_video/send_animation/send_video_note
            # отрезают раньше, а обёрнутые в InputMedia ловим здесь
            if self.media.startswith(("http://", "https://")):
                raise ValueError(
                    "MAX принимает URL только для изображений (send_photo). "
                    "Видео можно отправить байтами, file-like объектом или "
                    "строкой-токеном ранее загруженного видео"
                )
            return {"type": "video", "payload": {"token": self.media}}
        upload = self._get_upload_url(type_attach=self.type)
        upload_url = upload.get("url")
        if not upload_url:
            return []
        if is_pil_image(self.media):
            self.media = pil_image_to_bytes(self.media)
        load_file_result = self._load_file_to_max(url=upload_url, file_name=file_name)
        if self.type in ("video", "audio"):
            # у видео и аудио MAX отдаёт token сразу в ответе POST /uploads,
            # ответ самой загрузки файла токена не содержит
            token_dict = {"token": upload.get("token")}
        elif file_name:
            token_dict = {"token": load_file_result.get("token")}
        else:
            token_dict = list(list(load_file_result.values())[0].values())[0]
        return {
            "type": self.compare_types.get(self.type),
            "payload": token_dict
        }


class InputMediaPhoto(InputMedia, JsonDeserializable):
    """
    Класс для отправки фотографий

    :param media: Байты изображения
    :type media: bytes

    :param caption: Подпись к фото
    :type caption: Optional[str]

    :param parse_mode: Режим парсинга текста
    :type parse_mode: Optional[str]
    """

    def __init__(self, media=None, caption=None, parse_mode=None):
        super().__init__(type="photo", media=media, caption=caption, parse_mode=parse_mode)


class InputMediaVideo(InputMedia, JsonDeserializable):
    """
    Класс для отправки видео

    :param media: Байты видео
    :type media: bytes

    :param caption: Подпись к видео
    :type caption: Optional[str]

    :param parse_mode: Режим парсинга текста
    :type parse_mode: Optional[str]
    """

    def __init__(self, media=None, caption=None, parse_mode=None):
        super().__init__(type="video", media=media, caption=caption, parse_mode=parse_mode)


class InputMediaAudio(InputMedia, JsonDeserializable):
    """
    Класс для отправки аудио

    :param media: Байты аудио или file-like объект
    :type media: bytes

    :param caption: Подпись к аудио
    :type caption: Optional[str]

    :param parse_mode: Режим парсинга текста
    :type parse_mode: Optional[str]
    """

    def __init__(self, media=None, caption=None, parse_mode=None):
        super().__init__(type="audio", media=media, caption=caption, parse_mode=parse_mode)


class MessageID(JsonDeserializable):
    """
    Идентификатор сообщения — аналог telebot.types.MessageID
    (его возвращают copy_message, forward_messages и copy_messages).

    :param message_id: Идентификатор сообщения (mid в MAX — строка,
        в отличие от телеграмного int)
    :type message_id: str
    """

    def __init__(self, message_id):
        self.message_id = message_id


class Message(JsonDeserializable):
    """
    Класс для работы с сообщениями (аналог telebot.types.Message)

    Все атрибуты telebot.types.Message существуют и по умолчанию равны
    None — код, переехавший с telebot, не падает с AttributeError.
    Отличие от telebot: у медиа-сообщений текст доступен и в text,
    и в caption (в telebot text у медиа пуст)

    :param update: Обновление от MAX API
    :type update: Dict[str, Any]

    :param api: Объект API
    :type api: Api
    """

    # атрибуты telebot.types.Message 4.15.4 (включая устаревшие forward_*) —
    # выставляются в None до заполнения реальных полей
    _TELEBOT_ATTRIBUTES = (
        "content_type", "id", "message_id", "from_user", "date", "chat",
        "sender_chat", "is_automatic_forward", "reply_to_message", "via_bot",
        "edit_date", "has_protected_content", "media_group_id",
        "author_signature", "text", "entities", "caption_entities", "audio",
        "document", "photo", "sticker", "video", "video_note", "voice",
        "caption", "contact", "location", "venue", "animation", "dice",
        "new_chat_members", "left_chat_member", "new_chat_title",
        "new_chat_photo", "delete_chat_photo", "group_chat_created",
        "supergroup_chat_created", "channel_chat_created",
        "migrate_to_chat_id", "migrate_from_chat_id", "pinned_message",
        "invoice", "successful_payment", "connected_website", "reply_markup",
        "message_thread_id", "is_topic_message", "forum_topic_created",
        "forum_topic_closed", "forum_topic_reopened", "has_media_spoiler",
        "forum_topic_edited", "general_forum_topic_hidden",
        "general_forum_topic_unhidden", "write_access_allowed",
        "users_shared", "chat_shared", "story", "external_reply", "quote",
        "link_preview_options", "giveaway_created", "giveaway",
        "giveaway_winners", "giveaway_completed", "forward_origin",
        "forward_from", "forward_from_chat", "forward_from_message_id",
        "forward_signature", "forward_sender_name", "forward_date",
        "user_shared", "new_chat_member",
    )

    # маппинг типов вложений MAX -> content_type telebot
    _CONTENT_TYPE_MAP = {
        "image": "photo",
        "file": "document",
    }
    # вложения-оформление: не определяют тип контента сообщения
    _SERVICE_ATTACHMENTS = ("inline_keyboard", "share")

    @staticmethod
    def _get_photo_from_attachments(update: Dict[str, Any]) -> Optional[ImageAttachment]:
        """
        Извлечение фото из вложений сообщения

        :param update: Обновление от MAX API
        :type update: Dict[str, Any]

        :return: Объект ImageAttachment или None
        :rtype: Optional[ImageAttachment]
        """
        if update.get("message"):
            update = update.get("message")
            if update.get("body"):
                update = update.get("body")
                if update.get("attachments"):
                    attachs = update.get("attachments")
                    for attach in attachs:
                        if attach.get("type") == "image":
                            return ImageAttachment(attach=attach)
        return None

    def _fill_media_attachments(self, update: Dict[str, Any]) -> None:
        """
        Заполняет message.video / message.audio / message.document
        объектами вложений (Video/Audio/Document) — чтобы работал
        канонический телеботовский паттерн
        bot.get_file(message.document.file_id). Берётся первое вложение
        каждого типа; в MAX голосовые не отличаются от аудио, поэтому
        voice всегда None, а голосовое приходит в audio (как в №2:
        voice -> audio)
        """
        attachments = ((update.get("message") or {}).get("body")
                       or {}).get("attachments") or ()
        for attach in attachments:
            if not isinstance(attach, dict):
                continue
            a_type = attach.get("type")
            if a_type == "video" and self.video is None:
                self.video = Video(attach)
            elif a_type == "audio" and self.audio is None:
                self.audio = Audio(attach)
            elif a_type == "file" and self.document is None:
                self.document = Document(attach)

    @staticmethod
    def _get_content_type(update: Dict[str, Any]) -> str:
        """
        Определение типа контента сообщения

        :param update: Обновление от MAX API
        :type update: Dict[str, Any]

        :return: Тип контента
        :rtype: str
        """
        try:
            attachments = update.get("message").get("body").get("attachments")
            for attach in attachments or ():
                a_type = attach.get("type")
                if a_type in Message._SERVICE_ATTACHMENTS:
                    # клавиатура/превью ссылки не делают сообщение медиа
                    continue
                return Message._CONTENT_TYPE_MAP.get(a_type, a_type)
            return "text"
        except Exception:
            if update.get("update_type") == UpdateType.BOT_ADDED:
                return UpdateType.BOT_ADDED
            else:
                return "text"

    @staticmethod
    def _get_msg_id(update: Dict[str, Any]) -> Optional[str]:
        """
        Получение ID сообщения

        :param update: Обновление от MAX API
        :type update: Dict[str, Any]

        :return: ID сообщения или None
        :rtype: Optional[str]
        """
        try:
            if update.get("message").get("body"):
                return update.get("message").get("body").get("mid")
            elif update.get("message").get("mid"):
                return update.get("message").get("mid")
            else:
                return None
        except Exception:
            return None

    @staticmethod
    def _get_msg_timestamp(update: Dict[str, Any]) -> Optional[datetime]:
        """
        Получение времени сообщения

        :param update: Обновление от MAX API
        :type update: Dict[str, Any]

        :return: Время сообщения или None
        :rtype: Optional[datetime]
        """
        if update.get("timestamp"):
            time = str(update.get("timestamp"))
            main_time = time[:10]
            milisec = time[10:]
            alltime = float(main_time + "." + milisec)
            return datetime.fromtimestamp(alltime)
        else:
            return None

    @staticmethod
    def _get_msg_text(update: Dict[str, Any]) -> Optional[str]:
        """
        Получение текста сообщения

        :param update: Обновление от MAX API
        :type update: Dict[str, Any]

        :return: Текст сообщения или None
        :rtype: Optional[str]
        """
        if update.get("message", {}).get("body", None):
            return update.get("message").get("body").get("text")
        elif update.get("update_type") == UpdateType.BOT_STARTED:
            return "/start" + " " + update.get("payload", "")
        else:
            return None

    def __init__(self, update: Dict[str, Any], api: Api):
        """
        Инициализация объекта сообщения
        """
        if not isinstance(update, dict):
            return None
        else:
            # сначала все атрибуты telebot по умолчанию None, реальные
            # значения перекрывают их ниже
            for attribute in self._TELEBOT_ATTRIBUTES:
                setattr(self, attribute, None)
            self.update = update
            self.api = api
            self.json: Dict[str, Any] = update.get("message") or update
            self.content_type: str = self._get_content_type(update=update)
            self.id: Optional[str] = self._get_msg_id(update=update)
            self.message_id: Optional[str] = self._get_msg_id(update=update)
            message_payload = update.get("message")
            if (isinstance(message_payload, dict)
                    and message_payload.get("sender") is None
                    and not update.get("callback")):
                # пост от имени канала: sender null/отсутствует — как
                # в telebot, у channel_post нет from_user. Именно is None:
                # синтетический sender {} (результаты edit_*-методов,
                # см. util.get_edit_message_data) даёт User, как раньше
                self.from_user: Optional[User] = None
            else:
                self.from_user: Optional[User] = User(update=update)
            self.date: Optional[datetime] = self._get_msg_timestamp(update=update)
            self.chat: Chat = Chat(update=update, api=api)
            link = update.get("message", {}).get("link")
            if link:
                # без link остаётся None из дефолтов — телеботовский
                # `if message.reply_to_message:` работает как ожидается
                self.reply_to_message: Link = Link(link=link)
            self.text: Optional[str] = self._get_msg_text(update=update)
            self.photo: Optional[ImageAttachment] = self._get_photo_from_attachments(update=update)
            self.photo_reply: Photo = Photo(update=update)
            self._fill_media_attachments(update=update)
            self.update_type = update.get('update_type')
            if self.content_type != "text" and self.text:
                # у медиа-сообщений подпись доступна и как caption;
                # text тоже остаётся заполненным (отличие от telebot)
                self.caption: Optional[str] = self.text

    @property
    def html_text(self) -> Optional[str]:
        """
        Текст как в telebot.html_text; entities в MAX нет, поэтому это
        просто text (в telebot без entities поведение то же)
        """
        return self.text

    @property
    def html_caption(self) -> Optional[str]:
        """
        Подпись как в telebot.html_caption; entities в MAX нет
        """
        return self.caption

    # def reply(self, text: str, **kwargs) -> Dict[str, Any]:
    #     """
    #     Ответ на текущее сообщение
    #
    #     :param text: Текст ответа
    #     :type text: str
    #
    #     :param kwargs: Дополнительные параметры:
    #         - parse_mode: Режим парсинга (markdown/html)
    #         - reply_markup: Клавиатура
    #         - attachments: Вложения
    #
    #     :return: Ответ API
    #     :rtype: Dict[str, Any]
    #     """
    #     attachments = kwargs.get('attachments', [])
    #     reply_markup = kwargs.get('reply_markup')
    #
    #     if reply_markup:
    #         attachments.append(reply_markup.to_attachment())
    #
    #     return self.api.send_message(
    #         chat_id=self.chat.id,
    #         text=text,
    #         attachments=attachments,
    #         link=self.message_id
    #     )


class CallbackQuery:
    """
    Класс для обработки callback-запросов от inline-кнопок

    :param update: Обновление от MAX API с типом 'message_callback'
    :type update: Dict[str, Any]

    :param api: Объект API для отправки ответов
    :type api: Api
    """

    def __init__(self, update: Dict[str, Any], api: Api):
        self.api = api
        cb = update.get("callback", {})
        self.id: str = cb.get("callback_id", "")
        self.chat_instance: str = self.id
        self.data: Optional[str] = cb.get("payload")

        # Если нет в callback, пытаемся извлечь из message attachments
        if not self.data:
            self.data = self._extract_button_data_from_message(update)

        msg = update.get("message", {})
        self.from_user = User(update=update) if msg else None
        self.message = Message(update=update, api=api) if msg else None

    def _extract_button_data_from_message(self, update: Dict[str, Any]) -> Optional[str]:
        """
        Извлечение данных кнопки из message attachments

        :param update: Обновление от MAX API
        :type update: Dict[str, Any]

        :return: Данные кнопки или None если не найдены
        :rtype: Optional[str]
        """
        callback_id = self.id
        message = update.get("message", {})

        if not message:
            return None

        body = message.get("body", {})
        attachments = body.get("attachments", [])

        for attachment in attachments:
            if attachment.get("callback_id") == callback_id:
                payload = attachment.get("payload", {})
                buttons = payload.get("buttons", [])

                for row in buttons:
                    for button in row:
                        if button.get("type") == "callback":
                            return button.get("text", "unknown")

        return None

    def answer(self, text: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Ответ на нажатие inline-кнопки в Max API

        :param text: Текст для обновления сообщения
        :type text: Optional[str]

        :param kwargs: Дополнительные параметры:
            - notification: Текст уведомления для пользователя
            - attachments: Вложения для обновления сообщения
            - link: Ссылка на сообщение для reply/forward
            - notify: Отправлять ли уведомление о редактировании
            - format: Формат текста (markdown/html)

        :return: Ответ от API
        :rtype: Dict[str, Any]
        """
        notification = kwargs.pop('notification', None)
        attachments = kwargs.pop('attachments', None)
        link = kwargs.pop('link', None)
        notify = kwargs.pop('notify', True)
        format = kwargs.pop('format', None)

        should_update_message = (text is not None or
                                 attachments is not None or
                                 link is not None)

        try:
            if not should_update_message and notification:
                return self.api.answer_callback(
                    callback_id=self.id,
                    notification=notification
                )
            else:
                return self.api.answer_callback(
                    callback_id=self.id,
                    text=text,
                    notification=notification,
                    attachments=attachments,
                    link=link,
                    notify=notify,
                    format=format
                )
        except Exception as e:
            if notification:
                try:
                    return self.api.answer_callback(
                        callback_id=self.id,
                        notification=notification
                    )
                except:
                    return {"success": False, "error": str(e)}
            return {"success": False, "error": str(e)}

    def answer_notification(self, text: str) -> Dict[str, Any]:
        """
        Отправка только уведомления (без изменения сообщения)

        :param text: Текст уведомления
        :type text: str

        :return: Ответ от API
        :rtype: Dict[str, Any]
        """
        return self.answer(notification=text)

    def answer_update(self, text: str, **kwargs) -> Dict[str, Any]:
        """
        Обновление сообщения с опциональным уведомлением

        :param text: Текст для обновления сообщения
        :type text: str

        :param kwargs: Дополнительные параметры
        :type kwargs: Dict[str, Any]

        :return: Ответ от API
        :rtype: Dict[str, Any]
        """
        if 'notification' not in kwargs:
            kwargs['notification'] = "Обновлено!"
        return self.answer(text=text, **kwargs)


class Update(JsonDeserializable):
    """
    Обновление от MAX API целиком (аналог telebot.types.Update). Его
    получают middleware без update_types; в message, edited_message и
    callback_query лежат те же объекты, которые затем попадут в
    обработчики, поэтому атрибуты, выставленные на них в middleware,
    видны и обработчикам. Как в telebot, заполнено только поле своего
    типа обновления; сырой payload всегда доступен в json

    :param update: Обновление от MAX API
    :type update: Dict[str, Any]

    :param api: Объект API
    :type api: Api
    """

    def __init__(self, update: Dict[str, Any], api: Api):
        self.json: Dict[str, Any] = update
        self.update_type: Optional[str] = update.get("update_type")
        self.timestamp: Optional[int] = update.get("timestamp")
        self.message: Optional[Message] = None
        self.edited_message: Optional[Message] = None
        self.callback_query: Optional[CallbackQuery] = None
        # телеботовские поля каналов: в MAX отдельного типа обновления
        # нет, посты каналов лежат в message/edited_message — атрибуты
        # всегда None, чтобы мигрантский `if update.channel_post:`
        # не падал с AttributeError (философия _TELEBOT_ATTRIBUTES)
        self.channel_post = None
        self.edited_channel_post = None
        # события членства: ChatMemberUpdated сюда подставляет
        # MaxiBot._process_update — при построении нужен кэш данных
        # бота, которого у Update нет; без подписки остаются None
        self.my_chat_member = None
        self.chat_member = None
        try:
            if self.update_type in (UpdateType.BOT_STARTED, UpdateType.BOT_ADDED) or \
                    self.update_type == UpdateType.MESSAGE_CREATED and "message" in update:
                # bot_started и bot_added бот обрабатывает как сообщения
                # (/start и появление в чате), поэтому они тоже в message
                self.message = Message(update=update, api=api)
            elif self.update_type == UpdateType.MESSAGE_EDITED and "message" in update:
                self.edited_message = Message(update=update, api=api)
            elif self.update_type == UpdateType.MESSAGE_CALLBACK and "callback" in update:
                self.callback_query = CallbackQuery(update=update, api=api)
        except Exception:
            # payload, который парсер не понял (например, сообщение без
            # recipient): общие middleware всё равно получат Update с сырым
            # json, а до обработчиков такое обновление не дойдёт — как и раньше
            logger.error(
                "Error while parsing update %s:\n%s", self.update_type, traceback.format_exc()
            )

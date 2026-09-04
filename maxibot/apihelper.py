import requests
from typing import Dict, Any, List, Optional

from maxibot.core.network.client import Client


# Модульные настройки сетевого слоя — аналог одноимённых в telebot.apihelper;
# proxy, URL, таймауты и ретраи читаются на каждый запрос — их можно менять
# на лету. Если proxy = None, применяются прокси из переменных окружения
# HTTP(S)_PROXY (стандарт requests); отключить их: proxy = {"http": "", "https": ""}
proxy = None            # прокси для requests, например {"https": "socks5://127.0.0.1:9050"}
session = None          # своя requests.Session (например, со своим CA-бандлом — см. docs/cert.md);
                        # применяется при создании сессии потока, к уже созданным — после reset/TTL

API_URL = None          # переопределение базового URL API (по умолчанию Client.BASE_URL)
CA_BUNDLE = None        # None — certifi + встроенные сертификаты Минцифры;
                        # путь к своему PEM-бандлу; False — отключить TLS-проверку

CONNECT_TIMEOUT = 15    # секунд на установку соединения
READ_TIMEOUT = 30       # секунд на чтение ответа; для long polling поднимается автоматически

LONG_POLLING_TIMEOUT = 30  # секунд серверного удержания GET /updates (дефолт сервера MAX — 30)

SESSION_TIME_TO_LIVE = 600  # жизнь сессии в секундах; None — вечно, 0 — новая на каждый запрос

RETRY_ON_ERROR = False  # повторять запрос при сетевых ошибках
RETRY_TIMEOUT = 2       # пауза между повторами, секунд
MAX_RETRIES = 15        # всего попыток при RETRY_ON_ERROR
RETRY_ENGINE = 1        # 1 — повторы с паузой (как telebot), 2 — urllib3 Retry

# TLS-проверка включена: цепочка platform-api2.max.ru подписана сертификатами
# Минцифры, они встроены в библиотеку (core/network/cacert.py, источник —
# gosuslugi.ru/crt). Флаг глушит предупреждения urllib3 — актуально только
# при CA_BUNDLE = False
ignore_warnings = False
# Как telebot.apihelper.ENABLE_MIDDLEWARE: регистрация middleware
# (bot.middleware_handler) работает только после ENABLE_MIDDLEWARE = True
ENABLE_MIDDLEWARE = False


class Api:
    """
    Клиент для рабты с api MAX
    """
    def __init__(self, token: str):
        """
        Docstring for __init__

        :param token: Токен бота
        :type token: str
        """
        if ignore_warnings:
            requests.packages.urllib3.disable_warnings()
        # модульный apihelper.proxy клиент читает сам на каждый запрос —
        # не запекаем его сюда, иначе apihelper.proxy = None не отключит прокси
        self.client = Client(token=token)

    def get_my_info(self) -> Dict[str, Any]:
        """
        Получает информацию о текущем боте

        :return: Информация о боте
        :rtype: Dict[str, Any]
        """
        return self.client.request("GET", "/me")

    def get_updates(self, allowed_updates: List[str], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Получает новые обновления от API через лонгполлинг

        :param allowed_updates: Список типов обновлений, которые нужно получать
        :param extra: Дополнительные параметры запроса

        :return: Список обновлений
        :rtype: Dict[str, Any]
        """
        params = dict(extra) if extra else {}
        # длительность серверного удержания long polling; по ней Client
        # поднимает и HTTP-таймаут чтения (timeout + 5, как в telebot)
        params.setdefault("timeout", LONG_POLLING_TIMEOUT)

        if allowed_updates:
            params["types"] = ",".join(allowed_updates)

        return self.client.request("GET", "/updates", params=params)

    def get_message(self, msg_id: str):
        """
        Получает сообщение по `msg_id`
        """
        return self.client.request("GET", f"/messages/{msg_id}")

    def send_message(
        self,
        chat_id: str = None,
        msg_id: str = None,
        text: str = None,
        method: str = "POST",
        attachments: Optional[List[Dict[str, Any]]] = None,
        parse_mode: str = "markdown",
        notify: bool = True,
        disable_link_preview: Optional[bool] = None,
        link: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Отправляет/удаляет/обновляет сообщение в чате

        :param chat_id: Идентификатор чата
        :type chat_id: str

        :param text: Текст сообщения
        :type text: str

        :param attachments: Вложения сообщения
        :type text: Optional[List[Dict[str, Any]]]

        :param disable_link_preview: Если True, сервер не будет генерировать
            превью для ссылок в тексте сообщения. Query-параметр MAX API,
            есть только у POST /messages (у PUT/DELETE параметра нет).
            None — параметр не отправляется, поведение сервера по умолчанию
        :type disable_link_preview: Optional[bool]

        :param link: Ссылка на другое сообщение — словарь вида
            {"type": "reply"|"forward", "mid": "<id сообщения>"}.
            None — обычное сообщение без ссылки
        :type link: Optional[Dict[str, Any]]

        :return: Информация об отправленном сообщении
        :rtype: Dict[str, Any]
        """
        # query параметры запроса
        if chat_id:
            params = {"chat_id": chat_id}
        elif msg_id and method in ("DELETE", "PUT"):
            params = {"message_id": msg_id}

        # disable_link_preview — только у POST /messages; requests сериализует
        # Python bool как "True"/"False", MAX ждёт нижний регистр — шлём строкой
        if method == "POST" and disable_link_preview is not None:
            params["disable_link_preview"] = "true" if disable_link_preview else "false"

        data = {}
        if text:
            data = {"text": text}

        if attachments:
            data["attachments"] = attachments
        else:
            data["attachments"] = []

        if text and parse_mode:
            data["format"] = parse_mode

        if notify:
            data["notify"] = notify

        if link:
            data["link"] = link

        return self.client.request(method, "/messages", params=params, data=data)

    def get_upload_file_url(self, type_attach: str):
        """
        Апи метод для получения url загрузки файла.

        :param type_attach: Тип файла, который требуется загрузить
        :type type_attach: str

        :return: Json с url для загрузки файла
        :rtype: Dict[str: Any]
        """
        return self.client.request("POST", f"/uploads?type={type_attach}")

    def get_chat_info(self, chat_id: str):
        """
        Апи метод для получения инфомрации о чате.

        :param chat_id: Айди чата
        :type chat_id: str

        :return: Json
        :rtype: Dict[str: Any]
        """
        return self.client.request("GET", f"/chats/{chat_id}")

    def send_action(self, chat_id, action: str, timeout=None):
        """
        Апи метод отправки действия бота в чат (POST /chats/{chatId}/actions):
        участники видят индикатор «печатает…», «отправляет фото» и т.п.

        :param chat_id: Идентификатор чата
        :param action: Действие MAX (enum SenderAction): typing_on,
            sending_photo, sending_video, sending_audio, sending_file
        :param timeout: Таймаут запроса в секундах на этот вызов

        :return: Json ({"success": bool, "message": str})
        :rtype: Dict[str: Any]
        """
        return self.client.request(
            "POST", f"/chats/{chat_id}/actions", data={"action": action}, timeout=timeout
        )

    def get_bot_info(self):
        """
        Апи метод для получения информации о боте

        :return: Json
        :rtype: Dict[str: Any]
        """
        return self.client.request("GET", "/me")

    def leave_chat(self, chat_id: str):
        """
        Апи метод для получения информации о боте

        :return: Json
        :rtype: Dict[str: Any]
        """
        return self.client.request("DELETE", f"/chats/{chat_id}/members/me")

    def load_file(self, url: str, files: Dict, content_types: str = None):
        """
        Апи метод для получения url загрузки файла.

        :param type_attach: Тип файла, который требуется загрузить
        :type type_attach: str

        :return: Json с url для загрузки файла
        :rtype: Dict[str: Any]
        """
        # тело файла уходит на connect-фазе таймаута — оставляем загрузкам
        # прежний бюджет 60 секунд, а не общий CONNECT_TIMEOUT
        return self.client.request(
            method="POST", url=url, files=files,
            content_types=content_types, timeout=60
        )

    def set_webhook(
        self,
        url: str,
        update_types: Optional[List[str]] = None,
        secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Регистрирует webhook-подписку в MAX API.

        :param url: HTTPS-адрес, на который MAX будет отправлять обновления
        :param update_types: Список типов обновлений для получения (None — все)
        :param secret: Секрет для валидации заголовка X-Max-Bot-Api-Secret (5–256 символов)
        :return: Ответ API
        """
        data: Dict[str, Any] = {"url": url}
        if update_types:
            data["update_types"] = update_types
        if secret:
            data["secret"] = secret
        return self.client.request("POST", "/subscriptions", data=data)

    def delete_webhook(self, url: str) -> Dict[str, Any]:
        """
        Удаляет webhook-подписку.

        :param url: URL подписки для удаления
        :return: Ответ API
        """
        return self.client.request("DELETE", "/subscriptions", params={"url": url})

    def get_webhook_info(self) -> Dict[str, Any]:
        """
        Возвращает список активных webhook-подписок.

        :return: Список подписок
        """
        return self.client.request("GET", "/subscriptions")

    def answer_callback(
            self,
            callback_id: str,
            text: Optional[str] = None,
            notification: Optional[str] = None,
            attachments: Optional[List[Dict[str, Any]]] = None,
            link: Optional[Dict[str, Any]] = None,
            notify: bool = True,
            format: Optional[str] = None,
            disable_link_preview: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Метод позволяет отправить уведомление пользователю и/или обновить
        исходное сообщение после нажатия на inline-кнопку.

        :param callback_id: Уникальный идентификатор callback-запроса.
                            Получается из поля `callback.callback_id` в обновлении
        :type callback_id: str

        :param text: Новый текст сообщения. Если указан, сообщение будет обновлено
        :type text: Optional[str]

        :param notification: Текст всплывающего уведомления для пользователя. 
                             Пользователь увидит это уведомление как всплывающее сообщение
                             Пока не очень работает, в тесте :)
        :type notification: Optional[str]

        :param attachments: Новые вложения сообщения. Если указаны, сообщение будет обновлено.
                            Для полной замены вложений передайте новый список.
                            Чтобы удалить все вложения, передайте пустой список.
        :type attachments: Optional[List[Dict[str, Any]]]

        :param link: Ссылка на сообщение для reply/forward формата.
                     Должен содержать поля `type` ("reply" или "forward") и `mid`
        :type link: Optional[Dict[str, Any]]

        :param notify: Отправлять ли системное уведомление в чат об изменении сообщения.
                       По умолчанию True - участники увидят "Сообщение было изменено"
        :type notify: bool

        :param format: Формат текста сообщения. Доступные значения: "markdown", "html"
        :type format: Optional[str]

        :param disable_link_preview: Если True, сервер не будет генерировать превью
                                     для ссылок в тексте сообщения (query-параметр,
                                     добавлен в MAX API в августе 2026).
                                     None — параметр не отправляется
        :type disable_link_preview: Optional[bool]

        :return: Ответ от MAX API
        :rtype: Dict[str, Any]

        :raises HTTPError: При ошибке HTTP запроса

        Примеры использования:

        1. Только уведомление:
        api.answer_callback(
            callback_id="callback123",
            notification="Действие выполнено!"
        )

        2. Обновление сообщения с уведомлением:
        api.answer_callback(
            callback_id="callback123",
            text="**Сообщение обновлено!**",
            notification="Обновление выполнено",
            format="markdown",
            notify=False  # Не показывать "Сообщение было изменено" в чате
        )

        3, 4. Пока в тесте
        3. Обновление с новыми вложениями:
        api.answer_callback(
            callback_id="callback123",
            text="Вот новые вложения:",
            attachments=[
                {
                    "type": "photo",
                    "payload": {"url": "https://example.com/photo.jpg"}
                }
            ],
            notification="Фотография добавлена"
        )

        4. Удаление всех вложений (оставить только текст):
        api.answer_callback(
            callback_id="callback123",
            text="Вложения удалены",
            attachments=[],  # Пустой список удалит все вложения
            notification="Вложения удалены"
        )
        """
        params = {"callback_id": callback_id}

        # disable_link_preview у POST /answers появился в MAX API в августе 2026;
        # как и у /messages — query-параметр, строкой в нижнем регистре
        if disable_link_preview is not None:
            params["disable_link_preview"] = "true" if disable_link_preview else "false"

        data: Dict[str, Any] = {}

        # Если нужно изменить сообщение (text, attachments, link, format)
        if text is not None or attachments is not None or link is not None or format is not None:
            msg: Dict[str, Any] = {"notify": notify}
            if text is not None:
                msg["text"] = text
            if attachments is not None:
                msg["attachments"] = attachments
            if link is not None:
                msg["link"] = link
            if format is not None:
                msg["format"] = format
            data["message"] = msg

        # Если нужно отправить уведомление
        if notification is not None:
            data["notification"] = notification

        # print(f"Answer params: {params}")
        # print(f"Answer data: {data}")

        # Если data пустой, отправляем пустой объект
        if not data:
            data = {}

        return self.client.request("POST", "/answers", params=params, data=data)

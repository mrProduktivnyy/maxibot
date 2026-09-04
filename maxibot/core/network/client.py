import json
import logging
import threading
import time

from datetime import datetime
from typing import Dict, Any, Optional, Tuple, Union

import requests

from maxibot.exceptions import (
    MaxApiHTTPException,
    MaxApiInvalidJSONException,
    MaxApiRequestException,
)

logger = logging.getLogger("maxibot")


class Client:
    """
    Класс низкоуровневых запросов к API MAX

    Сетевое поведение настраивается модульными переменными maxibot.apihelper
    (API_URL, CA_BUNDLE, proxy, session, CONNECT_TIMEOUT/READ_TIMEOUT,
    SESSION_TIME_TO_LIVE, RETRY_*) — аналог telebot.apihelper. Они читаются
    на каждый запрос, поэтому их можно менять на лету.
    """
    # актуальный домен MAX Bot API (https://dev.max.ru/docs-api); прежние
    # botapi.max.ru и platform-api.max.ru отключены при миграциях 2026 года
    BASE_URL = "https://platform-api2.max.ru"

    def __init__(self, token: str, proxy: Optional[dict] = None):
        """
        Инициализация клиента

        :param token: Токен бота
        :type token: str

        :param proxy: Прокси этого клиента; модульная настройка
            maxibot.apihelper.proxy приоритетнее и читается на каждый запрос
        :type proxy: Optional[dict]
        """
        self.token = token
        self.proxy = proxy
        # сессии requests создаются на поток — requests.Session не потокобезопасна,
        # а запросы идут и из воркеров пула
        self._local = threading.local()

    def _get_session(self, reset: bool = False) -> requests.Session:
        """
        Возвращает requests.Session текущего потока — как
        telebot.apihelper._get_req_session

        apihelper.session — использовать свою сессию (например, со своим
        CA-бандлом или verify=False — см. docs/cert.md);
        apihelper.SESSION_TIME_TO_LIVE — время жизни сессии в секундах,
        None — вечно, 0 — новая сессия на каждый запрос.

        :param reset: Принудительно пересоздать сессию потока
        :type reset: bool
        :return: Сессия для выполнения запроса
        :rtype: requests.Session
        """
        from maxibot import apihelper

        if apihelper.SESSION_TIME_TO_LIVE == 0:
            # одноразовая сессия на запрос; apihelper.session игнорируется —
            # так же ведёт себя telebot._get_req_session
            return self._new_session()

        if apihelper.SESSION_TIME_TO_LIVE:
            created = getattr(self._local, "session_created", None)
            if created is None:
                self._local.session_created = datetime.now()
            elif (datetime.now() - created).total_seconds() > apihelper.SESSION_TIME_TO_LIVE:
                reset = True

        if reset or getattr(self._local, "session", None) is None:
            self._local.session = apihelper.session if apihelper.session else self._new_session()
            self._local.session_created = datetime.now()
        return self._local.session

    @staticmethod
    def _new_session() -> requests.Session:
        """
        Создаёт requests.Session с настроенной TLS-проверкой: по умолчанию
        бандл certifi + встроенные сертификаты Минцифры (ими подписана
        цепочка platform-api2.max.ru), путь из apihelper.CA_BUNDLE или
        False — проверка отключена. Пользовательская apihelper.session
        не трогается — её verify остаётся как настроил пользователь

        :return: Новая сессия
        :rtype: requests.Session
        """
        from maxibot import apihelper

        session = requests.Session()
        if apihelper.CA_BUNDLE is None:
            from maxibot.core.network.cacert import get_ca_bundle_path
            session.verify = get_ca_bundle_path()
        else:
            session.verify = apihelper.CA_BUNDLE
        return session

    def _make_url(self, path: str) -> str:
        """
        Метод формирует полную ссылку к API запросу

        :param path: API метод
        :type path: str
        :return: Полный URL запроса к API
        :rtype: str
        """
        from maxibot import apihelper

        base = apihelper.API_URL or self.BASE_URL
        return f"{base.rstrip('/')}{path}"

    def request(
        self,
        method: str,
        path: str = None,
        url: str = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        content_types: Optional[str] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None
    ) -> Dict[str, Any]:
        """
        Главные метод по отправке запроса к API MAX

        :param method: HTTP-метод (GET, POST, PUT, DELETE)
        :type method: str

        :param path: Путь к методу API
        :type path: str

        :param params: Параметры запроса
        :type params: Optional[Dict[str, Any]]

        :param data: Данные для отправки в теле запроса
        :type data: Optional[Dict[str, Any]]

        :param files: Файлы для отправки
        :type files: Optional[Dict[str, Any]]

        :param timeout: Таймаут только этого запроса: число (секунд) или пара
            (connect, read); по умолчанию берутся apihelper.CONNECT_TIMEOUT
            и apihelper.READ_TIMEOUT
        :type timeout: Optional[Union[float, Tuple[float, float]]]

        :return: Ответ API MAX на заданный метод
        :rtype: Dict[str, Any]
        """
        from maxibot import apihelper

        url = self._make_url(path) if not url else url
        header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/41.0.2272.101 Safari/537.36",
            "Authorization": self.token
        }
        if content_types:
            header["Content-Type"] = content_types
        if data and not files:
            header["Content-Type"] = "application/json"
            data = json.dumps(data)

        connect_timeout = apihelper.CONNECT_TIMEOUT
        read_timeout = apihelper.READ_TIMEOUT
        if timeout is not None:
            if isinstance(timeout, tuple):
                connect_timeout, read_timeout = timeout
            else:
                connect_timeout = read_timeout = timeout
        # long polling: GET /updates держит запрос на сервере до timeout секунд —
        # HTTP-таймаут чтения должен быть больше (в telebot так же:
        # long_polling_timeout + 5); значение может прийти и строкой через extra
        server_hold = params.get("timeout") if params else None
        if server_hold is not None and not isinstance(server_hold, bool):
            try:
                read_timeout = max(read_timeout, float(server_hold) + 5)
            except (TypeError, ValueError):
                pass

        proxies = apihelper.proxy if apihelper.proxy is not None else self.proxy

        request_kwargs = dict(
            method=method,
            url=url,
            params=params,
            data=data,
            files=files,
            headers=header,
            proxies=proxies,
            timeout=(connect_timeout, read_timeout)
        )
        function_name = f"{method} {path or url}"

        response = self._send(function_name, request_kwargs)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            raise MaxApiHTTPException(function_name=function_name, result=response)

        try:
            result = response.json()
        except json.JSONDecodeError:
            raise MaxApiInvalidJSONException(function_name=function_name, result=response)

        if isinstance(result, dict) and result.get('code') and not result.get('success', True):
            raise MaxApiRequestException(
                function_name=function_name,
                result=response,
                result_json=result
            )

        return result

    def _send(self, function_name: str, request_kwargs: Dict[str, Any]) -> requests.Response:
        """
        Выполняет HTTP-запрос, при apihelper.RETRY_ON_ERROR повторяя его после
        сетевых ошибок — как в telebot.apihelper._make_request

        :param function_name: Имя вызова для логов ("GET /updates")
        :type function_name: str

        :param request_kwargs: Аргументы requests.Session.request
        :type request_kwargs: Dict[str, Any]

        :return: HTTP-ответ
        :rtype: requests.Response
        """
        from maxibot import apihelper

        retry_errors = (
            requests.exceptions.HTTPError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        )

        if apihelper.RETRY_ON_ERROR and apihelper.RETRY_ENGINE == 1:
            file_positions = self._seekable_positions(request_kwargs.get("files"))
            for current_try in range(1, apihelper.MAX_RETRIES):
                try:
                    return self._get_session().request(**request_kwargs)
                except retry_errors as error:
                    logger.debug(
                        "Сетевая ошибка на %s (попытка %s): %s",
                        function_name, current_try, error
                    )
                    time.sleep(apihelper.RETRY_TIMEOUT)
                    self._rewind_files(request_kwargs.get("files"), file_positions)
            return self._get_session().request(**request_kwargs)

        if apihelper.RETRY_ON_ERROR and apihelper.RETRY_ENGINE == 2:
            http = self._get_session()
            retry_strategy = requests.packages.urllib3.util.retry.Retry(
                total=apihelper.MAX_RETRIES,
            )
            adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
            for prefix in ("http://", "https://"):
                http.mount(prefix, adapter)
            return http.request(**request_kwargs)

        return self._get_session().request(**request_kwargs)

    @staticmethod
    def _seekable_positions(files: Optional[Dict[str, Any]]) -> Dict[str, int]:
        """
        Запоминает стартовые позиции file-like объектов в files — при повторе
        запроса requests читает поток заново, и без перемотки вторая попытка
        молча отправила бы пустой файл

        :param files: Файлы запроса
        :type files: Optional[Dict[str, Any]]
        :return: Позиции по ключам files
        :rtype: Dict[str, int]
        """
        positions = {}
        for key, value in (files or {}).items():
            if hasattr(value, "seek") and hasattr(value, "tell"):
                try:
                    positions[key] = value.tell()
                except (OSError, ValueError):
                    pass
        return positions

    @staticmethod
    def _rewind_files(files: Optional[Dict[str, Any]], positions: Dict[str, int]) -> None:
        """
        Перематывает file-like объекты на запомненные позиции перед повтором

        :param files: Файлы запроса
        :type files: Optional[Dict[str, Any]]

        :param positions: Позиции из _seekable_positions
        :type positions: Dict[str, int]
        """
        for key, position in positions.items():
            try:
                files[key].seek(position)
            except (OSError, ValueError):
                pass

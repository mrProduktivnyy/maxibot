class MaxApiException(Exception):
    """
    Базовое исключение для ошибок MAX API.

    :param msg: Описание ошибки
    :param function_name: Метод/эндпоинт, вызвавший ошибку
    :param result: Объект ответа requests.Response
    """

    def __init__(self, msg: str, function_name: str, result):
        super().__init__(f"Запрос к MAX API завершился с ошибкой. {msg}")
        self.function_name = function_name
        self.result = result


class MaxApiHTTPException(MaxApiException):
    """
    HTTP-статус ответа отличается от 2xx.
    """

    def __init__(self, function_name: str, result):
        super().__init__(
            f"Сервер вернул HTTP {result.status_code} {result.reason}. "
            f"Тело ответа:\n[{result.text}]",
            function_name,
            result
        )
        self.status_code: int = result.status_code


class MaxApiInvalidJSONException(MaxApiException):
    """
    Сервер вернул невалидный JSON.
    """

    def __init__(self, function_name: str, result):
        super().__init__(
            f"Сервер вернул невалидный JSON. Тело ответа:\n[{result.text}]",
            function_name,
            result
        )


class MaxApiRequestException(MaxApiException):
    """
    MAX API вернул ответ с описанием ошибки в теле (code + message).
    """

    def __init__(self, function_name: str, result, result_json: dict):
        super().__init__(
            f"Код ошибки: {result_json.get('code')}. "
            f"Описание: {result_json.get('message')}",
            function_name,
            result
        )
        self.result_json = result_json
        self.error_code: str = result_json.get('code')
        self.description: str = result_json.get('message')


class MaxApiNotReadyException(MaxApiException):
    """
    Загруженное вложение не было обработано MAX за отведённое время.

    MAX обрабатывает загруженный файл асинхронно и до окончания обработки
    отклоняет отправку сообщения с ошибкой ``attachment.not.ready``.
    Бросается, когда бюджет ретраев (``bot.send_retry_timeout``) исчерпан,
    а файл так и не был готов.
    """

    def __init__(self, msg: str, function_name: str = None, result=None):
        super().__init__(msg, function_name, result)

import json
import logging
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Callable, Optional

logger = logging.getLogger("maxibot")

# Кап на тело запроса: обновления MAX — килобайты, а тело приходится
# вычитывать до проверки секрета (см. do_POST) — без капа
# неаутентифицированный клиент мог бы скармливать серверу гигабайты
MAX_BODY_SIZE = 8 * 1024 * 1024


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class WebhookServer:
    """
    Класс HTTP-сервера для получения обновлений через webhook
    """

    def __init__(
        self,
        host: str,
        port: int,
        secret: Optional[str] = None,
        on_error: Optional[Callable] = None,
    ):
        """
        :param host: Адрес для прослушивания (например, '0.0.0.0')
        :param port: Порт для прослушивания
        :param secret: Секрет для валидации заголовка X-Max-Bot-Api-Secret
        :param on_error: Колбэк отчёта об ошибке (exception, message) —
            MaxiBot передаёт сюда _report_exception, чтобы ошибки webhook
            уходили в exception_handler; None — просто логирование
        """
        self.host = host
        self.port = port
        self.secret = secret
        self.on_error = on_error
        self._server: Optional[_ThreadedHTTPServer] = None
        self.is_running = False

    def _report(self, exception: Exception, message: str):
        """
        Отчёт об ошибке: через on_error бота (exception_handler + логгер),
        без него — в логгер. Вызывается из except-блока.
        """
        if self.on_error is not None:
            self.on_error(exception, message)
        else:
            logger.error("%s: %s", message, exception)
            logger.debug("Exception traceback:\n%s", traceback.format_exc())

    def start(self, handler: Callable[[dict], None]):
        """
        Запускает сервер в фоновом потоке (daemon).

        :param handler: Функция-обработчик, принимающая dict с данными обновления
        """
        secret = self.secret
        report = self._report

        class _RequestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                # тело читается до ответа в любой ветке: ответ с непрочитанным
                # телом в сокете обрывает соединение сбросом (RST), и клиент
                # вместо чистого 403 получает Connection reset
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    self.close_connection = True
                    self.send_response(400)
                    self.end_headers()
                    return
                if length < 0 or length > MAX_BODY_SIZE:
                    # не читая тело: соединение всё равно закрывается
                    self.close_connection = True
                    self.send_response(413)
                    self.end_headers()
                    return
                body = self.rfile.read(length)

                if secret:
                    received = self.headers.get("X-Max-Bot-Api-Secret", "")
                    if received != secret:
                        self.send_response(403)
                        self.end_headers()
                        return

                self.send_response(200)
                self.end_headers()

                try:
                    update = json.loads(body)
                    handler(update)
                except Exception as e:
                    report(e, "Webhook handler error")

            def log_message(self, format, *args):
                pass

        self._server = _ThreadedHTTPServer((self.host, self.port), _RequestHandler)
        # serve_forever блокирует — запускаем в daemon-потоке через сам сервер
        import threading
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        self.is_running = True
        logger.info("Webhook server listening on %s:%s", self.host, self.port)

    def stop(self):
        """
        Останавливает сервер.
        """
        if self._server:
            self._server.shutdown()
        self.is_running = False
        logger.info("Webhook server stopped")

import json
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Callable, Optional


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class WebhookServer:
    """
    Класс HTTP-сервера для получения обновлений через webhook
    """

    def __init__(self, host: str, port: int, secret: Optional[str] = None):
        """
        :param host: Адрес для прослушивания (например, '0.0.0.0')
        :param port: Порт для прослушивания
        :param secret: Секрет для валидации заголовка X-Max-Bot-Api-Secret
        """
        self.host = host
        self.port = port
        self.secret = secret
        self._server: Optional[_ThreadedHTTPServer] = None
        self.is_running = False

    def start(self, handler: Callable[[dict], None]):
        """
        Запускает сервер в фоновом потоке (daemon).

        :param handler: Функция-обработчик, принимающая dict с данными обновления
        """
        secret = self.secret

        class _RequestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                if secret:
                    received = self.headers.get("X-Max-Bot-Api-Secret", "")
                    if received != secret:
                        self.send_response(403)
                        self.end_headers()
                        return

                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)

                self.send_response(200)
                self.end_headers()

                try:
                    update = json.loads(body)
                    handler(update)
                except Exception:
                    print(f"Webhook handler error: {traceback.format_exc()}")

            def log_message(self, format, *args):
                pass

        self._server = _ThreadedHTTPServer((self.host, self.port), _RequestHandler)
        # serve_forever блокирует — запускаем в daemon-потоке через сам сервер
        import threading
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        self.is_running = True
        print(f"Webhook server listening on {self.host}:{self.port}")

    def stop(self):
        """
        Останавливает сервер.
        """
        if self._server:
            self._server.shutdown()
        self.is_running = False
        print("Webhook server stopped")

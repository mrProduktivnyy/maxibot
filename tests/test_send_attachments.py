"""
Проверка надёжной отправки вложений (issue #48): ретраи по бюджету времени,
MaxApiNotReadyException при отказе, ожидание публикации сообщения.

Тест использует стабы вместо реального API. Важно: на ветке с обработкой
исключений (#33) реальный ``api.send_message`` / ``api.get_message`` при ошибке
БРОСАЕТ ``MaxApiException``, а не возвращает строку — поэтому фейки здесь тоже
бросают исключения.

Запуск:
    python3 tests/test_send_attachments.py
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None  # ускоряем ретраи

from maxibot import MaxiBot, MaxApiNotReadyException
from maxibot.exceptions import MaxApiHTTPException

SEND_OK = {
    "message": {
        "sender": {"user_id": 1, "is_bot": True, "first_name": "b", "name": "b", "last_name": None},
        "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 7},
        "timestamp": 1751400000000,
        "body": {"mid": "mid.123", "seq": 5, "text": "hi", "attachments": [
            {"type": "file", "payload": {"url": "https://f", "token": "t"}}
        ]},
    }
}
GET_READY = {"recipient": SEND_OK["message"]["recipient"], "body": SEND_OK["message"]["body"]}
GET_NOT_READY = {"recipient": SEND_OK["message"]["recipient"],
                 "body": {"mid": "mid.123", "attachments": [{"type": "file", "payload": {"token": "t"}}]}}


class FakeResponse:
    """Минимальный объект-ответ, как у requests.Response, для конструирования исключений."""
    def __init__(self, status_code, text, reason="Error"):
        self.status_code = status_code
        self.text = text
        self.reason = reason


def not_ready_error():
    """Исключение, эквивалентное attachment.not.ready (HTTP 400) от реального клиента."""
    return MaxApiHTTPException(
        function_name="POST /messages",
        result=FakeResponse(400, '{"code": "attachment.not.ready"}', "Bad Request")
    )


def not_found_error():
    """Исключение 404 — сообщение ещё не опубликовано."""
    return MaxApiHTTPException(
        function_name="GET /messages/mid.123",
        result=FakeResponse(404, '{"code": "not.found"}', "Not Found")
    )


# Маркеры для очереди ответов, которые фейк должен превратить в исключение
NOT_READY = object()
NOT_FOUND = object()


class FakeApi:
    def __init__(self, send_responses, get_responses):
        self.send_responses = list(send_responses)
        self.get_responses = list(get_responses)
        self.send_calls = 0
        self.get_calls = 0

    def get_upload_file_url(self, type_attach):
        return {"url": "https://upload"}

    def load_file(self, url, files, content_types=None):
        # порядок ключей важен: photo-ветка to_dict берёт первое значение словаря
        return {"photos": {"k": {"token": "t"}}, "token": "t"}

    def send_message(self, **kwargs):
        self.send_calls += 1
        resp = self.send_responses.pop(0) if self.send_responses else SEND_OK
        if resp is NOT_READY:
            raise not_ready_error()
        return resp

    def get_message(self, mid):
        self.get_calls += 1
        resp = self.get_responses.pop(0) if self.get_responses else GET_READY
        if resp is NOT_FOUND:
            raise not_found_error()
        return resp

    def get_chat_info(self, chat_id):
        return {"title": "chat"}


def make_bot(api):
    bot = MaxiBot.__new__(MaxiBot)
    bot.api = api
    bot.count_retries = 10
    bot.send_retry_timeout = 120
    bot.publish_wait_timeout = 10
    return bot


# 1. Обычная отправка: 1 send + 1 get, порядок не задерживается
api = FakeApi([SEND_OK], [GET_READY])
msg = make_bot(api).send_document(42, io.BytesIO(b'x'), caption='c', parse_mode='HTML', visible_file_name='a.pdf')
assert msg.message_id == 'mid.123'
assert api.send_calls == 1 and api.get_calls == 1, (api.send_calls, api.get_calls)
print('1 ok: обычная отправка')

# 2. attachment.not.ready 15 раз (больше старых 10 попыток), потом успех
api = FakeApi([NOT_READY] * 15 + [SEND_OK], [GET_READY])
msg = make_bot(api).send_document(42, io.BytesIO(b'x'), parse_mode='HTML', visible_file_name='a.pdf')
assert msg.message_id == 'mid.123'
assert api.send_calls == 16, api.send_calls
print('2 ok: ретраи дольше старого лимита в 10 попыток')

# 3. Публикация с задержкой: сообщение недоступно/вложение не готово, потом готово
api = FakeApi([SEND_OK], [NOT_FOUND, GET_NOT_READY, GET_READY])
make_bot(api).send_document(42, io.BytesIO(b'x'), parse_mode='HTML', visible_file_name='a.pdf')
assert api.get_calls == 3, api.get_calls
print('3 ok: дожидаемся публикации перед возвратом')

# 4. Отправка не принята за весь бюджет -> MaxApiNotReadyException
api = FakeApi([NOT_READY] * 1000, [])
bot = make_bot(api)
bot.send_retry_timeout = 0
try:
    bot.send_document(42, io.BytesIO(b'x'), parse_mode='HTML', visible_file_name='a.pdf')
    raise AssertionError('должен был упасть')
except MaxApiNotReadyException as e:
    print(f'4 ok: MaxApiNotReadyException: {e}')

# 5. Таймаут ожидания публикации не роняет отправку
api = FakeApi([SEND_OK], [NOT_FOUND] * 1000)
bot = make_bot(api)
bot.publish_wait_timeout = 0
msg = bot.send_document(42, io.BytesIO(b'x'), parse_mode='HTML', visible_file_name='a.pdf')
assert msg.message_id == 'mid.123'
print('5 ok: таймаут публикации не блокирует')

# 6. send_media_group теперь тоже ретраит (раньше — одна попытка и пустой Message)
api = FakeApi([NOT_READY, SEND_OK], [GET_READY])
msg = make_bot(api).send_media_group(42, [io.BytesIO(b'x')], caption='c', parse_mode='html')
assert msg.message_id == 'mid.123'
assert api.send_calls == 2, api.send_calls
print('6 ok: send_media_group с ретраями')

# 7. parse_mode=None у send_document больше не падает на .lower()
api = FakeApi([SEND_OK], [GET_READY])
msg = make_bot(api).send_document(42, io.BytesIO(b'x'), visible_file_name='a.pdf')
assert msg.message_id == 'mid.123'
print('7 ok: parse_mode=None не падает')

# 8. Не-attachment ошибка не ретраится, а сразу пробрасывается наружу
api = FakeApi([], [])

def _raise_other(**kwargs):
    api.send_calls += 1
    raise MaxApiHTTPException(
        function_name="POST /messages",
        result=FakeResponse(400, '{"code": "chat.not.found"}', "Bad Request")
    )

api.send_message = _raise_other
bot = make_bot(api)
try:
    bot.send_document(42, io.BytesIO(b'x'), visible_file_name='a.pdf')
    raise AssertionError('должна была проброситься исходная ошибка')
except MaxApiHTTPException:
    assert api.send_calls == 1, api.send_calls  # без ретраев
    print('8 ok: посторонняя ошибка не ретраится')

print('ALL OK')

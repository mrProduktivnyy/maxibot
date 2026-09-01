import asyncio
# import json
import logging
import queue
import re
import threading
import time
import traceback

from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Callable, Union

from maxibot.apihelper import Api
from maxibot.types import Message, CallbackQuery, InputMedia
from maxibot.types import UpdateType, InlineKeyboardMarkup
from maxibot.util import extract_command, get_text, get_parse_mode, get_edit_message_data
from maxibot.exceptions import (
    MaxApiException,
    MaxApiHTTPException,
    MaxApiInvalidJSONException,
    MaxApiRequestException,
    MaxApiNotReadyException,
)
from maxibot.core.network.polling import Polling
from maxibot.core.network.webhook import WebhookServer


HandlerFunc = Callable[[Message], None]

logger = logging.getLogger("maxibot")


@dataclass
class StepHandler:
    callback: Callable
    args: tuple
    kwargs: dict
    timestamp: float


class _WorkerPool:
    """
    Пул демон-потоков для выполнения обработчиков — аналог util.ThreadPool
    из telebot. Именно демон-потоки (ThreadPoolExecutor так не умеет):
    как и в telebot, Ctrl+C завершает процесс сразу, не дожидаясь
    зависших или стоящих в очереди обработчиков.
    """

    def __init__(self, num_threads: int):
        self._queue = queue.Queue()
        self._threads = []
        for i in range(num_threads):
            thread = threading.Thread(
                target=self._worker, name=f"maxibot-worker_{i}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def submit(self, task: Callable, *args, **kwargs):
        self._queue.put((task, args, kwargs))

    def _worker(self):
        while True:
            task, args, kwargs = self._queue.get()
            try:
                task(*args, **kwargs)
            except Exception:
                # страховка, чтобы поток пула не умер; сами обработчики
                # уже обёрнуты в MaxiBot._run_task
                print(f"Error while processing update: {traceback.format_exc()}")
            finally:
                self._queue.task_done()


class MaxiBot:
    """
    Главный класс бота
    """
    def __init__(self, token: str, threaded: bool = True, num_threads: int = 2):
        """
        Метод инициализации бота

        :param token: Токен бота
        :type token: str

        :param threaded: Как в telebot: если True (по умолчанию),
            обработчики выполняются в пуле потоков и медленный обработчик
            не блокирует остальных пользователей. False — прежняя
            последовательная обработка в потоке поллинга
        :type threaded: bool

        :param num_threads: Размер пула потоков для обработчиков
            (используется при threaded=True). По умолчанию 2, как в telebot
        :type num_threads: int
        """
        self.api = Api(token=token)
        self.threaded = threaded
        self.num_threads = num_threads
        if threaded:
            self._worker_pool = _WorkerPool(num_threads=num_threads)
        else:
            self._worker_pool = None
        self.handlers = {
            "update": [],  # Общие обработчики для всех типов обновлений
            UpdateType.MESSAGE_CREATED: [],
            UpdateType.MESSAGE_CALLBACK: [],
            UpdateType.BOT_STARTED: [],
            UpdateType.MESSAGE_EDITED: [],
            UpdateType.MESSAGE_DELETED: [],
            UpdateType.MESSAGE_CHAT_CREATED: [],
        }
        self.message_handlers = []
        self.callback_query_handlers = []
        self.poll = None
        self._webhook: WebhookServer = None
        self.is_running = False
        self.count_retries = 10  # устарело, оставлено для совместимости
        # Сколько секунд повторять отправку сообщения, пока MAX обрабатывает
        # загруженное вложение (ошибка attachment.not.ready). Файлы от
        # нескольких мегабайт обрабатываются заметно дольше 10 секунд.
        self.send_retry_timeout = 120
        # Сколько секунд ждать фактической публикации сообщения с файлом в
        # чате, чтобы следующие отправленные сообщения не появились раньше него.
        self.publish_wait_timeout = 10
        self._next_steps: Dict[int, StepHandler] = {}

    @staticmethod
    def _build_handler_dict(handler: HandlerFunc, **filters):
        """
        Функция, которая формирует словарь для добавления в список обработчиков событий (handler)

        :param handler: Description
        :type handler: HandlerFunc
        :param filters: Description
        """
        return {
            'function': handler,
            'filters': {ftype: fvalue for ftype, fvalue in filters.items() if fvalue is not None}
        }

    def polling(self, allowed_updates: Optional[List[str]] = None):
        """
        Запускает получение обновлений через long polling.
        """
        asyncio.run(self.start(allowed_updates=allowed_updates))

    def _skip_updates(self):
        """
        Пропускает обновления, накопленные до запуска бота (skip_pending).

        Крутит GET /updates с timeout=0 (запрос возвращается сразу, без
        long polling), подтверждая полученное маркером, пока очередь не
        опустеет — поллинг после этого начнёт с чистого листа.
        """
        marker = None
        while True:
            params = {"timeout": 0}
            if marker is not None:
                params["marker"] = marker
            data = self.api.get_updates([], params) or {}
            new_marker = data.get("marker")
            if not data.get("updates") or new_marker is None or new_marker == marker:
                break
            marker = new_marker

    def infinity_polling(
        self,
        timeout: Optional[int] = 20,
        skip_pending: Optional[bool] = False,
        long_polling_timeout: Optional[int] = 20,
        logger_level: Optional[int] = logging.ERROR,
        allowed_updates: Optional[List[str]] = None,
        restart_on_change: Optional[bool] = False,
        path_to_watch: Optional[str] = None,
        *args,
        **kwargs
    ):
        """
        Запускает polling в бесконечном цикле с обработкой исключений,
        чтобы бот не останавливался из-за ошибок. Сигнатура один в один
        с telebot.infinity_polling; выход — через bot.stop() или Ctrl+C
        (KeyboardInterrupt не перехватывается).

        :param timeout: Принимается для совместимости с telebot и
            игнорируется — таймаутами соединения управляет клиент MAX
        :type timeout: Optional[int]

        :param skip_pending: Пропустить обновления, накопленные до запуска
        :type skip_pending: Optional[bool]

        :param long_polling_timeout: Принимается для совместимости с telebot
            и игнорируется — длительность long polling задаёт сервер MAX
            (по умолчанию 30 секунд)
        :type long_polling_timeout: Optional[int]

        :param logger_level: Уровень логирования ошибок цикла (значения из
            модуля logging). None/NOTSET — ошибки не логируются
        :type logger_level: Optional[int]

        :param allowed_updates: Список типов обновлений, которые нужно
            получать. None — все типы
        :type allowed_updates: Optional[List[str]]

        :param restart_on_change: Принимается для совместимости с telebot
            и игнорируется — перезапуск по изменению файлов не поддерживается
        :type restart_on_change: Optional[bool]

        :param path_to_watch: Принимается для совместимости с telebot
            и игнорируется
        :type path_to_watch: Optional[str]

        :return: None
        """
        if skip_pending:
            self._skip_updates()

        if restart_on_change:
            logger.warning("restart_on_change не поддерживается maxibot и игнорируется")

        while True:
            try:
                self.polling(allowed_updates=allowed_updates)
            except Exception as e:
                if logger_level and logger_level >= logging.ERROR:
                    logger.error("Infinity polling exception: %s", str(e))
                if logger_level and logger_level >= logging.DEBUG:
                    logger.error("Exception traceback:\n%s", traceback.format_exc())
                # без сброса флага start() откажется перезапускаться
                self.is_running = False
                time.sleep(3)
                continue
            if not self.is_running:
                break
            # polling завершился сам, но stop() не вызывали — перезапускаем
            if logger_level and logger_level >= logging.INFO:
                logger.error("Infinity polling: polling exited")
            time.sleep(3)
        if logger_level and logger_level >= logging.INFO:
            logger.error("Break infinity polling")

    def stop(self):
        """
        Останавливает polling или webhook-сервер бота
        """
        if not self.is_running:
            print("Bot is not running")
            return None
        if self.poll:
            self.poll.stop()
        if self._webhook:
            self._webhook.stop()
        self.is_running = False

    async def start(self, allowed_updates: Optional[List[str]] = None):
        """
        Метод запускает получение обновлений по боту

        :param allowed_updates: Description
        :type allowed_updates: Optional[List[str]]
        """
        if self.is_running:
            print("Bot is already running")
            return None
        self.is_running = True
        self.poll = Polling(api=self.api, allowed_updates=allowed_updates)
        await self.poll.loop(self._process_update)

    # def on(self, update_type: str):
    #     """
    #     Декоратор для регистрации обработчика определенного типа обновлений

    #     :param update_type: Тип обновления (см. UpdateType)
    #     """
    #     def decorator(func: HandlerFunc):
    #         self.handlers.setdefault(update_type, []).append(func)
    #         return func
    #     return decorator

    def message_handler(
        self,
        commands: Optional[List[str]] = None,
        regexp: Optional[str] = None,
        func: Optional[Callable] = None,
        content_types: Optional[List[str]] = None,
        chat_types: Optional[List[str]] = None
    ):
        """
        Декоратор для регистрации обработчика текстовых сообщений по шаблону

        :param pattern: Шаблон текста (точное совпадение или регулярное выражение)
        :type pattern: str
        """
        def decorator(funcs: HandlerFunc):
            handler_dict = self._build_handler_dict(
                funcs,
                commands=commands,
                regexp=regexp,
                func=func,
                content_types=content_types,
                chat_types=chat_types
            )
            self.message_handlers.append(handler_dict)
            return funcs
        return decorator

    def run_handler(self, context: Message, message_handlers: List[Dict]):
        """
        Метод запуска обработчиков событий текстового сообщения

        :param context: Description
        :type context: Context
        """
        for handler in message_handlers:
            if self._check_filters(context=context, handler=handler):
                self._exec_task(handler.get("function"), context)
                break

    def _test_filter(self, message_filter: str, filter_value: List, context: Message):
        """
        Метод проверки соответствия сообщения всем фильтрам текстовых сообщений

        :param message_filter: Description
        :type message_filter: str
        :param filter_value: Description
        :type filter_value: List
        :param context: Description
        :type context: Context
        """

        text = context.text
        if message_filter == 'content_types':
            return context.content_type in filter_value
        if message_filter == 'regexp':
            return re.search(filter_value, text, re.IGNORECASE)
        elif message_filter == 'commands':
            return extract_command(text) in filter_value
        elif message_filter == 'chat_types':
            return context.chat.type in filter_value
        elif message_filter == 'func':
            # print("FUUUUUUUUUUUUUUUUUUUUUUUUNCCCCCCCCCCCCCCCCC")
            return filter_value(context)
        return False

    def _check_filters(self, context, handler: Dict):
        """
        Проверка текстового сообщения на фильтры

        :param context: Сообщение
        :type context: Context
        """
        if handler['filters']:
            if isinstance(context, CallbackQuery):
                # Сначала проверяем фильтр по data
                if 'data' in handler['filters']:
                    filter_data = handler['filters']['data']
                    if context.data != filter_data:
                        return False
                func_filter = handler['filters'].get('func')
                if func_filter:
                    try:
                        return func_filter(context)
                    except Exception as e:
                        print(f"Error in filter function: {e}")
                        return False

                return True
            elif isinstance(context, Message):
                for message_filter, filter_value in handler['filters'].items():
                    if filter_value is None:
                        continue
                    if not self._test_filter(message_filter, filter_value, context):
                        return False
                return True
            return False

    def _process_text_message(self, context: Message):
        """
        Обрабатывает входящее сообщение

        :param context: Контекст обновления
        :type context: Context
        """
        # if text.startswith("/"):
        #     print("Command send. Do nothing now))")
        self.run_handler(context=context, message_handlers=self.message_handlers)
        # for pattern, handler in self.message_handlers:
        #     if pattern == text or re.search(pattern, text):
        #         handler(context)

    def _process_update(self, update: Dict[str, Any]):
        """
        Метод для обработки входящего полученного обновления

        :param update: Данные по обновлениям
        :type update: Dict[str, Any]
        """
        try:
            # print("===============\nUPDATE RECEIVED\n===============")
            # print(f"Update type: {update.get('update_type')}")
            # print(f"Full update: {json.dumps(update, indent=2)}")

            update_type = update.get("update_type")
            if update_type == UpdateType.MESSAGE_CREATED and "message" in update.keys() or \
               update_type == UpdateType.BOT_STARTED or update_type == UpdateType.BOT_ADDED:
                context = Message(update, self.api)
                # атомарный pop вместо `in` + pop: clear_step_handler может
                # выполняться в воркере параллельно и убрать ключ между
                # проверкой и извлечением — сообщение тогда потерялось бы
                handler = self._next_steps.pop(context.from_user.id, None)
                if handler is not None:
                    self._exec_task(handler.callback, context, *handler.args, **handler.kwargs)
                else:
                    self._process_text_message(context)
            elif update_type == UpdateType.MESSAGE_CALLBACK:
                print("Processing message_callback...")
                if "callback" in update:
                    callback = CallbackQuery(update, self.api)
                    # print(f"Created callback: id={callback.id}, data={callback.data}")
                    self._process_callback_query(callback)
        except Exception:
            print(f"Error while processing update: {traceback.format_exc()}")

    def _exec_task(self, task: Callable, *args, **kwargs):
        """
        Выполняет пользовательский обработчик: при threaded=True — в пуле
        потоков (как telebot), иначе синхронно в текущем потоке. Фильтры
        при этом всегда проверяются в потоке поллинга, в пул уходит
        только сам обработчик.
        """
        if getattr(self, "_worker_pool", None):
            self._worker_pool.submit(self._run_task, task, *args, **kwargs)
        else:
            self._run_task(task, *args, **kwargs)

    @staticmethod
    def _run_task(task: Callable, *args, **kwargs):
        """
        Вызов обработчика с перехватом ошибок: исключение в потоке пула
        иначе молча потерялось бы внутри Future.
        """
        try:
            task(*args, **kwargs)
        except Exception:
            print(f"Error while processing update: {traceback.format_exc()}")

    def _check_text_length(self, text):
        """
        Проверки длины строки
        """
        return text is not None and not (len(text) < 4000)

    def register_next_step_handler(self, message: Message, callback: Callable, *args, **kwargs):
        """
        Регистрирует функцию обратного вызова для получения уведомления о поступлении нового сообщения после `message`.

        Предупреждение: Если `callback` используется как лямбда-функция,
        сохранение обработчиков следующего шага работать не будет.

        :param message: Объект сообщения
        :type message: Message
        :param callback: Функция обратного вызова
        :type callback: Callable
        :param args:
        :param kwargs:
        """

        handler = StepHandler(
            callback=callback,
            args=args,
            kwargs=kwargs,
            timestamp=time.time()
        )
        self._next_steps[message.from_user.id] = handler

    def clear_step_handler(self, message: Message) -> None:
        """
        Сбрасывает обработчик, зарегистрированный через register_next_step_handler().

        Сигнатура один в один с telebot. Используется, когда пользователь ушёл
        в другой раздел меню, не ответив на ожидаемый вопрос.

        :param message: Сообщение из чата, для которого сбрасывается ожидание
        :type message: Message

        :return: None
        """
        self.clear_step_handler_by_chat_id(message.chat.id)

    def clear_step_handler_by_chat_id(self, chat_id: Union[int, str]) -> None:
        """
        Сбрасывает обработчик, зарегистрированный через register_next_step_handler().

        Сигнатура один в один с telebot. В maxibot step-handlers ключуются по
        ``from_user.id``, который в MAX равен ``chat_id`` диалога (см. класс User) —
        поэтому chat_id здесь и есть ключ.

        :param chat_id: Чат, для которого сбрасывается ожидание ввода
        :type chat_id: Union[int, str]

        :return: None
        """
        self._next_steps.pop(chat_id, None)
        # register_next_step_handler мог положить ключ и как int, и как str —
        # подчищаем оба представления
        if isinstance(chat_id, str) and chat_id.isdigit():
            self._next_steps.pop(int(chat_id), None)
        elif isinstance(chat_id, int):
            self._next_steps.pop(str(chat_id), None)

    # -------------------------------------------------------------------------
    # Webhook
    # -------------------------------------------------------------------------

    def set_webhook(
        self,
        url: str,
        secret: Optional[str] = None,
        allowed_updates: Optional[List[str]] = None
    ) -> dict:
        """
        Регистрирует webhook в MAX API.

        :param url: Публичный HTTPS-адрес, на который MAX будет слать обновления
        :param secret: Секрет для проверки заголовка X-Max-Bot-Api-Secret (5–256 символов)
        :param allowed_updates: Список типов обновлений (None — все)
        """
        return self.api.set_webhook(url=url, update_types=allowed_updates, secret=secret)

    def delete_webhook(self, url: str) -> dict:
        """
        Удаляет webhook-подписку из MAX API.

        :param url: URL подписки для удаления
        """
        return self.api.delete_webhook(url=url)

    def get_webhook_info(self) -> dict:
        """
        Возвращает список активных webhook-подписок.
        """
        return self.api.get_webhook_info()

    def start_webhook(
        self,
        host: str = "0.0.0.0",
        port: int = 443,
        secret: Optional[str] = None,
        webhook_url: Optional[str] = None,
        allowed_updates: Optional[List[str]] = None
    ):
        """
        Запускает локальный HTTP-сервер для приёма обновлений через webhook.

        :param host: Адрес для прослушивания (по умолчанию '0.0.0.0')
        :param port: Порт для прослушивания (по умолчанию 443, как требует MAX)
        :param secret: Секрет для валидации заголовка X-Max-Bot-Api-Secret (опционально)
        :param webhook_url: Если указан — автоматически регистрирует этот URL в MAX API
                            через POST /subscriptions
        :param allowed_updates: Список типов обновлений (None — все)

        Пример использования::

            bot.start_webhook(
                host="0.0.0.0",
                port=443,
                secret="my-secret",
                webhook_url="https://example.com/webhook"
            )
        """
        if self.is_running:
            print("Bot is already running")
            return

        if webhook_url:
            self.set_webhook(url=webhook_url, secret=secret, allowed_updates=allowed_updates)

        self._webhook = WebhookServer(host=host, port=port, secret=secret)
        self._webhook.start(handler=self._process_update)
        self.is_running = True

        try:
            import time
            while self.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.stop()

    def _send_attachments(self, chat_id, text, attachments, parse_mode, disable_link_preview=None):
        """
        Отправляет сообщение с вложениями, повторяя отправку, пока MAX
        обрабатывает загруженный файл (ошибка ``attachment.not.ready``).

        Вложение при этом повторно не загружается — используется уже
        полученный токен. Если API так и не принял сообщение за
        ``send_retry_timeout`` секунд, выбрасывается ``MaxApiNotReadyException``
        вместо возврата пустого объекта Message без атрибутов.
        """
        deadline = time.monotonic() + self.send_retry_timeout
        pause = 1
        while True:
            try:
                response = self.api.send_message(
                    chat_id=chat_id,
                    text=text,
                    attachments=attachments,
                    parse_mode=parse_mode,
                    disable_link_preview=disable_link_preview
                )
                break
            except MaxApiException as exc:
                if not self._is_attachment_not_ready(exc):
                    raise
                if time.monotonic() + pause > deadline:
                    raise MaxApiNotReadyException(
                        f"MAX API не принял сообщение за {self.send_retry_timeout} c "
                        f"(вложение не обработано): {exc}",
                        function_name=getattr(exc, "function_name", None),
                        result=getattr(exc, "result", None)
                    ) from exc
                time.sleep(pause)
                pause = min(pause + 1, 5)

        message = Message(update=response, api=self.api)
        self._wait_message_published(message)
        return message

    def _wait_message_published(self, message):
        """
        Ждёт, пока отправленное сообщение с файлом станет видно в чате.

        MAX публикует сообщение с файловым вложением только после окончания
        обработки файла, поэтому сообщение, отправленное следом, может
        появиться в чате раньше него. Ожидание сохраняет порядок отправки.
        Если сообщение уже опубликовано (обычный случай), проверка занимает
        один запрос без пауз; по истечении ``publish_wait_timeout`` ожидание
        прекращается без ошибки.
        """
        message_id = getattr(message, "message_id", None)
        if not message_id:
            return
        deadline = time.monotonic() + self.publish_wait_timeout
        while True:
            try:
                info = self.api.get_message(message_id)
                if isinstance(info, dict) and self._file_attachments_ready(info):
                    return
            except MaxApiException:
                # Сообщение ещё не опубликовано (например, 404) — продолжаем ждать.
                pass
            if time.monotonic() >= deadline:
                return
            time.sleep(1)

    @staticmethod
    def _file_attachments_ready(info):
        """
        Проверяет, что у файловых вложений сообщения появился url — признак
        того, что обработка файла закончена и сообщение опубликовано.
        """
        body = (info.get("message") or info).get("body") or {}
        for attachment in body.get("attachments") or []:
            if attachment.get("type") == "file" and not (attachment.get("payload") or {}).get("url"):
                return False
        return True

    @staticmethod
    def _is_attachment_not_ready(exc):
        """
        Определяет, что ошибка API — это ``attachment.not.ready`` (файл ещё
        обрабатывается на стороне MAX), а не какая-то другая ошибка.
        """
        if "attachment.not.ready" in str(exc):
            return True
        result = getattr(exc, "result", None)
        text = getattr(result, "text", "") or ""
        if "attachment.not.ready" in text:
            return True
        result_json = getattr(exc, "result_json", None)
        if isinstance(result_json, dict) and result_json.get("code") == "attachment.not.ready":
            return True
        return False

    def send_photo(
        self,
        chat_id: Union[int, str],
        photo: Union[Any, str],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        disable_web_page_preview: Optional[bool] = None
    ):
        """
        Отправляет сообщение с фото

        :param chat_id: Чат, куда надо отправить сообщение
        :type chat_id: Union[int, str]

        :param photo: Фото — байты, file-like объект, InputMedia или, как
            в telebot, строка: прямая http(s)-ссылка на изображение (MAX
            скачает его сам, без POST /uploads) либо токен ранее
            загруженного изображения (аналог file_id, лежит в
            message.photo.payload.token)
        :type photo: Union[Any, str]

        :param caption: Текст сообщения под фото
        :type caption: Optional[str]

        :param parse_mode: Разметка сообщения
        :type parse_mode: Optional[str]

        :param disable_web_page_preview: Если True, сервер не генерирует превью
            для ссылок в подписи (в MAX caption — это text того же POST /messages).
            В telebot у send_photo параметра нет — расширение для MAX
        :type disable_web_page_preview: Optional[bool]

        :return: Информация об отправленном сообщении
        :rtype: Dict[str, Any]
        """

        if self._check_text_length(text=caption):
            raise ValueError(f'caption должен быть меньше 4000 символов.\nСейчас их {len(caption)}')
        final_attachments = []
        if isinstance(photo, InputMedia):
            final_attachments.append(photo.to_dict(api=self.api))
        else:
            final_attachments.append(InputMedia(media=photo).to_dict(api=self.api))
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)
        return self._send_attachments(chat_id, caption, final_attachments, parse_mode,
                                      disable_link_preview=disable_web_page_preview)

    def send_media_group(
        self,
        chat_id: Union[int, str],
        media: list,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        disable_web_page_preview: Optional[bool] = None
    ):
        """
        Отправляет сообщение с фото

        :param chat_id: Чат, куда надо отправить сообщение
        :type chat_id: Union[int, str]

        :param media: Список фото — байты, file-like объекты, InputMedia
            или, как в telebot, строки: прямые http(s)-ссылки (MAX скачает
            их сам) либо токены ранее загруженных изображений
        :type media: list

        :param caption: Текст сообщения под фото
        :type caption: Optional[str]

        :param parse_mode: Разметка сообщения
        :type parse_mode: Optional[str]

        :param disable_web_page_preview: Если True, сервер не генерирует превью
            для ссылок в подписи. В telebot у send_media_group параметра нет —
            расширение для MAX
        :type disable_web_page_preview: Optional[bool]

        :return: Информация об отправленном сообщении
        :rtype: Dict[str, Any]
        """

        if self._check_text_length(text=caption):
            raise ValueError(f'caption должен быть меньше 4000 символов.\nСейчас их {len(caption)}')
        final_attachments = []
        for photo in media:
            if isinstance(photo, InputMedia):
                final_attachments.append(photo.to_dict(api=self.api))
            else:
                final_attachments.append(InputMedia(media=photo).to_dict(api=self.api))
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)
        return self._send_attachments(chat_id, caption, final_attachments, parse_mode,
                                      disable_link_preview=disable_web_page_preview)

    def send_document(
        self,
        chat_id: Union[int, str],
        document: Union[Any, str],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        visible_file_name: Optional[str] = None,
        disable_web_page_preview: Optional[bool] = None
    ):
        """
        Отправляет сообщение с файлом

        :param chat_id: Чат, куда надо отправить сообщение
        :type chat_id: Union[int, str]

        :param document: Файл — байты или file-like объект. URL-строка не
            поддерживается (ValueError): MAX принимает URL только для
            изображений
        :type document: Union[Any, str]

        :param caption: Текст сообщения под фото
        :type caption: Optional[str]

        :param parse_mode: Разметка сообщения
        :type parse_mode: Optional[str]

        :param disable_web_page_preview: Если True, сервер не генерирует превью
            для ссылок в подписи к файлу. В telebot у send_document параметра
            нет — расширение для MAX
        :type disable_web_page_preview: Optional[bool]

        :return: Информация об отправленном сообщении
        :rtype: Dict[str, Any]
        """

        if self._check_text_length(text=caption):
            raise ValueError(f'caption должен быть меньше 4000 символов.\nСейчас их {len(caption)}')
        if isinstance(document, str) and document.startswith(("http://", "https://")):
            raise ValueError(
                "MAX принимает URL только для изображений (send_photo). "
                "Документ можно отправить только байтами или file-like объектом"
            )
        final_attachments = []
        if isinstance(document, InputMedia) and document.type == "file":
            final_attachments.append(document.to_dict(api=self.api))
        else:
            final_attachments.append(
                InputMedia(type="file", media=document).to_dict(api=self.api, file_name=visible_file_name)
            )
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)
        return self._send_attachments(
            chat_id, caption, final_attachments,
            parse_mode.lower() if parse_mode else None,
            disable_link_preview=disable_web_page_preview
        )

    def send_video(
        self,
        chat_id: Union[int, str],
        video: Union[Any, str],
        duration: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        thumbnail: Optional[Any] = None,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        disable_web_page_preview: Optional[bool] = None
    ):
        """
        Отправляет сообщение с видео. Порядок первых позиционных параметров —
        как у telebot.send_video: (chat_id, video, duration, width, height,
        thumbnail, caption, parse_mode).

        Видео загружается в MAX через POST /uploads?type=video (форматы
        MP4/MOV/MKV/WEBM, до 250 МБ), затем отправляется вложением
        {"type": "video", "payload": {"token": ...}} в POST /messages.

        :param chat_id: Чат, куда надо отправить сообщение
        :type chat_id: Union[int, str]

        :param video: Видео — байты или file-like объект. URL-строка не
            поддерживается (ValueError): MAX принимает URL только для
            изображений
        :type video: Union[Any, str]

        :param duration: Принимается для совместимости с telebot и
            игнорируется — MAX определяет длительность из самого файла
        :type duration: Optional[int]

        :param width: Принимается для совместимости с telebot и игнорируется —
            MAX определяет ширину из самого файла
        :type width: Optional[int]

        :param height: Принимается для совместимости с telebot и игнорируется —
            MAX определяет высоту из самого файла
        :type height: Optional[int]

        :param thumbnail: Принимается для совместимости с telebot и
            игнорируется — Bot API MAX не позволяет задать обложку видео
        :type thumbnail: Optional[Any]

        :param caption: Текст сообщения под видео
        :type caption: Optional[str]

        :param parse_mode: Разметка сообщения
        :type parse_mode: Optional[str]

        :param disable_web_page_preview: Если True, сервер не генерирует превью
            для ссылок в подписи. В telebot у send_video параметра нет —
            расширение для MAX
        :type disable_web_page_preview: Optional[bool]

        :return: Информация об отправленном сообщении
        :rtype: Message
        """

        if self._check_text_length(text=caption):
            raise ValueError(f'caption должен быть меньше 4000 символов.\nСейчас их {len(caption)}')
        if isinstance(video, str) and video.startswith(("http://", "https://")):
            raise ValueError(
                "MAX принимает URL только для изображений (send_photo). "
                "Видео можно отправить только байтами или file-like объектом"
            )
        final_attachments = []
        if isinstance(video, InputMedia) and video.type == "video":
            final_attachments.append(video.to_dict(api=self.api))
        else:
            final_attachments.append(InputMedia(type="video", media=video).to_dict(api=self.api))
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)
        return self._send_attachments(
            chat_id, caption, final_attachments,
            parse_mode.lower() if parse_mode else None,
            disable_link_preview=disable_web_page_preview
        )

    def delete_message(
        self,
        chat_id: Union[str, int],
        message_id: str,
    ):
        """
        Метод удаления сообщения `message_id` в чате `chat_id`

        :param chat_id: Айди чата
        :type chat_id: Union[str, int]

        :param message_id: Айди сообщения
        :type message_id: int
        """
        self.api.send_message(msg_id=message_id, method="DELETE")
        return {}

    def edit_message_text(
        self,
        text: str,
        chat_id: Union[str, int],
        message_id: str,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        parse_mode: Union[str, Any] = None
    ):
        """
        Метод изменения текстового сообщения `message_id` в чате `chat_id`

        :param text: Текст, на который надо заменить текущий
        :type text: str

        :param chat_id: Айди чата
        :type chat_id: Union[str, int]

        :param message_id: Айди сообщения
        :type message_id: int

        :return: Информация об отправленном сообщении
        :rtype: Message | {} (не успех)
        """
        final_attachments = []

        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)

        response = self.api.send_message(
            msg_id=message_id,
            text=text,
            method="PUT",
            attachments=final_attachments,
            parse_mode=parse_mode
        )

        if isinstance(response, dict) and response.get("success"):
            timestamp = int(time.time() * 1000)
            message_data = get_edit_message_data(text, chat_id, message_id, final_attachments, timestamp)
            return Message(update=message_data, api=self.api)

        return {}

    def edit_message_media(
        self,
        media: Any,
        chat_id: Union[str, int],
        message_id: str,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        parse_mode: Union[str, Any] = "markdown"
    ):
        """
        Метод изменения медиа сообщения `message_id` в чате `chat_id`

        :param media: Медиа, на которое надо заменить текущее
        :type media: str

        :param chat_id: Айди чата
        :type chat_id: Union[str, int]

        :param message_id: Айди сообщения
        :type message_id: int

        :return: Информация об отправленном сообщении
        :rtype: Message | {} (не успех)
        """
        final_attachments = []
        # if isinstance(media, Photo):
        #     final_attachments.append(media.to_dict())
        if isinstance(media, InputMedia):
            final_attachments.append(media.to_dict(api=self.api))
        else:
            final_attachments.append(InputMedia(media=media).to_dict(api=self.api))
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)
        text = get_text(media=media)
        parse_mode = get_parse_mode(media=media, parse_mode=parse_mode)

        response = self.api.send_message(
            msg_id=message_id,
            text=text,
            method="PUT",
            attachments=final_attachments,
            parse_mode=parse_mode
        )

        if isinstance(response, dict) and response.get("success"):
            timestamp = int(time.time() * 1000)
            message_data = get_edit_message_data(text, chat_id, message_id, final_attachments, timestamp)
            return Message(update=message_data, api=self.api)

        return {}

    def edit_message_reply_markup(
        self,
        chat_id: Union[str, int],
        message_id: str,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        parse_mode: Union[str, Any] = "markdown"
    ):
        """
        Метод изменения клавиатуры сообщения `message_id` в чате `chat_id`

        :param chat_id: Айди чата
        :type chat_id: Union[str, int]

        :param message_id: Айди сообщения
        :type message_id: int

        :param reply_markup: Новая клавиатура
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :return: Информация об отправленном сообщении
        :rtype: Message | {} (не успех)
        """
        final_attachments = []
        msg: Message = self.get_message(message_id=message_id)
        if msg.photo:
            final_attachments.append(msg.photo.to_dict())
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)

        response = self.api.send_message(
            msg_id=message_id,
            method="PUT",
            attachments=final_attachments,
            parse_mode=parse_mode
        )

        if isinstance(response, dict) and response.get("success"):
            timestamp = int(time.time() * 1000)
            message_data = get_edit_message_data(None, chat_id, message_id, final_attachments, timestamp)
            return Message(update=message_data, api=self.api)

        return None

    def send_message(
        self,
        chat_id: Union[str, int],
        text: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        reply_markup: Optional[Any] = None,
        parse_mode: str = "markdown",
        notify: bool = True,
        disable_web_page_preview: Optional[bool] = None,
        reply_to_message_id: Optional[str] = None
    ) -> Message:
        """
        Отправляет ответ на текущее сообщение/обновление

        :param text: Текст сообщения
        :type text:

        :param attachments: Вложения сообщения
        :type attachments:

        :param keyboard: Объект клавиатуры (будет добавлен к attachments)
        :type keyboard:

        :param disable_web_page_preview: Если True, сервер не генерирует превью
            для ссылок в тексте (имя параметра как в telebot; в MAX API это
            query-параметр disable_link_preview). None — поведение сервера
            по умолчанию
        :type disable_web_page_preview: Optional[bool]

        :param reply_to_message_id: Идентификатор сообщения, на которое нужно
            ответить (имя параметра как в telebot; в MAX API это поле
            link={"type": "reply", "mid": ...} в теле запроса)
        :type reply_to_message_id: Optional[str]

        :return: Информация об отправленном сообщении
        :rtype: Message
        """
        if self._check_text_length(text=text):
            raise ValueError(f'text должен быть меньше 4000 символов\nСейчас их {len(text)}')
        if isinstance(chat_id, int):
            chat_id = str(chat_id)

        final_attachments = attachments.copy() if attachments else []

        # Если передана клавиатура, добавляем её как вложение
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)

        link = None
        if reply_to_message_id:
            link = {"type": "reply", "mid": reply_to_message_id}

        return Message(
            update=self.api.send_message(
                chat_id=chat_id,
                text=text,
                attachments=final_attachments,
                parse_mode=parse_mode.lower(),
                notify=notify,
                disable_link_preview=disable_web_page_preview,
                link=link
            ),
            api=self.api
        )

    def reply_to(self, message: Message, text: str, **kwargs) -> Message:
        """
        Отвечает на сообщение `message` (цитата-реплай). Удобная обёртка,
        как в telebot: send_message(message.chat.id, text,
        reply_to_message_id=message.message_id, **kwargs)

        :param message: Сообщение, на которое нужно ответить
        :type message: Message

        :param text: Текст ответа
        :type text: str

        :param kwargs: Дополнительные параметры, передаются в send_message

        :return: Информация об отправленном сообщении
        :rtype: Message
        """
        return self.send_message(message.chat.id, text, reply_to_message_id=message.message_id, **kwargs)

    def get_message(self, message_id: str):
        """
        Метод получения сообщения по айди

        :param message_id: Айди сообщения
        :type message_id: str
        """
        msg = self.api.get_message(msg_id=message_id)
        update = {"update_type": "get_message"}
        update["message"] = msg
        return Message(update=update, api=self.api)

    def get_me(self):
        """
        Метод получения информации о боте
        """
        info = self.api.get_bot_info()
        return info

    def leave_chat(self, chat_id: str):
        """
        Метод получения информации о боте
        """
        return self.api.leave_chat(chat_id=chat_id)

    def callback_query_handler(self, data=None, **kwargs):
        """
        Декоратор для регистрации обработчиков callback-запросов от inline-кнопок

        :param data: Данные кнопки для фильтрации (callback_data)
        :type data: Optional[str]

        :param kwargs: Дополнительные фильтры для обработчика

        :return: Декоратор для функции-обработчика
        :rtype: Callable

        Пример использования:
        @bot.callback_query_handler(func=lambda cb: cb.data == "yes")
        def yes_handler(callback):
            callback.answer(notification="да да")
        """
        def decorator(handler):
            filters = {}
            if data:
                filters['data'] = data
            filters.update(kwargs)

            handler_dict = self._build_handler_dict(handler, **filters)
            self.callback_query_handlers.append(handler_dict)
            return handler

        return decorator

    def add_callback_query_handler(self, handler_dict):
        """
        Добавляет обработчик callback-запросов напрямую

        :param handler_dict: Словарь с описанием обработчика
        :type handler_dict: Dict[str, Any]

        :return: None
        """
        self.callback_query_handlers.append(handler_dict)

    def _process_callback_query(self, callback: CallbackQuery):
        """
        Обрабатывает входящий callback-запрос
        Метод ищет подходящий обработчик среди зарегистрированных и вызывает первый соответствующий фильтрам

        :param callback: Объект callback-запроса
        :type callback: CallbackQuery

        :return: None
        """
        # print(f"Processing callback: id={callback.id}, data={callback.data}")
        # print(f"Callback user: {callback.from_user}")

        for handler in self.callback_query_handlers:
            # print(f"Checking handler with filters: {handler['filters']}")
            if self._check_filters(callback, handler):
                # print("Handler matched! Calling function...")
                self._exec_task(handler["function"], callback)
                break
        else:
            print("No matching handler found for callback")

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: Optional[bool] = None,
        url: Optional[str] = None,
        cache_time: Optional[int] = None
    ) -> bool:
        """
        Отвечает на callback-запрос от нажатия inline-кнопки.

        :param callback_query_id: Уникальный идентификатор callback-запроса
        :type callback_query_id: str

        :param text: Текст всплывающего уведомления для пользователя (до 200 символов)
        :type text: Optional[str]

        :param show_alert: В Telegram показывает alert вместо уведомления.
                           В MAX API не поддерживается, параметр принимается для совместимости
        :type show_alert: Optional[bool]

        :param url: В Telegram открывает URL. В MAX API не поддерживается,
                    параметр принимается для совместимости
        :type url: Optional[str]

        :param cache_time: В Telegram задаёт время кэша. В MAX API не поддерживается,
                           параметр принимается для совместимости
        :type cache_time: Optional[int]

        :return: True если запрос выполнен успешно
        :rtype: bool
        """
        response = self.api.answer_callback(
            callback_id=callback_query_id,
            notification=text
        )
        return bool(response.get("success", False))

    def answer_inline_query(
        self,
        inline_query_id: str,
        results: List[Any],
        cache_time: Optional[int] = None,
        is_personal: Optional[bool] = None,
        next_offset: Optional[str] = None,
        switch_pm_text: Optional[str] = None,
        switch_pm_parameter: Optional[str] = None,
        button: Optional[Any] = None
    ) -> bool:
        """
        Заглушка для совместимости с telebot: сигнатура один в один с
        telebot.answer_inline_query, но вызов всегда бросает
        NotImplementedError.

        Инлайн-режима (@имя_бота запрос в поле ввода любого чата) в MAX
        Bot API не существует: нет ни метода ответа, ни типа обновления
        inline_query, поэтому реализовать метод на стороне MAX невозможно.
        Заглушка нужна, чтобы перенесённый с telebot код падал с понятным
        объяснением, а не с AttributeError.

        Альтернативы в MAX: inline-клавиатуры (InlineKeyboardMarkup) и
        reply-клавиатуры (ReplyKeyboardMarkup) на сообщениях бота.

        :param inline_query_id: Идентификатор inline-запроса (в MAX не бывает)
        :type inline_query_id: str

        :param results: Список результатов inline-запроса
        :type results: List[Any]

        :param cache_time: Параметр telebot, в MAX не применим
        :type cache_time: Optional[int]

        :param is_personal: Параметр telebot, в MAX не применим
        :type is_personal: Optional[bool]

        :param next_offset: Параметр telebot, в MAX не применим
        :type next_offset: Optional[str]

        :param switch_pm_text: Параметр telebot, в MAX не применим
        :type switch_pm_text: Optional[str]

        :param switch_pm_parameter: Параметр telebot, в MAX не применим
        :type switch_pm_parameter: Optional[str]

        :param button: Параметр telebot, в MAX не применим
        :type button: Optional[Any]

        :raises NotImplementedError: всегда — инлайн-режима в MAX Bot API нет
        """
        raise NotImplementedError(
            "Инлайн-режим не поддерживается MAX Bot API: у MAX нет ни метода "
            "ответа на inline-запрос, ни самого типа обновления inline_query. "
            "Используйте inline-клавиатуры (InlineKeyboardMarkup) или "
            "reply-клавиатуры (ReplyKeyboardMarkup)."
        )

    @staticmethod
    def _warn_inline_handler_unsupported(handler: Callable):
        """
        Пишет в лог предупреждение о регистрации inline-обработчика,
        который в MAX никогда не будет вызван.
        """
        name = getattr(handler, "__name__", repr(handler))
        logger.warning(
            "Обработчик %s зарегистрирован, но никогда не будет вызван: "
            "инлайн-режима в MAX Bot API нет (обновления inline_query "
            "не существуют)", name
        )

    def inline_handler(self, func, **kwargs):
        """
        Заглушка для совместимости с telebot: сигнатура один в один с
        telebot.inline_handler, но зарегистрированный обработчик никогда
        не будет вызван — инлайн-режима (обновления inline_query) в MAX
        Bot API нет.

        Регистрация намеренно НЕ роняет бота: перенесённый с telebot код
        с @bot.inline_handler(...) запускается, остальные обработчики
        работают, а в лог пишется предупреждение. Прямой вызов
        answer_inline_query, наоборот, бросает NotImplementedError.

        :param func: Функция-фильтр (в MAX не применяется)
        :type func: Callable

        :param kwargs: Дополнительные фильтры telebot (игнорируются)

        :return: Декоратор, возвращающий функцию без изменений
        """
        def decorator(handler):
            self._warn_inline_handler_unsupported(handler)
            return handler

        return decorator

    def register_inline_handler(self, callback: Callable, func: Callable, pass_bot: Optional[bool] = False, **kwargs):
        """
        Заглушка для совместимости с telebot: сигнатура один в один с
        telebot.register_inline_handler. Обработчик никогда не будет
        вызван — инлайн-режима в MAX Bot API нет; в лог пишется
        предупреждение. См. inline_handler.

        :param callback: Функция-обработчик (в MAX не будет вызвана)
        :type callback: Callable

        :param func: Функция-фильтр (в MAX не применяется)
        :type func: Callable

        :param pass_bot: Параметр telebot, в MAX не применим
        :type pass_bot: Optional[bool]

        :param kwargs: Дополнительные фильтры telebot (игнорируются)
        """
        self._warn_inline_handler_unsupported(callback)

    def chosen_inline_handler(self, func, **kwargs):
        """
        Заглушка для совместимости с telebot: сигнатура один в один с
        telebot.chosen_inline_handler. Обработчик никогда не будет
        вызван — инлайн-режима (обновления chosen_inline_result) в MAX
        Bot API нет; в лог пишется предупреждение. См. inline_handler.

        :param func: Функция-фильтр (в MAX не применяется)
        :type func: Callable

        :param kwargs: Дополнительные фильтры telebot (игнорируются)

        :return: Декоратор, возвращающий функцию без изменений
        """
        def decorator(handler):
            self._warn_inline_handler_unsupported(handler)
            return handler

        return decorator

    def register_chosen_inline_handler(self, callback: Callable, func: Callable, pass_bot: Optional[bool] = False, **kwargs):
        """
        Заглушка для совместимости с telebot: сигнатура один в один с
        telebot.register_chosen_inline_handler. Обработчик никогда не
        будет вызван — инлайн-режима в MAX Bot API нет; в лог пишется
        предупреждение. См. inline_handler.

        :param callback: Функция-обработчик (в MAX не будет вызвана)
        :type callback: Callable

        :param func: Функция-фильтр (в MAX не применяется)
        :type func: Callable

        :param pass_bot: Параметр telebot, в MAX не применим
        :type pass_bot: Optional[bool]

        :param kwargs: Дополнительные фильтры telebot (игнорируются)
        """
        self._warn_inline_handler_unsupported(callback)

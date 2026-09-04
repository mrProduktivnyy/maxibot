import asyncio
# import json
import logging
import queue
import re
import sys
import threading
import time
import traceback

from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Callable, Union

from maxibot import apihelper, util
from maxibot.apihelper import Api
from maxibot.types import Message, CallbackQuery, InputMedia, Update
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

# Имена типов обновлений telebot, у которых есть точный аналог в MAX:
# перенесённый @bot.middleware_handler(update_types=['message']) работает как есть
_TELEBOT_UPDATE_TYPES = {
    "message": UpdateType.MESSAGE_CREATED,
    "edited_message": UpdateType.MESSAGE_EDITED,
    "callback_query": UpdateType.MESSAGE_CALLBACK,
}

# Типы обновлений telebot, которых в MAX нет (каналы, инлайн-режим, платежи,
# опросы, реакции): такой middleware регистрируется вхолостую с предупреждением,
# чтобы перенесённый бот запускался — как с inline_handler
_TELEBOT_ONLY_UPDATE_TYPES = frozenset((
    "channel_post", "edited_channel_post", "inline_query", "chosen_inline_result",
    "shipping_query", "pre_checkout_query", "poll", "poll_answer", "my_chat_member",
    "chat_member", "chat_join_request", "message_reaction", "message_reaction_count",
    "chat_boost", "removed_chat_boost",
))

# Типы обновлений, у которых есть свой объект (Message или CallbackQuery)
_OBJECT_UPDATE_TYPES = (
    UpdateType.MESSAGE_CREATED, UpdateType.BOT_STARTED, UpdateType.BOT_ADDED,
    UpdateType.MESSAGE_EDITED, UpdateType.MESSAGE_CALLBACK,
)

# Маппинг действий telebot.send_chat_action в действия MAX
# (POST /chats/{chatId}/actions, enum SenderAction: typing_on, sending_photo,
# sending_video, sending_audio, sending_file). Отдельных индикаторов для
# стикеров, геолокации и кружков в MAX нет — уходит ближайший по смыслу
_CHAT_ACTIONS = {
    "typing": "typing_on",
    "upload_photo": "sending_photo",
    "record_video": "sending_video",
    "upload_video": "sending_video",
    "record_video_note": "sending_video",
    "upload_video_note": "sending_video",
    "record_voice": "sending_audio",
    "upload_voice": "sending_audio",
    "record_audio": "sending_audio",  # прежние имена voice-действий Telegram
    "upload_audio": "sending_audio",
    "upload_document": "sending_file",
    "choose_sticker": "typing_on",
    "find_location": "typing_on",
}

logger = logging.getLogger("maxibot")
# как в telebot: у логгера из коробки свой stderr-хендлер — не перехваченные
# ошибки видны без настройки logging, а maxibot.logger.setLevel(logging.DEBUG)
# включает traceback'и (у telebot — telebot.logger, формат строки тот же).
# Уровень WARNING, а не телеботовский ERROR: предупреждения совместимости
# (content_types=['file'], channel_post, WebAppInfo и т.п.) должны быть видны
formatter = logging.Formatter(
    '%(asctime)s (%(filename)s:%(lineno)d %(threadName)s) %(levelname)s - %(name)s: "%(message)s"'
)
console_output_handler = logging.StreamHandler(sys.stderr)
console_output_handler.setFormatter(formatter)
logger.addHandler(console_output_handler)
logger.setLevel(logging.WARNING)


@dataclass
class StepHandler:
    callback: Callable
    args: tuple
    kwargs: dict
    timestamp: float


class ExceptionHandler:
    """
    Базовый класс обработчика ошибок — как telebot.ExceptionHandler.

    Наследник с переопределённым handle() передаётся в
    ``MaxiBot(exception_handler=...)`` и получает каждое исключение из
    обработчиков, middleware, func-фильтров, цикла поллинга и
    webhook-сервера — сюда вешаются Sentry, алерты и своё логирование.

    handle() возвращает True, если ошибка обработана — maxibot её больше
    никуда не пишет; False/None — ошибка уходит в логгер 'maxibot'
    (logger.error, traceback — на уровне DEBUG), как в telebot.

    Необработанная ошибка не останавливает бот: и обработка обновлений,
    и цикл поллинга продолжаются (как telebot.infinity_polling;
    телеботовский polling() по умолчанию от таких ошибок падает — этого
    режима в maxibot нет). Единственные ошибки мимо exception_handler —
    парс-ошибки Update (payload, который парсер не понял): они только
    логируются на уровне ERROR с traceback, а обновление уходит в общие
    middleware с сырым json.
    """

    def handle(self, exception: Exception) -> bool:
        return False


class _WorkerPool:
    """
    Пул демон-потоков для выполнения обработчиков — аналог util.ThreadPool
    из telebot. Именно демон-потоки (ThreadPoolExecutor так не умеет):
    как и в telebot, Ctrl+C завершает процесс сразу, не дожидаясь
    зависших или стоящих в очереди обработчиков.
    """

    def __init__(self, num_threads: int, on_error: Optional[Callable] = None):
        self._queue = queue.Queue()
        self._on_error = on_error
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
            except Exception as e:
                # страховка, чтобы поток пула не умер; сами обработчики
                # уже обёрнуты в MaxiBot._run_task
                if self._on_error is not None:
                    self._on_error(e, "Error while processing update")
                else:
                    logger.error("Error while processing update:\n%s", traceback.format_exc())
            finally:
                self._queue.task_done()


class MaxiBot:
    """
    Главный класс бота
    """
    def __init__(
        self,
        token: str,
        parse_mode: Optional[str] = None,
        threaded: bool = True,
        skip_pending: bool = False,
        num_threads: int = 2,
        exception_handler: Optional[ExceptionHandler] = None
    ):
        """
        Метод инициализации бота

        :param token: Токен бота
        :type token: str

        :param parse_mode: Разметка на весь уровень бота: используется всеми
            методами отправки и редактирования, если parse_mode не задан в
            самом вызове (как в telebot). None — прежнее поведение каждого
            метода: send_message, edit_message_media и edit_message_reply_markup
            размечают текст как markdown, а подписи к вложениям и
            edit_message_text уходят без разметки
        :type parse_mode: Optional[str]

        :param skip_pending: Пропустить обновления, накопленные до запуска
            бота. Как в telebot, пропуск выполняется один раз — при старте
            поллинга
        :type skip_pending: bool

        :param threaded: Как в telebot: если True (по умолчанию),
            обработчики выполняются в пуле потоков и медленный обработчик
            не блокирует остальных пользователей. False — прежняя
            последовательная обработка в потоке поллинга
        :type threaded: bool

        :param num_threads: Размер пула потоков для обработчиков
            (используется при threaded=True). По умолчанию 2, как в telebot
        :type num_threads: int

        :param exception_handler: Обработчик ошибок — наследник
            ExceptionHandler с методом handle(exception) -> bool, как в
            telebot. Получает исключения обработчиков, middleware,
            func-фильтров, цикла поллинга и webhook-сервера (кроме
            парс-ошибок Update — те только логируются). handle()
            вернул истину — ошибка считается обработанной и не логируется;
            иначе — logger.error в логгер 'maxibot' и traceback на уровне
            DEBUG. Можно назначить и позже: bot.exception_handler = ...
            Передавайте по имени: в telebot этот параметр стоит после
            next_step_backend и reply_backend, которых в maxibot нет
        :type exception_handler: Optional[ExceptionHandler]
        """
        if parse_mode is not None and not isinstance(parse_mode, str):
            # второй позиционный параметр раньше был threaded: без этой проверки
            # MaxiBot(token, False) молча снял бы разметку со всех сообщений,
            # а MaxiBot(token, True) отправил бы в MAX невалидный format: true
            raise TypeError(
                "parse_mode должен быть строкой ('markdown' или 'html'), получено "
                f"{type(parse_mode).__name__}. Порядок параметров — как в telebot: "
                "MaxiBot(token, parse_mode, threaded, skip_pending, num_threads), "
                "поэтому threaded и num_threads передавайте по имени: "
                "MaxiBot(token, threaded=False, num_threads=4)"
            )
        self.api = Api(token=token)
        self.parse_mode = parse_mode
        self.skip_pending = skip_pending
        self.threaded = threaded
        self.num_threads = num_threads
        self.exception_handler = exception_handler
        if threaded:
            self._worker_pool = _WorkerPool(
                num_threads=num_threads, on_error=self._report_exception
            )
        else:
            self._worker_pool = None
        self.message_handlers = []
        self.callback_query_handlers = []
        # middleware (см. middleware_handler): по типам обновлений MAX и общие.
        # Как в telebot, регистрация требует apihelper.ENABLE_MIDDLEWARE = True
        self.typed_middleware_handlers: Dict[str, List[Callable]] = {t: [] for t in util.update_types}
        self.default_middleware_handlers: List[Callable] = []
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
            и игнорируется — длительность long polling задаёт настройка
            apihelper.LONG_POLLING_TIMEOUT (по умолчанию 30 секунд)
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
            logger.info("Bot is not running")
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
            logger.warning("Bot is already running")
            return None
        if self.skip_pending:
            # как в telebot: пропуск накопленных обновлений выполняется один
            # раз, чтобы перезапуск поллинга не терял свежие сообщения
            self._skip_updates()
            self.skip_pending = False
        self.is_running = True
        self.poll = Polling(
            api=self.api,
            allowed_updates=allowed_updates,
            on_error=self._report_exception,
        )
        await self.poll.loop(self._process_update)

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
        if content_types is None:
            # как в telebot: без явных content_types обработчик получает
            # только текстовые сообщения
            content_types = ["text"]
        elif isinstance(content_types, str):
            logger.warning("content_types должен быть списком, обернул строку")
            content_types = [content_types]
        renamed = {name: telebot_name for name, telebot_name
                   in Message._CONTENT_TYPE_MAP.items() if name in content_types}
        if renamed:
            # сырые имена вложений MAX из старых ботов ('file', 'image')
            logger.warning("content_types: используйте имена telebot: %s", renamed)
            content_types = [Message._CONTENT_TYPE_MAP.get(name, name) for name in content_types]
        if isinstance(commands, str):
            logger.warning("commands должен быть списком, обернул строку")
            commands = [commands]

        def decorator(funcs: HandlerFunc):
            # порядок фильтров = порядок проверки; как в telebot, content_types
            # раньше commands/regexp/func — func не видит не-текстовые сообщения
            handler_dict = self._build_handler_dict(
                funcs,
                chat_types=chat_types,
                content_types=content_types,
                commands=commands,
                regexp=regexp,
                func=func
            )
            self.message_handlers.append(handler_dict)
            return funcs
        return decorator

    def middleware_handler(self, update_types: Optional[List[str]] = None):
        """
        Декоратор для регистрации middleware — функции, которую бот вызывает
        для каждого обновления до любых обработчиков. Сигнатура один в один
        с telebot.middleware_handler; как и в telebot, сначала нужно
        включить apihelper.ENABLE_MIDDLEWARE = True, иначе регистрация
        бросит RuntimeError.

        Middleware получает два аргумента: бота и обновление. С update_types
        это объект своего типа: Message для message_created и
        message_edited, CallbackQuery для message_callback; у остальных
        типов (message_removed, bot_stopped, user_added...) своего объекта
        нет — придёт Update целиком, сырой payload в update.json. Как в
        telebot, middleware для message_created получает каждое сообщение,
        которое пойдёт в пайплайн обработчиков: в MAX это и bot_started
        (кнопка «Начать» приходит как /start), и bot_added (до самих
        обработчиков bot_added дойдёт только при явной подписке
        content_types=['bot_added'] — по умолчанию они ловят text). Без
        update_types middleware вызывается для всех обновлений и получает
        Update. Обработчики получают те же объекты, поэтому атрибуты,
        выставленные в middleware, видны в обработчике.

        Порядок — как в telebot: сначала middleware своего типа, затем
        общие, потом обработчики. Middleware выполняется до обработчиков в
        потоке, принявшем обновление, даже при threaded=True: при поллинге
        это единственный поток поллинга, и долгая работа в middleware
        задержит остальные обновления; при webhook у каждого запроса свой
        поток, и middleware разных обновлений выполняются параллельно.
        Исключение в middleware уходит в exception_handler, не обработано
        — логируется, а обновление дальше не обрабатывается — обработчики
        не вызываются (как telebot с suppress_middleware_excepions=True;
        ронять поллинг, как telebot по умолчанию, maxibot не станет).

        Пример:

            from maxibot import MaxiBot, apihelper

            apihelper.ENABLE_MIDDLEWARE = True
            bot = MaxiBot("TOKEN")

            @bot.middleware_handler(update_types=['message_created'])
            def add_lang(bot_instance, message):
                message.lang = message.from_user.language_code or "ru"

            @bot.middleware_handler()
            def log_update(bot_instance, update):
                print(update.update_type, update.json)

        :param update_types: Типы обновлений MAX, для которых вызывать
            middleware (все — в maxibot.util.update_types); телеботовские
            'message', 'edited_message' и 'callback_query' тоже принимаются,
            а типы telebot, которых в MAX нет (channel_post, inline_query...),
            пропускаются с предупреждением в логе — перенесённый бот
            запускается, как и с inline_handler. None — для всех обновлений
        :type update_types: Optional[List[str]]

        :return: Декоратор, возвращающий функцию без изменений
        :rtype: Callable
        """
        def decorator(handler):
            self.add_middleware_handler(handler, update_types)
            return handler

        return decorator

    def add_middleware_handler(self, handler, update_types=None):
        """
        Регистрирует middleware (см. middleware_handler). Сигнатура один в
        один с telebot.add_middleware_handler

        :param handler: Функция middleware: handler(bot, update)
        :type handler: Callable

        :param update_types: Типы обновлений, None — все
        :type update_types: Optional[List[str]]

        :raises RuntimeError: если не включён apihelper.ENABLE_MIDDLEWARE
        :raises ValueError: если тип обновления неизвестен ни MAX, ни telebot
        """
        if not apihelper.ENABLE_MIDDLEWARE:
            raise RuntimeError(
                "Middleware выключены. Как в telebot, до регистрации выполните "
                "apihelper.ENABLE_MIDDLEWARE = True (from maxibot import apihelper)"
            )
        if not update_types:
            self.default_middleware_handlers.append(handler)
            return
        if isinstance(update_types, str):
            update_types = [update_types]
        resolved, unsupported, unknown = [], [], []
        for update_type in update_types:
            update_type = _TELEBOT_UPDATE_TYPES.get(update_type, update_type)
            if update_type in self.typed_middleware_handlers:
                resolved.append(update_type)
            elif update_type in _TELEBOT_ONLY_UPDATE_TYPES:
                unsupported.append(update_type)
            else:
                unknown.append(update_type)
        if unknown:
            # telebot молча сделал бы такой middleware общим, и он получал бы все
            # обновления не того типа — лучше упасть при регистрации
            raise ValueError(
                f"Нет таких типов обновлений в MAX: {', '.join(map(repr, unknown))}. "
                f"Доступны: {', '.join(util.update_types)}; из telebot принимаются "
                f"{', '.join(_TELEBOT_UPDATE_TYPES)}"
            )
        if unsupported:
            name = getattr(handler, "__name__", repr(handler))
            if resolved:
                logger.warning(
                    "Middleware %s: обновлений %s в MAX нет, для них он вызван не будет",
                    name, ", ".join(unsupported)
                )
            else:
                logger.warning(
                    "Middleware %s зарегистрирован, но никогда не будет вызван: "
                    "обновлений %s в MAX нет", name, ", ".join(unsupported)
                )
        # алиас и имя MAX в одном списке ('message', 'message_created') — одна регистрация
        for update_type in dict.fromkeys(resolved):
            self.typed_middleware_handlers[update_type].append(handler)

    def register_middleware_handler(self, callback, update_types=None):
        """
        Регистрирует middleware без декоратора (см. middleware_handler).
        Сигнатура один в один с telebot.register_middleware_handler

            bot.register_middleware_handler(log_update, update_types=['message_created'])

        :param callback: Функция middleware: callback(bot, update)
        :type callback: Callable

        :param update_types: Типы обновлений, None — все
        :type update_types: Optional[List[str]]

        :return: None
        """
        self.add_middleware_handler(callback, update_types)

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
            # как в telebot: regexp и commands применимы только к тексту
            return context.content_type == 'text' and text and re.search(filter_value, text, re.IGNORECASE)
        elif message_filter == 'commands':
            return context.content_type == 'text' and extract_command(text) in filter_value
        elif message_filter == 'chat_types':
            return context.chat.type in filter_value
        elif message_filter == 'func':
            try:
                return filter_value(context)
            except Exception as e:
                # ошибка func-фильтра не роняет диспатч: обработчик
                # считается несовпавшим (в telebot такое исключение
                # роняло поллинг)
                self._report_exception(e, "Error in filter function")
                return False
        return False

    def _check_filters(self, context, handler: Dict):
        """
        Проверка текстового сообщения на фильтры

        :param context: Сообщение
        :type context: Context
        """
        if not handler['filters']:
            # без фильтров обработчик матчит всё (как в telebot); у
            # message_handler при этом всегда есть content_types=['text']
            return True
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
                        # ошибка func-фильтра не роняет диспатч: обработчик
                        # считается несовпавшим (в telebot такое исключение
                        # роняло поллинг)
                        self._report_exception(e, "Error in filter function")
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

    def process_middlewares(self, update: Update) -> bool:
        """
        Прогоняет обновление через middleware (аналог
        telebot.process_middlewares): сначала middleware своего типа, затем
        общие. Middleware своего типа получает объект этого типа (Message,
        CallbackQuery), а если у типа обновления своего объекта нет —
        Update; общий middleware всегда получает Update.

        Как в telebot, middleware для message_created получает каждое
        сообщение, которое дойдёт до обработчиков сообщений, — в MAX это и
        bot_started (кнопка «Начать» приходит как /start), и bot_added;
        затем вызываются middleware самого типа обновления, каждая функция
        — один раз

        :param update: Обновление
        :type update: Update

        :return: False, если какой-то middleware упал — обновление тогда
            дальше не обрабатывается
        :rtype: bool
        """
        if update.message is not None:
            context, types = update.message, [UpdateType.MESSAGE_CREATED, update.update_type]
        elif update.edited_message is not None:
            context, types = update.edited_message, [UpdateType.MESSAGE_EDITED]
        elif update.callback_query is not None:
            context, types = update.callback_query, [UpdateType.MESSAGE_CALLBACK]
        elif update.update_type in _OBJECT_UPDATE_TYPES:
            # объект своего типа построить не удалось — как в telebot, middleware
            # этого типа пропускаем, общие всё равно получат Update
            context, types = update, []
        else:
            context, types = update, [update.update_type]
        typed = []
        for update_type in dict.fromkeys(types):
            for middleware in self.typed_middleware_handlers.get(update_type, []):
                if middleware not in typed:
                    typed.append(middleware)
        calls = [(m, context) for m in typed] + [(m, update) for m in self.default_middleware_handlers]
        for middleware, ctx in calls:
            try:
                middleware(self, ctx)
            except Exception as e:
                name = getattr(middleware, "__qualname__", repr(middleware))
                self._report_exception(e, f"Error in middleware {name}, update skipped")
                return False
        return True

    def _process_update(self, update: Dict[str, Any]):
        """
        Метод для обработки входящего полученного обновления: сначала
        middleware, затем обработчики

        :param update: Данные по обновлениям
        :type update: Dict[str, Any]
        """
        try:
            update_type = update.get("update_type")
            has_handlers = update_type in (
                UpdateType.MESSAGE_CREATED, UpdateType.BOT_STARTED, UpdateType.BOT_ADDED, UpdateType.MESSAGE_CALLBACK
            )
            if not has_handlers and not (
                self.default_middleware_handlers or self.typed_middleware_handlers.get(update_type)
            ):
                # остальные типы обновлений бот не обрабатывает — объекты не
                # строим: Message ради названия чата ходит в API
                return
            upd = Update(update, self.api)
            if not self.process_middlewares(upd):
                return
            if upd.message is not None:
                # атомарный pop вместо `in` + pop: clear_step_handler может
                # выполняться в воркере параллельно и убрать ключ между
                # проверкой и извлечением — сообщение тогда потерялось бы
                handler = self._next_steps.pop(upd.message.from_user.id, None)
                if handler is not None:
                    self._exec_task(handler.callback, upd.message, *handler.args, **handler.kwargs)
                else:
                    self._process_text_message(upd.message)
            elif upd.callback_query is not None:
                self._process_callback_query(upd.callback_query)
        except Exception as e:
            self._report_exception(e, "Error while processing update")

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

    def _run_task(self, task: Callable, *args, **kwargs):
        """
        Вызов обработчика с перехватом ошибок: исключение обработчика
        уходит в exception_handler, не обработано — в логгер, и поллинг
        продолжается (в потоке пула ошибка иначе молча потерялась бы).
        В telebot по умолчанию необработанная ошибка обработчика роняет
        polling() — maxibot ведёт себя как telebot с
        use_class_middlewares=True и infinity_polling: логирует и живёт.
        """
        try:
            task(*args, **kwargs)
        except Exception as e:
            self._report_exception(e, "Error in handler")

    def _handle_exception(self, exception: Exception) -> bool:
        """
        Отдаёт исключение в exception_handler — как telebot._handle_exception.

        :return: True, если обработчик назначен и вернул истину — ошибка
            считается обработанной и дальше не логируется
        :rtype: bool
        """
        if self.exception_handler is None:
            return False
        return self.exception_handler.handle(exception)

    def _report_exception(self, exception: Exception, message: str):
        """
        Единая точка отчёта об ошибке: сначала exception_handler, если тот
        не обработал (или его нет) — logger.error, traceback — на уровне
        DEBUG (как в telebot). Сама не бросает: упавший handle()
        логируется, а не роняет поллинг. Вызывается из except-блока —
        traceback берётся из текущего исключения.

        :param exception: Перехваченное исключение
        :param message: Что происходило, когда оно случилось
        """
        try:
            handled = self._handle_exception(exception)
        except Exception:
            logger.error("Error in exception handler:\n%s", traceback.format_exc())
            handled = False
        if not handled:
            logger.error("%s: %s", message, exception)
            logger.debug("Exception traceback:\n%s", traceback.format_exc())

    def _resolve_parse_mode(self, parse_mode, default=None):
        """
        Определяет разметку сообщения. Как в telebot: parse_mode из вызова
        важнее общей разметки бота (``MaxiBot(token, parse_mode=...)``), а
        если не задан ни там, ни там — остаётся ``default``, прежнее
        поведение конкретного метода. Пустая строка отключает разметку.

        :param parse_mode: Разметка, переданная в вызов метода
        :param default: Разметка метода по умолчанию

        :return: Разметка в нижнем регистре (MAX ждёт markdown/html)
        """
        if parse_mode is None:
            parse_mode = self.parse_mode if self.parse_mode is not None else default
        return parse_mode.lower() if isinstance(parse_mode, str) else parse_mode

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
            logger.warning("Bot is already running")
            return

        if webhook_url:
            self.set_webhook(url=webhook_url, secret=secret, allowed_updates=allowed_updates)

        self._webhook = WebhookServer(
            host=host, port=port, secret=secret, on_error=self._report_exception
        )
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

        :param parse_mode: Разметка подписи (markdown/html). Если не задана,
            берётся общая разметка бота — MaxiBot(token, parse_mode=...);
            если и там пусто, подпись уходит без разметки
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
        return self._send_attachments(chat_id, caption, final_attachments,
                                      self._resolve_parse_mode(parse_mode),
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

        :param parse_mode: Разметка подписи (markdown/html). Если не задана,
            берётся общая разметка бота — MaxiBot(token, parse_mode=...);
            если и там пусто, подпись уходит без разметки
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
        return self._send_attachments(chat_id, caption, final_attachments,
                                      self._resolve_parse_mode(parse_mode),
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

        :param parse_mode: Разметка подписи (markdown/html). Если не задана,
            берётся общая разметка бота — MaxiBot(token, parse_mode=...);
            если и там пусто, подпись уходит без разметки
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
            self._resolve_parse_mode(parse_mode),
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

        :param parse_mode: Разметка подписи (markdown/html). Если не задана,
            берётся общая разметка бота — MaxiBot(token, parse_mode=...);
            если и там пусто, подпись уходит без разметки
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
            self._resolve_parse_mode(parse_mode),
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

        :param parse_mode: Разметка сообщения (markdown/html). Если не задана,
            берётся общая разметка бота — MaxiBot(token, parse_mode=...);
            если и там пусто, текст уходит без разметки
        :type parse_mode: Optional[str]

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
            parse_mode=self._resolve_parse_mode(parse_mode)
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
        parse_mode: Union[str, Any] = None
    ):
        """
        Метод изменения медиа сообщения `message_id` в чате `chat_id`

        :param media: Медиа, на которое надо заменить текущее
        :type media: str

        :param chat_id: Айди чата
        :type chat_id: Union[str, int]

        :param message_id: Айди сообщения
        :type message_id: int

        :param parse_mode: Разметка подписи (markdown/html). Разметка самого
            media (InputMedia(parse_mode=...)) важнее. Если не задана, берётся
            общая разметка бота — MaxiBot(token, parse_mode=...); если и там
            пусто, подпись размечается как markdown, как и раньше
        :type parse_mode: Optional[str]

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
        parse_mode = get_parse_mode(
            media=media,
            parse_mode=self._resolve_parse_mode(parse_mode, default="markdown")
        )

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
        parse_mode: Union[str, Any] = None
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
            parse_mode=self._resolve_parse_mode(parse_mode, default="markdown")
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
        parse_mode: Optional[str] = None,
        notify: bool = True,
        disable_web_page_preview: Optional[bool] = None,
        reply_to_message_id: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Message:
        """
        Отправляет ответ на текущее сообщение/обновление

        :param text: Текст сообщения
        :type text:

        :param attachments: Вложения сообщения
        :type attachments:

        :param keyboard: Объект клавиатуры (будет добавлен к attachments)
        :type keyboard:

        :param parse_mode: Разметка сообщения (markdown/html). Если не задана,
            берётся общая разметка бота — MaxiBot(token, parse_mode=...);
            если и там пусто, текст размечается как markdown, как и раньше.
            Пустая строка отключает разметку
        :type parse_mode: Optional[str]

        :param disable_web_page_preview: Если True, сервер не генерирует превью
            для ссылок в тексте (имя параметра как в telebot; в MAX API это
            query-параметр disable_link_preview). None — поведение сервера
            по умолчанию
        :type disable_web_page_preview: Optional[bool]

        :param reply_to_message_id: Идентификатор сообщения, на которое нужно
            ответить (имя параметра как в telebot; в MAX API это поле
            link={"type": "reply", "mid": ...} в теле запроса)
        :type reply_to_message_id: Optional[str]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot;
            None (и 0, как в telebot) — модульные таймауты apihelper
        :type timeout: Optional[int]

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
                parse_mode=self._resolve_parse_mode(parse_mode, default="markdown"),
                notify=notify,
                disable_link_preview=disable_web_page_preview,
                link=link,
                # как в telebot: timeout=0 означает «без своего таймаута»
                timeout=timeout or None
            ),
            api=self.api
        )

    def send_chat_action(
        self,
        chat_id: Union[int, str],
        action: str,
        timeout: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> bool:
        """
        Отправляет действие бота в чат — участники видят индикатор
        «печатает…», «отправляет фото» и т.п. (POST /chats/{chatId}/actions).
        Сигнатура один в один с telebot.send_chat_action. Индикатор живёт
        несколько секунд — для долгой операции вызов надо повторять.

        Имена действий telebot мапятся в действия MAX:
        typing -> typing_on; upload_photo -> sending_photo;
        record_video/upload_video и кружки record_video_note/
        upload_video_note -> sending_video; record_voice/upload_voice
        (и прежние record_audio/upload_audio) -> sending_audio;
        upload_document -> sending_file. Отдельных индикаторов для
        choose_sticker и find_location в MAX нет — уходит typing_on.
        Родные значения MAX (typing_on, sending_photo, sending_video,
        sending_audio, sending_file) принимаются как есть.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param action: Действие — имя telebot или родное имя MAX (см.
            выше); незнакомое имя уходит в MAX как есть и вернёт ошибку API
        :type action: str

        :param timeout: Таймаут запроса в секундах
        :type timeout: Optional[int]

        :param message_thread_id: Принимается для совместимости с telebot
            и игнорируется — тредов в MAX нет
        :type message_thread_id: Optional[int]

        :return: True при успехе; False, если MAX ответил success: false —
            telebot в такой ситуации бросает ApiTelegramException, поэтому
            при переносе проверяйте возврат. HTTP-ошибки, как и в telebot,
            бросают исключение (MaxApiHTTPException)
        :rtype: bool
        """
        # как в telebot: timeout=0 означает «без своего таймаута» (falsy
        # отбрасывается), а не нулевой HTTP-таймаут
        response = self.api.send_action(
            chat_id, _CHAT_ACTIONS.get(action, action), timeout=timeout or None
        )
        return bool(isinstance(response, dict) and response.get("success", False))

    @staticmethod
    def _resolve_reply_target(reply_to_message_id, reply_parameters, method_name):
        """
        Выбирает сообщение для ответа цитатой из пары телеботовских
        параметров: как в telebot, reply_parameters важнее устаревшего
        reply_to_message_id — при конфликте используется reply_parameters
        и пишется предупреждение в логгер.
        """
        rp_message_id = None
        if reply_parameters is not None:
            rp_message_id = getattr(reply_parameters, "message_id", None)
        if rp_message_id:
            if reply_to_message_id is not None:
                logger.warning(
                    "%s: заданы и reply_parameters, и устаревший "
                    "reply_to_message_id — конфликт, используется "
                    "reply_parameters (как в telebot)",
                    method_name,
                )
            return rp_message_id
        return reply_to_message_id

    def send_location(
        self,
        chat_id: Union[int, str],
        latitude: float,
        longitude: float,
        live_period: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        disable_notification: Optional[bool] = None,
        timeout: Optional[int] = None,
        horizontal_accuracy: Optional[float] = None,
        heading: Optional[int] = None,
        proximity_alert_radius: Optional[int] = None,
        allow_sending_without_reply: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        message_thread_id: Optional[int] = None,
        reply_parameters: Optional[Any] = None,
    ) -> Message:
        """
        Отправляет точку на карте. Сигнатура один в один с
        telebot.send_location; в MAX это обычный POST /messages со
        вложением {"type": "location", "latitude": ..., "longitude": ...}
        (координаты лежат на верхнем уровне вложения, payload у него нет).

        Live-локаций в MAX нет: live_period при передаче игнорируется
        с предупреждением в логгере, пин статичен. horizontal_accuracy,
        heading, proximity_alert_radius, allow_sending_without_reply,
        protect_content и message_thread_id принимаются для совместимости
        и игнорируются — таких настроек в MAX нет.

        У возвращаемого Message заполняются базовые поля (message_id,
        chat, content_type "location"), но атрибут location остаётся
        None — телеботовский паттерн result.location.latitude не
        работает, координаты и так известны вызывающему.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param latitude: Широта
        :type latitude: float

        :param longitude: Долгота
        :type longitude: float

        :param live_period: Игнорируется (live-локаций в MAX нет)
        :type live_period: Optional[int]

        :param reply_to_message_id: Идентификатор сообщения, на которое
            ответить цитатой
        :type reply_to_message_id: Optional[int]

        :param reply_markup: Клавиатура (уйдёт вторым вложением)
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param disable_notification: True — отправить без звука (в MAX это
            notify=false)
        :type disable_notification: Optional[bool]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :param reply_parameters: Как в telebot: если передан объект с
            message_id, он используется вместо reply_to_message_id;
            остальные его поля игнорируются
        :type reply_parameters: Optional[Any]

        :return: Отправленное сообщение
        :rtype: Message
        """
        if live_period is not None:
            logger.warning(
                "send_location: live-локаций в MAX нет — live_period "
                "игнорируется, пин статичен"
            )
        reply_to_message_id = self._resolve_reply_target(
            reply_to_message_id, reply_parameters, "send_location"
        )
        return self.send_message(
            chat_id,
            None,
            attachments=[{
                "type": "location",
                "latitude": latitude,
                "longitude": longitude,
            }],
            reply_markup=reply_markup,
            notify=not disable_notification,
            reply_to_message_id=reply_to_message_id,
            timeout=timeout,
        )

    def send_contact(
        self,
        chat_id: Union[int, str],
        phone_number: str,
        first_name: str,
        last_name: Optional[str] = None,
        vcard: Optional[str] = None,
        disable_notification: Optional[bool] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        timeout: Optional[int] = None,
        allow_sending_without_reply: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        message_thread_id: Optional[int] = None,
        reply_parameters: Optional[Any] = None,
    ) -> Message:
        """
        Отправляет карточку контакта. Сигнатура один в один с
        telebot.send_contact; в MAX это POST /messages со вложением
        {"type": "contact", "payload": {name, vcf_phone[, vcf_info]}}:
        name собирается из first_name/last_name, phone_number уходит в
        vcf_phone, переданный vcard — как есть в vcf_info.

        По документации MAX контакт обязан быть ЕДИНСТВЕННЫМ вложением
        сообщения, поэтому переданный reply_markup игнорируется
        с предупреждением в логгере (в telebot клавиатуру к контакту
        приложить можно) — отправьте её отдельным сообщением.
        allow_sending_without_reply, protect_content и message_thread_id
        принимаются для совместимости и игнорируются. У возвращаемого
        Message content_type — "contact", но атрибут contact остаётся
        None (данные контакта и так известны вызывающему).

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param phone_number: Телефон контакта
        :type phone_number: str

        :param first_name: Имя контакта
        :type first_name: str

        :param last_name: Фамилия контакта (склеивается с именем в
            payload.name)
        :type last_name: Optional[str]

        :param vcard: Визитка в формате vCard — уходит в vcf_info как есть
        :type vcard: Optional[str]

        :param disable_notification: True — отправить без звука
        :type disable_notification: Optional[bool]

        :param reply_to_message_id: Идентификатор сообщения, на которое
            ответить цитатой
        :type reply_to_message_id: Optional[int]

        :param reply_markup: Игнорируется — контакт в MAX обязан быть
            единственным вложением
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :param reply_parameters: Как в telebot: если передан объект с
            message_id, он используется вместо reply_to_message_id
        :type reply_parameters: Optional[Any]

        :return: Отправленное сообщение
        :rtype: Message
        """
        if reply_markup is not None:
            logger.warning(
                "send_contact: по документации MAX контакт обязан быть "
                "единственным вложением сообщения — reply_markup "
                "игнорируется, отправьте клавиатуру отдельным сообщением"
            )
        reply_to_message_id = self._resolve_reply_target(
            reply_to_message_id, reply_parameters, "send_contact"
        )
        name = f"{first_name} {last_name}" if last_name else first_name
        payload = {"name": name, "vcf_phone": phone_number}
        if vcard:
            payload["vcf_info"] = vcard
        return self.send_message(
            chat_id,
            None,
            attachments=[{"type": "contact", "payload": payload}],
            notify=not disable_notification,
            reply_to_message_id=reply_to_message_id,
            timeout=timeout,
        )

    def send_venue(
        self,
        chat_id: Union[int, str],
        latitude: Optional[float],
        longitude: Optional[float],
        title: str,
        address: str,
        foursquare_id: Optional[str] = None,
        foursquare_type: Optional[str] = None,
        disable_notification: Optional[bool] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        timeout: Optional[int] = None,
        allow_sending_without_reply: Optional[bool] = None,
        google_place_id: Optional[str] = None,
        google_place_type: Optional[str] = None,
        protect_content: Optional[bool] = None,
        message_thread_id: Optional[int] = None,
        reply_parameters: Optional[Any] = None,
    ) -> Message:
        """
        Отправляет место (венью). Сигнатура один в один с
        telebot.send_venue. Отдельного типа венью в MAX нет — честная
        эмуляция одним сообщением: location-вложение с координатами
        плюс текст «title\\naddress» (без разметки, как в telebot).

        foursquare_id/foursquare_type/google_place_id/google_place_type
        принимаются для совместимости и игнорируются — привязки к
        справочникам мест в MAX нет; allow_sending_without_reply,
        protect_content и message_thread_id — тоже. У возвращаемого
        Message content_type — "location" (не "venue"), атрибуты venue
        и location остаются None.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param latitude: Широта
        :type latitude: Optional[float]

        :param longitude: Долгота
        :type longitude: Optional[float]

        :param title: Название места (первая строка текста)
        :type title: str

        :param address: Адрес места (вторая строка текста)
        :type address: str

        :param disable_notification: True — отправить без звука
        :type disable_notification: Optional[bool]

        :param reply_to_message_id: Идентификатор сообщения, на которое
            ответить цитатой
        :type reply_to_message_id: Optional[int]

        :param reply_markup: Клавиатура (уйдёт вторым вложением)
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :param reply_parameters: Как в telebot: если передан объект с
            message_id, он используется вместо reply_to_message_id
        :type reply_parameters: Optional[Any]

        :return: Отправленное сообщение
        :rtype: Message
        """
        reply_to_message_id = self._resolve_reply_target(
            reply_to_message_id, reply_parameters, "send_venue"
        )
        return self.send_message(
            chat_id,
            f"{title}\n{address}",
            attachments=[{
                "type": "location",
                "latitude": latitude,
                "longitude": longitude,
            }],
            reply_markup=reply_markup,
            # название и адрес — сырой текст без разметки, как в telebot
            parse_mode="",
            notify=not disable_notification,
            reply_to_message_id=reply_to_message_id,
            timeout=timeout,
        )

    def edit_message_live_location(
        self,
        latitude: float,
        longitude: float,
        chat_id: Optional[Union[int, str]] = None,
        message_id: Optional[str] = None,
        inline_message_id: Optional[str] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        timeout: Optional[int] = None,
        horizontal_accuracy: Optional[float] = None,
        heading: Optional[int] = None,
        proximity_alert_radius: Optional[int] = None,
    ) -> Message:
        """
        Передвигает пин сообщения-локации: PUT /messages заменяет тело
        сообщения новым location-вложением (плюс reply_markup, если
        передана). Сигнатура как в telebot.edit_message_live_location,
        но семантики live-локации в MAX нет — редактировать можно любое
        сообщение-локацию, а не только «живое», и пин просто переезжает
        при каждом вызове.

        PUT /messages заменяет тело целиком, поэтому текст у сообщения
        (если был) пропадёт — у сообщений send_location его нет.
        Участники не получают «Сообщение было изменено» (notify=false) —
        переезжающий по таймеру пин не шумит в чате. message_id
        обязателен: инлайн-сообщений в MAX нет, вызов с одним
        inline_message_id даёт ValueError. horizontal_accuracy, heading
        и proximity_alert_radius принимаются для совместимости и
        игнорируются.

        :param latitude: Новая широта
        :type latitude: float

        :param longitude: Новая долгота
        :type longitude: float

        :param chat_id: Идентификатор чата (используется только для
            сборки возвращаемого Message — сообщение в MAX адресуется
            одним message_id; без chat_id у возвращаемого Message не
            будет данных чата)
        :type chat_id: Optional[Union[int, str]]

        :param message_id: Идентификатор сообщения-локации (обязателен)
        :type message_id: Optional[str]

        :param reply_markup: Клавиатура (уйдёт вторым вложением)
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :return: Message с новыми вложениями при успехе, иначе {} (как
            edit_message_media)
        :rtype: Message | {}
        """
        if message_id is None:
            raise ValueError(
                "edit_message_live_location: инлайн-сообщений в MAX нет — "
                "передайте message_id"
            )
        final_attachments = [{
            "type": "location",
            "latitude": latitude,
            "longitude": longitude,
        }]
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)

        response = self.api.send_message(
            msg_id=message_id,
            method="PUT",
            attachments=final_attachments,
            # без «Сообщение было изменено» участникам — пин, который
            # переезжает по таймеру, иначе шумел бы на каждый вызов
            notify=False,
            timeout=timeout or None,
        )

        if isinstance(response, dict) and response.get("success"):
            timestamp = int(time.time() * 1000)
            message_data = get_edit_message_data(None, chat_id, message_id, final_attachments, timestamp)
            return Message(update=message_data, api=self.api)

        return {}

    def stop_message_live_location(
        self,
        chat_id: Optional[Union[int, str]] = None,
        message_id: Optional[str] = None,
        inline_message_id: Optional[str] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        timeout: Optional[int] = None,
    ) -> Message:
        """
        Заглушка для совместимости с telebot.stop_message_live_location:
        live-локаций в MAX нет, останавливать нечего, пин и так статичен.
        Без reply_markup ничего не отправляет и возвращает сообщение как
        есть. Если передана reply_markup — заменяет клавиатуру сообщения
        (как делает telebot при остановке), сохраняя его текст и остальные
        вложения; участники не получают «Сообщение было изменено»
        (notify=false). message_id обязателен: инлайн-сообщений в MAX
        нет, вызов с одним inline_message_id даёт ValueError.

        :param chat_id: Идентификатор чата (используется только для
            сборки возвращаемого Message при замене клавиатуры)
        :type chat_id: Optional[Union[int, str]]

        :param message_id: Идентификатор сообщения-локации (обязателен)
        :type message_id: Optional[str]

        :param reply_markup: Новая клавиатура сообщения
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :return: Сообщение; при передаче reply_markup — Message с новыми
            вложениями при успехе, иначе {} (как edit_message_media)
        :rtype: Message | {}
        """
        if message_id is None:
            raise ValueError(
                "stop_message_live_location: инлайн-сообщений в MAX нет — "
                "передайте message_id"
            )
        if reply_markup is None:
            return self.get_message(message_id=message_id)

        # заменить только клавиатуру: PUT /messages перезаписывает тело
        # целиком, поэтому текст и остальные вложения надо переотправить
        info = self.api.get_message(msg_id=message_id)
        body = {}
        if isinstance(info, dict):
            body = (info.get("message") or info).get("body") or {}
        final_attachments = [
            attachment for attachment in body.get("attachments") or []
            if attachment.get("type") != "inline_keyboard"
        ]
        if hasattr(reply_markup, 'to_attachment'):
            final_attachments.append(reply_markup.to_attachment())
        else:
            final_attachments.append(reply_markup)

        response = self.api.send_message(
            msg_id=message_id,
            method="PUT",
            text=body.get("text"),
            # None: не навешивать разметку на уже отправленный текст
            parse_mode=None,
            attachments=final_attachments,
            # смена клавиатуры — не повод для «Сообщение было изменено»
            notify=False,
            timeout=timeout or None,
        )

        if isinstance(response, dict) and response.get("success"):
            timestamp = int(time.time() * 1000)
            message_data = get_edit_message_data(
                body.get("text"), chat_id, message_id, final_attachments, timestamp
            )
            return Message(update=message_data, api=self.api)

        return {}

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
            logger.debug("No matching handler found for callback")

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

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
from maxibot.types import Chat, ChatMember, Message, CallbackQuery, InputMedia, MessageID, Update
from maxibot.types import BotCommand, BotName, BotDescription, BotShortDescription
from maxibot.types import File, Video
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

# Типы обновлений telebot, которых в MAX нет (инлайн-режим, платежи,
# опросы, реакции): такой middleware регистрируется вхолостую с предупреждением,
# чтобы перенесённый бот запускался — как с inline_handler.
# channel_post/edited_channel_post здесь про MIDDLEWARE: отдельного типа
# обновления для каналов в MAX нет (посты приходят как message_created
# с chat_type='channel'); сами обработчики channel_post_handler работают
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

# телеботовские content_types, которых MAX не порождает: такие сообщения
# приходят под другим типом, и хендлер с этим content_type не сработал бы
# никогда — message_handler предупреждает и подсказывает реальный тип
_CONTENT_TYPE_HINTS = {
    "voice": "audio",  # голосовые в MAX — обычное аудио (см. send_voice)
    "video_note": "video",  # кружки в MAX — обычное видео (см. send_video_note)
    "animation": "video",  # гифки в MAX — обычное видео или картинка (см. send_animation)
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
        self.edited_message_handlers = []
        self.channel_post_handlers = []
        self.edited_channel_post_handlers = []
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
    def _build_handler_dict(handler: HandlerFunc, pass_bot=False, **filters):
        """
        Функция, которая формирует словарь для добавления в список обработчиков событий (handler)

        :param handler: Description
        :type handler: HandlerFunc
        :param pass_bot: Передавать ли обработчику бота именованным
            аргументом bot (как в telebot register_*_handler)
        :param filters: Description
        """
        return {
            'function': handler,
            'pass_bot': pass_bot,
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

    @staticmethod
    def _prepare_message_filters(content_types, commands, default_text=True):
        """
        Общая нормализация фильтров message_handler /
        edited_message_handler: дефолт ['text'], строки оборачиваются
        в списки, сырые имена вложений MAX переводятся в имена telebot,
        по не порождаемым в MAX типам — предупреждение.

        default_text=False — не подставлять ['text'] при content_types
        is None: так ведут себя телеботовские register_*_handler
        (в отличие от одноимённых декораторов — внутренняя
        непоследовательность telebot, повторяем её ради переносимости)

        :return: (content_types, commands)
        """
        if content_types is None:
            # как в telebot: без явных content_types обработчик-декоратор
            # получает только текстовые сообщения
            if default_text:
                content_types = ["text"]
        elif isinstance(content_types, str):
            logger.warning("content_types должен быть списком, обернул строку")
            content_types = [content_types]
        renamed = {name: telebot_name for name, telebot_name
                   in Message._CONTENT_TYPE_MAP.items() if name in (content_types or ())}
        if renamed:
            # сырые имена вложений MAX из старых ботов ('file', 'image')
            logger.warning("content_types: используйте имена telebot: %s", renamed)
            content_types = [Message._CONTENT_TYPE_MAP.get(name, name) for name in content_types]
        hinted = {name: real for name, real in _CONTENT_TYPE_HINTS.items()
                  if name in (content_types or ())}
        if hinted:
            # тип не переименовывается: 'voice' ловил бы ВСЕ аудио — пусть
            # автор бота осознанно подпишется на реальный тип сам
            logger.warning(
                "content_types: MAX не порождает %s — такие сообщения приходят "
                "как %s, хендлер с этим content_type не сработает",
                sorted(hinted), sorted(set(hinted.values())),
            )
        if isinstance(commands, str):
            logger.warning("commands должен быть списком, обернул строку")
            commands = [commands]
        return content_types, commands

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
        content_types, commands = self._prepare_message_filters(content_types, commands)

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

    def edited_message_handler(
        self,
        commands: Optional[List[str]] = None,
        regexp: Optional[str] = None,
        func: Optional[Callable] = None,
        content_types: Optional[List[str]] = None,
        chat_types: Optional[List[str]] = None
    ):
        """
        Декоратор для регистрации обработчика ПРАВОК сообщений
        (message_edited) — как telebot.edited_message_handler. Фильтры
        те же, что у message_handler: без content_types обработчик
        получает только текстовые правки; commands/regexp применимы
        к тексту.

        Обработчик получает Message отредактированного сообщения —
        как в telebot, где приходит обновлённый message.

        :param commands: Список команд
        :param regexp: Регулярное выражение по тексту
        :param func: Функция-фильтр
        :param content_types: Типы контента (по умолчанию ['text'])
        :param chat_types: Типы чатов — сырые имена MAX
            ('dialog'/'chat'/'channel'), как и у message_handler;
            телеботовские 'private'/'group' не совпадут
        """
        content_types, commands = self._prepare_message_filters(content_types, commands)

        def decorator(funcs: HandlerFunc):
            handler_dict = self._build_handler_dict(
                funcs,
                chat_types=chat_types,
                content_types=content_types,
                commands=commands,
                regexp=regexp,
                func=func
            )
            self.add_edited_message_handler(handler_dict)
            return funcs
        return decorator

    def add_edited_message_handler(self, handler_dict):
        """
        Добавляет обработчик правок сообщений напрямую (низкоуровневый
        способ — как telebot.add_edited_message_handler; обычно
        используйте декоратор или register_edited_message_handler)

        :param handler_dict: Словарь из _build_handler_dict
        """
        self.edited_message_handlers.append(handler_dict)

    def register_edited_message_handler(
        self,
        callback: Callable,
        content_types: Optional[List[str]] = None,
        commands: Optional[List[str]] = None,
        regexp: Optional[str] = None,
        func: Optional[Callable] = None,
        chat_types: Optional[List[str]] = None,
        pass_bot: Optional[bool] = False
    ):
        """
        Недекораторная регистрация обработчика правок сообщений — как
        telebot.register_edited_message_handler (удобно, когда
        обработчики разнесены по файлам). С pass_bot=True обработчик
        получает бота именованным аргументом:
        callback(message, bot=bot).

        Как и в telebot, без content_types регистрация через register_
        матчит правки ЛЮБОГО типа контента (телеботовские register_,
        в отличие от одноимённых декораторов, дефолт ['text']
        не подставляют — повторяем ради переносимости).

        :param callback: Функция-обработчик
        :param content_types: Типы контента (None — все, как в telebot)
        :param commands: Список команд
        :param regexp: Регулярное выражение по тексту
        :param func: Функция-фильтр
        :param chat_types: Типы чатов — сырые имена MAX
            ('dialog'/'chat'/'channel'); телеботовские
            'private'/'group' не совпадут
        :param pass_bot: Передавать бота в обработчик аргументом bot
        """
        content_types, commands = self._prepare_message_filters(
            content_types, commands, default_text=False)
        handler_dict = self._build_handler_dict(
            callback,
            pass_bot=pass_bot,
            chat_types=chat_types,
            content_types=content_types,
            commands=commands,
            regexp=regexp,
            func=func
        )
        self.add_edited_message_handler(handler_dict)

    def channel_post_handler(
        self,
        commands: Optional[List[str]] = None,
        regexp: Optional[str] = None,
        func: Optional[Callable] = None,
        content_types: Optional[List[str]] = None
    ):
        """
        Декоратор обработчика постов каналов — как
        telebot.channel_post_handler. Отдельного типа обновления для
        каналов в MAX нет: пост приходит как message_created с типом
        чата 'channel', и maxibot, как telebot, разводит их сам — посты
        каналов попадают ТОЛЬКО сюда и не попадают в message_handler.
        Фильтры как у message_handler (без content_types — только
        текст); у поста от имени канала message.from_user равен None
        (как в telebot).

        :param commands: Список команд
        :param regexp: Регулярное выражение по тексту
        :param func: Функция-фильтр
        :param content_types: Типы контента (по умолчанию ['text'])
        """
        content_types, commands = self._prepare_message_filters(content_types, commands)

        def decorator(funcs: HandlerFunc):
            handler_dict = self._build_handler_dict(
                funcs,
                content_types=content_types,
                commands=commands,
                regexp=regexp,
                func=func
            )
            self.add_channel_post_handler(handler_dict)
            return funcs
        return decorator

    def add_channel_post_handler(self, handler_dict):
        """
        Добавляет обработчик постов каналов напрямую — как
        telebot.add_channel_post_handler

        :param handler_dict: Словарь из _build_handler_dict
        """
        self.channel_post_handlers.append(handler_dict)

    def register_channel_post_handler(
        self,
        callback: Callable,
        content_types: Optional[List[str]] = None,
        commands: Optional[List[str]] = None,
        regexp: Optional[str] = None,
        func: Optional[Callable] = None,
        pass_bot: Optional[bool] = False
    ):
        """
        Недекораторная регистрация обработчика постов каналов — как
        telebot.register_channel_post_handler. pass_bot=True — бот
        приходит именованным аргументом bot. Как и в telebot, без
        content_types register_ матчит посты любого типа (дефолт
        ['text'] подставляют только декораторы).

        :param callback: Функция-обработчик
        :param content_types: Типы контента (None — все, как в telebot)
        :param commands: Список команд
        :param regexp: Регулярное выражение по тексту
        :param func: Функция-фильтр
        :param pass_bot: Передавать бота в обработчик аргументом bot
        """
        content_types, commands = self._prepare_message_filters(
            content_types, commands, default_text=False)
        handler_dict = self._build_handler_dict(
            callback,
            pass_bot=pass_bot,
            content_types=content_types,
            commands=commands,
            regexp=regexp,
            func=func
        )
        self.add_channel_post_handler(handler_dict)

    def edited_channel_post_handler(
        self,
        commands: Optional[List[str]] = None,
        regexp: Optional[str] = None,
        func: Optional[Callable] = None,
        content_types: Optional[List[str]] = None
    ):
        """
        Декоратор обработчика ПРАВОК постов каналов — как
        telebot.edited_channel_post_handler: message_edited с типом
        чата 'channel' попадает только сюда (не в
        edited_message_handler). Остальное — как у channel_post_handler.

        :param commands: Список команд
        :param regexp: Регулярное выражение по тексту
        :param func: Функция-фильтр
        :param content_types: Типы контента (по умолчанию ['text'])
        """
        content_types, commands = self._prepare_message_filters(content_types, commands)

        def decorator(funcs: HandlerFunc):
            handler_dict = self._build_handler_dict(
                funcs,
                content_types=content_types,
                commands=commands,
                regexp=regexp,
                func=func
            )
            self.add_edited_channel_post_handler(handler_dict)
            return funcs
        return decorator

    def add_edited_channel_post_handler(self, handler_dict):
        """
        Добавляет обработчик правок постов каналов напрямую — как
        telebot.add_edited_channel_post_handler

        :param handler_dict: Словарь из _build_handler_dict
        """
        self.edited_channel_post_handlers.append(handler_dict)

    def register_edited_channel_post_handler(
        self,
        callback: Callable,
        content_types: Optional[List[str]] = None,
        commands: Optional[List[str]] = None,
        regexp: Optional[str] = None,
        func: Optional[Callable] = None,
        pass_bot: Optional[bool] = False
    ):
        """
        Недекораторная регистрация обработчика правок постов каналов —
        как telebot.register_edited_channel_post_handler. Без
        content_types матчит правки любого типа (как в telebot,
        см. register_channel_post_handler).

        :param callback: Функция-обработчик
        :param content_types: Типы контента (None — все, как в telebot)
        :param commands: Список команд
        :param regexp: Регулярное выражение по тексту
        :param func: Функция-фильтр
        :param pass_bot: Передавать бота в обработчик аргументом bot
        """
        content_types, commands = self._prepare_message_filters(
            content_types, commands, default_text=False)
        handler_dict = self._build_handler_dict(
            callback,
            pass_bot=pass_bot,
            content_types=content_types,
            commands=commands,
            regexp=regexp,
            func=func
        )
        self.add_edited_channel_post_handler(handler_dict)

    def process_new_channel_posts(self, new_channel_post: List[Message]):
        """
        Прогоняет посты каналов по обработчикам channel_post — как
        telebot.process_new_channel_posts (публичная точка пайплайна)

        :param new_channel_post: Список сообщений-постов
        """
        for message in new_channel_post:
            self.run_handler(context=message,
                             message_handlers=self.channel_post_handlers)

    def process_new_edited_channel_posts(self, new_edited_channel_post: List[Message]):
        """
        Прогоняет правки постов каналов по обработчикам
        edited_channel_post — как
        telebot.process_new_edited_channel_posts

        :param new_edited_channel_post: Список правок постов
        """
        for message in new_edited_channel_post:
            self.run_handler(context=message,
                             message_handlers=self.edited_channel_post_handlers)

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
            а типы telebot, которых в MAX нет (inline_query, poll...),
            пропускаются с предупреждением в логе — перенесённый бот
            запускается, как и с inline_handler. 'channel_post' тоже
            пропускается: отдельного типа обновления для каналов в MAX
            нет, посты каналов приходят в middleware message_created
            (сами обработчики channel_post_handler при этом работают).
            None — для всех обновлений
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
                if handler.get("pass_bot"):
                    # как в telebot: register_*_handler(pass_bot=True)
                    # передаёт бота именованным аргументом
                    self._exec_task(handler.get("function"), context, bot=self)
                else:
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
            ) or (
                # правки диспатчатся только при подписке: без обработчиков
                # не строим Message зря (он ходит в API за названием чата)
                update_type == UpdateType.MESSAGE_EDITED
                and bool(self.edited_message_handlers or self.edited_channel_post_handlers)
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
                if getattr(upd.message.chat, "type", None) == "channel":
                    # посты каналов — только в канальные обработчики, как
                    # в telebot (до message_handlers и next_step не доходят;
                    # у поста от имени канала from_user равен None)
                    self.process_new_channel_posts([upd.message])
                    return
                # атомарный pop вместо `in` + pop: clear_step_handler может
                # выполняться в воркере параллельно и убрать ключ между
                # проверкой и извлечением — сообщение тогда потерялось бы;
                # ключ — chat.id (см. register_next_step_handler), он же
                # безопасен при from_user=None (sender null вне канала)
                handler = self._next_steps.pop(upd.message.chat.id, None)
                if handler is not None:
                    self._exec_task(handler.callback, upd.message, *handler.args, **handler.kwargs)
                else:
                    self._process_text_message(upd.message)
            elif upd.edited_message is not None:
                if getattr(upd.edited_message.chat, "type", None) == "channel":
                    self.process_new_edited_channel_posts([upd.edited_message])
                    return
                self.run_handler(
                    context=upd.edited_message,
                    message_handlers=self.edited_message_handlers,
                )
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
        # ключ — chat.id, как в telebot (register_next_step_handler там
        # делегирует в *_by_chat_id) и как clear_step_handler ниже;
        # для входящих значение совпадает с from_user.id (User.id — это
        # chat_id), а from_user=None (пост канала) не роняет регистрацию
        self._next_steps[message.chat.id] = handler

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

    def _send_attachments(self, chat_id, text, attachments, parse_mode,
                          disable_link_preview=None, notify=True, link=None,
                          timeout=None):
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
                    disable_link_preview=disable_link_preview,
                    notify=notify,
                    link=link,
                    timeout=timeout
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

        :param video: Видео — байты, file-like объект или, как file_id
            в telebot, строка-токен ранее загруженного видео (лежит во
            входящем вложении payload.token) — уходит без повторной
            загрузки. URL-строка не поддерживается (ValueError):
            MAX принимает URL только для изображений
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
                "Видео можно отправить байтами, file-like объектом или "
                "строкой-токеном ранее загруженного видео"
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

    def send_animation(
        self,
        chat_id: Union[int, str],
        animation: Union[Any, str],
        duration: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        thumbnail: Optional[Any] = None,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        caption_entities: Optional[Any] = None,
        disable_notification: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        reply_to_message_id: Optional[int] = None,
        allow_sending_without_reply: Optional[bool] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        timeout: Optional[int] = None,
        message_thread_id: Optional[int] = None,
        has_spoiler: Optional[bool] = None,
        thumb: Optional[Any] = None,
        reply_parameters: Optional[Any] = None,
    ) -> Message:
        """
        Отправляет анимацию (GIF или видео без звука). Сигнатура один
        в один с telebot.send_animation, но отдельного типа анимаций
        в MAX нет — честная деградация:

        - файл (байты, file-like, InputMedia) уходит обычным видео
          через POST /uploads?type=video — придёт с content_type
          "video", без GIF-семантики (зацикливание — на усмотрение
          клиента MAX);
        - http(s)-ссылка уходит вложением
          {"type": "image", "payload": {"url": ...}} — MAX скачает
          файл сам; придёт картинкой (content_type "photo"). URL
          должен вести на изображение (gif/jpg/png): ссылка на
          видеофайл не сработает — очевидные видеорасширения
          (.mp4 и т. п., частый формат анимаций telebot) отрезаются
          с ValueError, такой файл отправьте байтами;
        - прочая строка — как file_id в telebot: токен ранее
          загруженного видео, уходит без повторной загрузки.

        Следствие: телеботовский обработчик content_types=['animation']
        не сработает никогда — подписывайтесь на ['video'] (а для
        URL-гифок — ['photo']); message_handler предупредит об этом
        в логгере. Атрибут Message.animation остаётся None.

        duration/width/height/thumbnail/thumb принимаются для
        совместимости и игнорируются — MAX берёт метаданные из самого
        файла; caption_entities, allow_sending_without_reply,
        protect_content, message_thread_id и has_spoiler (спойлеров
        в MAX нет) — тоже.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param animation: Анимация — байты, file-like объект,
            InputMedia, http(s)-ссылка на файл или, как file_id
            в telebot, строка-токен ранее загруженного видео
        :type animation: Union[Any, str]

        :param caption: Подпись к анимации
        :type caption: Optional[str]

        :param parse_mode: Разметка подписи (markdown/html). Если не
            задана, берётся общая разметка бота
        :type parse_mode: Optional[str]

        :param disable_notification: True — отправить без звука
        :type disable_notification: Optional[bool]

        :param reply_to_message_id: Идентификатор сообщения, на которое
            ответить цитатой
        :type reply_to_message_id: Optional[int]

        :param reply_markup: Клавиатура — добавляется вложением
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param timeout: Таймаут запроса POST /messages в секундах, как
            в telebot; загрузку файла не покрывает — она идёт отдельными
            запросами со своими таймаутами
        :type timeout: Optional[int]

        :param reply_parameters: Как в telebot: если передан объект с
            message_id, он используется вместо reply_to_message_id
        :type reply_parameters: Optional[Any]

        :return: Отправленное сообщение
        :rtype: Message
        """
        if self._check_text_length(text=caption):
            raise ValueError(f'caption должен быть меньше 4000 символов.\nСейчас их {len(caption)}')
        reply_to_message_id = self._resolve_reply_target(
            reply_to_message_id, reply_parameters, "send_animation"
        )
        link = None
        if reply_to_message_id:
            link = {"type": "reply", "mid": reply_to_message_id}
        final_attachments = []
        if isinstance(animation, str) and animation.startswith(("http://", "https://")):
            # видео по URL MAX не принимает, а картинку — скачает сам:
            # гифка-ссылка деградирует до изображения; ссылка на видеофайл
            # умерла бы непонятной серверной ошибкой — отрезаем понятной
            path = animation.split("?", 1)[0].split("#", 1)[0].lower()
            if path.endswith((".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")):
                raise ValueError(
                    "send_animation: MAX скачивает URL только как изображение "
                    "(gif/jpg/png и т. п.) — ссылка на видеофайл не сработает "
                    "(в telebot анимации часто именно .mp4). Видео-анимацию "
                    "отправьте байтами или file-like объектом"
                )
            final_attachments.append({"type": "image", "payload": {"url": animation}})
        elif isinstance(animation, InputMedia) and animation.type == "video":
            final_attachments.append(animation.to_dict(api=self.api))
        else:
            final_attachments.append(
                InputMedia(type="video", media=animation).to_dict(api=self.api)
            )
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)
        return self._send_attachments(
            chat_id, caption, final_attachments,
            self._resolve_parse_mode(parse_mode),
            notify=not disable_notification,
            link=link,
            # как в telebot: timeout=0 означает «без своего таймаута»
            timeout=timeout or None
        )

    def send_video_note(
        self,
        chat_id: Union[int, str],
        data: Union[Any, str],
        duration: Optional[int] = None,
        length: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        disable_notification: Optional[bool] = None,
        timeout: Optional[int] = None,
        thumbnail: Optional[Any] = None,
        allow_sending_without_reply: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        message_thread_id: Optional[int] = None,
        thumb: Optional[Any] = None,
        reply_parameters: Optional[Any] = None,
    ) -> Message:
        """
        Отправляет видеосообщение («кружок»). Сигнатура один в один
        с telebot.send_video_note (видео передаётся первым параметром
        data — историческое имя telebot), но отдельного типа кружков
        в MAX нет — файл уходит обычным видео через
        POST /uploads?type=video и придёт прямоугольным, с content_type
        "video". Строка — как file_id в telebot: токен ранее
        загруженного видео, без повторной загрузки. URL-строка не
        поддерживается (ValueError) — как и в telebot, где кружки
        по URL не отправляются.

        Следствие: телеботовский обработчик
        content_types=['video_note'] не сработает никогда —
        подписывайтесь на ['video'] (message_handler предупредит);
        атрибут Message.video_note остаётся None.

        duration/length/thumbnail/thumb принимаются для совместимости
        и игнорируются — MAX берёт метаданные из самого файла;
        allow_sending_without_reply, protect_content и
        message_thread_id — тоже.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param data: Видео — байты, file-like объект, InputMedia или,
            как file_id в telebot, строка-токен ранее загруженного
            видео. URL-строка не поддерживается (ValueError)
        :type data: Union[Any, str]

        :param duration: Принимается для совместимости и игнорируется
        :type duration: Optional[int]

        :param length: Диаметр кружка в telebot — принимается для
            совместимости и игнорируется, в MAX видео прямоугольное
        :type length: Optional[int]

        :param reply_to_message_id: Идентификатор сообщения, на которое
            ответить цитатой
        :type reply_to_message_id: Optional[int]

        :param reply_markup: Клавиатура — добавляется вложением
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param disable_notification: True — отправить без звука
        :type disable_notification: Optional[bool]

        :param timeout: Таймаут запроса POST /messages в секундах, как
            в telebot; загрузку файла не покрывает — она идёт отдельными
            запросами со своими таймаутами
        :type timeout: Optional[int]

        :param reply_parameters: Как в telebot: если передан объект с
            message_id, он используется вместо reply_to_message_id
        :type reply_parameters: Optional[Any]

        :return: Отправленное сообщение
        :rtype: Message
        """
        if isinstance(data, str) and data.startswith(("http://", "https://")):
            raise ValueError(
                "send_video_note: URL не поддерживается (как и в telebot — "
                "кружки по URL не отправляются). Видео можно отправить "
                "байтами, file-like объектом или строкой-токеном ранее "
                "загруженного видео"
            )
        reply_to_message_id = self._resolve_reply_target(
            reply_to_message_id, reply_parameters, "send_video_note"
        )
        link = None
        if reply_to_message_id:
            link = {"type": "reply", "mid": reply_to_message_id}
        final_attachments = []
        if isinstance(data, InputMedia) and data.type == "video":
            final_attachments.append(data.to_dict(api=self.api))
        else:
            final_attachments.append(
                InputMedia(type="video", media=data).to_dict(api=self.api)
            )
        if reply_markup:
            if hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)
        return self._send_attachments(
            chat_id, None, final_attachments,
            # подписи у кружка нет — text=None, разметка не уходит
            None,
            notify=not disable_notification,
            link=link,
            # как в telebot: timeout=0 означает «без своего таймаута»
            timeout=timeout or None
        )

    def send_audio(
        self,
        chat_id: Union[int, str],
        audio: Union[Any, str],
        caption: Optional[str] = None,
        duration: Optional[int] = None,
        performer: Optional[str] = None,
        title: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        parse_mode: Optional[str] = None,
        disable_notification: Optional[bool] = None,
        timeout: Optional[int] = None,
        thumbnail: Optional[Any] = None,
        caption_entities: Optional[Any] = None,
        allow_sending_without_reply: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        message_thread_id: Optional[int] = None,
        thumb: Optional[Any] = None,
        reply_parameters: Optional[Any] = None,
    ) -> Message:
        """
        Отправляет аудио. Сигнатура один в один с telebot.send_audio.
        У MAX родной тип загрузки: POST /uploads?type=audio (токен
        приходит сразу в ответе, как у видео), затем POST /messages
        с вложением {"type": "audio", "payload": {"token": ...}};
        ретраи attachment.not.ready — те же, что у видео и файлов.

        По документации MAX аудио обязано быть ЕДИНСТВЕННЫМ вложением
        сообщения, поэтому переданный reply_markup игнорируется
        с предупреждением в логгере (в telebot клавиатуру к аудио
        приложить можно) — отправьте её отдельным сообщением.

        duration/performer/title принимаются для совместимости и
        игнорируются — MAX берёт метаданные из самого файла;
        thumbnail/thumb (обложка), caption_entities,
        allow_sending_without_reply, protect_content и
        message_thread_id — тоже. У возвращаемого Message заполняются
        базовые поля (message_id, chat, content_type "audio"), атрибут
        audio остаётся None.

        :param chat_id: Чат, куда надо отправить аудио
        :type chat_id: Union[int, str]

        :param audio: Аудио — байты, file-like объект, InputMedia или,
            как file_id в telebot, строка-токен ранее загруженного аудио
            (лежит во входящем вложении payload.token) — уходит без
            повторной загрузки. URL-строка не поддерживается
            (ValueError): MAX принимает URL только для изображений
        :type audio: Union[Any, str]

        :param caption: Текст сообщения при аудио
        :type caption: Optional[str]

        :param reply_to_message_id: Идентификатор сообщения, на которое
            ответить цитатой
        :type reply_to_message_id: Optional[int]

        :param reply_markup: Игнорируется — аудио в MAX обязано быть
            единственным вложением
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param parse_mode: Разметка подписи (markdown/html). Если не
            задана, берётся общая разметка бота
        :type parse_mode: Optional[str]

        :param disable_notification: True — отправить без звука
        :type disable_notification: Optional[bool]

        :param timeout: Таймаут запроса POST /messages в секундах, как в
            telebot. Отличие: в telebot аудио уходит одним запросом и
            timeout покрывает загрузку файла; в MAX файл загружается
            отдельными запросами со своими таймаутами (60 с на
            сокет-операцию загрузки), timeout на них не влияет
        :type timeout: Optional[int]

        :param reply_parameters: Как в telebot: если передан объект с
            message_id, он используется вместо reply_to_message_id
        :type reply_parameters: Optional[Any]

        :return: Отправленное сообщение
        :rtype: Message
        """
        if self._check_text_length(text=caption):
            raise ValueError(f'caption должен быть меньше 4000 символов.\nСейчас их {len(caption)}')
        if isinstance(audio, str) and audio.startswith(("http://", "https://")):
            raise ValueError(
                "MAX принимает URL только для изображений (send_photo). "
                "Аудио можно отправить байтами, file-like объектом или "
                "строкой-токеном ранее загруженного аудио"
            )
        if reply_markup is not None:
            logger.warning(
                "send_audio: по документации MAX аудио обязано быть "
                "единственным вложением сообщения — reply_markup "
                "игнорируется, отправьте клавиатуру отдельным сообщением"
            )
        reply_to_message_id = self._resolve_reply_target(
            reply_to_message_id, reply_parameters, "send_audio"
        )
        link = None
        if reply_to_message_id:
            link = {"type": "reply", "mid": reply_to_message_id}
        final_attachments = []
        if isinstance(audio, InputMedia) and audio.type == "audio":
            final_attachments.append(audio.to_dict(api=self.api))
        else:
            final_attachments.append(InputMedia(type="audio", media=audio).to_dict(api=self.api))
        return self._send_attachments(
            chat_id, caption, final_attachments,
            self._resolve_parse_mode(parse_mode),
            notify=not disable_notification,
            link=link,
            # как в telebot: timeout=0 означает «без своего таймаута»
            timeout=timeout or None
        )

    def send_voice(
        self,
        chat_id: Union[int, str],
        voice: Union[Any, str],
        caption: Optional[str] = None,
        duration: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        parse_mode: Optional[str] = None,
        disable_notification: Optional[bool] = None,
        timeout: Optional[int] = None,
        caption_entities: Optional[Any] = None,
        allow_sending_without_reply: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        message_thread_id: Optional[int] = None,
        reply_parameters: Optional[Any] = None,
    ) -> Message:
        """
        Отправляет голосовое сообщение. Сигнатура один в один с
        telebot.send_voice, но отдельного типа голосовых в MAX нет —
        файл уходит обычным аудио (тонкая обёртка над send_audio,
        предупреждения в логгере будут от имени send_audio): без
        «кружка»-плеера голосового, формат должен быть звуковым,
        который принимает MAX (MP3, WAV, M4A и другие).

        Следствие: и у отправленного, и у входящего сообщения
        content_type — "audio", а не "voice", поэтому телеботовский
        обработчик content_types=['voice'] не сработает никогда —
        подписывайтесь на content_types=['audio'] (message_handler
        предупредит об этом в логгере); атрибут voice у Message
        остаётся None.

        duration, caption_entities, allow_sending_without_reply,
        protect_content и message_thread_id принимаются для
        совместимости и игнорируются; reply_markup игнорируется
        с предупреждением — аудио в MAX обязано быть единственным
        вложением сообщения.

        :param chat_id: Чат, куда надо отправить голосовое
        :type chat_id: Union[int, str]

        :param voice: Аудио — байты, file-like объект или InputMedia.
            URL-строка не поддерживается (ValueError)
        :type voice: Union[Any, str]

        :param caption: Текст сообщения при аудио
        :type caption: Optional[str]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :return: Отправленное сообщение
        :rtype: Message
        """
        return self.send_audio(
            chat_id,
            voice,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            timeout=timeout,
            reply_parameters=reply_parameters,
        )

    def send_sticker(
        self,
        chat_id: Union[int, str],
        sticker: Union[Any, str],
        reply_to_message_id: Optional[int] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        disable_notification: Optional[bool] = None,
        timeout: Optional[int] = None,
        allow_sending_without_reply: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        data: Union[Any, str] = None,
        message_thread_id: Optional[int] = None,
        emoji: Optional[str] = None,
        reply_parameters: Optional[Any] = None,
    ) -> Message:
        """
        Отправляет стикер. Сигнатура один в один с telebot.send_sticker;
        в MAX это POST /messages со вложением
        {"type": "sticker", "payload": {"code": ...}}.

        Отличие от telebot: параметр sticker — это строка-КОД стикера
        MAX (аналог file_id; код лежит во входящем вложении
        payload.code, когда пользователь присылает стикер). Свои
        webp/tgs-файлы загрузить нельзя — типа sticker в POST /uploads
        нет, поэтому файл, байты или URL вместо кода — ValueError
        с объяснением. Пользуйтесь стикерами из каталога MAX.

        По документации MAX стикер обязан быть ЕДИНСТВЕННЫМ вложением
        сообщения, поэтому переданный reply_markup игнорируется
        с предупреждением в логгере (в telebot клавиатуру к стикеру
        приложить можно) — отправьте её отдельным сообщением.

        emoji, allow_sending_without_reply, protect_content и
        message_thread_id принимаются для совместимости и игнорируются.
        У возвращаемого Message content_type — "sticker", как в telebot,
        но атрибут sticker остаётся None.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param sticker: Код стикера MAX (payload.code входящего
            стикера). Файл/байты/URL не поддерживаются — ValueError
        :type sticker: Union[Any, str]

        :param reply_to_message_id: Идентификатор сообщения, на которое
            ответить цитатой
        :type reply_to_message_id: Optional[int]

        :param reply_markup: Игнорируется — стикер в MAX обязан быть
            единственным вложением
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param disable_notification: True — отправить без звука
        :type disable_notification: Optional[bool]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :param data: Устаревший алиас sticker — как в telebot,
            используется с предупреждением, если sticker не передан
        :type data: Union[Any, str]

        :param emoji: Принимается для совместимости и игнорируется —
            эмодзи к стикеру в MAX не прикладывается
        :type emoji: Optional[str]

        :param reply_parameters: Как в telebot: если передан объект с
            message_id, он используется вместо reply_to_message_id
        :type reply_parameters: Optional[Any]

        :return: Отправленное сообщение
        :rtype: Message
        """
        if data and not sticker:
            # как в telebot: data — устаревший алиас sticker
            logger.warning(
                'send_sticker: параметр "data" устарел, используйте "sticker"'
            )
            sticker = data
        if not isinstance(sticker, str) or not sticker:
            raise ValueError(
                "send_sticker: sticker должен быть строкой-кодом стикера MAX "
                "(payload.code входящего стикера). Свои файлы загрузить "
                "нельзя — типа sticker в POST /uploads нет, пользуйтесь "
                "стикерами из каталога MAX"
            )
        if sticker.startswith(("http://", "https://")):
            raise ValueError(
                "send_sticker: URL не поддерживается — sticker должен быть "
                "строкой-кодом стикера MAX (payload.code входящего стикера)"
            )
        if reply_markup is not None:
            logger.warning(
                "send_sticker: по документации MAX стикер обязан быть "
                "единственным вложением сообщения — reply_markup "
                "игнорируется, отправьте клавиатуру отдельным сообщением"
            )
        reply_to_message_id = self._resolve_reply_target(
            reply_to_message_id, reply_parameters, "send_sticker"
        )
        return self.send_message(
            chat_id,
            None,
            attachments=[{"type": "sticker", "payload": {"code": sticker}}],
            notify=not disable_notification,
            reply_to_message_id=reply_to_message_id,
            timeout=timeout,
        )

    def forward_message(
        self,
        chat_id: Union[int, str],
        from_chat_id: Union[int, str],
        message_id: Union[int, str],
        disable_notification: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        timeout: Optional[int] = None,
        message_thread_id: Optional[int] = None,
    ) -> Message:
        """
        Пересылает сообщение. Сигнатура один в один с
        telebot.forward_message; в MAX пересылка встроена в отправку —
        POST /messages с link={"type": "forward", "mid": message_id}
        (само тело пустое: без текста и вложений).

        Идентификатор сообщения (mid) в MAX глобален, поэтому
        from_chat_id принимается для совместимости и не используется —
        сообщение находится по одному message_id. protect_content и
        message_thread_id принимаются и игнорируются.

        :param chat_id: Чат, куда переслать
        :type chat_id: Union[int, str]

        :param from_chat_id: Принимается для совместимости с telebot
            и не используется — mid в MAX глобален
        :type from_chat_id: Union[int, str]

        :param message_id: Идентификатор пересылаемого сообщения (mid)
        :type message_id: Union[int, str]

        :param disable_notification: True — переслать без звука
        :type disable_notification: Optional[bool]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :return: Отправленное сообщение-пересылка
        :rtype: Message
        """
        if isinstance(chat_id, int):
            chat_id = str(chat_id)
        response = self.api.send_message(
            chat_id=chat_id,
            text=None,
            attachments=None,
            parse_mode=None,
            notify=not disable_notification,
            link={"type": "forward", "mid": message_id},
            # как в telebot: timeout=0 означает «без своего таймаута»
            timeout=timeout or None,
        )
        return Message(update=response, api=self.api)

    def forward_messages(
        self,
        chat_id: Union[str, int],
        from_chat_id: Union[str, int],
        message_ids: List[Union[int, str]],
        disable_notification: Optional[bool] = None,
        message_thread_id: Optional[int] = None,
        protect_content: Optional[bool] = None,
    ) -> List[MessageID]:
        """
        Пересылает несколько сообщений: цикл forward_message по
        message_ids. Как в telebot, сообщения, которые переслать не
        удалось (например, не найдены), пропускаются с предупреждением
        в логгере — возвращается список успешно пересланных.

        :param message_ids: Идентификаторы пересылаемых сообщений
        :type message_ids: List[Union[int, str]]

        :return: Список MessageID пересланных сообщений
        :rtype: List[MessageID]
        """
        result = []
        for message_id in message_ids:
            try:
                message = self.forward_message(
                    chat_id, from_chat_id, message_id,
                    disable_notification=disable_notification,
                )
            except MaxApiException as e:
                logger.warning(
                    "forward_messages: сообщение %s пропущено: %s", message_id, e
                )
                continue
            result.append(MessageID(getattr(message, "message_id", None)))
        return result

    @staticmethod
    def _rebuild_attachments(attachments):
        """
        Пересобирает вложения полученного сообщения в форму отправки
        (для copy_message): медиа — по token (задокументированный в MAX
        способ переиспользовать вложение в другом сообщении), стикер —
        по code, локация — по координатам, контакт — по vcf_info и
        max_info. Клавиатура исходного сообщения не копируется (как у
        copyMessage в telebot), share-превью MAX построит заново по
        тексту; вложения без токена пропускаются.
        """
        rebuilt = []
        for attachment in attachments:
            a_type = attachment.get("type")
            payload = attachment.get("payload") or {}
            if a_type in ("image", "video", "audio", "file"):
                token = payload.get("token")
                if token:
                    rebuilt.append({"type": a_type, "payload": {"token": token}})
            elif a_type == "sticker":
                code = payload.get("code")
                if code:
                    rebuilt.append({"type": "sticker", "payload": {"code": code}})
            elif a_type == "location":
                rebuilt.append({
                    "type": "location",
                    "latitude": attachment.get("latitude"),
                    "longitude": attachment.get("longitude"),
                })
            elif a_type == "contact":
                max_info = payload.get("max_info") or {}
                name = max_info.get("name")
                if not name:
                    # по спеке у User нет name — только first_name/last_name
                    name = " ".join(filter(None, [
                        max_info.get("first_name"), max_info.get("last_name"),
                    ])) or None
                contact_payload = {"name": name}
                if max_info.get("user_id"):
                    contact_payload["contact_id"] = max_info.get("user_id")
                if payload.get("vcf_info"):
                    contact_payload["vcf_info"] = payload.get("vcf_info")
                rebuilt.append({"type": "contact", "payload": contact_payload})
            # inline_keyboard и share сознательно пропускаются
        return rebuilt

    def _copy_message(self, chat_id, message_id, caption=None, parse_mode=None,
                      disable_notification=None, reply_to_message_id=None,
                      reply_markup=None, timeout=None, remove_caption=False):
        """
        Общий путь copy_message/copy_messages: GET /messages/{messageId},
        пересборка вложений и новый POST /messages. Возвращает MessageID
        нового сообщения.
        """
        info = self.api.get_message(msg_id=message_id)
        msg = {}
        if isinstance(info, dict):
            msg = info.get("message") or info
        body = msg.get("body") or {}
        # у чистой пересылки собственное body пустое (по спеке может быть
        # и null) — видимый контент лежит в link.message; пересылка
        # с комментарием копируется как комментарий (текст body)
        link_info = msg.get("link") or {}
        if (link_info.get("type") == "forward"
                and not body.get("text") and not body.get("attachments")):
            body = link_info.get("message") or body
        rebuilt = self._rebuild_attachments(body.get("attachments") or [])
        attachments = list(rebuilt)
        if reply_markup:
            must_be_alone = {"audio", "file", "contact", "sticker"}
            alone_type = next((a.get("type") for a in rebuilt
                               if a.get("type") in must_be_alone), None)
            if alone_type:
                logger.warning(
                    "copy_message: вложение «%s» по документации MAX обязано "
                    "быть единственным вложением сообщения — reply_markup "
                    "игнорируется, отправьте клавиатуру отдельным сообщением",
                    alone_type,
                )
            elif hasattr(reply_markup, 'to_attachment'):
                attachments.append(reply_markup.to_attachment())
            else:
                attachments.append(reply_markup)
        if remove_caption:
            # как в telebot: снимается только подпись медиа — текст чисто
            # текстового сообщения сохраняется
            text = None if rebuilt else body.get("text")
        elif caption is not None:
            text = caption
        else:
            text = body.get("text")
        # формат — только для НОВОЙ подписи; исходный текст уходит как есть,
        # без повторной разметки (исходное оформление не переносится)
        resolved_parse_mode = None
        if caption is not None and not remove_caption:
            resolved_parse_mode = self._resolve_parse_mode(parse_mode)
        link = None
        if reply_to_message_id:
            link = {"type": "reply", "mid": reply_to_message_id}
        if isinstance(chat_id, int):
            chat_id = str(chat_id)
        response = self.api.send_message(
            chat_id=chat_id,
            text=text,
            attachments=attachments,
            parse_mode=resolved_parse_mode,
            notify=not disable_notification,
            link=link,
            timeout=timeout or None,
        )
        new_message_id = None
        if isinstance(response, dict):
            new_message_id = ((response.get("message") or {}).get("body") or {}).get("mid")
        return MessageID(new_message_id)

    def copy_message(
        self,
        chat_id: Union[int, str],
        from_chat_id: Union[int, str],
        message_id: Union[int, str],
        caption: Optional[str] = None,
        parse_mode: Optional[str] = None,
        caption_entities: Optional[Any] = None,
        disable_notification: Optional[bool] = None,
        protect_content: Optional[bool] = None,
        reply_to_message_id: Optional[int] = None,
        allow_sending_without_reply: Optional[bool] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
        timeout: Optional[int] = None,
        message_thread_id: Optional[int] = None,
        reply_parameters: Optional[Any] = None,
    ) -> MessageID:
        """
        Копирует сообщение без ссылки на оригинал (в отличие от
        forward_message). Сигнатура один в один с telebot.copy_message.
        Своего copyMessage в MAX нет — честная эмуляция:
        GET /messages/{messageId}, затем новый POST /messages с тем же
        текстом и пересобранными вложениями (медиа — по token, стикер —
        по code, локация — по координатам, контакт — по vcf_info).

        Копия сообщения-пересылки: у чистой пересылки собственное тело
        пустое, поэтому копируется видимый контент оригинала (из
        link.message); у пересылки с комментарием копируется комментарий.

        Отличия от telebot: клавиатура оригинала не копируется (как и в
        telebot) — новую можно передать в reply_markup, но если копия —
        это аудио, файл, стикер или контакт, MAX требует, чтобы вложение
        было единственным, и reply_markup игнорируется
        с предупреждением; исходное оформление текста (разметка) не
        переносится — текст уходит как есть; parse_mode применяется
        только к НОВОЙ подписи caption. from_chat_id принимается для
        совместимости и не используется — mid в MAX глобален.
        caption_entities, allow_sending_without_reply, protect_content
        и message_thread_id принимаются и игнорируются.

        :param chat_id: Чат, куда скопировать
        :type chat_id: Union[int, str]

        :param from_chat_id: Принимается для совместимости и не
            используется — mid в MAX глобален
        :type from_chat_id: Union[int, str]

        :param message_id: Идентификатор копируемого сообщения (mid)
        :type message_id: Union[int, str]

        :param caption: Новый текст вместо исходного
        :type caption: Optional[str]

        :param parse_mode: Разметка НОВОГО текста caption; исходный
            текст уходит без разметки
        :type parse_mode: Optional[str]

        :param disable_notification: True — отправить без звука
        :type disable_notification: Optional[bool]

        :param reply_to_message_id: Идентификатор сообщения, на которое
            ответить цитатой
        :type reply_to_message_id: Optional[int]

        :param reply_markup: Клавиатура нового сообщения
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :param timeout: Таймаут HTTP-запроса в секундах, как в telebot
        :type timeout: Optional[int]

        :param reply_parameters: Как в telebot: если передан объект с
            message_id, он используется вместо reply_to_message_id
        :type reply_parameters: Optional[Any]

        :return: Идентификатор нового сообщения
        :rtype: MessageID
        """
        return self._copy_message(
            chat_id,
            message_id,
            caption=caption,
            parse_mode=parse_mode,
            disable_notification=disable_notification,
            reply_to_message_id=self._resolve_reply_target(
                reply_to_message_id, reply_parameters, "copy_message"
            ),
            reply_markup=reply_markup,
            timeout=timeout,
        )

    def copy_messages(
        self,
        chat_id: Union[str, int],
        from_chat_id: Union[str, int],
        message_ids: List[Union[int, str]],
        disable_notification: Optional[bool] = None,
        message_thread_id: Optional[int] = None,
        protect_content: Optional[bool] = None,
        remove_caption: Optional[bool] = None,
    ) -> List[MessageID]:
        """
        Копирует несколько сообщений: цикл copy_message по message_ids.
        Как в telebot, сообщения, которые скопировать не удалось,
        пропускаются с предупреждением в логгере.

        :param message_ids: Идентификаторы копируемых сообщений
        :type message_ids: List[Union[int, str]]

        :param remove_caption: True — копировать медиа без подписи; как
            в telebot, снимается только подпись у сообщений
            с вложениями — чисто текстовые копируются с текстом
        :type remove_caption: Optional[bool]

        :return: Список MessageID новых сообщений
        :rtype: List[MessageID]
        """
        result = []
        for message_id in message_ids:
            try:
                result.append(self._copy_message(
                    chat_id,
                    message_id,
                    disable_notification=disable_notification,
                    remove_caption=bool(remove_caption),
                ))
            except MaxApiException as e:
                logger.warning(
                    "copy_messages: сообщение %s пропущено: %s", message_id, e
                )
                continue
        return result

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

    def edit_message_caption(
        self,
        caption: str,
        chat_id: Optional[Union[int, str]] = None,
        message_id: Optional[str] = None,
        inline_message_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
        caption_entities: Optional[Any] = None,
        reply_markup: Union[InlineKeyboardMarkup, Any] = None,
    ):
        """
        Меняет подпись сообщения с вложениями. Сигнатура один в один
        с telebot.edit_message_caption (caption — первым параметром).

        Своего editMessageCaption в MAX нет, а PUT /messages заменяет
        body целиком, поэтому честная эмуляция: GET /messages/{messageId}
        → текущие вложения пересобираются в форму отправки (медиа — по
        token, стикер — по code, локация — по координатам, контакт — по
        vcf_info/max_info) → PUT /messages с новой подписью и теми же
        вложениями. Reply/forward-связка исходного сообщения
        переносится в PUT — правка подписи не снимает ответ (как и в
        Telegram). Правка приходит без пуша (notify=False).

        Как в telebot: без reply_markup клавиатура исходного сообщения
        СНИМАЕТСЯ (editMessageCaption в Telegram ведёт себя так же) —
        чтобы сохранить её, передайте клавиатуру заново. К сообщению
        с аудио/файлом/стикером/контактом клавиатура не прикладывается
        (по документации MAX такое вложение обязано быть единственным) —
        предупреждение в логгере.

        Отличия от telebot: на чисто текстовом сообщении просто заменит
        текст (в Telegram была бы ошибка «нет подписи»); разметка
        исходной подписи не переносится — parse_mode действует на новую
        подпись; caption_entities игнорируется.

        :param caption: Новая подпись
        :type caption: str

        :param chat_id: Идентификатор чата — принимается для
            совместимости, mid в MAX глобален
        :type chat_id: Optional[Union[int, str]]

        :param message_id: Идентификатор сообщения — в MAX обязателен
            (без него ValueError: инлайн-сообщений в MAX нет)
        :type message_id: Optional[str]

        :param inline_message_id: Принимается для совместимости и
            игнорируется — инлайн-режима в MAX нет
        :type inline_message_id: Optional[str]

        :param parse_mode: Разметка новой подписи (markdown/html). Если
            не задана, берётся общая разметка бота
        :type parse_mode: Optional[str]

        :param caption_entities: Принимается для совместимости и
            игнорируется
        :type caption_entities: Optional[Any]

        :param reply_markup: Новая клавиатура; None — клавиатура
            снимается, как в telebot
        :type reply_markup: Union[InlineKeyboardMarkup, Any]

        :return: Message при успехе, иначе {} (как у соседних
            edit_message_*)
        :rtype: Message | {}
        """
        if not message_id:
            raise ValueError(
                "edit_message_caption: в MAX нужен message_id — "
                "инлайн-сообщений (inline_message_id) в MAX нет"
            )
        info = self.api.get_message(msg_id=message_id)
        msg = {}
        if isinstance(info, dict):
            msg = info.get("message") or info
        body = msg.get("body") or {}
        rebuilt = self._rebuild_attachments(body.get("attachments") or [])
        final_attachments = list(rebuilt)
        if reply_markup:
            must_be_alone = {"audio", "file", "contact", "sticker"}
            alone_type = next((a.get("type") for a in rebuilt
                               if a.get("type") in must_be_alone), None)
            if alone_type:
                logger.warning(
                    "edit_message_caption: вложение «%s» по документации MAX "
                    "обязано быть единственным вложением сообщения — "
                    "reply_markup игнорируется, отправьте клавиатуру "
                    "отдельным сообщением",
                    alone_type,
                )
            elif hasattr(reply_markup, 'to_attachment'):
                final_attachments.append(reply_markup.to_attachment())
            else:
                final_attachments.append(reply_markup)

        # PUT заменяет body целиком — reply/forward-связку исходного
        # сообщения переносим, чтобы правка подписи не снимала ответ
        # (editMessageCaption в Telegram связку не трогает)
        link_info = msg.get("link") or {}
        link_mid = (link_info.get("message") or {}).get("mid")
        put_link = None
        if link_info.get("type") and link_mid:
            put_link = {"type": link_info["type"], "mid": link_mid}

        response = self.api.send_message(
            msg_id=message_id,
            text=caption,
            method="PUT",
            attachments=final_attachments,
            parse_mode=self._resolve_parse_mode(parse_mode),
            # правка не должна пушить «Сообщение было изменено»
            notify=False,
            link=put_link,
        )

        if isinstance(response, dict) and response.get("success"):
            timestamp = int(time.time() * 1000)
            message_data = get_edit_message_data(caption, chat_id, message_id, final_attachments, timestamp)
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

    def get_chat(self, chat_id: Union[int, str]) -> Chat:
        """
        Возвращает информацию о чате (GET /chats/{chatId}). Сигнатура
        один в один с telebot.get_chat.

        Поля результата как в telebot: id, type — типы MAX мапятся
        в телеботовские (dialog -> private, chat -> group,
        channel -> channel), title, description, photo (URL иконки
        чата — строка, а не ChatPhoto с file_id), pinned_message
        (Message или None), invite_link (постоянная ссылка чата);
        для диалогов — first_name/last_name/username собеседника.
        Дополнительно поля MAX: status, participants_count, is_public.

        Отличие от message.chat: там type — сырой тип MAX
        ("dialog"/"chat"/"channel"), исторически; у get_chat —
        телеботовские имена, чтобы работали перенесённые проверки
        вида chat.type == "private". Остальные атрибуты
        telebot.types.Chat существуют и равны None (permissions,
        is_forum и т.п. — в MAX их нет); bio диалога — описание
        профиля собеседника.

        :param chat_id: Идентификатор чата; строкой, как в telebot,
            можно передать "@username" или публичную ссылку чата
            (в MAX есть GET /chats/{chatLink}). У PATCH-методов
            (set_chat_*) такого маршрута нет — там только числовой id
        :type chat_id: Union[int, str]

        :return: Информация о чате
        :rtype: Chat
        """
        info = self.api.get_chat_info(chat_id=chat_id)
        return Chat.from_chat_info(info if isinstance(info, dict) else {}, api=self.api)

    def get_chat_member_count(self, chat_id: Union[int, str]) -> int:
        """
        Возвращает число участников чата (participants_count из
        GET /chats/{chatId}). Сигнатура один в один с
        telebot.get_chat_member_count. Для диалогов MAX всегда
        возвращает 2 (как и Telegram для private-чатов).

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :return: Число участников
        :rtype: int
        """
        info = self.api.get_chat_info(chat_id=chat_id)
        return info.get("participants_count") if isinstance(info, dict) else None

    def get_chat_members_count(self, *args, **kwargs) -> int:
        """
        Устаревший алиас get_chat_member_count — как в telebot,
        предупреждает в логгере и зовёт новый метод.
        """
        logger.warning(
            "get_chat_members_count устарел — используйте "
            "get_chat_member_count (как в telebot)"
        )
        return self.get_chat_member_count(*args, **kwargs)

    def set_chat_title(self, chat_id: Union[int, str], title: str) -> bool:
        """
        Меняет название чата (PATCH /chats/{chatId} с {"title"}).
        Сигнатура один в один с telebot.set_chat_title.

        Название диалога сменить нельзя (как и private-чата
        в Telegram) — MAX ответит ошибкой, она пробросится
        исключением. Участники увидят системное сообщение
        об изменении (поведение MAX по умолчанию, как в Telegram).

        :param chat_id: ЧИСЛОВОЙ идентификатор чата — в отличие от
            telebot, "@username" здесь не работает: у PATCH /chats
            в MAX нет маршрута по ссылке (у get_chat — есть)
        :type chat_id: Union[int, str]

        :param title: Новое название, 1–200 символов (лимит MAX;
            в Telegram — 1–128)
        :type title: str

        :return: True при успехе
        :rtype: bool
        """
        response = self.api.edit_chat_info(chat_id, {"title": title})
        return isinstance(response, dict)

    def set_chat_description(self, chat_id: Union[int, str],
                             description: Optional[str] = None) -> bool:
        """
        Меняет описание чата (PATCH /chats/{chatId} с {"description"}).
        Сигнатура один в один с telebot.set_chat_description.

        Как в telebot/Telegram: description=None или пустая строка —
        описание удаляется (MAX удаляет по пустой строке). Лимит MAX —
        16000 символов (в Telegram — 255).

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param description: Новое описание; None/"" — удалить
        :type description: Optional[str]

        :return: True при успехе
        :rtype: bool
        """
        response = self.api.edit_chat_info(
            chat_id,
            {"description": description if description is not None else ""},
        )
        return isinstance(response, dict)

    def set_chat_photo(self, chat_id: Union[int, str], photo: Any) -> bool:
        """
        Меняет фото (иконку) чата — PATCH /chats/{chatId} с {"icon"}.
        Сигнатура один в один с telebot.set_chat_photo.

        photo — байты или file-like объект (файл загружается через
        POST /uploads?type=image, в иконку уходит токен); строка —
        расширение против telebot: http(s)-ссылка на изображение
        (MAX скачает сам) или токен ранее загруженного изображения.
        Участники увидят системное сообщение об изменении.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param photo: Изображение — байты, file-like, URL или токен
        :type photo: Any

        :return: True при успехе
        :rtype: bool
        """
        icon = InputMedia(type="photo", media=photo).to_dict(api=self.api)
        payload = icon.get("payload") if isinstance(icon, dict) else None
        if not payload:
            raise ValueError(
                "set_chat_photo: не удалось подготовить изображение — "
                "передайте байты, file-like объект, URL или токен"
            )
        response = self.api.edit_chat_info(chat_id, {"icon": payload})
        return isinstance(response, dict)

    def delete_chat_photo(self, chat_id: Union[int, str]) -> bool:
        """
        Удаляет фото (иконку) чата — PATCH /chats/{chatId}
        с {"icon": null} (поле по спеке nullable). Сигнатура один
        в один с telebot.delete_chat_photo. Если сервер MAX отвергнет
        null-иконку, ошибка пробросится исключением.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :return: True при успехе
        :rtype: bool
        """
        response = self.api.edit_chat_info(chat_id, {"icon": None})
        return isinstance(response, dict)

    def export_chat_invite_link(self, chat_id: Union[int, str]) -> str:
        """
        Возвращает ссылку-приглашение чата. Сигнатура один в один
        с telebot.export_chat_invite_link.

        Отличие от Telegram: ссылка НЕ перегенерируется — в MAX у чата
        одна постоянная ссылка (поле link из GET /chats/{chatId}),
        отозвать или пересоздать её через Bot API нельзя. У приватного
        чата без ссылки вернётся None.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :return: Постоянная ссылка чата или None
        :rtype: str
        """
        info = self.api.get_chat_info(chat_id=chat_id)
        return info.get("link") if isinstance(info, dict) else None

    @staticmethod
    def _member_user_id(user_id):
        """user_id из telebot приходит и строкой — для сравнения с
        числовыми user_id MAX приводим к int, когда возможно."""
        try:
            return int(user_id)
        except (TypeError, ValueError):
            return user_id

    def get_chat_member(self, chat_id: Union[int, str], user_id: int) -> ChatMember:
        """
        Возвращает информацию об участнике чата
        (GET /chats/{chatId}/members?user_ids={user_id}). Сигнатура
        один в один с telebot.get_chat_member. Видно только админам:
        бот должен быть администратором чата.

        Статусы MAX мапятся в телеботовские: владелец -> 'creator',
        админ -> 'administrator', иначе 'member'; если пользователя
        в чате нет, вернётся заглушка со status='left' (как в Telegram
        для вышедших). Статусов 'restricted' и 'kicked' в MAX не
        разглядеть. can_*-флаги собираются из прав MAX (см. ChatMember).

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param user_id: Идентификатор пользователя
        :type user_id: int

        :return: Участник чата
        :rtype: ChatMember
        """
        wanted = self._member_user_id(user_id)
        response = self.api.get_chat_members(chat_id, user_ids=[wanted])
        members = response.get("members") if isinstance(response, dict) else None
        for member in members or []:
            if member.get("user_id") == wanted:
                return ChatMember(member)
        return ChatMember({"user_id": wanted}, status="left")

    def get_chat_administrators(self, chat_id: Union[int, str]) -> List[ChatMember]:
        """
        Возвращает администраторов чата
        (GET /chats/{chatId}/members/admins). Сигнатура один в один
        с telebot.get_chat_administrators. Бот должен быть
        администратором чата — иначе MAX ответит ошибкой, она
        пробросится исключением.

        Владелец в списке имеет status='creator', остальные —
        'administrator' (как в telebot).

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :return: Список администраторов
        :rtype: List[ChatMember]
        """
        response = self.api.get_chat_admins(chat_id)
        members = response.get("members") if isinstance(response, dict) else None
        return [ChatMember(member) for member in members or []]

    def get_chat_membership(self, chat_id: Union[int, str]) -> ChatMember:
        """
        Возвращает членство самого бота в чате
        (GET /chats/{chatId}/members/me) — расширение MAX, в telebot
        аналога нет (ближайшее — get_chat_member(chat_id, bot.id)).
        Удобно проверять, админ ли бот и какие у него права.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :return: Участник-бот
        :rtype: ChatMember
        """
        member = self.api.get_chat_membership(chat_id)
        return ChatMember(member if isinstance(member, dict) else {})

    def ban_chat_member(
        self,
        chat_id: Union[int, str],
        user_id: int,
        until_date: Optional[Union[int, Any]] = None,
        revoke_messages: Optional[bool] = None,
    ) -> bool:
        """
        Удаляет пользователя из чата с блокировкой
        (DELETE /chats/{chatId}/members с block=true). Сигнатура один
        в один с telebot.ban_chat_member. Боту нужно право
        add_remove_members.

        Отличия от Telegram: блокировка действует только в чатах
        с публичной или приватной ссылкой — в остальных MAX её
        игнорирует и просто удаляет участника; временных банов нет —
        until_date игнорируется с предупреждением (бан бессрочный);
        разбана через Bot API тоже нет (unban_chat_member бросает
        NotImplementedError) — снять блокировку может только
        администратор вручную. Если нужно удалить с возможностью
        вернуться — bot.api.remove_chat_member(chat_id, user_id)
        без block.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param user_id: Идентификатор пользователя
        :type user_id: int

        :param until_date: Игнорируется с предупреждением — временных
            банов в MAX нет
        :type until_date: Optional[Union[int, datetime]]

        :param revoke_messages: Игнорируется с предупреждением —
            массового удаления сообщений при бане в MAX нет
        :type revoke_messages: Optional[bool]

        :return: True при успехе; False, если MAX ответил
            success: false — telebot в такой ситуации бросает
            ApiTelegramException, поэтому при переносе проверяйте
            возврат. HTTP-ошибки, как и в telebot, бросают исключение
        :rtype: bool
        """
        if until_date is not None:
            logger.warning(
                "ban_chat_member: until_date игнорируется — временных "
                "банов в MAX нет, блокировка бессрочная"
            )
        if revoke_messages:
            logger.warning(
                "ban_chat_member: revoke_messages игнорируется — "
                "массового удаления сообщений забаненного в MAX нет"
            )
        response = self.api.remove_chat_member(
            chat_id, self._member_user_id(user_id), block=True
        )
        return bool(isinstance(response, dict) and response.get("success", False))

    def kick_chat_member(self, *args, **kwargs) -> bool:
        """
        Устаревший алиас ban_chat_member — как в telebot, предупреждает
        в логгере и зовёт новый метод.
        """
        logger.warning(
            "kick_chat_member устарел — используйте ban_chat_member "
            "(как в telebot)"
        )
        return self.ban_chat_member(*args, **kwargs)

    def unban_chat_member(
        self,
        chat_id: Union[int, str],
        user_id: int,
        only_if_banned: Optional[bool] = False,
    ) -> bool:
        """
        Заглушка: разбана в Bot API MAX нет. Сигнатура один в один
        с telebot.unban_chat_member, но вызов всегда бросает
        NotImplementedError (прецедент — answer_inline_query):
        блокировка ban_chat_member необратима со стороны бота, снять
        её может только администратор вручную в приложении.

        Телеграмный приём «кикнуть с правом вернуться» (ban + unban)
        в MAX делается одним вызовом
        bot.api.remove_chat_member(chat_id, user_id) без block.

        :raises NotImplementedError: всегда
        """
        raise NotImplementedError(
            "unban_chat_member: в Bot API MAX нет разбана — блокировка "
            "ban_chat_member необратима со стороны бота, её снимает "
            "только администратор вручную. Удаление с возможностью "
            "вернуться: bot.api.remove_chat_member(chat_id, user_id)"
        )

    def promote_chat_member(
        self,
        chat_id: Union[int, str],
        user_id: int,
        can_change_info: Optional[bool] = None,
        can_post_messages: Optional[bool] = None,
        can_edit_messages: Optional[bool] = None,
        can_delete_messages: Optional[bool] = None,
        can_invite_users: Optional[bool] = None,
        can_restrict_members: Optional[bool] = None,
        can_pin_messages: Optional[bool] = None,
        can_promote_members: Optional[bool] = None,
        is_anonymous: Optional[bool] = None,
        can_manage_chat: Optional[bool] = None,
        can_manage_video_chats: Optional[bool] = None,
        can_manage_voice_chats: Optional[bool] = None,
        can_manage_topics: Optional[bool] = None,
        can_post_stories: Optional[bool] = None,
        can_edit_stories: Optional[bool] = None,
        can_delete_stories: Optional[bool] = None,
    ) -> bool:
        """
        Назначает пользователя администратором чата
        (POST /chats/{chatId}/members/admins) или, если все флаги
        False/None, снимает с него админку
        (DELETE /chats/{chatId}/members/admins/{userId}) — как
        в Telegram, где promote со всеми False разжалует. Сигнатура
        один в один с telebot.promote_chat_member. Боту нужно право
        add_admins.

        Телеботовские флаги мапятся в права MAX:
        can_change_info -> change_chat_info;
        can_pin_messages -> pin_message;
        can_invite_users и can_restrict_members -> add_remove_members
        (в MAX это одно право «добавлять и удалять участников»);
        can_promote_members -> add_admins;
        can_post_messages -> write (в каналах — писать посты,
        в группах MAX это же право позволяет править и удалять чужие
        сообщения); can_edit_messages -> edit и
        can_delete_messages -> delete (в MAX действуют в каналах);
        can_manage_video_chats/can_manage_voice_chats -> can_call;
        can_manage_chat -> read_all_messages (читать все сообщения).
        Флаги без аналога (is_anonymous, can_manage_topics,
        can_post_stories, can_edit_stories, can_delete_stories) при
        True игнорируются с предупреждением. Права MAX edit_link
        и view_stats из telebot не выдать — при необходимости
        используйте bot.api.set_chat_admins напрямую.

        Повторный вызов заменяет набор прав целиком (PUT-семантика
        MAX — совпадает с Telegram). Внимание: alias при этом не
        передаётся, поэтому выставленный ранее титул админа может
        сброситься (в Telegram custom_title повторный promote
        переживает) — при необходимости повторите
        set_chat_administrator_custom_title после смены прав.

        :return: True при успехе; False, если MAX ответил
            success: false — при переносе проверяйте возврат
            (telebot бросил бы исключение). False и предупреждение —
            также если запрошены только права без аналога в MAX
            (например, один is_anonymous): назначить такого админа
            нечем, а разжаловать было бы противоположно намерению
        :rtype: bool
        """
        unmapped_flags = (
            ("is_anonymous", is_anonymous),
            ("can_manage_topics", can_manage_topics),
            ("can_post_stories", can_post_stories),
            ("can_edit_stories", can_edit_stories),
            ("can_delete_stories", can_delete_stories),
        )
        for name, value in unmapped_flags:
            if value:
                logger.warning(
                    "promote_chat_member: флаг %s игнорируется — "
                    "аналога в MAX нет", name
                )

        flag_permissions = (
            (can_change_info, ("change_chat_info",)),
            (can_post_messages, ("write",)),
            (can_edit_messages, ("edit",)),
            (can_delete_messages, ("delete",)),
            (can_invite_users, ("add_remove_members",)),
            (can_restrict_members, ("add_remove_members",)),
            (can_pin_messages, ("pin_message",)),
            (can_promote_members, ("add_admins",)),
            (can_manage_chat, ("read_all_messages",)),
            (can_manage_video_chats, ("can_call",)),
            (can_manage_voice_chats, ("can_call",)),
        )
        permissions = []
        for value, mapped in flag_permissions:
            if value:
                for permission in mapped:
                    if permission not in permissions:
                        permissions.append(permission)

        wanted = self._member_user_id(user_id)
        if permissions:
            response = self.api.set_chat_admins(
                chat_id, [{"user_id": wanted, "permissions": permissions}]
            )
        elif any(value for _, value in unmapped_flags):
            # запрошены ТОЛЬКО права без аналога в MAX: делать DELETE
            # нельзя — это разжаловало бы пользователя, хотя намерение
            # было противоположным (в Telegram такой promote назначает
            # админа)
            logger.warning(
                "promote_chat_member: запрошены только права без аналога "
                "в MAX — пользователь %s не назначен админом и не "
                "разжалован", user_id
            )
            return False
        else:
            # как в Telegram: promote со всеми False — разжалование
            response = self.api.delete_chat_admin(chat_id, wanted)
        return bool(isinstance(response, dict) and response.get("success", False))

    def set_chat_administrator_custom_title(
        self, chat_id: Union[int, str], user_id: int, custom_title: str
    ) -> bool:
        """
        Задаёт администратору отображаемый титул — alias админа MAX.
        Сигнатура один в один с telebot.set_chat_administrator_custom_title.

        Пользователь уже должен быть администратором (иначе ValueError —
        сначала promote_chat_member): метод читает текущие права через
        GET /chats/{chatId}/members/admins и переотправляет их вместе
        с alias (POST admins заменяет набор прав целиком, поэтому слать
        один alias нельзя).

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param user_id: Идентификатор администратора
        :type user_id: int

        :param custom_title: Титул; лимит telebot (16 символов) MAX
            не навязывает
        :type custom_title: str

        :return: True при успехе; False, если MAX ответил
            success: false — при переносе проверяйте возврат
            (telebot бросил бы исключение)
        :rtype: bool
        """
        wanted = self._member_user_id(user_id)
        response = self.api.get_chat_admins(chat_id)
        members = response.get("members") if isinstance(response, dict) else None
        target = None
        for member in members or []:
            if member.get("user_id") == wanted:
                target = member
                break
        if target is None:
            raise ValueError(
                "set_chat_administrator_custom_title: пользователь "
                f"{user_id} не администратор чата — сначала назначьте "
                "его через promote_chat_member"
            )
        if target.get("is_owner"):
            # у владельца permissions по спеке null — POST с пустым
            # набором прав по PUT-семантике MAX попытался бы их срезать;
            # в Telegram титул владельцу ботом тоже не задать
            raise ValueError(
                "set_chat_administrator_custom_title: пользователь "
                f"{user_id} — владелец чата, титул владельцу через "
                "Bot API не задать (как в Telegram, где метод работает "
                "только для назначенных администраторов)"
            )
        admin = {
            "user_id": wanted,
            "permissions": target.get("permissions") or [],
            "alias": custom_title,
        }
        result = self.api.set_chat_admins(chat_id, [admin])
        return bool(isinstance(result, dict) and result.get("success", False))

    def add_chat_members(self, chat_id: Union[int, str],
                         user_ids: Union[int, List[int]]) -> bool:
        """
        Добавляет участников в чат (POST /chats/{chatId}/members) —
        расширение MAX: Telegram-боты добавлять людей не умеют,
        в telebot аналога нет. Боту нужно право add_remove_members.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param user_ids: Идентификатор пользователя или их список
        :type user_ids: Union[int, List[int]]

        :return: True, если все добавлены; если кого-то добавить
            не удалось (failed_user_ids в ответе — например, настройки
            приватности), пишется предупреждение и возвращается False
        :rtype: bool
        """
        if isinstance(user_ids, (int, str)):
            user_ids = [user_ids]
        response = self.api.add_chat_members(
            chat_id, [self._member_user_id(uid) for uid in user_ids]
        )
        response = response if isinstance(response, dict) else {}
        # у FailedUserDetails по спеке плюральный user_ids (список)
        details = response.get("failed_user_details") or []
        failed = response.get("failed_user_ids") or [
            uid for detail in details for uid in detail.get("user_ids") or []
        ]
        if failed:
            codes = sorted({
                detail.get("error_code")
                for detail in details if detail.get("error_code")
            })
            logger.warning(
                "add_chat_members: не удалось добавить пользователей %s (%s)",
                failed,
                ", ".join(codes) if codes
                else "например, настройки приватности не позволяют",
            )
        return bool(response.get("success", False)) and not failed

    def pin_chat_message(
        self,
        chat_id: Union[int, str],
        message_id: Union[int, str],
        disable_notification: Optional[bool] = False,
    ) -> bool:
        """
        Закрепляет сообщение в чате (PUT /chats/{chatId}/pin).
        Сигнатура один в один с telebot.pin_chat_message. Боту нужно
        право pin_message.

        Отличие от Telegram: закреп в MAX один на чат — новый
        вытесняет старый (в Telegram закрепов много).

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param message_id: Идентификатор (mid) закрепляемого сообщения —
            в MAX это строка (message.message_id)
        :type message_id: Union[int, str]

        :param disable_notification: True — не уведомлять участников
            (по умолчанию, как в Telegram, уведомление уходит)
        :type disable_notification: Optional[bool]

        :return: True при успехе; False, если MAX ответил
            success: false — telebot в такой ситуации бросает
            ApiTelegramException, поэтому при переносе проверяйте
            возврат. HTTP-ошибки, как и в telebot, бросают исключение
        :rtype: bool
        """
        # notify шлём только при отключении: пропуск поля = серверный
        # default true, что и означает disable_notification=False/None
        notify = False if disable_notification else None
        response = self.api.pin_message(chat_id, message_id, notify=notify)
        return bool(isinstance(response, dict) and response.get("success", False))

    def unpin_chat_message(
        self,
        chat_id: Union[int, str],
        message_id: Optional[Union[int, str]] = None,
    ) -> bool:
        """
        Снимает закреп в чате (DELETE /chats/{chatId}/pin). Сигнатура
        один в один с telebot.unpin_chat_message.

        Закреп в MAX один на чат, поэтому message_id не нужен серверу;
        если он передан, метод сверяет его с текущим закрепом
        (GET /chats/{chatId}/pin) и, когда закреплено ДРУГОЕ сообщение
        или закрепа нет вовсе, ничего не снимает — предупреждение
        и False (в Telegram снялся бы именно указанный закреп из
        многих).

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :param message_id: Идентификатор (mid) сообщения, чей закреп
            снять — в MAX это строка; None — снять текущий закреп
        :type message_id: Optional[Union[int, str]]

        :return: True при успехе; False, если закреплено другое
            сообщение или MAX ответил success: false — при переносе
            проверяйте возврат (telebot бросил бы исключение)
        :rtype: bool
        """
        if message_id is not None:
            info = self.api.get_pinned_message(chat_id)
            pinned = info.get("message") if isinstance(info, dict) else None
            # message в 200-ответе бывает и СТРОКОЙ — текстом ошибки
            # (формы {"success": false, "message": ...} и {code, message}
            # проходят мимо guard'а клиента), поэтому isinstance
            pinned_mid = (
                (pinned.get("body") or {}).get("mid")
                if isinstance(pinned, dict) else None
            )
            if pinned_mid != message_id:
                logger.warning(
                    "unpin_chat_message: закреплено сообщение %s, а не %s — "
                    "закреп не снят (в MAX закреп один на чат)",
                    pinned_mid, message_id,
                )
                return False
        response = self.api.unpin_message(chat_id)
        return bool(isinstance(response, dict) and response.get("success", False))

    def unpin_all_chat_messages(self, chat_id: Union[int, str]) -> bool:
        """
        Снимает все закрепы чата (DELETE /chats/{chatId}/pin).
        Сигнатура один в один с telebot.unpin_all_chat_messages.
        Закреп в MAX один на чат, поэтому метод эквивалентен
        unpin_chat_message без message_id.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :return: True при успехе; False при success: false — при
            переносе проверяйте возврат (telebot бросил бы исключение)
        :rtype: bool
        """
        response = self.api.unpin_message(chat_id)
        return bool(isinstance(response, dict) and response.get("success", False))

    def get_pinned_message(self, chat_id: Union[int, str]) -> Optional[Message]:
        """
        Возвращает закреплённое сообщение чата
        (GET /chats/{chatId}/pin) — расширение MAX: в telebot закреп
        достаётся только через get_chat(chat_id).pinned_message.
        None — если закрепа нет.

        :param chat_id: Идентификатор чата
        :type chat_id: Union[int, str]

        :return: Закреплённое сообщение или None
        :rtype: Optional[Message]
        """
        info = self.api.get_pinned_message(chat_id)
        pinned = info.get("message") if isinstance(info, dict) else None
        # message бывает и строкой — текстом ошибки в формах
        # {"success": false, "message": ...} / {code, message}, которые
        # проходят мимо guard'а клиента
        if not isinstance(pinned, dict):
            return None
        # sender по спеке может быть null (пост от имени канала) —
        # from_user тогда None, как в telebot; timestamp нужен наверху
        # для date
        return Message(
            update={
                "message": pinned,
                "timestamp": pinned.get("timestamp"),
            },
            api=self.api,
        )

    def _warn_commands_scope_unsupported(self, method_name, scope, language_code):
        """Скоупов и языковых версий команд в MAX нет — предупреждаем,
        если мигрантский код на них рассчитывает."""
        if scope is not None:
            logger.warning(
                "%s: скоупов команд в MAX нет — scope игнорируется, "
                "команды применяются во всех чатах", method_name
            )
        if language_code is not None:
            logger.warning(
                "%s: языковых версий команд в MAX нет — language_code "
                "игнорируется", method_name
            )

    @staticmethod
    def _bot_command_to_max(command) -> Dict[str, Any]:
        """
        Приводит команду к объекту BotCommand MAX ({"name",
        "description"}): принимает maxibot/telebot BotCommand (любой
        объект с атрибутом command) и словарь с ключами name/command.
        """
        if isinstance(command, BotCommand):
            data = command.to_dict()
        else:
            if hasattr(command, "command"):
                name = getattr(command, "command", None)
                description = getattr(command, "description", None)
            elif isinstance(command, dict):
                name = command.get("name") or command.get("command")
                description = command.get("description")
            else:
                raise ValueError(
                    "set_my_commands: команда должна быть BotCommand или "
                    f"словарём с ключом name/command, получено: {command!r}"
                )
            data = {"name": (name or "").lstrip("/")}
            # пустая строка — как «без описания» (по спеке minLength 1)
            if description:
                data["description"] = description
        if not data.get("name"):
            raise ValueError(
                "set_my_commands: у команды пустое имя — нужен хотя бы "
                "один символ (лимит MAX — 64)"
            )
        return data

    def set_my_commands(
        self,
        commands: List[BotCommand],
        scope: Optional[Any] = None,
        language_code: Optional[str] = None,
    ) -> bool:
        """
        Задаёт список команд бота (PATCH /me с {"commands"}) — меню
        команд в клиенте MAX. Сигнатура один в один
        с telebot.set_my_commands. Список заменяется целиком.

        Команды — maxibot.types.BotCommand (или телеботовские
        BotCommand/словари {"command"/"name", "description"}); ведущий
        '/' срезается. Лимиты MAX: до 32 команд, имя до 64 символов,
        описание до 128. Скоупов и языковых версий в MAX нет — scope
        и language_code игнорируются с предупреждением.

        :param commands: Список команд
        :type commands: List[BotCommand]

        :param scope: Игнорируется с предупреждением — скоупов в MAX нет
        :type scope: Optional[Any]

        :param language_code: Игнорируется с предупреждением
        :type language_code: Optional[str]

        :return: True при успехе
        :rtype: bool
        """
        self._warn_commands_scope_unsupported(
            "set_my_commands", scope, language_code
        )
        # commands=None падает TypeError, как в telebot: молча слать []
        # значило бы удалить все команды — тихая потеря вместо краша
        payload = [self._bot_command_to_max(command) for command in commands]
        response = self.api.edit_bot_info({"commands": payload})
        return isinstance(response, dict)

    def get_my_commands(
        self,
        scope: Optional[Any] = None,
        language_code: Optional[str] = None,
    ) -> List[BotCommand]:
        """
        Возвращает список команд бота (commands из GET /me). Сигнатура
        один в один с telebot.get_my_commands. Скоупов и языковых
        версий в MAX нет — scope и language_code игнорируются
        с предупреждением.

        :return: Список команд (у каждой .command без '/'
            и .description)
        :rtype: List[BotCommand]
        """
        self._warn_commands_scope_unsupported(
            "get_my_commands", scope, language_code
        )
        info = self.api.get_bot_info()
        commands = info.get("commands") if isinstance(info, dict) else None
        return [BotCommand.from_max(command) for command in commands or []]

    def delete_my_commands(
        self,
        scope: Optional[Any] = None,
        language_code: Optional[str] = None,
    ) -> bool:
        """
        Удаляет все команды бота (PATCH /me с {"commands": []} — по
        спеке пустой список снимает команды). Сигнатура один в один
        с telebot.delete_my_commands. scope и language_code
        игнорируются с предупреждением — скоупов в MAX нет.

        :return: True при успехе
        :rtype: bool
        """
        self._warn_commands_scope_unsupported(
            "delete_my_commands", scope, language_code
        )
        response = self.api.edit_bot_info({"commands": []})
        return isinstance(response, dict)

    def set_my_name(
        self,
        name: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> bool:
        """
        Меняет отображаемое имя бота (PATCH /me с {"first_name"}) —
        в Telegram это умеет только BotFather, а MAX даёт ботам API.
        Сигнатура один в один с telebot.set_my_name.

        Отличие: сбросить имя нельзя — name обязателен (1–59 символов),
        с None/пустым будет ValueError (в Telegram пустое имя
        возвращает username).

        :param name: Новое имя, 1–59 символов
        :type name: Optional[str]

        :param language_code: Игнорируется с предупреждением —
            языковых версий имени в MAX нет
        :type language_code: Optional[str]

        :return: True при успехе
        :rtype: bool
        """
        if language_code is not None:
            logger.warning(
                "set_my_name: языковых версий имени в MAX нет — "
                "language_code игнорируется"
            )
        if not name:
            raise ValueError(
                "set_my_name: сбросить имя бота в MAX нельзя — "
                "передайте новое имя (1–59 символов)"
            )
        response = self.api.edit_bot_info({"first_name": name})
        return isinstance(response, dict)

    def get_my_name(self, language_code: Optional[str] = None) -> BotName:
        """
        Возвращает имя бота (first_name и last_name из GET /me,
        склеенные пробелом). Сигнатура один в один
        с telebot.get_my_name; language_code игнорируется
        с предупреждением — языковых версий имени в MAX нет.

        :return: Имя бота (.name)
        :rtype: BotName
        """
        if language_code is not None:
            logger.warning(
                "get_my_name: языковых версий имени в MAX нет — "
                "language_code игнорируется"
            )
        info = self.api.get_bot_info()
        info = info if isinstance(info, dict) else {}
        parts = [info.get("first_name"), info.get("last_name")]
        return BotName(name=" ".join(part for part in parts if part))

    def set_my_description(
        self,
        description: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> bool:
        """
        Меняет описание бота (PATCH /me с {"description"}) — в Telegram
        это умеет только BotFather, а MAX даёт ботам API. Сигнатура
        один в один с telebot.set_my_description. None/пустая строка —
        описание снимается (уходит null, поле по спеке nullable).
        Лимит MAX — 16000 символов (в Telegram — 512).

        :param description: Новое описание; None/"" — удалить
        :type description: Optional[str]

        :param language_code: Игнорируется с предупреждением —
            языковых версий описания в MAX нет
        :type language_code: Optional[str]

        :return: True при успехе
        :rtype: bool
        """
        if language_code is not None:
            logger.warning(
                "set_my_description: языковых версий описания в MAX "
                "нет — language_code игнорируется"
            )
        response = self.api.edit_bot_info(
            {"description": description if description else None}
        )
        return isinstance(response, dict)

    def get_my_description(
        self, language_code: Optional[str] = None
    ) -> BotDescription:
        """
        Возвращает описание бота (description из GET /me; пустая
        строка, если не задано — как в Telegram). Сигнатура один
        в один с telebot.get_my_description; language_code
        игнорируется с предупреждением — языковых версий в MAX нет.

        :return: Описание бота (.description)
        :rtype: BotDescription
        """
        if language_code is not None:
            logger.warning(
                "get_my_description: языковых версий описания в MAX "
                "нет — language_code игнорируется"
            )
        info = self.api.get_bot_info()
        description = info.get("description") if isinstance(info, dict) else None
        return BotDescription(description=description or "")

    def set_my_short_description(
        self,
        short_description: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> bool:
        """
        Заглушка: отдельного короткого описания в MAX нет — у бота
        одно description. Метод предупреждает и возвращает False,
        НЕ трогая основное описание (иначе типовой мигрантский код
        «set_my_description(длинное); set_my_short_description(короткое)»
        затирал бы длинное описание коротким). Сигнатура один в один
        с telebot.set_my_short_description.

        :return: Всегда False
        :rtype: bool
        """
        logger.warning(
            "set_my_short_description: отдельного короткого описания "
            "в MAX нет — вызов игнорируется, основное описание не "
            "тронуто (используйте set_my_description)"
        )
        return False

    def get_my_short_description(
        self, language_code: Optional[str] = None
    ) -> BotShortDescription:
        """
        Возвращает короткое описание бота. Отдельного короткого
        описания в MAX нет — заполняется из единственного description
        (пустая строка, если не задано). Сигнатура один в один
        с telebot.get_my_short_description; language_code игнорируется
        с предупреждением.

        :return: Короткое описание (.short_description)
        :rtype: BotShortDescription
        """
        if language_code is not None:
            logger.warning(
                "get_my_short_description: языковых версий описания "
                "в MAX нет — language_code игнорируется"
            )
        info = self.api.get_bot_info()
        description = info.get("description") if isinstance(info, dict) else None
        return BotShortDescription(short_description=description or "")

    def set_my_photo(self, photo: Any) -> bool:
        """
        Меняет аватар бота (PATCH /me с {"photo"}) — расширение MAX:
        в Telegram аватар бота меняется только через BotFather,
        в telebot аналога нет.

        photo — байты или file-like объект (загружается через
        POST /uploads?type=image, уходит токен); строка — http(s)-ссылка
        на изображение или токен ранее загруженного.

        :param photo: Изображение — байты, file-like, URL или токен
        :type photo: Any

        :return: True при успехе
        :rtype: bool
        """
        icon = InputMedia(type="photo", media=photo).to_dict(api=self.api)
        payload = icon.get("payload") if isinstance(icon, dict) else None
        if not payload:
            raise ValueError(
                "set_my_photo: не удалось подготовить изображение — "
                "передайте байты, file-like объект, URL или токен"
            )
        response = self.api.edit_bot_info({"photo": payload})
        return isinstance(response, dict)

    @staticmethod
    def _is_http_url(value: Any) -> bool:
        """Строка выглядит прямой http(s)-ссылкой"""
        return (isinstance(value, str)
                and value.lower().startswith(("http://", "https://")))

    def get_file(self, file_id: Optional[str]) -> File:
        """
        Готовит файл к скачиванию — как telebot.get_file, но в MAX нет
        file_id, поэтому метод принимает то, что лежит во вложениях:

        - прямую ссылку (message.document.file_path,
          message.photo[-1].file_path, message.audio.file_path) —
          возвращается сразу, без запроса к API;
        - токен видео (message.video.file_id) — ссылка берётся из
          GET /videos/{videoToken}: file_path = лучший доступный mp4
          (1080 -> … -> 144, если mp4 нет — hls); None, если видео
          недоступно.

        Токены остальных вложений (документов, аудио, фото) в MAX
        разрешить в ссылку нельзя — такого эндпоинта нет, GET /videos
        ответит 404 (MaxApiHTTPException). Поэтому канонический
        телеботовский паттерн для видео работает без правок:

            file_info = bot.get_file(message.video.file_id)
            data = bot.download_file(file_info.file_path)

        а для остальных вложений замените .file_id на .file_path —
        прямая ссылка уже лежит в самом вложении:

            file_info = bot.get_file(message.document.file_path)

        (или сразу bot.download_file(message.document.file_path)).

        :param file_id: Прямая ссылка или токен видео-вложения
        :type file_id: Optional[str]

        :return: File с file_path — полным URL для download_file
        :rtype: File
        """
        if not file_id:
            raise ValueError(
                "get_file: передайте прямую ссылку вложения "
                "(message.document.file_path) или токен видео "
                "(message.video.file_id)"
            )
        if self._is_http_url(file_id):
            return File(file_id=file_id, file_path=file_id)
        try:
            video = self.get_video(file_id)
        except MaxApiHTTPException as error:
            if error.status_code == 404:
                # частый случай миграции: в get_file попал токен
                # документа/аудио/фото, который в ссылку не разрешить
                logger.warning(
                    "get_file: токен не найден среди видео. В MAX "
                    "в ссылку разрешаются только токены видео; у "
                    "остальных вложений передавайте прямую ссылку — "
                    "message.document.file_path и т.п."
                )
            raise
        file_path = video.file_path if video else None
        return File(file_id=file_id, file_path=file_path)

    def get_file_url(self, file_id: Optional[str]) -> Optional[str]:
        """
        Прямая ссылка для скачивания файла — как telebot.get_file_url.
        Принимает то же, что get_file (ссылку или токен видео);
        в отличие от Telegram ссылка не собирается из токена бота —
        это готовый URL MAX. None — если видео недоступно
        (urls: null в GET /videos).

        :param file_id: Прямая ссылка или токен видео-вложения
        :type file_id: Optional[str]

        :return: Полный URL файла; None — видео недоступно
        :rtype: Optional[str]
        """
        return self.get_file(file_id).file_path

    def download_file(self, file_path: str) -> bytes:
        """
        Скачивает файл и возвращает байты — как telebot.download_file.
        file_path в MAX — это ПОЛНЫЙ URL (get_file(...).file_path или
        payload.url вложения: message.document.file_path и т.п.);
        относительных путей, как в Telegram, здесь нет. Запрос идёт
        с настройками сети maxibot.apihelper (прокси, таймауты,
        ретраи), но без токена бота — ссылки ведут на CDN.

        :param file_path: Полный URL файла
        :type file_path: str

        :return: Содержимое файла
        :rtype: bytes
        """
        if not file_path:
            # сюда чаще всего приходит get_file(...).file_path
            # недоступного видео (urls: null) — не путать с токеном
            raise ValueError(
                "download_file: file_path пуст — видео недоступно "
                "(GET /videos вернул urls: null); проверяйте "
                "file_info.file_path перед скачиванием"
            )
        if not self._is_http_url(file_path):
            raise ValueError(
                "download_file: в MAX file_path — это полный URL; "
                "возьмите его из get_file(...).file_path или прямо из "
                "вложения (message.document.file_path). Токен сюда "
                "передавать нельзя — сначала get_file(токен)"
            )
        return self.api.download_file(file_path)

    def get_video(self, video_token: str) -> Optional[Video]:
        """
        Информация о видео-вложении (GET /videos/{videoToken}) —
        расширение MAX, в telebot аналога нет: прямые ссылки
        воспроизведения (video.urls.mp4_1080 … mp4_144, hls,
        video.file_path — лучшая из них) и метаданные (width, height,
        duration, thumbnail). urls может быть null — видео недоступно,
        тогда file_path тоже None.

        :param video_token: Токен видео-вложения
            (message.video.file_id)
        :type video_token: str

        :return: Видео с прямыми ссылками или None
        :rtype: Optional[Video]
        """
        details = self.api.get_video(video_token)
        if not isinstance(details, dict):
            return None
        return Video.from_details(details)

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
                if handler.get("pass_bot"):
                    # как в telebot: callback_query_handler(pass_bot=True)
                    self._exec_task(handler["function"], callback, bot=self)
                else:
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

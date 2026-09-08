"""
Состояния FSM и бэкенды next_step/reply-хендлеров — как
`telebot.handler_backends`.

Здесь живут `State` и `StatesGroup`, чтобы телеботовский импорт
переезжал заменой одного слова:

.. code-block:: python3

    from maxibot.handler_backends import State, StatesGroup

    class MyStates(StatesGroup):
        name = State()
        age = State()

а также `HandlerBackend` / `MemoryHandlerBackend` /
`FileHandlerBackend` — хранилища ожидающих next_step- и
reply-обработчиков (второй включается через
bot.enable_save_next_step_handlers() / enable_save_reply_handlers()
и переживает рестарт).

Остальных обитателей telebot.handler_backends (BaseMiddleware,
SkipHandler, CancelUpdate, ContinueHandling) в maxibot пока нет:
класс-middleware и продолжение обработки не реализованы.
"""
import os
import pickle
import threading

from maxibot import apihelper


class HandlerBackend(object):
    """
    База хранилищ (next step | reply) обработчиков — как
    telebot.HandlerBackend.

    :meta private:
    """

    def __init__(self, handlers=None):
        if handlers is None:
            handlers = {}
        self.handlers = handlers

    def register_handler(self, handler_group_id, handler):
        raise NotImplementedError()

    def clear_handlers(self, handler_group_id):
        raise NotImplementedError()

    def get_handlers(self, handler_group_id):
        raise NotImplementedError()


class MemoryHandlerBackend(HandlerBackend):
    """
    Хранилище ожидающих обработчиков в памяти (по умолчанию) — как
    telebot.MemoryHandlerBackend.

    :meta private:
    """

    def register_handler(self, handler_group_id, handler):
        if handler_group_id in self.handlers:
            self.handlers[handler_group_id].append(handler)
        else:
            self.handlers[handler_group_id] = [handler]

    def clear_handlers(self, handler_group_id):
        self.handlers.pop(handler_group_id, None)

    def get_handlers(self, handler_group_id):
        return self.handlers.pop(handler_group_id, None)

    def load_handlers(self, filename, del_file_after_loading):
        raise NotImplementedError()


class FileHandlerBackend(HandlerBackend):
    """
    Хранилище ожидающих обработчиков с сохранением в pickle-файл по
    таймеру — как telebot.FileHandlerBackend. Включается через
    bot.enable_save_next_step_handlers() / enable_save_reply_handlers();
    лямбды и локальные функции pickle не переживут — используйте
    именованные функции уровня модуля.

    :meta private:
    """

    def __init__(self, handlers=None, filename='./.handler-saves/handlers.save',
                 delay=120):
        super(FileHandlerBackend, self).__init__(handlers)
        self.filename = filename
        self.delay = delay
        self.timer = threading.Timer(delay, self.save_handlers)

    def register_handler(self, handler_group_id, handler):
        if handler_group_id in self.handlers:
            self.handlers[handler_group_id].append(handler)
        else:
            self.handlers[handler_group_id] = [handler]
        self.start_save_timer()

    def clear_handlers(self, handler_group_id):
        self.handlers.pop(handler_group_id, None)
        self.start_save_timer()

    def get_handlers(self, handler_group_id):
        handlers = self.handlers.pop(handler_group_id, None)
        self.start_save_timer()
        return handlers

    def start_save_timer(self):
        if not self.timer.is_alive():
            if self.delay <= 0:
                self.save_handlers()
            else:
                self.timer = threading.Timer(self.delay, self.save_handlers)
                self.timer.daemon = True  # таймер не держит процесс при выходе
                self.timer.start()

    def save_handlers(self):
        self.dump_handlers(self.handlers, self.filename)

    def load_handlers(self, filename=None, del_file_after_loading=True):
        if not filename:
            filename = self.filename
        tmp = self.return_load_handlers(
            filename, del_file_after_loading=del_file_after_loading)
        if tmp is not None:
            self.handlers.update(tmp)

    @staticmethod
    def dump_handlers(handlers, filename, file_mode="wb"):
        # os.path.split вместо телеботовского rsplit('/'): у файла без
        # папки в пути telebot создавал ПАПКУ с именем файла
        dirs, _ = os.path.split(filename)
        if dirs:
            os.makedirs(dirs, exist_ok=True)

        with open(filename + ".tmp", file_mode) as file:
            if apihelper.CUSTOM_SERIALIZER is None:
                pickle.dump(handlers, file)
            else:
                apihelper.CUSTOM_SERIALIZER.dump(handlers, file)

        if os.path.isfile(filename):
            os.remove(filename)

        os.rename(filename + ".tmp", filename)

    @staticmethod
    def return_load_handlers(filename, del_file_after_loading=True):
        if os.path.isfile(filename) and os.path.getsize(filename) > 0:
            with open(filename, "rb") as file:
                if apihelper.CUSTOM_SERIALIZER is None:
                    handlers = pickle.load(file)
                else:
                    handlers = apihelper.CUSTOM_SERIALIZER.load(file)

            if del_file_after_loading:
                os.remove(filename)

            return handlers


class State:
    """
    Одно состояние. Внутри :class:`StatesGroup` получает имя
    ``ИмяГруппы:имя_атрибута`` — оно и хранится в хранилище состояний.

    .. code-block:: python3

        class MyStates(StatesGroup):
            my_state = State()  # str(MyStates.my_state) == 'MyStates:my_state'
    """

    def __init__(self) -> None:
        self.name = None

    def __str__(self) -> str:
        return self.name


class StatesGroup:
    """
    Группа состояний: наследник объявляет атрибуты-:class:`State`,
    и при создании класса каждому проставляются `name`
    (``ИмяГруппы:имя_атрибута``) и `group` (сам класс). Список
    состояний группы — `cls._state_list` (как в telebot).
    """

    def __init_subclass__(cls) -> None:
        state_list = []
        for name, value in cls.__dict__.items():
            if (
                not name.startswith("__")
                and not callable(value)
                and isinstance(value, State)
            ):
                value.name = ":".join((cls.__name__, name))
                value.group = cls
                state_list.append(value)
        cls._state_list = state_list

    @property
    def state_list(self):
        return self._state_list

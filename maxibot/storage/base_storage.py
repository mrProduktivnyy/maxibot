"""
База хранилищ состояний — как `telebot.storage.base_storage`.

Ключ записи — пара (chat_id, user_id): состояние пользователя
в конкретном чате. Форма данных:
``{chat_id: {user_id: {'state': ..., 'data': {...}}}}``.
"""
import copy


class StateStorageBase:
    """
    Базовый класс хранилища: своё хранилище — наследник с этими
    методами (сигнатуры как в telebot.storage.StateStorageBase).
    """

    def __init__(self) -> None:
        pass

    def set_data(self, chat_id, user_id, key, value):
        """
        Записать одно значение в данные пользователя в чате.
        Записи нет (состояние не ставилось) — ошибка.
        """
        raise NotImplementedError

    def get_data(self, chat_id, user_id):
        """
        Данные пользователя в чате (dict) или None, если записи нет.
        """
        raise NotImplementedError

    def set_state(self, chat_id, user_id, state):
        """
        Поставить состояние: записи нет — создать, есть — обновить.
        """
        raise NotImplementedError

    def delete_state(self, chat_id, user_id):
        """
        Удалить запись пользователя в чате (вместе с данными).
        """
        raise NotImplementedError

    def reset_data(self, chat_id, user_id):
        """
        Очистить данные пользователя в чате (состояние остаётся).
        """
        raise NotImplementedError

    def get_state(self, chat_id, user_id):
        raise NotImplementedError

    def get_interactive_data(self, chat_id, user_id):
        raise NotImplementedError

    def save(self, chat_id, user_id, data):
        raise NotImplementedError


class StateContext:
    """
    Контекст-менеджер данных состояния — то, что возвращает
    `bot.retrieve_data(...)`. На входе отдаёт копию данных, на выходе
    сохраняет её в хранилище:

    .. code-block:: python3

        with bot.retrieve_data(user_id, chat_id) as data:
            data['age'] = 25

    Как в telebot: если записи нет, `as data` даст None, а выход из
    блока упадёт при сохранении — сначала ставьте состояние.
    """

    def __init__(self, obj, chat_id, user_id) -> None:
        self.obj = obj
        self.data = copy.deepcopy(obj.get_data(chat_id, user_id))
        self.chat_id = chat_id
        self.user_id = user_id

    def __enter__(self):
        return self.data

    def __exit__(self, exc_type, exc_val, exc_tb):
        # результат save не возвращается: в telebot redis-save отдавал
        # True, и __exit__ глотал исключения внутри with-блока
        self.obj.save(self.chat_id, self.user_id, self.data)

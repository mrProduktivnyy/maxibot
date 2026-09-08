"""
Хранилище состояний в Redis — как `telebot.storage.redis_storage`.
Нужен пакет `redis` (pip install redis). Записи лежат по ключу
``{prefix}{chat_id}`` в JSON вида
``{user_id: {'state': ..., 'data': {...}}}`` — user_id внутри записи
строковый (наследие telebot, наружу это не видно).
"""
import json

redis_installed = True
try:
    from redis import ConnectionPool, Redis
except ImportError:
    redis_installed = False

from maxibot.storage.base_storage import StateContext, StateStorageBase


class StateRedisStorage(StateStorageBase):
    """
    Хранилище в Redis: `MaxiBot(state_storage=StateRedisStorage())`.
    Параметры подключения — как у telebot.storage.StateRedisStorage
    (host/port/db/password/prefix либо готовый redis_url).
    """

    def __init__(self, host='localhost', port=6379, db=0, password=None,
                 prefix='telebot_', redis_url=None):
        super().__init__()
        # проверка до ConnectionPool: в telebot без redis падал NameError
        # раньше, чем печаталась подсказка про pip install
        if not redis_installed:
            raise ImportError(
                "Redis не установлен. Поставьте его: 'pip install redis'"
            )
        if redis_url:
            self.redis = ConnectionPool.from_url(redis_url)
        else:
            self.redis = ConnectionPool(host=host, port=port, db=db,
                                        password=password)
        self.prefix = prefix

    def get_record(self, key):
        """
        Прочитать запись чата целиком (dict или None).
        """
        connection = Redis(connection_pool=self.redis)
        result = connection.get(self.prefix + str(key))
        connection.close()
        if result:
            return json.loads(result)
        return None

    def set_record(self, key, value):
        """
        Записать запись чата целиком.
        """
        connection = Redis(connection_pool=self.redis)
        connection.set(self.prefix + str(key), json.dumps(value))
        connection.close()
        return True

    def delete_record(self, key):
        """
        Удалить запись чата целиком.
        """
        connection = Redis(connection_pool=self.redis)
        connection.delete(self.prefix + str(key))
        connection.close()
        return True

    def set_state(self, chat_id, user_id, state):
        response = self.get_record(chat_id)
        user_id = str(user_id)
        if hasattr(state, 'name'):
            state = state.name

        if response:
            if user_id in response:
                response[user_id]['state'] = state
            else:
                response[user_id] = {'state': state, 'data': {}}
        else:
            response = {user_id: {'state': state, 'data': {}}}
        self.set_record(chat_id, response)

        return True

    def delete_state(self, chat_id, user_id):
        response = self.get_record(chat_id)
        user_id = str(user_id)
        if response:
            if user_id in response:
                del response[user_id]
                if user_id == str(chat_id):
                    self.delete_record(chat_id)
                    return True
                else:
                    self.set_record(chat_id, response)
                return True
        return False

    def get_value(self, chat_id, user_id, key):
        """
        Одно значение из данных пользователя (или None) — как в telebot.
        """
        response = self.get_record(chat_id)
        user_id = str(user_id)
        if response:
            if user_id in response:
                if key in response[user_id]['data']:
                    return response[user_id]['data'][key]
        return None

    def get_state(self, chat_id, user_id):
        response = self.get_record(chat_id)
        user_id = str(user_id)
        if response:
            if user_id in response:
                return response[user_id]['state']

        return None

    def get_data(self, chat_id, user_id):
        response = self.get_record(chat_id)
        user_id = str(user_id)
        if response:
            if user_id in response:
                return response[user_id]['data']
        return None

    def reset_data(self, chat_id, user_id):
        response = self.get_record(chat_id)
        user_id = str(user_id)
        if response:
            if user_id in response:
                response[user_id]['data'] = {}
                self.set_record(chat_id, response)
                return True
        return False

    def set_data(self, chat_id, user_id, key, value):
        # как в telebot: без записи — False, а не RuntimeError памяти/pickle
        response = self.get_record(chat_id)
        user_id = str(user_id)
        if response:
            if user_id in response:
                response[user_id]['data'][key] = value
                self.set_record(chat_id, response)
                return True
        return False

    def get_interactive_data(self, chat_id, user_id):
        return StateContext(self, chat_id, user_id)

    def save(self, chat_id, user_id, data):
        response = self.get_record(chat_id)
        user_id = str(user_id)
        if response:
            if user_id in response:
                response[user_id]['data'] = data
                self.set_record(chat_id, response)
                return True
        return None

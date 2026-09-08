"""
Хранилища состояний FSM — как пакет `telebot.storage`.
"""
from maxibot.storage.base_storage import StateContext, StateStorageBase
from maxibot.storage.memory_storage import StateMemoryStorage
from maxibot.storage.pickle_storage import StatePickleStorage
from maxibot.storage.redis_storage import StateRedisStorage

__all__ = [
    'StateStorageBase', 'StateContext',
    'StateMemoryStorage', 'StateRedisStorage', 'StatePickleStorage'
]

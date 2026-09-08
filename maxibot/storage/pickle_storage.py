"""
Хранилище состояний в pickle-файле — как `telebot.storage.pickle_storage`.
Каждая запись сразу сбрасывается на диск, поэтому состояния переживают
рестарт бота. Включается через `MaxiBot(state_storage=StatePickleStorage())`
или `bot.enable_saving_states()`.
"""
import os
import pickle

from maxibot.storage.base_storage import StateContext, StateStorageBase


class StatePickleStorage(StateStorageBase):
    """
    Хранилище в файле `file_path` (по умолчанию ./.state-save/states.pkl).
    Форма данных та же, что у памяти:
    ``{chat_id: {user_id: {'state': ..., 'data': {...}}}}``.
    """

    def __init__(self, file_path: str = "./.state-save/states.pkl") -> None:
        super().__init__()
        self.file_path = file_path
        self.create_dir()
        self.data = self.read()

    def convert_old_to_new(self):
        """
        Перевод файла старого формата telebot (<=4.3.1,
        ``{id: {'state': ..., 'data': ...}}``) в новый двухуровневый —
        для тех, кто переезжает со старым pickle-файлом.
        """
        new_data = {}
        for key, value in self.data.items():
            new_data[key] = {key: value}
        self.data = new_data
        self.update_data()

    def create_dir(self):
        """
        Создать папку под файл и пустой файл, если их ещё нет.
        """
        dirs, filename = os.path.split(self.file_path)
        # в telebot файл без папки ('states.pkl') ронял makedirs('')
        if dirs:
            os.makedirs(dirs, exist_ok=True)
        if not os.path.isfile(self.file_path):
            with open(self.file_path, "wb") as file:
                pickle.dump({}, file)

    def read(self):
        with open(self.file_path, "rb") as file:
            return pickle.load(file)

    def update_data(self):
        with open(self.file_path, "wb+") as file:
            pickle.dump(self.data, file, protocol=pickle.HIGHEST_PROTOCOL)

    def set_state(self, chat_id, user_id, state):
        if hasattr(state, "name"):
            state = state.name
        if chat_id in self.data:
            if user_id in self.data[chat_id]:
                self.data[chat_id][user_id]["state"] = state
                self.update_data()
                return True
            else:
                self.data[chat_id][user_id] = {"state": state, "data": {}}
                self.update_data()
                return True
        self.data[chat_id] = {user_id: {"state": state, "data": {}}}
        self.update_data()
        return True

    def delete_state(self, chat_id, user_id):
        if self.data.get(chat_id):
            if self.data[chat_id].get(user_id):
                del self.data[chat_id][user_id]
                if chat_id == user_id:
                    del self.data[chat_id]
                self.update_data()
                return True

        return False

    def get_state(self, chat_id, user_id):
        if self.data.get(chat_id):
            if self.data[chat_id].get(user_id):
                return self.data[chat_id][user_id]["state"]

        return None

    def get_data(self, chat_id, user_id):
        if self.data.get(chat_id):
            if self.data[chat_id].get(user_id):
                return self.data[chat_id][user_id]["data"]

        return None

    def reset_data(self, chat_id, user_id):
        if self.data.get(chat_id):
            if self.data[chat_id].get(user_id):
                self.data[chat_id][user_id]["data"] = {}
                self.update_data()
                return True
        return False

    def set_data(self, chat_id, user_id, key, value):
        if self.data.get(chat_id):
            if self.data[chat_id].get(user_id):
                self.data[chat_id][user_id]["data"][key] = value
                self.update_data()
                return True
        raise RuntimeError(
            "chat_id {} and user_id {} does not exist".format(chat_id, user_id)
        )

    def get_interactive_data(self, chat_id, user_id):
        return StateContext(self, chat_id, user_id)

    def save(self, chat_id, user_id, data):
        self.data[chat_id][user_id]["data"] = data
        self.update_data()

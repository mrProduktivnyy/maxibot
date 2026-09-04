"""
send_chat_action: индикатор «печатает…» как в telebot (issue про
POST /chats/{chatId}/actions).

Имена действий telebot мапятся в enum SenderAction MAX (typing_on,
sending_photo, sending_video, sending_audio, sending_file); родные имена
MAX проходят как есть; message_thread_id принимается и игнорируется.

Запуск:
    python3 tests/test_send_chat_action.py
"""
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import telebot

from maxibot import MaxiBot
from maxibot.apihelper import Api

MAX_ACTIONS = {"typing_on", "sending_photo", "sending_video", "sending_audio", "sending_file"}


# 1. Сигнатура один в один с telebot.send_chat_action
maxi_params = inspect.signature(MaxiBot.send_chat_action).parameters
tele_params = inspect.signature(telebot.TeleBot.send_chat_action).parameters
assert list(maxi_params) == list(tele_params), (list(maxi_params), list(tele_params))
for name in tele_params:
    assert maxi_params[name].default == tele_params[name].default, name
print("1 ok: сигнатура как в telebot")

# 2. Api.send_action шлёт POST /chats/{chatId}/actions с JSON-телом
calls = []


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"success": True}


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return FakeResponse()


real_request = requests.Session.request
requests.Session.request = fake_request
try:
    api = Api("tok")
    result = api.send_action(42, "typing_on")
    kw = calls[-1]
    assert kw["method"] == "POST", kw["method"]
    assert kw["url"] == "https://platform-api2.max.ru/chats/42/actions", kw["url"]
    assert json.loads(kw["data"]) == {"action": "typing_on"}, kw["data"]
    assert kw["headers"]["Content-Type"] == "application/json"
    assert kw["timeout"] == (15, 30), kw["timeout"]  # дефолтные таймауты apihelper
    assert result == {"success": True}

    # таймаут вызова пробрасывается в запрос
    api.send_action(42, "typing_on", timeout=7)
    assert calls[-1]["timeout"] == (7, 7), calls[-1]["timeout"]
finally:
    requests.Session.request = real_request
print("2 ok: POST /chats/{chatId}/actions с JSON-телом, таймаут пробрасывается")


# 3. Маппинг имён telebot в действия MAX — все значения из enum MAX
class RecordingApi:
    def __init__(self):
        self.actions = []
        self.response = {"success": True}

    def send_action(self, chat_id, action, timeout=None):
        self.actions.append((chat_id, action, timeout))
        return self.response


bot = MaxiBot("t", threaded=False)
bot.api = RecordingApi()

expected = {
    "typing": "typing_on",
    "upload_photo": "sending_photo",
    "record_video": "sending_video",
    "upload_video": "sending_video",
    "record_video_note": "sending_video",
    "upload_video_note": "sending_video",
    "record_voice": "sending_audio",
    "upload_voice": "sending_audio",
    "record_audio": "sending_audio",
    "upload_audio": "sending_audio",
    "upload_document": "sending_file",
    "choose_sticker": "typing_on",
    "find_location": "typing_on",
}
for telebot_name, max_name in expected.items():
    assert bot.send_chat_action(42, telebot_name) is True
    assert bot.api.actions[-1] == (42, max_name, None), (telebot_name, bot.api.actions[-1])
    assert max_name in MAX_ACTIONS, max_name
print("3 ok: все имена telebot мапятся в enum SenderAction MAX")

# 4. Родные имена MAX проходят как есть
for max_name in sorted(MAX_ACTIONS):
    bot.send_chat_action(42, max_name)
    assert bot.api.actions[-1][1] == max_name, bot.api.actions[-1]
print("4 ok: родные имена MAX как есть")

# 5. Незнакомое имя уходит в API без подмены (сервер вернёт ошибку — как в
#    telebot с кривым action)
bot.send_chat_action(42, "juggling")
assert bot.api.actions[-1][1] == "juggling", bot.api.actions[-1]
print("5 ok: незнакомое действие не подменяется")

# 6. timeout пробрасывается, message_thread_id принимается и игнорируется;
#    timeout=0 — «без своего таймаута», как в telebot (иначе requests
#    падает с ValueError на timeout=(0, 0))
bot.send_chat_action(42, "typing", timeout=9, message_thread_id=777)
assert bot.api.actions[-1] == (42, "typing_on", 9), bot.api.actions[-1]
bot.send_chat_action(42, "typing", timeout=0)
assert bot.api.actions[-1] == (42, "typing_on", None), bot.api.actions[-1]
print("6 ok: timeout пробрасывается (0 -> дефолт), message_thread_id игнорируется")

# 7. Возврат по полю success ответа MAX
assert bot.send_chat_action(42, "typing") is True
bot.api.response = {"success": False, "message": "chat not found"}
assert bot.send_chat_action(42, "typing") is False
bot.api.response = {}
assert bot.send_chat_action(42, "typing") is False
print("7 ok: True/False по success из ответа")

print("ALL OK")

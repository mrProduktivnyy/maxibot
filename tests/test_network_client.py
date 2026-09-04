"""
Проверка сетевого слоя Client + ручки maxibot.apihelper.

Официальный BASE_URL с включённой TLS-проверкой (verify=False убран),
таймауты/прокси/сессии/ретраи настраиваются как в telebot.apihelper.

Запуск:
    python3 tests/test_network_client.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

time.sleep = lambda s: None

import requests

from maxibot import apihelper
from maxibot.core.network.client import Client

calls = []


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True}


def fake_request(self, **kwargs):
    calls.append(kwargs)
    return FakeResponse()


real_request = requests.Session.request
requests.Session.request = fake_request

client = Client("tok")

# 1. Дефолт: актуальный URL, TLS-проверка по бандлу certifi + Минцифры
client.request("GET", "/me")
kw = calls[-1]
assert kw["url"] == "https://platform-api2.max.ru/me", kw["url"]
assert "verify" not in kw  # verify живёт на сессии, kwargs его не перебивают
assert kw["timeout"] == (15, 30), kw["timeout"]
assert kw["proxies"] is None
assert kw["headers"]["Authorization"] == "tok"

from maxibot.core.network.cacert import (
    RUSSIAN_TRUSTED_ROOT_CA,
    RUSSIAN_TRUSTED_SUB_CA,
)
import certifi

bundle_path = client._get_session().verify
assert isinstance(bundle_path, str) and os.path.exists(bundle_path), bundle_path
with open(bundle_path, "rb") as bundle_file:
    bundle = bundle_file.read()
with open(certifi.where(), "rb") as certifi_file:
    assert bundle.startswith(certifi_file.read())  # certifi остаётся в бандле
assert RUSSIAN_TRUSTED_ROOT_CA.strip().encode() in bundle
assert RUSSIAN_TRUSTED_SUB_CA.strip().encode() in bundle
print("1 ok: platform-api2.max.ru, verify по бандлу certifi + Минцифры")

# 2. apihelper.API_URL переопределяет базовый URL (хвостовой / срезается)
apihelper.API_URL = "https://example.org/api/"
client.request("GET", "/me")
assert calls[-1]["url"] == "https://example.org/api/me", calls[-1]["url"]
apihelper.API_URL = None
print("2 ok: apihelper.API_URL")

# 3. apihelper.proxy читается на каждый запрос и приоритетнее proxy клиента
proxied = Client("tok", proxy={"https": "http://old"})
proxied.request("GET", "/me")
assert calls[-1]["proxies"] == {"https": "http://old"}
apihelper.proxy = {"https": "socks5://127.0.0.1:9050"}
proxied.request("GET", "/me")
assert calls[-1]["proxies"] == {"https": "socks5://127.0.0.1:9050"}
apihelper.proxy = None
print("3 ok: proxy на каждый запрос, модульный приоритетнее")

# 4. Ручки таймаутов
apihelper.CONNECT_TIMEOUT = 5
apihelper.READ_TIMEOUT = 7
client.request("GET", "/me")
assert calls[-1]["timeout"] == (5, 7)
print("4 ok: CONNECT_TIMEOUT/READ_TIMEOUT")

# 5. Long polling: params["timeout"] остаётся в query, читающий таймаут больше него
client.request("GET", "/updates", params={"timeout": 90, "marker": 1})
assert calls[-1]["params"]["timeout"] == 90
assert calls[-1]["timeout"] == (5, 95), calls[-1]["timeout"]
apihelper.CONNECT_TIMEOUT = 15
apihelper.READ_TIMEOUT = 30
print("5 ok: long polling поднимает read-таймаут до timeout + 5")

# 6. Таймаут одного запроса: числом и парой (connect, read)
client.request("GET", "/me", timeout=3)
assert calls[-1]["timeout"] == (3, 3)
client.request("GET", "/me", timeout=(1, 2))
assert calls[-1]["timeout"] == (1, 2)
print("6 ok: per-request timeout")

# 7. JSON-тело сериализуется, Content-Type проставляется
client.request("POST", "/messages", params={"chat_id": 42}, data={"text": "hi"})
assert calls[-1]["data"] == '{"text": "hi"}'
assert calls[-1]["headers"]["Content-Type"] == "application/json"
print("7 ok: data -> json + Content-Type")

# 8. RETRY_ON_ERROR: две сетевые ошибки, третья попытка успешна
attempts = {"n": 0}


def flaky_request(self, **kwargs):
    attempts["n"] += 1
    if attempts["n"] < 3:
        raise requests.exceptions.ConnectionError("boom")
    calls.append(kwargs)
    return FakeResponse()


requests.Session.request = flaky_request
apihelper.RETRY_ON_ERROR = True
apihelper.MAX_RETRIES = 3
client.request("GET", "/me")
assert attempts["n"] == 3, attempts["n"]

# без ретраев ошибка пробрасывается сразу
apihelper.RETRY_ON_ERROR = False
attempts["n"] = 0


def always_down(self, **kwargs):
    attempts["n"] += 1
    raise requests.exceptions.ConnectionError("down")


requests.Session.request = always_down
try:
    client.request("GET", "/me")
    raise AssertionError("должен был пробросить ConnectionError")
except requests.exceptions.ConnectionError:
    pass
assert attempts["n"] == 1
requests.Session.request = fake_request
apihelper.MAX_RETRIES = 15
print("8 ok: RETRY_ON_ERROR/MAX_RETRIES")

# 9. Сессии: TTL=0 — одноразовые, apihelper.session — своя, иначе кэш потока
apihelper.SESSION_TIME_TO_LIVE = 0
assert client._get_session() is not client._get_session()
apihelper.SESSION_TIME_TO_LIVE = 600
own = requests.Session()
apihelper.session = own
assert client._get_session(reset=True) is own
apihelper.session = None
fresh = client._get_session(reset=True)
assert client._get_session() is fresh  # кэшируется в потоке
print("9 ok: SESSION_TIME_TO_LIVE/session")

# 10. Api.get_updates шлёт серверный timeout (LONG_POLLING_TIMEOUT) —
# и read-таймаут поднимается выше него (иначе идл-бот ловит ReadTimeout)
from maxibot.apihelper import Api

api = Api("tok")
api.get_updates([], {"marker": 5})
kw = calls[-1]
assert kw["params"]["timeout"] == 30 and kw["params"]["marker"] == 5, kw["params"]
assert kw["timeout"] == (15, 35), kw["timeout"]
apihelper.LONG_POLLING_TIMEOUT = 45
api.get_updates([], None)
assert calls[-1]["params"]["timeout"] == 45 and calls[-1]["timeout"] == (15, 50)
apihelper.LONG_POLLING_TIMEOUT = 30
print("10 ok: get_updates передаёт LONG_POLLING_TIMEOUT, read поднят на +5")

# 11. timeout строкой из extra тоже поднимает read-таймаут
client.request("GET", "/updates", params={"timeout": "90"})
assert calls[-1]["timeout"] == (15, 95), calls[-1]["timeout"]
print("11 ok: строковый timeout коэрсится")

# 12. Модульный proxy не запекается в Api: сброс в None действует сразу
apihelper.proxy = {"https": "http://corp:3128"}
api2 = Api("tok")
api2.get_my_info()
assert calls[-1]["proxies"] == {"https": "http://corp:3128"}
apihelper.proxy = None
api2.get_my_info()
assert calls[-1]["proxies"] is None, calls[-1]["proxies"]
print("12 ok: apihelper.proxy = None отключает прокси на лету")

# 13. Ретрай с file-like: поток перематывается, повтор не шлёт пустой файл
import io

apihelper.RETRY_ON_ERROR = True
apihelper.MAX_RETRIES = 3
attempts["n"] = 0
reads = []


def flaky_files(self, **kwargs):
    attempts["n"] += 1
    reads.append(kwargs["files"]["data"].read())  # requests читает поток
    if attempts["n"] < 3:
        raise requests.exceptions.ConnectionError("boom")
    calls.append(kwargs)
    return FakeResponse()


requests.Session.request = flaky_files
client.request("POST", url="https://upload", files={"data": io.BytesIO(b"payload")})
assert reads == [b"payload", b"payload", b"payload"], reads
requests.Session.request = fake_request
apihelper.RETRY_ON_ERROR = False
apihelper.MAX_RETRIES = 15
print("13 ok: перемотка файлов между попытками ретрая")

# 14. Загрузка файла держит прежний бюджет 60 секунд
api2.load_file("https://upload", {"data": b"x"})
assert calls[-1]["timeout"] == (60, 60), calls[-1]["timeout"]
print("14 ok: load_file с таймаутом 60")

# 15. apihelper.CA_BUNDLE: свой путь или False для создаваемых сессий
apihelper.CA_BUNDLE = "/etc/ssl/corp.pem"
assert client._get_session(reset=True).verify == "/etc/ssl/corp.pem"
apihelper.CA_BUNDLE = False
assert client._get_session(reset=True).verify is False
apihelper.CA_BUNDLE = None
assert client._get_session(reset=True).verify == bundle_path
print("15 ok: apihelper.CA_BUNDLE (путь / False / авто)")

requests.Session.request = real_request
print("ALL OK")

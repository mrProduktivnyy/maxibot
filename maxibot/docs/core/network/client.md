# Client
## class maxibot.core.network.Client(token, proxy=None)
Низкоуровневый HTTP-клиент запросов к API MAX  
Базовый URL — актуальный `https://platform-api2.max.ru` (переопределяется через `maxibot.apihelper.API_URL`). TLS-проверка включена: цепочка домена подписана сертификатами Минцифры, поэтому проверка идёт по бандлу certifi + встроенные сертификаты Минцифры (`core/network/cacert.py`, см. [cert.md](../../cert.md)); свой бандл или отключение — `maxibot.apihelper.CA_BUNDLE`  
**Параметры:**
* **token** (`str`) - Токен бота  
* **proxy** (`dict`) - Прокси этого клиента; модульная настройка `maxibot.apihelper.proxy` приоритетнее и читается на каждый запрос  
**Методы:**
* **request** (`method`, `path`, `url`, `params`, `data`, `files`, `content_types`, `timeout`) - Выполняет запрос к API; `timeout` — число секунд или пара `(connect, read)` только для этого запроса, по умолчанию `apihelper.CONNECT_TIMEOUT`/`apihelper.READ_TIMEOUT`  
* **_make_url** (`path`) - Формирует полную ссылку запроса из базового URL и пути  
* **_get_session** (`reset`) - Возвращает `requests.Session` текущего потока с учётом `apihelper.session` и `apihelper.SESSION_TIME_TO_LIVE`  

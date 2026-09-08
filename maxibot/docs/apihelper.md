# ApiHelper
## Модульные настройки
Аналог настроек `telebot.apihelper` — задаются на модуле и читаются на каждый запрос, менять можно на лету:
```python
from maxibot import apihelper

apihelper.proxy = {"https": "socks5://127.0.0.1:9050"}  # прокси (по умолчанию None)
apihelper.API_URL = None             # свой базовый URL (по умолчанию https://platform-api2.max.ru)
apihelper.CA_BUNDLE = None           # None — certifi + встроенные сертификаты Минцифры;
                                     # путь к своему PEM; False — отключить TLS-проверку
apihelper.CONNECT_TIMEOUT = 15       # секунд на установку соединения
apihelper.READ_TIMEOUT = 30          # секунд на чтение ответа (для long polling поднимается автоматически)
apihelper.LONG_POLLING_TIMEOUT = 30  # секунд серверного удержания GET /updates
apihelper.SESSION_TIME_TO_LIVE = 600 # жизнь requests.Session; None — вечно, 0 — новая на каждый запрос
apihelper.session = None             # своя requests.Session (свой CA-бандл, verify и т.п.)
apihelper.RETRY_ON_ERROR = False     # повторять запросы при сетевых ошибках
apihelper.MAX_RETRIES = 15           # всего попыток при RETRY_ON_ERROR
apihelper.RETRY_TIMEOUT = 2          # пауза между повторами, секунд
apihelper.RETRY_ENGINE = 1           # 1 — повторы с паузой (как telebot), 2 — urllib3 Retry
apihelper.ignore_warnings = False    # глушить предупреждения urllib3 (нужно только при verify=False)
apihelper.ENABLE_MIDDLEWARE = True   # включить регистрацию bot.middleware_handler
```
TLS: библиотека ходит на актуальный `https://platform-api2.max.ru` (прежние `botapi.max.ru` и `platform-api.max.ru` отключены при миграциях 2026 года). Цепочка домена подписана сертификатами Минцифры («Russian Trusted Root CA»), которых нет в certifi, поэтому проверка идёт по собственному бандлу: certifi + встроенные сертификаты Минцифры (источник — [gosuslugi.ru/crt](https://www.gosuslugi.ru/crt), подробности в [cert.md](cert.md)). Свой бандл — `apihelper.CA_BUNDLE = "/путь/к/ca.pem"`; отключить проверку (не рекомендуется) — `CA_BUNDLE = False` + `ignore_warnings = True`.

Прокси: при `proxy = None` применяются прокси из переменных окружения `HTTP_PROXY`/`HTTPS_PROXY` — стандартное поведение requests и telebot (раньше maxibot их игнорировал). Отключить: `apihelper.proxy = {"http": "", "https": ""}` или переменная `NO_PROXY=platform-api2.max.ru`.

## Телеботовские имена исключений
В `maxibot.apihelper` (и в `maxibot.exceptions`) есть алиасы, чтобы `except`-код переезжал заменой импорта: `ApiException` → `MaxApiException`, `ApiHTTPException` → `MaxApiHTTPException`, `ApiInvalidJSONException` → `MaxApiInvalidJSONException`. `ApiTelegramException` — алиас на **базовый** `MaxApiException`: Telegram шлёт осмысленные ошибки JSON-телом, а MAX — обычным HTTP-статусом (`MaxApiHTTPException`), и телеботовский `except ApiTelegramException` должен ловить оба вида. Учтите: `error_code` у MAX — строка (`'attachment.not.ready'`), не телеграмный int (`429`).

## class maxibot.apihelper.Api(token)
Клиент для рабты с api MAX  
**Параметры:**
* **client** (`str`) - тип сообщения  

**Методы:**
* **get_my_info** - Получение информации о текущем боте  
* **get_updates** (`allowed_updates`, `extra`) - Получение новых обновлений от API через лонгполлинг  
    * `allowed_updates` - Список типов обновлений, которые нужно получать  
    * `extra` - Дополнительные параметры запроса  
* **get_message** (`msg_id`) - Получение сообщений по `msg_id`  
    * `msg_id` - Уникальный идентификатор сообщения  
* **get_messages** (`chat_id`, `message_ids`, `from_time`, `to_time`, `count`, `timeout`) - История чата и/или выборка по id (`GET /messages`); сервер отдаёт от новых к старым, поэтому по спеке to < from; message_ids-список уходит через запятую  
* **get_chats** (`count`, `marker`, `timeout`) - Постраничный список чатов бота (`GET /chats`): в ответе chats и marker следующей страницы (null — конец)  
* **send_action** (`chat_id`, `action`, `timeout`) - Отправка действия бота в чат (`POST /chats/{chatId}/actions`): участники видят индикатор «печатает…» и т.п.  
    * `chat_id` - Уникальный идентификатор чата  
    * `action` - Действие MAX (enum SenderAction): `typing_on`, `sending_photo`, `sending_video`, `sending_audio`, `sending_file`  
    * `timeout` - Таймаут запроса в секундах на этот вызов  
* **send_message** (`chat_id`, `msg_id`, `text`, `method`, `attachments`, `parse_mode`, `notify`, `disable_link_preview`, `link`, `timeout`) - Отправка/удаление/обновление сообщение в чате  
    * `chat_id` - Уникальный идентификатор чата  
    * `msg_id` - Уникальный идентификатор сообщения  
    * `text` - Текст сообщения  
    * `method` - HTTP метод для запроса  
    * `attachments` - Вложения сообщения  
    * `parse_mode` - Формат текста сообщения (`Markdown`, `HTML`)  
    * `notify` - Флаг звукового уведомления; False уходит в тело явно (у NewMessageBody.notify серверный default true, пропуск поля звук не отключает)  
    * `timeout` - Таймаут HTTP-запроса в секундах на этот вызов; None — модульные CONNECT_TIMEOUT/READ_TIMEOUT  
* **get_comments** (`message_id`, `count`, `before`, `after`, `comment_ids`, `timeout`) - Комментарии к посту канала (`GET /messages/{messageId}/comments`); comment_ids-список уходит query-параметром через запятую. Блока комментариев нет в OpenAPI-спеке MAX — методы выверены по официальному TS-клиенту (CommentsApi)  
* **get_comment** (`message_id`, `comment_id`, `timeout`) - Один комментарий (`GET /messages/{messageId}/comments/{commentId}`)  
* **send_comment** (`message_id`, `text`, `link`, `format`, `disable_link_preview`, `timeout`) - Комментарий к посту (`POST /messages/{messageId}/comments`); disable_link_preview — query-параметр строкой true/false, format уходит только вместе с текстом (как у send_message)  
* **edit_comment** (`message_id`, `comment_id`, `text`, `link`, `format`, `timeout`) - Правка комментария (`PUT /messages/{messageId}/comments`); message_id уходит и в путь, и в query — TS-клиент кладёт его с comment_id в query при том же шаблоне пути  
* **delete_comment** (`message_id`, `comment_id`, `timeout`) - Удаление комментария (`DELETE /messages/{messageId}/comments?comment_id=...`)  
* **answer_callback**(`callback_id`,`text`,`notification`, `attachments`, `link`, `notify`, `format`)  
    * `callback_id` - Уникальный идентификатор callback-запроса
    * `text` - Новый текст сообщения. Если указан, сообщение будет обновлено  
    * `notification` - Текст всплывающего уведомления для пользователя  
    * `attachments` - Новые вложения сообщения  
    * `link` - Ссылка на сообщение для reply/forward формата  
    * `notify` - Отправлять ли системное уведомление в чат об изменении сообщения  
    * `format` - Формат текста сообщения (`Markdown`, `HTML`)  
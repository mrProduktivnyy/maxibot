# Util
## class maxibot.__init__.ExceptionHandler
Базовый класс обработчика ошибок — как `telebot.ExceptionHandler`. Наследник с методом `handle(exception) -> bool` передаётся в `MaxiBot(exception_handler=...)` и получает исключения обработчиков, middleware, func-фильтров, цикла поллинга и webhook-сервера (Sentry, алерты, своё логирование). `handle()` вернул истину — ошибка считается обработанной и никуда не пишется; False/None — уходит в логгер `maxibot`: `logger.error`, traceback на уровне DEBUG. print в stdout библиотека больше не использует. Необработанные ошибки бот не останавливают (как `infinity_polling` в telebot). Мимо exception_handler проходят только парс-ошибки Update (непонятный payload) — они логируются на ERROR с traceback, а обновление уходит в общие middleware с сырым json  
**Методы:**
* **handle** (`exception`) - Вызывается для каждой перехваченной ошибки; по умолчанию возвращает `False`  
## class maxibot.__init__.MaxiBot(token, parse_mode, threaded, skip_pending, num_threads, exception_handler)
Класс бота MAX  
**Параметры:**
* **token** (`str`) - Токен бота  
* **parse_mode** (`str`) - Разметка на весь уровень бота (как в telebot)  
* **threaded** (`bool`) - Выполнять обработчики в пуле потоков (по умолчанию True, как в telebot)  
* **skip_pending** (`bool`) - Пропустить обновления, накопленные до запуска  
* **num_threads** (`int`) - Размер пула потоков (по умолчанию 2, как в telebot)  
* **exception_handler** (`ExceptionHandler`) - Обработчик ошибок с методом `handle(exception) -> bool`; передавайте по имени (в telebot перед ним стоят next_step_backend и reply_backend, которых в maxibot нет). Можно назначить и позже: `bot.exception_handler = ...`  
**Методы:**
* **_build_handler_dict** (`handler` `**filters`) - Метод, которая формирует словарь для добавления в список обработчиков событий (handler)  
    * **handler** - Функция-обработчик события  
    * ****filters** - Фильтры для функции-обработчика событий  
* **polling** (`allowed_updates`) - Метод, который запускает корутину полинга событий  
* **start** (`allowed_updates`) - Метод, который запускает полинга событий по разрешённым событиям `allowed_updates` в ассинхронном режиме  
* **stop** - Метод, который останавлиявает полинг событий  
* **message_handler** (`commands`, `regexp`, `func`, `content_types`) - Декоратор для регистрации обработчика текстовых сообщений по шаблону  
    * **commands** - фильр по командам
    * **regexp** - фильр по регулярным выражениям
    * **func** - фильр по функции
    * **content_types** - фильр по типу контента
* **run_handler** (`context`, `message_handlers`) - Метод запуска обработчиков событий текстового сообщения  
    * **context** - Объект типа `Message`  
    * **message_handlers** - Список обработчиков событий  
* **_test_filter** (`message_filter`, `filter_value`, `context`) - Метод проверки соответствия сообщения всем фильтрам текстовых сообщений  
    * **message_filter** - Тип фильтра  
    * **filter_value** - Значение, которое надо сопоставить с фильтром  
    * **context** - Объект типа `Message`  
* **_check_filters** (`context`, `handler`) - Проверка текстового сообщения на фильтры  
    * **context** - Объект типа `Message`  
    * **handler** - Словарь обработчиков событий  
* **_process_text_message** (`context`) - Обрабатывает входящее сообщение  
    * **context** - Объект типа `Message`  
* **_process_update** (`update`) - Метод для обработки входящего полученного обновления  
    * **update** - Словарь, полученный от API MAX в процессе опроса API на обновления  
* **_process_update** (`update`) - Метод для обработки входящего полученного обновления  
    * **update** - Словарь, полученный от API MAX в процессе опроса API на обновления  
* **_check_text_length** (`text`) - Проверки длины строки `text`  
* **send_photo** (`chat_id`, `photo`, `caption`, `parse_mode`, `reply_markup`, `disable_web_page_preview`) - Отправляет сообщение с фото  
    * **chat_id** - Чат, куда надо отправить сообщение  
    * **photo** - Объект фото  
    * **caption** - Текст сообщения под фото  
    * **parse_mode** - Формат сообщения  
    * **reply_markup** - Объект клавиатуры  
    * **disable_web_page_preview** - Отключить предпросмотр ссылок  
* **send_media_group** (`chat_id`, `media`, `caption`, `parse_mode`, `reply_markup`, `disable_web_page_preview`) - Отправляет сообщение с группой медиафайлов  
    * **chat_id** - Чат, куда надо отправить сообщение  
    * **media** - Список объектов медиа  
    * **caption** - Текст сообщения под фото  
    * **parse_mode** - Формат сообщения  
    * **reply_markup** - Объект клавиатуры  
    * **disable_web_page_preview** - Отключить предпросмотр ссылок  
* **send_document** (`chat_id`, `document`, `caption`, `parse_mode`, `reply_markup`, `visible_file_name`, `disable_web_page_preview`) - Отправляет сообщение с документом  
    * **chat_id** - Чат, куда надо отправить сообщение  
    * **document** - Объект документа  
    * **caption** - Текст сообщения под фото  
    * **parse_mode** - Формат сообщения  
    * **reply_markup** - Объект клавиатуры  
    * **visible_file_name** - Имя файла, которое увидит пользователь  
    * **disable_web_page_preview** - Отключить предпросмотр ссылок  
* **delete_message** (`chat_id`, `message_id`) - Удаляет сообщение `message_id` в чате `chat_id`  
    * **chat_id** - Чат, где надо удалить сообщение  
    * **message_id** - Уникальный идентификатор сообщения  
* **edit_message_text** (`text`, `chat_id`, `message_id`, `reply_markup`, `parse_mode`) - Редактирует текст сообщения  
    * **text** - Текст, на который надо заменить текущий  
    * **chat_id** - Чат, где надо изменить сообщение  
    * **message_id** - Идентификатор сообщения, которое надо поменять  
    * **reply_markup** - Объект клавиатуры  
    * **parse_mode** - Формат сообщения  
* **edit_message_media** (`media`, `chat_id`, `message_id`, `reply_markup`, `parse_mode`) - Редактирует сообщение с медиа  
    * **media** - Медиа, на которое надо заменить текущее  
    * **chat_id** - Чат, где надо изменить сообщение  
    * **message_id** - Идентификатор сообщения, которое надо поменять  
    * **reply_markup** - Объект клавиатуры  
    * **parse_mode** - Формат сообщения  
* **edit_message_reply_markup** (`chat_id`, `message_id`, `reply_markup`, `parse_mode`) - Редактирует клавиатуру сообщения  
    * **chat_id** - Чат, где надо изменить сообщение  
    * **message_id** - Идентификатор сообщения, которое надо поменять  
    * **reply_markup** - Объект клавиатуры  
    * **parse_mode** - Формат сообщения  
* **send_message** (`chat_id`, `text`, `attachments`, `reply_markup`, `parse_mode`, `notify`, `disable_web_page_preview`, `reply_to_message_id`) - Отправляет сообщение  
    * **chat_id** - Чат, куда надо отправить сообщение  
    * **text** - Текст сообщения  
    * **attachments** - Вложения сообщения  
    * **reply_markup** - Объект клавиатуры  
    * **parse_mode** - Формат сообщения  
    * **notify** - Флаг звукового уведомления отправки сообщения (False теперь явно уходит в MAX и реально отключает звук)  
    * **disable_web_page_preview** - Отключить предпросмотр ссылок  
    * **reply_to_message_id** - Идентификатор сообщения, на которое бот ответит цитатой  
    * **timeout** - Таймаут HTTP-запроса в секундах, как в telebot (0 — «без своего», модульные таймауты apihelper)  
* **send_chat_action** (`chat_id`, `action`, `timeout`, `message_thread_id`) - Отправляет действие бота в чат: индикатор «печатает…», «отправляет фото» и т.п. Сигнатура как в telebot; индикатор живёт несколько секунд, для долгих операций вызов повторяют. Возвращает True при успехе и False, если MAX ответил `success: false` (telebot в этой ситуации бросает ApiTelegramException — при переносе проверяйте возврат); HTTP-ошибки бросают MaxApiHTTPException  
    * **chat_id** - Чат, куда надо отправить действие  
    * **action** - Имя telebot (`typing`, `upload_photo`, `record_video`, `upload_video`, `record_voice`, `upload_voice`, `record_audio`, `upload_audio`, `upload_document`, `record_video_note`, `upload_video_note`) мапится в действия MAX; `choose_sticker` и `find_location` уходят как `typing_on` — своих индикаторов в MAX нет; родные имена MAX (`typing_on`, `sending_photo`, `sending_video`, `sending_audio`, `sending_file`) проходят как есть  
    * **timeout** - Таймаут запроса в секундах  
    * **message_thread_id** - Принимается для совместимости с telebot и игнорируется — тредов в MAX нет  
* **send_location** (`chat_id`, `latitude`, `longitude`, `live_period`, `reply_to_message_id`, `reply_markup`, `disable_notification`, `timeout`, …) - Отправляет точку на карте: вложение `{"type": "location", "latitude", "longitude"}` (координаты на верхнем уровне вложения, payload у него нет). Сигнатура как в telebot  
    * **live_period** - Игнорируется с предупреждением — live-локаций в MAX нет, пин статичен  
    * **reply_markup** - Клавиатура вторым вложением  
    * **disable_notification** - True — без звука (notify=false)  
    * **reply_parameters** - Если передан объект с message_id — используется вместо reply_to_message_id (при конфликте предупреждение, как в telebot); horizontal_accuracy/heading/proximity_alert_radius/allow_sending_without_reply/protect_content/message_thread_id принимаются и игнорируются. У возвращаемого Message атрибут location остаётся None (координаты и так известны вызывающему)  
* **send_contact** (`chat_id`, `phone_number`, `first_name`, `last_name`, `vcard`, `disable_notification`, `reply_to_message_id`, `reply_markup`, `timeout`, …) - Отправляет карточку контакта: вложение `{"type": "contact", "payload": {name, vcf_phone[, vcf_info]}}`. Сигнатура как в telebot  
    * **first_name/last_name** - Склеиваются в payload.name  
    * **phone_number** - Уходит в vcf_phone  
    * **vcard** - Как есть в vcf_info  
    * **reply_markup** - Игнорируется с предупреждением: по документации MAX контакт обязан быть единственным вложением сообщения — клавиатуру шлите отдельным сообщением (отличие от telebot)  
* **send_venue** (`chat_id`, `latitude`, `longitude`, `title`, `address`, …) - Отправляет место. Отдельного типа венью в MAX нет — эмуляция одним сообщением: location-вложение + текст «title\naddress» без разметки (как в telebot). foursquare_*/google_place_* принимаются и игнорируются; reply_markup разрешена. content_type возвращаемого Message — 'location' (не 'venue'), атрибуты venue/location остаются None  
* **edit_message_live_location** (`latitude`, `longitude`, `chat_id`, `message_id`, `inline_message_id`, `reply_markup`, `timeout`, …) - Передвигает пин сообщения-локации: PUT /messages с новым location-вложением, без уведомления участников (notify=false). Семантики live-локаций в MAX нет — редактируется любое сообщение-локация, пин просто переезжает; PUT заменяет тело целиком, текст сообщения (если был) пропадёт. message_id обязателен (инлайн-сообщений в MAX нет — с одним inline_message_id будет ValueError). Возвращает Message при успехе, иначе {}  
* **stop_message_live_location** (`chat_id`, `message_id`, `inline_message_id`, `reply_markup`, `timeout`) - Заглушка совместимости: live-локаций в MAX нет, останавливать нечего. Без reply_markup возвращает сообщение как есть; с reply_markup — заменяет клавиатуру сообщения без уведомления участников, сохраняя его текст и остальные вложения. message_id обязателен  
* **get_message** (`message_id`) - Метод получения сообщения по айди  
    * **message_id** - Идентификатор сообщения, которое надо получить  
* **callback_query_handler** (`data` `**kwargs`) - Декоратор для регистрации обработчиков callback-запросов от inline-кнопок  
    * **data** - Данные кнопки для фильтрации  
    * **kwargs** - Дополнительные фильтры для обработчика  
* **add_callback_query_handler** (`handler_dict`) - Добавление обработчик callback-запросов напрямую  
    * **handler_dict** - Словарь обработчика событий  
* **_process_callback_query** (`callback`) - Обрабатывает входящий callback-запрос. Метод ищет подходящий обработчик среди зарегистрированных и вызывает первый соответствующий фильтрам  
    * **callback** - Объект callback-запроса  

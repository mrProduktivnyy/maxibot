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
    * **notify** - Флаг звукового уведомления отправки сообщения  
    * **disable_web_page_preview** - Отключить предпросмотр ссылок  
    * **reply_to_message_id** - Идентификатор сообщения, на которое бот ответит цитатой  
* **get_message** (`message_id`) - Метод получения сообщения по айди  
    * **message_id** - Идентификатор сообщения, которое надо получить  
* **callback_query_handler** (`data` `**kwargs`) - Декоратор для регистрации обработчиков callback-запросов от inline-кнопок  
    * **data** - Данные кнопки для фильтрации  
    * **kwargs** - Дополнительные фильтры для обработчика  
* **add_callback_query_handler** (`handler_dict`) - Добавление обработчик callback-запросов напрямую  
    * **handler_dict** - Словарь обработчика событий  
* **_process_callback_query** (`callback`) - Обрабатывает входящий callback-запрос. Метод ищет подходящий обработчик среди зарегистрированных и вызывает первый соответствующий фильтрам  
    * **callback** - Объект callback-запроса  

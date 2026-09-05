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
* **send_video** (`chat_id`, `video`, `duration`, `width`, `height`, `thumbnail`, `caption`, `parse_mode`, `reply_markup`, `disable_web_page_preview`) - Отправляет видео: POST /uploads?type=video (MP4/MOV/MKV/WEBM, до 250 МБ) → вложение `{"type": "video", "payload": {"token"}}`. Порядок первых позиционных параметров как у telebot. Строка — токен ранее загруженного видео (аналог file_id), без повторной загрузки; URL — ValueError  
* **send_animation** (`chat_id`, `animation`, `duration`, `width`, `height`, `thumbnail`, `caption`, `parse_mode`, …, `reply_markup`, `timeout`, …, `reply_parameters`) - Отправляет анимацию. Отдельного типа анимаций в MAX нет — деградация: файл уходит обычным видео (POST /uploads?type=video, придёт с content_type "video", без GIF-семантики); http(s)-ссылка — вложением `{"type": "image", "payload": {"url"}}`, MAX скачает сам (придёт картинкой, content_type "photo"), но URL должен вести на изображение: ссылка на видеофайл (.mp4 и т. п. — частый формат анимаций telebot) даёт ValueError, такой файл отправьте байтами; прочая строка — токен ранее загруженного видео. Сигнатура как в telebot; обработчик content_types=['animation'] не сработает никогда (message_handler предупредит) — подписывайтесь на ['video'] / ['photo']; Message.animation остаётся None; has_spoiler и прочие несуществующие в MAX параметры игнорируются  
* **send_video_note** (`chat_id`, `data`, `duration`, `length`, `reply_to_message_id`, `reply_markup`, `disable_notification`, `timeout`, …, `reply_parameters`) - Отправляет видеосообщение («кружок»). Отдельного типа кружков в MAX нет — файл уходит обычным видео и придёт прямоугольным, с content_type "video" (обработчик content_types=['video_note'] не сработает никогда — подписывайтесь на ['video'], message_handler предупредит). Сигнатура как в telebot (видео — первым параметром `data`, историческое имя); строка — токен ранее загруженного видео; URL — ValueError (как и в telebot); duration/length игнорируются; Message.video_note остаётся None  
* **send_audio** (`chat_id`, `audio`, `caption`, `duration`, `performer`, `title`, `reply_to_message_id`, `reply_markup`, `parse_mode`, `disable_notification`, `timeout`, …) - Отправляет аудио через родной тип загрузки MAX: POST /uploads?type=audio (токен сразу в ответе, как у видео) → вложение `{"type": "audio", "payload": {"token"}}`. Сигнатура как в telebot. У возвращаемого Message content_type — "audio", атрибут audio остаётся None  
    * **audio** - Байты, file-like объект, InputMedia или, как file_id в telebot, строка-токен ранее загруженного аудио (из входящего вложения payload.token) — уходит без повторной загрузки; URL — ValueError (MAX принимает URL только для изображений)  
    * **duration/performer/title, thumbnail/thumb** - Принимаются и игнорируются — MAX берёт метаданные из файла, обложку задать нельзя  
    * **reply_markup** - Игнорируется с предупреждением: по документации MAX аудио обязано быть единственным вложением сообщения (отличие от telebot)  
    * **disable_notification/reply_to_message_id/reply_parameters** - Работают как в telebot  
    * **timeout** - Таймаут запроса POST /messages; в отличие от telebot НЕ покрывает загрузку файла — она идёт отдельными запросами со своими таймаутами  
* **send_voice** (`chat_id`, `voice`, `caption`, `duration`, …) - Отправляет голосовое. Отдельного типа голосовых в MAX нет — тонкая обёртка над send_audio: уходит обычным аудио, без «кружка»-плеера; формат должен быть звуковым, который принимает MAX (MP3, WAV, M4A и другие). Следствие: content_type отправленного и входящего — "audio", не "voice", обработчик content_types=['voice'] не сработает никогда (message_handler предупредит) — подписывайтесь на ['audio']; Message.voice остаётся None  
* **send_sticker** (`chat_id`, `sticker`, `reply_to_message_id`, `reply_markup`, `disable_notification`, `timeout`, …, `data`, …, `emoji`, `reply_parameters`) - Отправляет стикер: вложение `{"type": "sticker", "payload": {"code": ...}}`. Сигнатура как в telebot, но `sticker` — строка-КОД стикера MAX (аналог file_id; лежит во входящем `payload.code`). Свои webp/tgs-файлы загрузить нельзя — типа sticker в POST /uploads нет: файл/байты/URL — ValueError, пользуйтесь стикерами из каталога MAX. reply_markup игнорируется с предупреждением (стикер обязан быть единственным вложением); `data` — устаревший алиас sticker (как в telebot); emoji игнорируется. Входящий стикер даёт content_type "sticker", атрибут Message.sticker остаётся None  
* **forward_message** (`chat_id`, `from_chat_id`, `message_id`, `disable_notification`, `protect_content`, `timeout`, `message_thread_id`) - Пересылает сообщение: в MAX пересылка встроена в отправку — POST /messages с `link={"type": "forward", "mid"}` и пустым телом. Сигнатура как в telebot; mid глобален, from_chat_id принимается и не используется. Возвращает Message  
* **forward_messages** (`chat_id`, `from_chat_id`, `message_ids`, …) - Цикл forward_message; не пересланные пропускаются с предупреждением в логгере (как в telebot). Возвращает список MessageID  
* **copy_message** (`chat_id`, `from_chat_id`, `message_id`, `caption`, `parse_mode`, …, `reply_markup`, `timeout`, …) - Копирует сообщение без ссылки на оригинал. Своего copyMessage в MAX нет — эмуляция: GET /messages/{messageId} → новый POST /messages с тем же текстом и пересобранными вложениями (медиа по token — задокументированный способ переиспользования, стикер по code, локация по координатам, контакт по vcf_info/max_info). У чистой пересылки копируется видимый контент оригинала (из link.message), у пересылки с комментарием — комментарий. Клавиатура оригинала не копируется (как в telebot), новую можно передать в reply_markup — но к копии аудио/файла/стикера/контакта она не прикладывается (MAX требует единственное вложение, предупреждение в логгере); исходная разметка текста не переносится — parse_mode действует только на новую подпись caption. Возвращает MessageID  
* **copy_messages** (`chat_id`, `from_chat_id`, `message_ids`, …, `remove_caption`) - Цикл copy_message; `remove_caption=True` снимает только подпись у сообщений с вложениями (чисто текстовые копируются с текстом, как в telebot); не скопированные пропускаются с предупреждением  
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
* **edit_message_caption** (`caption`, `chat_id`, `message_id`, `inline_message_id`, `parse_mode`, `caption_entities`, `reply_markup`) - Меняет подпись сообщения с вложениями. Сигнатура как в telebot (caption первым). Своего editMessageCaption в MAX нет, а PUT /messages заменяет body целиком — эмуляция: GET /messages/{messageId} → пересборка текущих вложений (медиа по token, стикер по code, локация по координатам, контакт по vcf_info/max_info) → PUT с новой подписью и теми же вложениями, без пуша (notify=False); reply/forward-связка исходного сообщения переносится в PUT — правка подписи не снимает ответ. Как в telebot: без reply_markup клавиатура исходного сообщения снимается; к аудио/файлу/стикеру/контакту клавиатура не прикладывается (warning — MAX требует единственное вложение). Отличия: на чисто текстовом сообщении заменит текст (в Telegram — ошибка); message_id обязателен (без него ValueError — инлайн-сообщений в MAX нет); caption_entities игнорируется. Возвращает Message при успехе, иначе {}  
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
* **get_chat** (`chat_id`) - Возвращает информацию о чате (GET /chats/{chatId}). Поля как в telebot: id, type (типы MAX мапятся: dialog → private, chat → group, channel → channel), title, description, photo (URL иконки — строка, не ChatPhoto), pinned_message (Message или None; переживает закреп от имени канала с sender: null), invite_link; у диалогов — first_name/last_name/username и bio собеседника. Остальные атрибуты telebot.types.Chat существуют и равны None (permissions, is_forum и т.п.). Дополнительно поля MAX: status, participants_count, is_public. chat_id строкой — "@username" или публичная ссылка (GET /chats/{chatLink}). Отличие: message.chat.type исторически сырой ("dialog"/"chat"/"channel"), у get_chat — телеботовские имена  
* **get_chat_member_count** (`chat_id`) - Число участников чата (participants_count из GET /chats/{chatId}); для диалогов всегда 2. **get_chat_members_count** — устаревший алиас с предупреждением, как в telebot  
* **set_chat_title** (`chat_id`, `title`) - Меняет название чата: PATCH /chats/{chatId} с `{"title"}` (1–200 символов). Название диалога сменить нельзя — ошибка MAX пробросится исключением. Участники увидят системное сообщение. У всех PATCH-методов chat_id — только числовой ("@username" работает лишь в get_chat*: у PATCH нет маршрута по ссылке). Возвращает True  
* **set_chat_description** (`chat_id`, `description`) - Меняет описание чата: PATCH с `{"description"}` (до 16000 символов). None/пустая строка — описание удаляется, как в Telegram. Возвращает True  
* **set_chat_photo** (`chat_id`, `photo`) - Меняет иконку чата: байты/file-like загружаются через POST /uploads?type=image → PATCH с `{"icon": {"token"}}`; строка — расширение против telebot: http(s)-ссылка (`{"icon": {"url"}}`) или токен ранее загруженного изображения. Возвращает True  
* **delete_chat_photo** (`chat_id`) - Удаляет иконку чата: PATCH с `{"icon": null}` (поле по спеке nullable; если сервер отвергнет — исключение). Возвращает True  
* **export_chat_invite_link** (`chat_id`) - Возвращает ссылку-приглашение чата (поле link из GET /chats/{chatId}). Отличие от Telegram: ссылка постоянная и НЕ перегенерируется при каждом вызове, отозвать её через Bot API нельзя; у приватного чата без ссылки — None  
* **get_chat_member** (`chat_id`, `user_id`) - Возвращает участника чата (GET /chats/{chatId}/members?user_ids=): types.ChatMember со статусами по-телеботовски (владелец → 'creator', админ → 'administrator', иначе 'member'; нет в чате → заглушка 'left'). can_*-флаги собираются из прав MAX; статусов 'restricted'/'kicked' в MAX не разглядеть. Бот должен быть админом чата  
* **get_chat_administrators** (`chat_id`) - Список админов чата (GET /chats/{chatId}/members/admins) как List[ChatMember]; владелец — 'creator'. Бот должен быть админом, иначе исключение  
* **get_chat_membership** (`chat_id`) - Членство самого бота (GET /chats/{chatId}/members/me) — расширение MAX: удобно проверять, админ ли бот и какие у него права. Возвращает ChatMember  
* **ban_chat_member** (`chat_id`, `user_id`, `until_date`, `revoke_messages`) - Удаляет пользователя с блокировкой: DELETE /chats/{chatId}/members с block=true (нужно право add_remove_members). Отличия от Telegram: блокировка работает только в чатах с публичной/приватной ссылкой (иначе просто удаление); until_date и revoke_messages игнорируются с предупреждением (временных банов и массового удаления сообщений нет); разбана через Bot API нет. Мягкое удаление с правом вернуться — `bot.api.remove_chat_member(chat_id, user_id)` без block. Возвращает True/False по success (telebot бросил бы исключение — проверяйте возврат). **kick_chat_member** — устаревший алиас с предупреждением, как в telebot  
* **unban_chat_member** (`chat_id`, `user_id`, `only_if_banned`) - Заглушка: разбана в Bot API MAX нет, вызов всегда бросает NotImplementedError (блокировку снимает только администратор вручную). Телеграмный приём «ban+unban = кик с правом вернуться» заменяется одним `bot.api.remove_chat_member(chat_id, user_id)`  
* **promote_chat_member** (`chat_id`, `user_id`, `can_*`…) - Назначает админа (POST /chats/{chatId}/members/admins; нужно право add_admins); все флаги False/None — снимает админку (DELETE …/admins/{userId}), как в Telegram. Маппинг флагов: can_change_info → change_chat_info; can_pin_messages → pin_message; can_invite_users и can_restrict_members → add_remove_members; can_promote_members → add_admins; can_post_messages → write; can_edit_messages → edit; can_delete_messages → delete; can_manage_video_chats/voice_chats → can_call; can_manage_chat → read_all_messages. is_anonymous/can_manage_topics/can_*_stories игнорируются с предупреждением; если запрошены ТОЛЬКО такие флаги — предупреждение и False без вызова API (разжаловать было бы противоположно намерению); права MAX edit_link и view_stats достижимы только через `bot.api.set_chat_admins`. Повторный вызов заменяет набор прав целиком (PUT-семантика MAX, совпадает с Telegram); alias при этом не передаётся — выставленный титул может сброситься, при необходимости повторите set_chat_administrator_custom_title. Возвращает True/False по success  
* **set_chat_administrator_custom_title** (`chat_id`, `user_id`, `custom_title`) - Титул админа — alias MAX: читает текущие права через GET admins и переотправляет их вместе с alias (POST admins заменяет права целиком). Пользователь должен уже быть админом, иначе ValueError; владельцу титул не задать — тоже ValueError (как в Telegram; у владельца permissions null, слать пустой набор прав опасно). Возвращает True/False по success  
* **add_chat_members** (`chat_id`, `user_ids`) - Добавляет участников (POST /chats/{chatId}/members; нужно право add_remove_members) — расширение MAX, Telegram-боты так не умеют. Принимает id или список; если кого-то добавить не удалось (failed_user_ids — например, приватность), предупреждает и возвращает False  
* **pin_chat_message** (`chat_id`, `message_id`, `disable_notification`) - Закрепляет сообщение (PUT /chats/{chatId}/pin; нужно право pin_message). Отличие от Telegram: закреп в MAX один на чат — новый вытесняет старый. Возвращает True/False по success  
* **unpin_chat_message** (`chat_id`, `message_id`) - Снимает закреп (DELETE /chats/{chatId}/pin). message_id серверу не нужен (закреп один); если он передан, метод сверяет его с текущим закрепом через GET /pin и чужой закреп НЕ снимает — предупреждение и False. Возвращает True/False по success  
* **unpin_all_chat_messages** (`chat_id`) - Тот же DELETE /chats/{chatId}/pin: закреп в MAX один, метод эквивалентен unpin_chat_message без message_id  
* **get_pinned_message** (`chat_id`) - Закреплённое сообщение чата (GET /chats/{chatId}/pin) — расширение MAX (в telebot закреп достаётся только через get_chat().pinned_message). Message или None; переживает закреп от имени канала (sender: null)  
* **set_my_commands** (`commands`, `scope`, `language_code`) - Задаёт команды бота (PATCH /me с `{"commands"}`, список заменяется целиком). Принимает maxibot/telebot BotCommand и словари {"command"/"name", "description"}; ведущий '/' срезается. Лимиты MAX: 32 команды, имя 64, описание 128. Скоупов и языковых версий в MAX нет — scope/language_code игнорируются с предупреждением. Возвращает True  
* **get_my_commands** (`scope`, `language_code`) - Список команд бота (commands из GET /me) как List[BotCommand] (.command без '/', .description). scope/language_code игнорируются с предупреждением  
* **delete_my_commands** (`scope`, `language_code`) - Удаляет все команды: PATCH /me с `{"commands": []}` (пустой список по спеке снимает команды)  
* **set_my_name** (`name`, `language_code`) - Меняет имя бота (PATCH /me с `{"first_name"}`, 1–59 символов) — в Telegram это умеет только BotFather. Сбросить имя нельзя: с None/пустым — ValueError. **get_my_name** — BotName из first_name+last_name  
* **set_my_description** (`description`, `language_code`) - Меняет описание бота (PATCH /me с `{"description"}`, до 16000 символов; None/"" — снять, уходит null) — в Telegram только BotFather. **get_my_description** — BotDescription ("" если не задано)  
* **set_my_short_description** (`short_description`, `language_code`) - Заглушка: отдельного короткого описания в MAX нет — предупреждение и False, основное описание НЕ трогается (иначе типовой код set_my_description+set_my_short_description затирал бы длинное описание). **get_my_short_description** — BotShortDescription из единственного description  
* **set_my_photo** (`photo`) - Меняет аватар бота (PATCH /me с `{"photo"}`) — расширение MAX, в telebot аналога нет (в Telegram только BotFather). Байты/file-like — загрузка через POST /uploads?type=image; строка — URL или токен  
* **get_file** (`file_id`) - Готовит файл к скачиванию — как в telebot, но file_id в MAX нет: принимает прямую ссылку вложения (message.document.file_path — возвращается без запроса к API) или токен видео (message.video.file_id — ссылка из GET /videos/{videoToken}: лучший mp4 1080→…→144, если mp4 нет — hls; None, если видео недоступно). File.file_path — ПОЛНЫЙ URL. Токены не-видео вложений в ссылку не разрешаются (эндпоинта нет — 404 с предупреждением-подсказкой): для них паттерн `get_file(x.file_id)` замените на `get_file(x.file_path)`  
* **get_file_url** (`file_id`) - Прямая ссылка для скачивания — get_file(...).file_path; в отличие от Telegram не собирается из токена бота, это готовый URL MAX. None — видео недоступно (urls: null)  
* **download_file** (`file_path`) - Скачивает файл, возвращает байты. file_path — полный URL (get_file(...).file_path или payload.url вложения); токен — ValueError с подсказкой, пустой/None (недоступное видео) — ValueError с указанием причины. Настройки сети apihelper (прокси, таймауты, ретраи) применяются, токен бота НЕ отправляется (ссылки ведут на CDN)  
* **get_video** (`video_token`) - Расширение MAX: информация о видео (GET /videos/{videoToken}) — types.Video с прямыми ссылками (urls.mp4_1080…mp4_144/hls, file_path — лучшая) и метаданными (width/height/duration/thumbnail); urls null (видео недоступно) → file_path None  
* **callback_query_handler** (`data` `**kwargs`) - Декоратор для регистрации обработчиков callback-запросов от inline-кнопок  
    * **data** - Данные кнопки для фильтрации  
    * **kwargs** - Дополнительные фильтры для обработчика  
* **add_callback_query_handler** (`handler_dict`) - Добавление обработчик callback-запросов напрямую  
    * **handler_dict** - Словарь обработчика событий  
* **_process_callback_query** (`callback`) - Обрабатывает входящий callback-запрос. Метод ищет подходящий обработчик среди зарегистрированных и вызывает первый соответствующий фильтрам  
    * **callback** - Объект callback-запроса  

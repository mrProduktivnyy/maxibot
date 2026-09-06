# Types
## class maxibot.types.Message(update: Dict[str, Any], api: Api)
Объект, представляющий сообщение  
MAX API документация: https://dev.max.ru/docs-api/objects/Message  
**Параметры:**
* **content_type** (`str`) - тип сообщения по именам telebot: `text`, `photo`, `video`, `audio`, `document`, `sticker`, `location`, `contact`; клавиатура и share-превью тип не определяют
* **message_id** (`str`) - Уникальный ID сообщения
* **from_user** (`maxibot.types.User`) - Пользователь, отправивший сообщение. У поста от имени канала (sender: null) — None, как в telebot  
* **date** (`datetime`) - Время создания сообщения  
* **chat** (`maxibot.types.Chat`) - Объект чата, в котором отправлено сообщение  
* **reply_to_message** (`maxibot.types.Link`) - Сообщение, на которое ответили; None, если это не ответ  
* **text** (`str`) - Текст сообщения  
* **caption** (`str`) - Подпись медиа-сообщения (у медиа text тоже заполнен — отличие от telebot)  
* **json** (`dict`) - Сырой dict сообщения из обновления MAX  
* **photo** (`ImageAttachment`) - Опционально. Содержит вложения фото. Поддерживает телеботовский паттерн списка: `message.photo[-1].file_id` (размер в MAX один)  
* **photo_reply** (`Photo`) - Опциолнально. Вложения фото из сообщения, на которое ответили  
* **video** (`Video`) / **audio** (`Audio`) / **document** (`Document`) - Опционально. Первое вложение соответствующего типа с телеботовскими атрибутами (file_id — токен, file_path — прямая ссылка; у видео file_path None — ссылки через bot.get_file/get_video). Голосовые в MAX не отличаются от аудио: voice всегда None, голосовое приходит в audio  
* **update_type** (`str`) - Тип события, произошедшего в чате  
* **html_text / html_caption** (`str`) - Как в telebot; entities в MAX нет — просто текст/подпись  

Все остальные атрибуты `telebot.types.Message` (`sticker`, `venue`, `media_group_id`, `forward_from`, ...) существуют и равны `None` — код, переехавший с telebot, не падает с AttributeError.  
## class maxibot.types.CallbackQuery(update: Dict[str, Any], api: Api)
Объект, представляющий входящий запрос нажатия кнопки на inline-клавитуре  
MAX API документация https://dev.max.ru/docs-api/objects/Update  
**Параметры:**
* **id** (`str`) - Текущий ID клавиатуры  
* **from_user** (`maxibot.types.User`) - Пользователь, отправивший сообщение  
* **message** (`maxibot.types.Message`) - Изначальное сообщение, содержащее встроенную клавиатуру  
* **chat_instance** (`str`) - Текущий ID клавиатуры  
* **data** (`str`) - Данные, связанные с кнопкой  
## class maxibot.types.InputMedia(type, media, caption, parse_mode)
Этот объект представляет собой содержимое медиасообщения, которое необходимо отправить  
**Параметры:**
* **type** (`str`) - Тип медиавложения (`photo`/`file`/`video`/`audio`)  
* **media** (`bytes`) - Медиавложение; строка: у фото — http(s)-ссылка или токен, у аудио и видео — токен ранее загруженного вложения; у file строка не поддерживается (загрузится как содержимое)  
* **caption** (`str`) - Описание отправляемого медиавложению  
* **parse_mode** (`str`) - Тип форматирования описания отправляемого медиавложения  

Подклассы с зафиксированным типом, как в telebot: `InputMediaPhoto(media, caption, parse_mode)`, `InputMediaVideo(...)`, `InputMediaAudio(...)` (у видео и аудио токен приходит сразу в ответе POST /uploads)  
## class maxibot.types.MessageID(message_id)
Идентификатор сообщения — аналог `telebot.types.MessageID`; его возвращают copy_message, forward_messages и copy_messages  
**Параметры:**
* **message_id** (`str`) - Идентификатор сообщения (mid в MAX — строка, в отличие от телеграмного int)  
## class maxibot.types.Photo(update: Dict[str, Any])
Класс сериализации и работы с фотографиями во вложениях  
**Параметры:**
* **file_id** (`str`) - Уникальный идентификатор приложенного фото  
* **token** (`str`) - Токен приложенного фото  
* **url** (`str`) - URL-загрузки приложенного фото  
## class maxibot.types.Link(update: Dict[str, Any])
Класс сериализации и работы со ссылками на сообщения (отвеченные, пересланные)  
**Параметры:**
* **type** (`str`) - Тип сообщения  
* **message_id** (`str`) - Идентификатор сообщения  
* **from_user** (`maxibot.types.User`) - Пользователь, отправивший сообщение  
* **chat** (`maxibot.types.ChatLink`) - Объект чата, в котором отправлено сообщение  
## class maxibot.types.ChatMember(member: Dict[str, Any], status: Optional[str])
Участник чата — результат get_chat_member, get_chat_administrators и get_chat_membership; собирается из объекта ChatMember MAX (GET /chats/{chatId}/members)  
**Параметры:**
* **status** (`str`) - Телеботовский статус: 'creator' (владелец), 'administrator', 'member'; 'left' — пользователя в чате нет; 'kicked' — в событиях my_chat_member (блокировка бота)  
* **user** (`User`) - Пользователь; здесь user.id — НАСТОЯЩИЙ id пользователя (в отличие от message.from_user.id, где исторически id чата)  
* **custom_title** (`str`) - Титул админа (alias MAX)  
* **can_change_info, can_pin_messages, can_invite_users, can_restrict_members, can_promote_members, can_post_messages, can_edit_messages, can_delete_messages, can_manage_video_chats** (`bool`) - Флаги из прав MAX (add_remove_members взводит и can_invite_users, и can_restrict_members); у владельца все True, у обычного участника — None, как в telebot  
* **can_manage_chat** (`bool`) - У админа и владельца всегда True (телеграмный инвариант «implied by any other administrator privilege»)  
* **is_member** (`bool`) - False у 'left' и 'kicked'  

Остальные атрибуты telebot.types.ChatMember существуют и равны None (until_date, is_anonymous, can_send_* и т.п.). Дополнительно сырые поля MAX: is_owner, is_admin, permissions (список прав как пришёл — в нём видны edit_link и view_stats, телеботовских флагов для них нет), alias, last_access_time, join_time, description (описание профиля), avatar_url, full_avatar_url  
## class maxibot.types.ChatMemberUpdated(chat, from_user, date, old_chat_member, new_chat_member, invite_link, via_chat_folder_invite_link)
Изменение статуса участника — как telebot.types.ChatMemberUpdated (включая property difference). Синтезируется из обновлений MAX: my_chat_member — bot_added/bot_removed (left↔member), bot_started/bot_stopped (kicked↔member, аналог разблокировки/блокировки); chat_member — user_added/user_removed (left↔member)  
**Параметры:**
* **chat** (`Chat`) - Чат события (лёгкий: id и type, без похода в API — у bot_removed бот уже удалён из чата). type — телеботовский: private/group/channel (в отличие от message.chat.type, где исторически сырые dialog/chat/channel)  
* **from_user** (`User`) - Инициатор (кто добавил/удалил); по ссылке вошёл/сам вышел — сам пользователь, со всеми полями. id — идентификатор ПОЛЬЗОВАТЕЛЯ, а не чата (в отличие от message.from_user.id): для ответа берите chat.id. Когда инициатор пришёл как inviter_id/admin_id (посторонний), известен только его id — имени и username MAX не присылает; language_code заполняется лишь у bot_started/bot_stopped (там есть user_locale)  
* **difference** (`property`) - Разница old/new в формате telebot ({'status': ['left', 'member']}); производное is_member в разницу не попадает — как и в telebot  
* **date** (`int`) - Unix-время в СЕКУНДАХ, как в telebot (не datetime, в отличие от Message.date)  
* **old_chat_member / new_chat_member** (`ChatMember`) - Статусы затронутого (у my_chat_member — сам бот; его данные берутся из GET /me один раз с кэшем)  
* **invite_link / via_chat_folder_invite_link** - Всегда None (в MAX таких сущностей нет)  
* **is_channel** (`bool`) - Флаг MAX; **json** — сырое обновление (deep-link кнопки «Начать» — в json['payload'])  
## class maxibot.types.BotCommand(command: str, description: Optional[str])
Команда бота — как telebot.types.BotCommand. В MAX у команды поле name; при отправке ведущий '/' срезается (лимиты: имя 64, описание 128 символов). description, в отличие от telebot, необязателен  
**Параметры:**
* **command** (`str`) - Имя команды  
* **description** (`str`) - Описание команды  
## class maxibot.types.BotName(name: str) / BotDescription(description: str) / BotShortDescription(short_description: str)
Результаты get_my_name / get_my_description / get_my_short_description — как одноимённые типы telebot. Отдельного короткого описания в MAX нет: BotShortDescription заполняется из единственного description  
## class maxibot.types.File(file_id, file_path, file_size)
Файл, готовый к скачиванию (результат bot.get_file) — как telebot.types.File, но file_path — ПОЛНЫЙ URL (в Telegram — относительный путь), роль file_id играет токен вложения либо сама ссылка  
**Параметры:**
* **file_id / file_unique_id** (`str`) - То, что передали в get_file (ссылка или токен)  
* **file_path** (`str`) - Полный URL для download_file (None, если видео недоступно)  
* **file_size** (`int`) - Всегда None: MAX не сообщает размер (кроме document.file_size из вложения)  
## class maxibot.types.Video(attach: Dict[str, Any])
Видео-вложение — атрибуты telebot.types.Video: file_id/file_unique_id (токен), width, height, duration, thumbnail (ImagePayload с телеботовскими полями PhotoSize) и устаревший алиас thumb, file_name/mime_type/file_size (None). MAX-поля: token, url (НЕ прямая ссылка!), urls (`VideoUrls` из get_video: mp4_1080…mp4_144, hls, .best — лучший mp4), file_path (лучшая прямая ссылка; у вложения из сообщения None — скачиваемые ссылки отдаёт только GET /videos/{videoToken})  
## class maxibot.types.Audio(attach: Dict[str, Any])
Аудио-вложение — атрибуты telebot.types.Audio: file_id (токен); duration/performer/title/file_name/mime_type/file_size/thumbnail (и алиас thumb) — None (MAX их не сообщает). MAX-поля: token, url, file_path (прямая ссылка), transcription (расшифровка речи)  
## class maxibot.types.Document(attach: Dict[str, Any])
Файл-вложение — атрибуты telebot.types.Document: file_id (токен), file_name, file_size; mime_type/thumbnail (и алиас thumb) — None. MAX-поля: token, url, file_path (прямая ссылка)  
## class maxibot.types.ChatLink(update: Dict[str, Any])
Класс сериализации и работы с объектом чата в пересланном сообщении  
**Параметры:**
* **id** (`str`) - Идентификатор чата  
## class maxibot.types.Chat(update: Dict[str, Any])
Класс чата  
**Параметры:**
* **id** (`str`) - Идентификатор чата  
* **type** (`str`) - Тип чата (в message.chat — сырой тип MAX: dialog/chat/channel)  
* **user_id** (`str`) - Идетификатор пользователя, если сообщение было отправлено пользователю  

Классметод `Chat.from_chat_info(info, api)` строит Chat из ответа GET /chats/{chatId} (используется bot.get_chat): id, type с телеботовскими именами (dialog → private, chat → group, channel → channel), title, description, photo (URL иконки), pinned_message (Message или None), invite_link, для диалогов — first_name/last_name/username собеседника; дополнительно status, participants_count, is_public  
## class maxibot.types.User(update: Dict[str, Any])
Класс пользователя  
**Параметры:**
* **id** (`str`) - Идентификатор пользователя/чата  
* **real_id** (`str`) - Уникальный идентификатор пользователя  
* **is_bot** (`boolean`) - `true`, если пользователь является ботом  
* **first_name** (`str`) - Отображаемое имя пользователя  
* **username** (`str`) - Уникальное публичное имя пользователя. Может быть null, если пользователь недоступен или имя не задано  
* **last_name** (`str`) - Отображаемая фамилия пользователя  
* **language_code** (`str`) - Текущий язык пользователя в формате IETF BCP 47. Доступно только в диалогах  
## class maxibot.types.Body(body: Dict[str, Any])
Класс тела сообщения  
**Параметры:**
* **mid** (`str`) - Уникальный идентификатор сообщения  
* **seq** (`str`) - Идентификатор последовательности сообщения в чате  
* **text** (`boolean`) - Новый текст сообщения  
* **attachments** (`str`) - Вложения сообщения. Могут быть одним из типов Attachment.  
## class maxibot.types.ImageAttachment(attach: Dict[str, Any])
Класс для работы с вложениями типа "image". Ведёт себя и как телеботовский список PhotoSize: `photo[-1]`/`photo[0]`, len, итерация (размер в MAX один — возвращается само вложение)  
**Параметры:**
* **payload** (`ImagePayload`) - Параметры вложения  
* **type** (`str`) - Тип вложения  
* **file_id / file_unique_id** (`str`) - Токен вложения (телеботовские имена)  
* **file_path** (`str`) - Прямая ссылка (payload.url) для download_file  
* **width / height / file_size** - Всегда None: MAX размеров изображения не сообщает  
## class maxibot.types.ImagePayload(payload: Dict[str, Any])
Класс для хранения данных изображения. Живёт и как message.video.thumbnail, поэтому несёт телеботовские поля PhotoSize  
**Параметры:**
* **photo_id** (`ImagePayload`) - Уникальный ID этого изображения  
* **token** (`str`) - Токен изображения  
* **url** (`str`) - URL изображения  
* **file_id / file_unique_id** (`str`) - Токен (телеботовские имена)  
* **file_path** (`str`) - Прямая ссылка (url) для download_file  
* **width / height / file_size** - Всегда None  
## class maxibot.types.InlineKeyboardMarkup(keyboard, row_width)
Класс для создания inline-клавиатур в сообщениях. Сигнатура как у telebot: keyboard — готовый список рядов кнопок, row_width по умолчанию 3  
**Параметры:**
* **MAX_ROWS** (`int`) - Максимум рядов в клавиатуре (30)  
* **MAX_BUTTONS** (`int`) - Максимум кнопок во всей клавиатуре (210)  
* **MAX_ROW_REGULAR** (`int`) - Максимум кнопок в ряду без специальных кнопок (7)  
* **MAX_ROW_SPECIAL** (`int`) - Максимум кнопок в ряду, где есть кнопка link, open_app, request_contact или request_geo_location (3)  
* **row_width** (`int`) - Сколько кнопок в ряду по умолчанию при add()  
* **keyboard** (`List[List[InlineKeyboardButton]]`) - Список объектов типа InlineKeyboardButton (inline-кнопка)  
## class maxibot.types.InlineKeyboardButton(text, url, callback_data, web_app, switch_inline_query, switch_inline_query_current_chat, switch_inline_query_chosen_chat, callback_game, pay, login_url)
Класс для создания inline-кнопок в сообщениях. Сигнатура один в один с telebot. Кнопка должна быть ровно одного вида: `url` (link), `callback_data` (callback) или `web_app` (open_app). В ряду с кнопками link и open_app не больше 3 кнопок  
**Параметры:**
* **MAX_URL_LEN** (`int`) - Ограничение максимально длины ссылки в поле url  
* **text** (`str`) - Текст на кнопке  
* **url** (`str`) - URL ссылка для кнопки типа "link"  
* **callback_data** (`str`) - Данные для callback-кнопки  
* **web_app** (`WebAppInfo`) - Мини-приложение для кнопки типа "open_app" (можно строкой — username бота или ссылка на него)  
* **switch_inline_query**, **switch_inline_query_current_chat**, **switch_inline_query_chosen_chat**, **callback_game**, **pay**, **login_url** - Принимаются для совместимости с telebot и игнорируются: inline-режима, игр и платежей в MAX нет; кнопка только с таким параметром не собирается (ValueError)  
## class maxibot.types.WebAppInfo(url, contact_id, payload)
Мини-приложение для кнопки `InlineKeyboardButton(web_app=...)`. Сигнатура как у telebot. В MAX кнопка open_app открывает мини-приложение бота (адрес приложения задаётся в настройках бота), поэтому `url` — это username бота или ссылка на него  
**Параметры:**
* **url** (`str`) - Публичное имя (username) бота (ведущий @ отбрасывается) или ссылка на него — поле web_app кнопки open_app; None допустим, если задан contact_id. Адрес самого приложения сюда не подходит — будет предупреждение в лог  
* **contact_id** (`int`) - ID бота, чьё мини-приложение надо открыть — поле contact_id кнопки open_app (только в MAX)  
* **payload** (`str`) - Параметр запуска, который попадёт в initData мини-приложения — поле payload кнопки open_app (только в MAX)  
## class maxibot.types.Update(update: Dict[str, Any], api: Optional[Api])
Обновление от MAX API целиком (аналог `telebot.types.Update`) — его получают middleware без update_types и возвращает `bot.get_updates()`. Заполнено только поле своего типа, сырой payload всегда в `json`  
**Параметры:**
* **json** (`dict`) - Сырое обновление от MAX  
* **update_type** (`str`) / **timestamp** (`int`) - Тип и время события  
* **message** / **edited_message** / **callback_query** - Объекты своего типа; в них те же экземпляры, что уйдут в обработчики, поэтому атрибуты, выставленные в middleware, видны и обработчикам  
* **my_chat_member** / **chat_member** (`ChatMemberUpdated`) - События членства; подставляет бот при обработке, без подписки — None  
* **channel_post** / **edited_channel_post** / **update_id** - Телеботовские поля, которых в MAX нет: всегда None, чтобы перенесённый код не падал с AttributeError. Маркер пачки вместо update_id — в `bot.last_update_id`  
* **api** - Клиент API, которым построены объекты; None — обновление сырое (см. de_json)  

**Update.de_json(json_string, api=None)** — как в telebot: принимает JSON-строку, bytes или готовый словарь. Без api обновление остаётся сырым (`update.message` равен None), потому что Chat ходит в API за названием чата: объекты появятся в этом же Update, когда бот разберёт его в `process_new_updates` — и только если этот тип обновления бот вообще диспатчит (есть обработчик или middleware). Нужен заполненный `update.message` в любом случае — передайте api: `Update.de_json(request.get_json(), bot.api)`  
## class maxibot.types.UpdateType
Типы обновлений, которые можно получать от MAX API (объект Update в документации; тот же список строк — `maxibot.util.update_types`)  
**Параметры:**
* **MESSAGE_CREATED** (`str`) - Новое сообщение создано  
* **MESSAGE_CALLBACK** (`str`) - Нажата кнопка клавиатуры бота  
* **MESSAGE_EDITED** (`str`) - Сообщение изменено  
* **MESSAGE_REMOVED** (`str`) - Сообщение удалено (`MESSAGE_DELETED` — прежнее имя той же константы)  
* **BOT_STARTED** (`str`) - Пользователь запустил бота  
* **BOT_STOPPED** (`str`) - Пользователь остановил бота  
* **BOT_ADDED** (`str`) - Бот добавлен в чат  
* **BOT_REMOVED** (`str`) - Бот удалён из чата  
* **USER_ADDED** (`str`) - Пользователь добавлен в чат  
* **USER_REMOVED** (`str`) - Пользователь удалён из чата  
* **CHAT_TITLE_CHANGED** (`str`) - Изменено название чата  
* **DIALOG_CLEARED** (`str`) - Пользователь очистил диалог с ботом  
* **DIALOG_MUTED** (`str`) - Пользователь отключил уведомления диалога с ботом  
* **DIALOG_UNMUTED** (`str`) - Пользователь включил уведомления диалога с ботом  
* **DIALOG_REMOVED** (`str`) - Пользователь удалил диалог с ботом  
* **COMMENT_CREATED** (`str`) - Создан комментарий  
* **COMMENT_EDITED** (`str`) - Комментарий изменён  
* **COMMENT_REMOVED** (`str`) - Комментарий удалён  

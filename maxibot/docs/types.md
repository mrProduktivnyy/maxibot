# Types
## class maxibot.types.Message(update: Dict[str, Any], api: Api)
Объект, представляющий сообщение  
MAX API документация: https://dev.max.ru/docs-api/objects/Message  
**Параметры:**
* **content_type** (`str`) - тип сообщения по именам telebot: `text`, `photo`, `video`, `audio`, `document`, `sticker`, `location`, `contact`; клавиатура и share-превью тип не определяют
* **message_id** (`str`) - Уникальный ID сообщения
* **from_user** (`maxibot.types.User`) - Пользователь, отправивший сообщение  
* **date** (`datetime`) - Время создания сообщения  
* **chat** (`maxibot.types.Chat`) - Объект чата, в котором отправлено сообщение  
* **reply_to_message** (`maxibot.types.Link`) - Сообщение, на которое ответили; None, если это не ответ  
* **text** (`str`) - Текст сообщения  
* **caption** (`str`) - Подпись медиа-сообщения (у медиа text тоже заполнен — отличие от telebot)  
* **json** (`dict`) - Сырой dict сообщения из обновления MAX  
* **photo** (`ImageAttachment`) - Опционально. Содержит вложения фото.  
* **photo_reply** (`Photo`) - Опциолнально. Вложения фото из сообщения, на которое ответили  
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
Класс для работы с вложениями типа "image"  
**Параметры:**
* **payload** (`ImagePayload`) - Параметры вложения  
* **type** (`str`) - Тип вложения  
## class maxibot.types.ImagePayload(payload: Dict[str, Any])
Класс для хранения данных изображения  
**Параметры:**
* **photo_id** (`ImagePayload`) - Уникальный ID этого изображения  
* **token** (`str`) - Токен изображения  
* **url** (`str`) - URL изображения  
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

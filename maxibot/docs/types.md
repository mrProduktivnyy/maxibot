# Types
## class maxibot.types.Message(update: Dict[str, Any], api: Api)
Объект, представляющий сообщение  
MAX API документация: https://dev.max.ru/docs-api/objects/Message  
**Параметры:**
* **content_type** (`str`) - тип сообщения
* **message_id** (`str`) - Уникальный ID сообщения
* **from_user** (`maxibot.types.User`) - Пользователь, отправивший сообщение  
* **date** (`datetime`) - Время создания сообщения  
* **chat** (`maxibot.types.Chat`) - Объект чата, в котором отправлено сообщение  
* **reply_to_message** (`maxibot.types.Link`) - Опционально содержит сообщение, на которое ответили  
* **text** (`str`) - Текст сообщения  
* **photo** (`ImageAttachment`) - Опционально. Содержит вложения фото.  
* **photo_reply** (`Photo`) - Опциолнально. Вложения фото из сообщения, на которое ответили  
* **update_type** (`str`) - Тип события, произошедшего в чате  
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
* **type** (`str`) - Тип медиавложения  
* **media** (`bytes`) - Медиавложение  
* **caption** (`str`) - Описание отправляемого медиавложению  
* **parse_mode** (`str`) - Тип форматирования описания отправляемого медиавложения  
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
* **type** (`str`) - Тип чата  
* **user_id** (`str`) - Идетификатор пользователя, если сообщение было отправлено пользователю  
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
## class maxibot.types.InlineKeyboardMarkup(payload: Dict[str, Any])
Класс для хранения данных изображения  
**Параметры:**
* **MAX_ROWS** (`int`) - Ограничение максимального кол-ва кнопок в ряду  
* **MAX_BUTTONS** (`int`) - Ограничение максимального кол-ва кнопок в клавиатуре  
* **MAX_ROW_REGULAR** (`int`) - Кол-во рядов простых кнопок по умолчанию  
* **MAX_ROW_SPECIAL** (`int`) - Кол-во рядов специальных кнопок по умолчанию  
* **row_width** (`int`) - Кол-во рядок кнопок  
* **keyboard** (`List[List[InlineKeyboardButton]]`) - Список объектов типа InlineKeyboardButton (inline-кнопка)  
## class maxibot.types.InlineKeyboardButton(text, url, callback_data)
Класс для создания inline-кнопок в сообщениях  
**Параметры:**
* **MAX_URL_LEN** (`int`) - Ограничение максимально длины ссылки в поле url  
* **text** (`str`) - Текст на кнопке  
* **url** (`str`) - URL ссылка для кнопки типа "link"  
* **callback_data** (`str`) - Данные для callback-кнопки  
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
* **MESSAGE_CHAT_CREATED** (`str`) - Устаревшее: в текущей документации MAX такого обновления нет  

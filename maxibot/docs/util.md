# Util
## class maxibot.util
Модуль, предоставляющий набор технических вспомагательных функций  
**Методы:**
* **is_command** (`text`) - Проверка, является ли `text` командой  
* **extract_command** (`text`) - Получение команды из текста `text` сообщения  
* **extract_arguments** (`text`) - Аргументы после команды, парный к `extract_command`: `/get name` → `'name'`, `/get` → `''`, не команда → `None`  
* **is_pil_image** (`var`) - Проверка, является ли `var` объектом типа `PIL.Image.Image`  
* **pil_image_to_bytes** (`image`, `extension`, `quality`) - Получение байткода из объекта типа, `PIL.Image.Image`  
    * **image** - объект типа `PIL.Image.Image`
    * **extension** - Разрешение изображения
    * **quality** - Качество изображения
* **get_text** (`media`) - Метод получения текста из `media`  
* **get_parce_mode** (`media`) - Метод получения типа формата из `media`  
* **smart_split** (`text`, `chars_per_string=4000`) - Разбиение длинного текста на части по `\n`, `. ` или пробелу (в этом порядке приоритета)  
* **split_string** (`text`, `chars_per_string`) - Разбиение текста на части ровно по числу символов, без оглядки на слова  
* **escape** (`text`) - Экранирование HTML: `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;` (для `parse_mode='HTML'`)  
* **user_link** (`user`, `include_id=False`) - HTML-упоминание пользователя `<a href='max://user/…'>имя</a>`; берётся `user.real_id` (настоящий id — `from_user.id` в maxibot равен id чата), имя экранируется; не забудьте `parse_mode='HTML'`  
* **quick_markup** (`values`, `row_width=2`) - Сборка `InlineKeyboardMarkup` из словаря `{'текст': kwargs}`, где kwargs — параметры `InlineKeyboardButton` (`url`, `callback_data`, `web_app`); телеботовские параметры без аналога в MAX игнорируются  
* **antiflood** (`function`, `*args`, `number_retries=5`, `**kwargs`) - Вызов `function` с пережиданием лимита запросов (HTTP 429): пауза из заголовка `Retry-After`, без него — 1 секунда (Telegram присылает retry_after в теле, MAX — нет); другие ошибки — сразу наружу  
* **update_types** - Список всех типов обновлений MAX (аналог `telebot.util.update_types`)  

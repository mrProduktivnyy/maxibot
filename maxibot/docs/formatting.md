# Formatting
## module maxibot.formatting
Функции разметки — как `telebot.formatting`, но под диалекты MAX. Телеботовский импорт переезжает заменой слова: `from maxibot import formatting`.

**Отличия маркдауна MAX от телеграмного MarkdownV2** (m-функции их учитывают):
| функция | maxibot (MAX) | telebot (Telegram) |
|---|---|---|
| `mbold` | `**текст**` | `*текст*` (в MAX это курсив!) |
| `mitalic` | `_текст_` | `_текст_\r` (хак под парсер Telegram) |
| `munderline` | `++текст++` | `__текст__` (в MAX это жирный!) |
| `mstrikethrough` | `~~текст~~` | `~текст~` |
| `mspoiler` | **нет в MAX** — предупреждение, текст без обёртки | `\|\|текст\|\|` |

HTML-диалект по телеботовским тегам совпадает — `hbold`/`hitalic`/`hunderline`/`hstrikethrough`/`hlink`/`hcode`/`hpre`/`hcite`/`hide_link` работают байт в байт как в telebot; `hspoiler` — как `mspoiler` (тег `<tg-spoiler>` MAX бы вырезал). Неподдержанные теги MAX вырезает молча.

**Методы** (сигнатуры телеботовские, у всех `escape=True` — экранировать спецсимволы):
* **format_text** (`*args`, `separator="\n"`) - Склейка размеченных строк
* **escape_html** (`content`) - Экранирование HTML (`html.escape`)
* **escape_markdown** (`content`) - Экранирование маркдауна; телеботовский набор символов плюс `^` (в MAX `^^текст^^` — выделение)
* **mbold / hbold**, **mitalic / hitalic**, **munderline / hunderline**, **mstrikethrough / hstrikethrough** (`content`, `escape=True`) - См. таблицу выше
* **mspoiler / hspoiler** (`content`, `escape=True`) - Спойлера в MAX нет: предупреждение в лог, текст возвращается без обёртки (виден сразу)
* **mmark / hmark** (`content`, `escape=True`) - `^^текст^^` / `<mark>текст</mark>` — выделение цветом, бонус MAX (в telebot аналога нет)
* **mlink / hlink** (`content`, `url`, `escape=True`) - Ссылка `[текст](url)` / `<a href="url">текст</a>`; в telebot ветка `escape=False` у `mlink` подставляла в url текст (битая ссылка) — здесь починено
* **mcode** (`content`, `language=""`, `escape=True`) / **hcode** (`content`, `escape=True`) / **hpre** (`content`, `escape=True`, `language=""`) - Код
* **mcite / hcite** (`content`, `escape=True`) - Цитата (`>` построчно / `<blockquote>`)
* **hide_link** (`url`) - Невидимая ссылка (слово-стык в `<a>`)

Не забудьте `parse_mode`: `'markdown'` для m-функций, `'html'` для h-функций.

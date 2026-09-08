"""
Функции разметки Markdown и HTML — как telebot.formatting, но под
диалекты MAX (раздел «Text formatting» в документации MAX Bot API).

Маркдаун MAX отличается от телеграмного MarkdownV2:

* жирный — ``**текст**`` (в Telegram ``*текст*``; у MAX одна
  звёздочка — курсив);
* курсив — ``_текст_`` (как в Telegram, но без телеграмного хака
  с ``\\r``);
* подчёркивание — ``++текст++`` (в Telegram ``__текст__``; у MAX
  двойное подчёркивание — жирный);
* зачёркивание — ``~~текст~~`` (в Telegram ``~текст~``);
* спойлера в MAX нет вовсе (``||текст||`` не работает) — mspoiler и
  hspoiler предупреждают и возвращают текст без обёртки;
* бонус MAX без аналога в Telegram — выделение ``^^текст^^``
  (mmark) и `<mark>` (hmark).

HTML-диалект совпадает по всем телеботовским тегам (`<b>`, `<i>`,
`<u>`, `<s>`, `<a>`, `<code>`, `<pre>`, `<blockquote>`) — h-функции
работают без изменений; неподдержанные теги MAX вырезает.

Использование — как в telebot:

.. code-block:: python3

    from maxibot import formatting

    bot.send_message(chat_id, formatting.format_text(
        formatting.mbold('Привет'),
        formatting.mitalic('мир'),
    ), parse_mode='markdown')
"""

import html
import logging
import re

from typing import Optional

logger = logging.getLogger("maxibot")


def format_text(*args, separator="\n"):
    """
    Склеивает строки в одну через separator — как
    telebot.formatting.format_text.

    .. code:: python3

        format_text(
            mbold('Привет'),
            mitalic('мир')
        )

    :param args: Строки для склейки
    :type args: str

    :param separator: Разделитель между строками
    :type separator: str

    :return: Склеенная строка
    :rtype: str
    """
    return separator.join(args)


def escape_html(content: str) -> str:
    """
    Экранирует HTML-символы — как telebot.formatting.escape_html
    (html.escape: & < > и кавычки).

    :param content: Строка для экранирования
    :type content: str

    :return: Экранированная строка
    :rtype: str
    """
    return html.escape(content)


def escape_markdown(content: str) -> str:
    """
    Экранирует спецсимволы маркдауна — как
    telebot.formatting.escape_markdown, плюс ``^`` (в MAX
    ``^^текст^^`` — выделение, у Telegram такого нет).

    :param content: Строка для экранирования
    :type content: str

    :return: Экранированная строка
    :rtype: str
    """
    parse = re.sub(r"([_*\[\]()~`>\#\+\-=|\.!\{\}\\^])", r"\\\1", content)
    reparse = re.sub(r"\\\\([_*\[\]()~`>\#\+\-=|\.!\{\}\\^])", r"\1", parse)
    return reparse


def mbold(content: str, escape: Optional[bool] = True) -> str:
    """
    Жирный текст в маркдауне: ``**текст**`` (диалект MAX; телеботовское
    ``*текст*`` в MAX означает курсив).

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '**{}**'.format(escape_markdown(content) if escape else content)


def hbold(content: str, escape: Optional[bool] = True) -> str:
    """
    Жирный текст в HTML: ``<b>текст</b>``.

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '<b>{}</b>'.format(escape_html(content) if escape else content)


def mitalic(content: str, escape: Optional[bool] = True) -> str:
    """
    Курсив в маркдауне: ``_текст_``. Телеботовский ``\\r`` в конце
    не добавляется — это хак под парсер Telegram, MAX перевод строки
    не вырезает.

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '_{}_'.format(escape_markdown(content) if escape else content)


def hitalic(content: str, escape: Optional[bool] = True) -> str:
    """
    Курсив в HTML: ``<i>текст</i>``.

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '<i>{}</i>'.format(escape_html(content) if escape else content)


def munderline(content: str, escape: Optional[bool] = True) -> str:
    """
    Подчёркнутый текст в маркдауне: ``++текст++`` (диалект MAX;
    телеботовское ``__текст__`` в MAX означает жирный).

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '++{}++'.format(escape_markdown(content) if escape else content)


def hunderline(content: str, escape: Optional[bool] = True) -> str:
    """
    Подчёркнутый текст в HTML: ``<u>текст</u>``.

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '<u>{}</u>'.format(escape_html(content) if escape else content)


def mstrikethrough(content: str, escape: Optional[bool] = True) -> str:
    """
    Зачёркнутый текст в маркдауне: ``~~текст~~`` (диалект MAX;
    телеботовская одиночная ``~`` в MAX не работает).

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '~~{}~~'.format(escape_markdown(content) if escape else content)


def hstrikethrough(content: str, escape: Optional[bool] = True) -> str:
    """
    Зачёркнутый текст в HTML: ``<s>текст</s>``.

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '<s>{}</s>'.format(escape_html(content) if escape else content)


def mspoiler(content: str, escape: Optional[bool] = True) -> str:
    """
    Спойлер — в MAX его НЕТ: телеграмная разметка ``||текст||`` не
    поддерживается ничем. Предупреждает и возвращает текст без
    обёртки (он будет виден сразу).

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Текст без обёртки
    :rtype: str
    """
    logger.warning("mspoiler: спойлера в MAX нет — текст будет виден сразу, без скрытия")
    return escape_markdown(content) if escape else content


def hspoiler(content: str, escape: Optional[bool] = True) -> str:
    """
    Спойлер — в MAX его НЕТ: телеграмный тег ``<tg-spoiler>`` был бы
    вырезан. Предупреждает и возвращает текст без обёртки (он будет
    виден сразу).

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Текст без обёртки
    :rtype: str
    """
    logger.warning("hspoiler: спойлера в MAX нет — текст будет виден сразу, без скрытия")
    return escape_html(content) if escape else content


def mmark(content: str, escape: Optional[bool] = True) -> str:
    """
    Выделенный (подсвеченный) текст в маркдауне: ``^^текст^^`` —
    бонус MAX, аналога в telebot нет.

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '^^{}^^'.format(escape_markdown(content) if escape else content)


def hmark(content: str, escape: Optional[bool] = True) -> str:
    """
    Выделенный (подсвеченный) текст в HTML: ``<mark>текст</mark>`` —
    бонус MAX, аналога в telebot нет.

    :param content: Текст
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '<mark>{}</mark>'.format(escape_html(content) if escape else content)


def mlink(content: str, url: str, escape: Optional[bool] = True) -> str:
    """
    Ссылка в маркдауне: ``[текст](url)``.

    В telebot ветка ``escape=False`` подставляла в url текст
    (``'[{}]({})'.format(..., url) if escape else content``) — ссылка
    получалась битой; здесь починено: подставляется url.

    :param content: Текст ссылки
    :type content: str

    :param url: Адрес
    :type url: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '[{}]({})'.format(escape_markdown(content), escape_markdown(url) if escape else url)


def hlink(content: str, url: str, escape: Optional[bool] = True) -> str:
    """
    Ссылка в HTML: ``<a href="url">текст</a>``.

    :param content: Текст ссылки
    :type content: str

    :param url: Адрес
    :type url: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '<a href="{}">{}</a>'.format(escape_html(url), escape_html(content) if escape else content)


def mcode(content: str, language: str = "", escape: Optional[bool] = True) -> str:
    """
    Блок кода в маркдауне: ``\\`\\`\\`код\\`\\`\\```.

    :param content: Код
    :type content: str

    :param language: Язык (подсветки в MAX нет — просто пометка)
    :type language: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '```{}\n{}```'.format(language, escape_markdown(content) if escape else content)


def hcode(content: str, escape: Optional[bool] = True) -> str:
    """
    Моноширинный текст в HTML: ``<code>текст</code>``.

    :param content: Код
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '<code>{}</code>'.format(escape_html(content) if escape else content)


def hpre(content: str, escape: Optional[bool] = True, language: str = "") -> str:
    """
    Преформатированный блок в HTML: ``<pre><code>…</code></pre>``.

    :param content: Код
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :param language: Язык (кладётся в class, как в telebot)
    :type language: str

    :return: Размеченная строка
    :rtype: str
    """
    return '<pre><code class="{}">{}</code></pre>'.format(language, escape_html(content) if escape else content)


def hide_link(url: str) -> str:
    """
    Невидимая ссылка (для превью картинки без текста ссылки) — как
    telebot.formatting.hide_link: слово-стык U+2060 внутри ``<a>``.

    :param url: Адрес картинки
    :type url: str

    :return: Размеченная строка
    :rtype: str
    """
    return f'<a href="{url}">&#8288;</a>'


def mcite(content: str, escape: Optional[bool] = True) -> str:
    """
    Цитата в маркдауне: каждая строка с ``>``.

    :param content: Текст цитаты
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    content = escape_markdown(content) if escape else content
    content = '\n'.join(['>' + line for line in content.split('\n')])
    return content


def hcite(content: str, escape: Optional[bool] = True) -> str:
    """
    Цитата в HTML: ``<blockquote>текст</blockquote>``.

    :param content: Текст цитаты
    :type content: str

    :param escape: Экранировать спецсимволы (по умолчанию — да)
    :type escape: bool

    :return: Размеченная строка
    :rtype: str
    """
    return '<blockquote>{}</blockquote>'.format(escape_html(content) if escape else content)

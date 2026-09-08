"""Клавиатуры: все типы кнопок через send_message(reply_markup=...)."""
from runner import step


@step(id="inline_keyboard", group="keyboards",
      title="InlineKeyboardMarkup — callback-кнопки",
      requires=("send_message",),
      eye="сообщение с двумя кнопками «Да [N]» и «Нет [N]» (жать будем"
          " в группе handlers)")
def s_inline(ctx):
    from maxibot.types import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(f"Да [{ctx.step_no}]", callback_data=f"smoke_yes_{ctx.run_id}"),
        InlineKeyboardButton(f"Нет [{ctx.step_no}]", callback_data=f"smoke_no_{ctx.run_id}"),
    )
    msg = ctx.bot.send_message(ctx.chat_id, ctx.tag("— кнопки"), reply_markup=markup)
    ctx.put("kb_mid", msg.message_id)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="quick_markup", group="keyboards",
      title="util.quick_markup — кнопка-ссылка",
      covers=("send_message",), requires=("send_message",),
      eye="сообщение с кнопкой «Открыть max.ru», тап открывает сайт")
def s_quick_markup(ctx):
    from maxibot.util import quick_markup
    markup = quick_markup({"Открыть max.ru": {"url": "https://max.ru"}})
    msg = ctx.bot.send_message(ctx.chat_id, ctx.tag("— кнопка-ссылка"),
                               reply_markup=markup)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="web_app_button", group="keyboards",
      title="InlineKeyboardButton(web_app=...)", requires=("send_message",),
      needs=("has_bot_username",),
      eye="кнопка «открыть приложение» видна (тап требует настроенного"
          " мини-приложения — просто посмотри, что кнопка есть)")
def s_web_app(ctx):
    from maxibot.types import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Мини-приложение",
                                    web_app=ctx.cfg["BOT_USERNAME"]))
    msg = ctx.bot.send_message(ctx.chat_id, ctx.tag("— web_app"), reply_markup=markup)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="reply_keyboard", group="keyboards",
      title="ReplyKeyboardMarkup", requires=("send_message",),
      eye="кнопки «Раз»/«Два» видны ПОД СООБЩЕНИЕМ (в MAX — не под полем"
          " ввода, это отличие от Telegram); тап отправляет текст в чат")
def s_reply_keyboard(ctx):
    from maxibot.types import ReplyKeyboardMarkup
    markup = ReplyKeyboardMarkup()
    markup.add("Раз", "Два")
    msg = ctx.bot.send_message(ctx.chat_id, ctx.tag("— reply-клавиатура"),
                               reply_markup=markup)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="request_buttons", group="keyboards",
      title="request_contact / request_location", requires=("send_message",),
      eye="две кнопки: «поделиться контактом» и «поделиться геопозицией»")
def s_request_buttons(ctx):
    from maxibot.types import KeyboardButton, ReplyKeyboardMarkup
    markup = ReplyKeyboardMarkup()
    markup.add(KeyboardButton("Контакт", request_contact=True),
               KeyboardButton("Гео", request_location=True))
    msg = ctx.bot.send_message(ctx.chat_id, ctx.tag("— request-кнопки"),
                               reply_markup=markup)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"

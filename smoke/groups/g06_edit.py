"""Правки и удаление: правим созданное, удаляем только своё мусорное."""
from runner import step


@step(id="edit_message_text", group="edit", title="edit_message_text",
      covers=("edit_message_text",), requires=("send_message",),
      eye="первое текстовое сообщение теперь гласит «отредактировано»")
def s_edit_text(ctx):
    new_text = ctx.tag("— отредактировано")
    ctx.bot.edit_message_text(new_text, ctx.chat_id, ctx.get("text_mid"))
    readback = ctx.bot.get_message(ctx.get("text_mid"))
    ctx.check(readback.text == new_text,
              f"round-trip: {readback.text!r} != {new_text!r}")
    return "текст сменился, round-trip совпал"


@step(id="edit_message_text_markup", group="edit",
      title="edit_message_text parse_mode", covers=("edit_message_text",),
      requires=("edit_message_text",),
      eye="то же сообщение теперь с жирной разметкой")
def s_edit_text_markup(ctx):
    ctx.bot.edit_message_text(ctx.tag("— **жирная правка**"), ctx.chat_id,
                              ctx.get("text_mid"), parse_mode="markdown")
    return "разметка применена"


@step(id="edit_message_caption", group="edit", title="edit_message_caption",
      covers=("edit_message_caption",), requires=("send_photo",),
      eye="подпись под фото-квадратом сменилась, ФОТО осталось тем же")
def s_edit_caption(ctx):
    msg = ctx.bot.edit_message_caption(ctx.tag("— новая подпись"),
                                       ctx.chat_id, ctx.get("photo_mid"))
    ctx.check(getattr(msg, "content_type", None) == "photo",
              f"content_type={getattr(msg, 'content_type', None)!r} — фото пропало?")
    return "подпись сменилась"


@step(id="edit_message_media", group="edit", title="edit_message_media",
      covers=("edit_message_media",), requires=("send_photo",), slow=True,
      eye="фото-квадрат ЗАМЕНИЛСЯ на квадрат другого цвета с другим номером")
def s_edit_media(ctx):
    from maxibot.types import InputMedia
    media = InputMedia("photo", ctx.assets.png(ctx.step_no),
                       caption=ctx.tag("— заменённое фото"))
    msg = ctx.bot.edit_message_media(media, ctx.chat_id, ctx.get("photo_mid"))
    ctx.check(getattr(msg, "content_type", None) == "photo",
              f"content_type={getattr(msg, 'content_type', None)!r}")
    return "медиа заменено"


@step(id="edit_message_reply_markup", group="edit",
      title="edit_message_reply_markup", covers=("edit_message_reply_markup",),
      requires=("inline_keyboard",),
      eye="на сообщении с кнопками клавиатура заменилась на ОДНУ кнопку"
          " «Новая кнопка»")
def s_edit_markup(ctx):
    from maxibot.types import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Новая кнопка",
                                    callback_data=f"smoke_new_{ctx.run_id}"))
    msg = ctx.bot.edit_message_reply_markup(ctx.chat_id, ctx.get("kb_mid"),
                                            reply_markup=markup)
    ctx.check(msg is not None, "ничего не вернул")
    return "клавиатура заменена"


@step(id="delete_message", group="edit", title="delete_message",
      covers=("delete_message",), requires=("send_message",),
      eye="сообщение «сейчас исчезну» появилось и тут же ИСЧЕЗЛО")
def s_delete(ctx):
    import time
    doomed = ctx.bot.send_message(ctx.chat_id, ctx.tag("— сейчас исчезну"))
    time.sleep(1.5)
    ctx.bot.delete_message(ctx.chat_id, doomed.message_id)
    return f"удалён mid={doomed.message_id}"


@step(id="delete_messages", group="edit", title="delete_messages — пачкой",
      covers=("delete_messages",), requires=("send_message",),
      eye="два сообщения «мусор 1/2» появились и исчезли оба")
def s_delete_many(ctx):
    import time
    first = ctx.bot.send_message(ctx.chat_id, ctx.tag("— мусор 1"))
    second = ctx.bot.send_message(ctx.chat_id, ctx.tag("— мусор 2"))
    time.sleep(1.5)
    result = ctx.bot.delete_messages(ctx.chat_id,
                                     [first.message_id, second.message_id])
    ctx.check(result is True, f"вернул {result!r}")
    return "оба удалены"

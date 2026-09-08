"""Текст: send_message во всех ипостасях, reply_to, get_message, action."""
from runner import step


@step(id="send_message", group="text", title="send_message — простой текст",
      covers=("send_message",), requires=("get_chat",),
      eye="в чате появился текст «smoke#… [N] send_message: живой текст»")
def s_send_message(ctx):
    msg = ctx.bot.send_message(ctx.chat_id, ctx.tag("— живой текст"))
    ctx.check(msg.content_type == "text", f"content_type={msg.content_type!r}")
    ctx.check(bool(msg.message_id), "нет message_id")
    ctx.check(str(msg.chat.id) == str(ctx.chat_id),
              f"chat.id={msg.chat.id!r} != {ctx.chat_id!r}")
    ctx.put("text_mid", msg.message_id)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_message_markdown", group="text",
      title="send_message parse_mode=markdown", requires=("send_message",),
      eye="жирный, курсив и моноширинный код отрисованы разметкой (не звёздочками)")
def s_markdown(ctx):
    msg = ctx.bot.send_message(
        ctx.chat_id, ctx.tag(": **жирный** _курсив_ `код`"),
        parse_mode="markdown")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_message_html", group="text",
      title="send_message parse_mode=html", requires=("send_message",),
      eye="то же самое разметкой через HTML-теги")
def s_html(ctx):
    msg = ctx.bot.send_message(
        ctx.chat_id, ctx.tag(": <b>жирный</b> <i>курсив</i> <code>код</code>"),
        parse_mode="html")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_message_notify", group="text",
      title="send_message notify=False", requires=("send_message",),
      eye="сообщение «без звука» пришло БЕЗ уведомления (проверка слабая: "
          "звук в клиенте может быть выключен вовсе)")
def s_notify(ctx):
    msg = ctx.bot.send_message(ctx.chat_id, ctx.tag("— без звука"), notify=False)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_message_preview", group="text",
      title="disable_web_page_preview", requires=("send_message",),
      eye="две ссылки на max.ru: у первой есть превью, у второй НЕТ")
def s_preview(ctx):
    with_preview = ctx.bot.send_message(
        ctx.chat_id, ctx.tag("с превью: https://max.ru"))
    without = ctx.bot.send_message(
        ctx.chat_id, ctx.tag("без превью: https://max.ru"),
        disable_web_page_preview=True)
    ctx.track_message(with_preview.message_id)
    ctx.track_message(without.message_id)
    return f"mid={with_preview.message_id}, {without.message_id}"


@step(id="send_message_reply", group="text",
      title="send_message reply_to_message_id", requires=("send_message",),
      covers=("send_message",),
      eye="ответ с цитатой первого текстового сообщения над ним")
def s_reply_param(ctx):
    msg = ctx.bot.send_message(ctx.chat_id, ctx.tag("— ответ цитатой"),
                               reply_to_message_id=ctx.get("text_mid"))
    ctx.check(msg.reply_to_message is not None, "msg.reply_to_message пуст")
    ctx.check(msg.reply_to_message.message_id == ctx.get("text_mid"),
              f"reply на {msg.reply_to_message.message_id!r},"
              f" ждали {ctx.get('text_mid')!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="reply_to", group="text", title="reply_to — обёртка ответа",
      covers=("reply_to",), requires=("send_message",),
      eye="ещё один ответ с цитатой")
def s_reply_to(ctx):
    original = ctx.bot.get_message(ctx.get("text_mid"))
    msg = ctx.bot.reply_to(original, ctx.tag("— через reply_to"))
    ctx.check(msg.reply_to_message is not None, "нет reply-связки")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="get_message", group="text", title="get_message — round-trip",
      covers=("get_message",), requires=("send_message",))
def s_get_message(ctx):
    msg = ctx.bot.get_message(ctx.get("text_mid"))
    ctx.check("живой текст" in (msg.text or ""),
              f"текст не совпал: {msg.text!r}")
    return "текст совпал с отправленным"


@step(id="send_chat_action", group="text", title="send_chat_action — «печатает…»",
      covers=("send_chat_action",), requires=("get_chat",),
      eye="в шапке чата ~6 секунд крутилось «печатает…»")
def s_chat_action(ctx):
    import time
    ctx.prepare("сейчас бот 6 секунд будет «печатать» — смотри на шапку чата")
    results = []
    for _ in range(3):
        results.append(ctx.bot.send_chat_action(ctx.chat_id, "typing"))
        time.sleep(2)
    ctx.check(all(results), f"send_chat_action вернул {results}")
    return "3 вызова typing по 2 c"


@step(id="text_length_limit", group="text", title="лимит 4000 символов",
      requires=("get_chat",))
def s_length_limit(ctx):
    try:
        ctx.bot.send_message(ctx.chat_id, "х" * 4100)
    except ValueError:
        return "ValueError, как задокументировано"
    ctx.check(False, "текст 4100 символов не отклонён ValueError")

"""Пересылка и копирование (mid в MAX глобален — хватает одного чата)."""
from runner import step


@step(id="forward_message", group="forward", title="forward_message",
      covers=("forward_message",), requires=("send_message",),
      eye="пересланное сообщение с плашкой «переслано» и автором")
def s_forward(ctx):
    msg = ctx.bot.forward_message(ctx.chat_id, ctx.chat_id, ctx.get("text_mid"))
    ctx.check(msg is not None and getattr(msg, "message_id", None),
              "не вернул Message")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="forward_message_second_chat", group="forward",
      title="forward_message — в другой чат", covers=("forward_message",),
      requires=("send_message",), needs=("has_second_chat",),
      eye="пересланное сообщение появилось во ВТОРОМ чате (SECOND_CHAT_ID)")
def s_forward_second(ctx):
    msg = ctx.bot.forward_message(ctx.cfg["SECOND_CHAT_ID"], ctx.chat_id,
                                  ctx.get("text_mid"))
    ctx.check(msg is not None, "не вернул Message")
    return f"mid={msg.message_id}"


@step(id="forward_messages", group="forward", title="forward_messages — пачкой",
      covers=("forward_messages",), requires=("send_message", "send_photo"),
      eye="две пересылки подряд (текст и фото)")
def s_forward_many(ctx):
    result = ctx.bot.forward_messages(
        ctx.chat_id, ctx.chat_id, [ctx.get("text_mid"), ctx.get("photo_mid")])
    ctx.check(isinstance(result, list) and len(result) == 2,
              f"вернул {type(result).__name__} длины {len(result) if isinstance(result, list) else '—'}")
    return f"переслано: {len(result)}"


@step(id="copy_message", group="forward", title="copy_message",
      covers=("copy_message",), requires=("send_message",),
      eye="копия текста БЕЗ плашки «переслано»")
def s_copy(ctx):
    result = ctx.bot.copy_message(ctx.chat_id, ctx.chat_id, ctx.get("text_mid"))
    ctx.check(result is not None and getattr(result, "message_id", None),
              "не вернул MessageID")
    ctx.track_message(result.message_id)
    return f"mid={result.message_id}"


@step(id="copy_message_caption", group="forward",
      title="copy_message фото с новой подписью", covers=("copy_message",),
      requires=("send_photo",),
      eye="копия фото-квадрата с подписью «копия с новой подписью»")
def s_copy_caption(ctx):
    result = ctx.bot.copy_message(ctx.chat_id, ctx.chat_id, ctx.get("photo_mid"),
                                  caption=ctx.tag("— копия с новой подписью"))
    ctx.check(result is not None, "не вернул MessageID")
    ctx.track_message(result.message_id)
    return f"mid={result.message_id}"


@step(id="copy_messages", group="forward",
      title="copy_messages remove_caption", covers=("copy_messages",),
      requires=("send_message", "send_photo"),
      eye="копия фото БЕЗ подписи и копия текста С текстом")
def s_copy_many(ctx):
    result = ctx.bot.copy_messages(ctx.chat_id, ctx.chat_id,
                                   [ctx.get("photo_mid"), ctx.get("text_mid")],
                                   remove_caption=True)
    ctx.check(isinstance(result, list) and len(result) == 2,
              f"вернул {result!r}")
    return f"скопировано: {len(result)}"

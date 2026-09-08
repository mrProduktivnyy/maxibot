"""Закрепы: в MAX закреп ОДИН на чат — новый вытесняет старый."""
from runner import step


@step(id="pin_chat_message", group="pins", title="pin_chat_message",
      covers=("pin_chat_message", "get_pinned_message"),
      requires=("send_message",), needs=("bot_is_admin", "is_group"),
      eye="вверху чата появилась плашка закрепа с первым текстовым сообщением")
def s_pin(ctx):
    result = ctx.bot.pin_chat_message(ctx.chat_id, ctx.get("text_mid"))
    ctx.check(result is True, f"вернул {result!r}")
    pinned = ctx.bot.get_pinned_message(ctx.chat_id)
    ctx.check(pinned is not None and pinned.message_id == ctx.get("text_mid"),
              f"get_pinned_message: {getattr(pinned, 'message_id', None)!r}")
    return "закреплено, round-trip совпал"


@step(id="pin_displaces", group="pins", title="второй закреп вытесняет первый",
      covers=("pin_chat_message",), requires=("pin_chat_message", "send_photo"),
      eye="в плашке закрепа теперь ФОТО (старый закреп вытеснен —"
          " особенность MAX: закреп один)")
def s_pin_displace(ctx):
    result = ctx.bot.pin_chat_message(ctx.chat_id, ctx.get("photo_mid"))
    ctx.check(result is True, f"вернул {result!r}")
    pinned = ctx.bot.get_pinned_message(ctx.chat_id)
    ctx.check(pinned is not None and pinned.message_id == ctx.get("photo_mid"),
              "закреп не вытеснился")
    return "вытеснен"


@step(id="unpin_foreign", group="pins",
      title="unpin_chat_message чужого mid — False",
      covers=("unpin_chat_message",), requires=("pin_displaces",))
def s_unpin_foreign(ctx):
    result = ctx.bot.unpin_chat_message(ctx.chat_id, ctx.get("text_mid"))
    ctx.check(result is False, f"вернул {result!r}, ждали False")
    pinned = ctx.bot.get_pinned_message(ctx.chat_id)
    ctx.check(pinned is not None, "закреп пропал, хотя снимали чужой mid")
    return "False, закреп на месте"


@step(id="unpin_chat_message", group="pins", title="unpin_chat_message",
      covers=("unpin_chat_message",), requires=("pin_displaces",),
      eye="плашка закрепа ИСЧЕЗЛА")
def s_unpin(ctx):
    result = ctx.bot.unpin_chat_message(ctx.chat_id)
    ctx.check(result is True, f"вернул {result!r}")
    pinned = ctx.bot.get_pinned_message(ctx.chat_id)
    ctx.check(pinned is None, "get_pinned_message не пуст после снятия")
    return "снято"


@step(id="unpin_all_chat_messages", group="pins",
      title="unpin_all_chat_messages на пустом закрепе",
      covers=("unpin_all_chat_messages",), requires=("unpin_chat_message",))
def s_unpin_all(ctx):
    ctx.bot.unpin_all_chat_messages(ctx.chat_id)
    return "не упал на пустом закрепе"

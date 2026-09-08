"""Гео и контакты: локация, live-переезд, контакт, venue."""
from runner import step


@step(id="send_location", group="geo", title="send_location — пин на карте",
      covers=("send_location",), requires=("get_chat",),
      eye="пин на карте в районе Москвы")
def s_send_location(ctx):
    msg = ctx.bot.send_location(ctx.chat_id, 55.7558, 37.6173)
    ctx.check(msg.content_type == "location", f"content_type={msg.content_type!r}")
    ctx.put("loc_mid", msg.message_id)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_location_live", group="geo",
      title="send_location live_period — предупреждение",
      covers=("send_location",), requires=("send_location",))
def s_live_period(ctx):
    msg = ctx.bot.send_location(ctx.chat_id, 55.7558, 37.6173, live_period=60)
    ctx.check(any("live" in line.lower() for line in ctx.logs()),
              "нет предупреждения про live-локации")
    ctx.track_message(msg.message_id)
    return "предупреждение в логе есть, пин отправлен обычным"


@step(id="send_contact", group="geo", title="send_contact — карточка",
      covers=("send_contact",), requires=("get_chat",),
      eye="карточка контакта «Смоук Тестовый» с телефоном")
def s_send_contact(ctx):
    msg = ctx.bot.send_contact(ctx.chat_id, "+79990000000", "Смоук",
                               last_name="Тестовый")
    ctx.check(msg.content_type == "contact", f"content_type={msg.content_type!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_venue", group="geo", title="send_venue — пин + текст",
      covers=("send_venue",), requires=("get_chat",),
      eye="пин и рядом текст «Красная площадь / Москва» (venue в MAX"
          " деградирует в локацию с подписью)")
def s_send_venue(ctx):
    msg = ctx.bot.send_venue(ctx.chat_id, 55.7539, 37.6208,
                             "Красная площадь", "Москва, Россия")
    ctx.check(msg.content_type == "location", f"content_type={msg.content_type!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="edit_message_live_location", group="geo",
      title="edit_message_live_location — пин переехал",
      covers=("edit_message_live_location",), requires=("send_location",),
      eye="пин из шага send_location ПЕРЕЕХАЛ в Санкт-Петербург")
def s_edit_live(ctx):
    msg = ctx.bot.edit_message_live_location(
        59.9386, 30.3141, chat_id=ctx.chat_id, message_id=ctx.get("loc_mid"))
    ctx.check(msg is not None, "ничего не вернул")
    return "пин переехал"


@step(id="stop_message_live_location", group="geo",
      title="stop_message_live_location", covers=("stop_message_live_location",),
      requires=("edit_message_live_location",),
      eye="пин остался на месте (Питер), сообщение не сломалось")
def s_stop_live(ctx):
    msg = ctx.bot.stop_message_live_location(
        chat_id=ctx.chat_id, message_id=ctx.get("loc_mid"))
    ctx.check(msg is not None, "ничего не вернул")
    return "остановлено"

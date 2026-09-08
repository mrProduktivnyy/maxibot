"""Настройки чата (mutate, с восстановлением) + MAX-бонусы: история и список
чатов (безопасные, читающие)."""
from runner import step


@step(id="get_chat_history", group="chat", title="get_chat_history — MAX-бонус",
      covers=("get_chat_history",), requires=("send_message",))
def s_history(ctx):
    history = ctx.bot.get_chat_history(ctx.chat_id, count=10)
    ctx.check(isinstance(history, list) and history, "история пуста")
    ctx.check(history[0].date is not None, "у сообщений нет date")
    if len(history) > 1 and history[0].date and history[1].date:
        ctx.check(history[0].date >= history[1].date,
                  "порядок не «свежие первыми»")
    texts = [m.text or "" for m in history]
    ctx.check(any(f"smoke#{ctx.run_id}" in t for t in texts),
              "в истории не нашлось сообщений этого прогона")
    return f"сообщений: {len(history)}, свежие первыми"


@step(id="get_messages", group="chat", title="get_messages по списку id",
      covers=("get_messages",), requires=("send_message",))
def s_get_messages(ctx):
    messages = ctx.bot.get_messages([ctx.get("text_mid")])
    ctx.check(len(messages) == 1, f"вернул {len(messages)} сообщений")
    ctx.check(messages[0].message_id == ctx.get("text_mid"), "mid не совпал")
    return "выборка по id совпала"


@step(id="get_chats", group="chat", title="get_chats — список чатов бота",
      covers=("get_chats",), requires=("get_chat",))
def s_get_chats(ctx):
    page = ctx.bot.get_chats(count=50)
    ctx.check(len(page) >= 1, "список чатов пуст")
    ids = [str(chat.id) for chat in page]
    ctx.check(str(ctx.chat_id) in ids or page.marker is not None,
              "тестового чата нет на первой странице и страниц больше нет")
    return f"чатов на странице: {len(page)}, marker={page.marker}"


@step(id="iter_chats", group="chat", title="iter_chats — автопагинация",
      covers=("iter_chats",), requires=("get_chats",))
def s_iter_chats(ctx):
    seen = 0
    for _chat in ctx.bot.iter_chats(count=50):
        seen += 1
        if seen > 500:
            break
    ctx.check(seen >= 1, "генератор не выдал ни одного чата")
    return f"обошли чатов: {seen}"


@step(id="set_chat_title", group="chat", title="set_chat_title + восстановление",
      covers=("set_chat_title",), requires=("get_chat",),
      needs=("bot_is_admin", "is_group"), danger="mutate",
      eye="название чата сменилось на «smoke#…» и ВЕРНУЛОСЬ обратно"
          " (в чате два системных сообщения)")
def s_set_title(ctx):
    original = ctx.get("chat_title")
    ctx.require(original, "не знаем исходного названия — не рискуем")
    try:
        result = ctx.bot.set_chat_title(ctx.chat_id, f"smoke#{ctx.run_id}")
        ctx.check(result is True, f"вернул {result!r}")
        renamed = ctx.bot.get_chat(ctx.chat_id)
        ctx.check(renamed.title == f"smoke#{ctx.run_id}",
                  f"get_chat().title={renamed.title!r}")
    finally:
        ctx.bot.set_chat_title(ctx.chat_id, original)
        ctx.restored.append("название чата")
    return "сменили и вернули"


@step(id="set_chat_description", group="chat",
      title="set_chat_description + восстановление",
      covers=("set_chat_description",), requires=("get_chat",),
      needs=("bot_is_admin", "is_group"), danger="mutate")
def s_set_description(ctx):
    original = ctx.get("chat_description")
    try:
        result = ctx.bot.set_chat_description(ctx.chat_id,
                                              f"смоук-прогон {ctx.run_id}")
        ctx.check(result is True, f"вернул {result!r}")
        changed = ctx.bot.get_chat(ctx.chat_id)
        ctx.check(changed.description == f"смоук-прогон {ctx.run_id}",
                  f"описание не применилось: {changed.description!r}")
    finally:
        ctx.bot.set_chat_description(ctx.chat_id, original)
        ctx.restored.append("описание чата")
    return "сменили и вернули"


@step(id="set_chat_photo", group="chat", title="set_chat_photo + восстановление",
      covers=("set_chat_photo", "delete_chat_photo"), requires=("get_chat",),
      needs=("bot_is_admin", "is_group"), danger="mutate", slow=True,
      eye="иконка чата сменилась на цветной квадрат и вернулась (или"
          " исчезла, если старой не было)")
def s_set_photo(ctx):
    old_url = ctx.get("chat_photo_url")
    if not old_url:
        ctx.require(
            ctx.ask("у чата НЕТ иконки — после проверки вернуть будет нечем,"
                    " иконку снимем. Продолжаем?"),
            "человек отказался (нет старой иконки)")
    try:
        result = ctx.bot.set_chat_photo(ctx.chat_id, ctx.assets.png(ctx.step_no))
        ctx.check(result is True, f"вернул {result!r}")
    finally:
        if old_url:
            ctx.bot.set_chat_photo(ctx.chat_id, old_url)
            ctx.restored.append("иконка чата")
        else:
            ctx.bot.delete_chat_photo(ctx.chat_id)
            ctx.restored.append("иконка чата (снята — старой не было)")
    return "сменили и вернули"


@step(id="get_chat_members_count_alias", group="chat",
      title="get_chat_members_count — deprecated-алиас",
      covers=("get_chat_members_count",), requires=("get_chat_member_count",))
def s_members_count_alias(ctx):
    count = ctx.bot.get_chat_members_count(ctx.chat_id)
    ctx.check(isinstance(count, int) and count >= 1, f"вернул {count!r}")
    ctx.check(any("устарел" in line or "deprecated" in line.lower()
                  for line in ctx.logs()),
              "нет предупреждения об устаревании")
    return f"{count} + предупреждение в логе"

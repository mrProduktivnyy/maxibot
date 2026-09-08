"""Профиль бота: команды, имя, описание, аватар. Всё с восстановлением."""
from runner import step


@step(id="my_commands_cycle", group="profile",
      title="set/get/delete_my_commands — цикл с восстановлением",
      covers=("get_my_commands", "set_my_commands", "delete_my_commands"),
      requires=("get_me",), danger="mutate",
      eye="в меню бота появились команды /smoke и /ping (клиент может"
          " обновить меню не мгновенно)")
def s_commands(ctx):
    from maxibot.types import BotCommand
    original = ctx.bot.get_my_commands()
    try:
        result = ctx.bot.set_my_commands([
            BotCommand("smoke", "смоук-прогон"),
            BotCommand("ping", "проверка связи"),
        ])
        ctx.check(result is True, f"set вернул {result!r}")
        readback = ctx.bot.get_my_commands()
        names = sorted(c.command for c in readback)
        ctx.check(names == ["ping", "smoke"], f"round-trip: {names}")
        ctx.check(ctx.bot.delete_my_commands() is True, "delete не True")
        ctx.check(ctx.bot.get_my_commands() == [], "после delete список не пуст")
    finally:
        if original:
            ctx.bot.set_my_commands(original)
        ctx.restored.append("команды бота")
    return "set -> get -> delete -> восстановление"


@step(id="my_name_cycle", group="profile",
      title="get/set_my_name + восстановление",
      covers=("get_my_name", "set_my_name"), requires=("get_me",),
      danger="mutate",
      eye="имя бота в шапке чата сменилось на «… (smoke)» и вернулось"
          " (имя публичное!)")
def s_my_name(ctx):
    original = ctx.bot.get_my_name()
    name = getattr(original, "name", None) or ctx.get("bot_name")
    ctx.require(name, "не знаем исходного имени")
    try:
        result = ctx.bot.set_my_name(f"{name} (smoke)"[:64])
        ctx.check(result is True, f"вернул {result!r}")
        changed = ctx.bot.get_my_name()
        ctx.check("(smoke)" in (getattr(changed, "name", "") or ""),
                  f"имя не применилось: {getattr(changed, 'name', None)!r}")
    finally:
        ctx.bot.set_my_name(name)
        ctx.restored.append("имя бота")
    return "сменили и вернули"


@step(id="my_description_cycle", group="profile",
      title="get/set_my_description + восстановление",
      covers=("get_my_description", "set_my_description"),
      requires=("get_me",), danger="mutate")
def s_my_description(ctx):
    original = ctx.bot.get_my_description()
    original_text = getattr(original, "description", None)
    try:
        result = ctx.bot.set_my_description(f"смоук {ctx.run_id}")
        ctx.check(result is True, f"вернул {result!r}")
        changed = ctx.bot.get_my_description()
        ctx.check(getattr(changed, "description", None) == f"смоук {ctx.run_id}",
                  "описание не применилось")
    finally:
        ctx.bot.set_my_description(original_text)
        ctx.restored.append("описание бота")
    return "сменили и вернули"


@step(id="short_description", group="profile",
      title="get/set_my_short_description",
      covers=("get_my_short_description", "set_my_short_description"),
      requires=("get_me",))
def s_short_description(ctx):
    short = ctx.bot.get_my_short_description()
    long_desc = ctx.bot.get_my_description()
    result = ctx.bot.set_my_short_description(f"короткое {ctx.run_id}")
    after = ctx.bot.get_my_description()
    ctx.check(getattr(after, "description", None)
              == getattr(long_desc, "description", None),
              "set_my_short_description ЗАТЁР длинное описание!")
    return (f"short={getattr(short, 'short_description', None)!r},"
            f" set вернул {result!r}, длинное описание не тронуто")


@step(id="set_my_photo", group="profile",
      title="set_my_photo + восстановление",
      covers=("set_my_photo",), requires=("get_me",), danger="mutate",
      slow=True,
      eye="аватар бота сменился на цветной квадрат и вернулся"
          " (аватар публичный!)")
def s_my_photo(ctx):
    old_url = ctx.get("bot_avatar_url")
    if not old_url:
        ctx.require(
            ctx.ask("у бота НЕТ аватара — вернуть будет нечем. Продолжаем?"),
            "человек отказался (нет старого аватара)")
    try:
        result = ctx.bot.set_my_photo(ctx.assets.png(ctx.step_no))
        ctx.check(result is True, f"вернул {result!r}")
    finally:
        if old_url:
            ctx.bot.set_my_photo(old_url)
            ctx.restored.append("аватар бота")
    return "сменили и вернули"

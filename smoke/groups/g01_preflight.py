"""Preflight: связь, чат, условия. Гейт — без него прогон не имеет смысла."""
from runner import step


@step(id="get_me", group="preflight", title="get_me — бот отвечает",
      covers=("get_me",))
def s_get_me(ctx):
    me = ctx.bot.get_me()
    ctx.check(isinstance(me, dict) and me.get("user_id"),
              f"get_me вернул {type(me).__name__} без user_id — токен?")
    ctx.put("bot_user_id", me.get("user_id"))
    ctx.put("bot_name", me.get("first_name") or me.get("name"))
    ctx.put("bot_avatar_url", me.get("avatar_url"))
    return f"бот «{ctx.get('bot_name')}», id {me.get('user_id')}"


@step(id="get_chat", group="preflight", title="get_chat — чат доступен",
      covers=("get_chat",), requires=("get_me",))
def s_get_chat(ctx):
    chat = ctx.bot.get_chat(ctx.chat_id)
    ctx.check(chat.type in ("private", "group", "channel"),
              f"chat.type={chat.type!r} — ждали private/group/channel")
    ctx.set_condition("is_group", chat.type == "group")
    if chat.type != "group":
        print("        [ВНИМАНИЕ] это не группа: закрепы, участники и"
              " настройки чата уйдут в SKIP")
    ctx.put("chat_title", chat.title)
    ctx.put("chat_description", chat.description)
    ctx.put("chat_photo_url", chat.photo)
    return f"«{chat.title}» ({chat.max_type}, id {chat.id})"


@step(id="get_chat_member_count", group="preflight",
      title="get_chat_member_count", covers=("get_chat_member_count",),
      requires=("get_chat",))
def s_member_count(ctx):
    count = ctx.bot.get_chat_member_count(ctx.chat_id)
    ctx.check(isinstance(count, int) and count >= 1, f"вернул {count!r}")
    return f"участников: {count}"


@step(id="get_chat_membership", group="preflight",
      title="get_chat_membership — бот админ?",
      covers=("get_chat_membership",), requires=("get_chat",))
def s_membership(ctx):
    member = ctx.bot.get_chat_membership(ctx.chat_id)
    is_admin = bool(getattr(member, "is_admin", False)
                    or getattr(member, "is_owner", False))
    ctx.set_condition("bot_is_admin", is_admin)
    if not is_admin:
        print("        [ВНИМАНИЕ] бот НЕ админ — закрепы/участники/настройки"
              " чата уйдут в SKIP")
    return f"status={member.status}, admin={is_admin}"


@step(id="export_chat_invite_link", group="preflight",
      title="export_chat_invite_link", covers=("export_chat_invite_link",),
      requires=("get_chat",))
def s_invite_link(ctx):
    link = ctx.bot.export_chat_invite_link(ctx.chat_id)
    ctx.check(link is None or isinstance(link, str), f"вернул {type(link).__name__}")
    return f"ссылка: {link or '(нет — у приватного чата это норма)'}"


@step(id="conditions", group="preflight", title="условия конфига",
      requires=("get_me",))
def s_conditions(ctx):
    cfg = ctx.cfg
    ctx.set_condition("has_peer", bool(cfg["PEER_USER_ID"]))
    ctx.set_condition("has_sticker", bool(cfg["STICKER_CODE"]))
    ctx.set_condition("has_channel", bool(cfg["CHANNEL_ID"]))
    ctx.set_condition("has_webhook_url", bool(cfg["WEBHOOK_URL"]))
    ctx.set_condition("has_second_chat", bool(cfg["SECOND_CHAT_ID"]))
    ctx.set_condition("has_bot_username", bool(cfg["BOT_USERNAME"]))
    ctx.set_condition("has_add_user", bool(cfg["ADD_USER_ID"]))
    ctx.set_condition("has_leave_chat", bool(cfg["LEAVE_CHAT_ID"])
                      and cfg["LEAVE_CHAT_ID"] != cfg["CHAT_ID"])
    empty = [name for name, cond in (
        ("PEER_USER_ID", "has_peer"), ("STICKER_CODE", "has_sticker"),
        ("CHANNEL_ID", "has_channel"), ("WEBHOOK_URL", "has_webhook_url"),
    ) if not ctx.conditions.get(cond)]
    return ("не заданы: " + ", ".join(empty) + " — зависимые шаги в SKIP"
            if empty else "все условия конфига заданы")

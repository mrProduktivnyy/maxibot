"""Участники и админы. Опасное — за флагами и словами-подтверждениями."""
from runner import step


@step(id="get_chat_administrators", group="members",
      title="get_chat_administrators", covers=("get_chat_administrators",),
      requires=("get_chat",), needs=("bot_is_admin", "is_group"))
def s_admins(ctx):
    admins = ctx.bot.get_chat_administrators(ctx.chat_id)
    ctx.check(isinstance(admins, list) and admins, "список админов пуст")
    statuses = {getattr(a, "status", None) for a in admins}
    ctx.check("creator" in statuses, f"нет владельца: {statuses}")
    return f"админов: {len(admins)}"


@step(id="get_chat_member", group="members", title="get_chat_member",
      covers=("get_chat_member",), requires=("get_chat",),
      needs=("is_group", "has_peer"))
def s_get_member(ctx):
    member = ctx.bot.get_chat_member(ctx.chat_id, ctx.cfg["PEER_USER_ID"])
    ctx.check(member.status in ("creator", "administrator", "member"),
              f"status={member.status!r}")
    ctx.check(member.user is not None
              and member.user.id == ctx.cfg["PEER_USER_ID"],
              "user.id не совпал с PEER_USER_ID")
    return f"status={member.status}"


@step(id="get_chat_member_missing", group="members",
      title="get_chat_member несуществующего — left",
      covers=("get_chat_member",), requires=("get_chat",), needs=("is_group",))
def s_get_member_missing(ctx):
    member = ctx.bot.get_chat_member(ctx.chat_id, 999999999999)
    ctx.check(getattr(member, "status", None) == "left",
              f"status={getattr(member, 'status', None)!r}, ждали 'left'")
    ctx.check(getattr(member, "is_member", None) is False, "is_member не False")
    return "заглушка left"


@step(id="add_chat_members", group="members", title="add_chat_members",
      covers=("add_chat_members",), requires=("get_chat",),
      needs=("bot_is_admin", "is_group", "has_add_user"), danger="mutate",
      eye="в чате появился участник, которого добавил бот")
def s_add_members(ctx):
    result = ctx.bot.add_chat_members(ctx.chat_id, [ctx.cfg["ADD_USER_ID"]])
    ctx.check(result is True, f"вернул {result!r}")
    return "добавлен"


@step(id="promote_chat_member", group="members",
      title="promote_chat_member + разжалование",
      covers=("promote_chat_member",), requires=("get_chat_member",),
      needs=("bot_is_admin", "is_group", "has_peer"), danger="destructive",
      eye="участник стал админом (системное сообщение) и потом разжалован")
def s_promote(ctx):
    word = input("        Назначаем и снимаем админку PEER_USER_ID="
                 f"{ctx.cfg['PEER_USER_ID']}. Введи слово АДМИН для"
                 " продолжения: ").strip()
    ctx.require(word == "АДМИН", "не подтверждено словом")
    promoted = ctx.bot.promote_chat_member(ctx.chat_id, ctx.cfg["PEER_USER_ID"],
                                           can_pin_messages=True)
    ctx.check(promoted is True, f"promote вернул {promoted!r}")
    try:
        member = ctx.bot.get_chat_member(ctx.chat_id, ctx.cfg["PEER_USER_ID"])
        ctx.check(member.status == "administrator",
                  f"после promote status={member.status!r}")
    finally:
        demoted = ctx.bot.promote_chat_member(ctx.chat_id, ctx.cfg["PEER_USER_ID"])
        ctx.restored.append("права участника (разжалован обратно)")
        ctx.check(demoted is True, f"разжалование вернуло {demoted!r}")
    return "назначили и разжаловали"


@step(id="promote_anonymous_warn", group="members",
      title="promote(is_anonymous) — предупреждение без API",
      covers=("promote_chat_member",), requires=("get_chat",),
      needs=("is_group", "has_peer"))
def s_promote_anon(ctx):
    result = ctx.bot.promote_chat_member(ctx.chat_id, ctx.cfg["PEER_USER_ID"],
                                         is_anonymous=True)
    ctx.check(result is False, f"вернул {result!r}, ждали False без вызова API")
    ctx.check(bool(ctx.logs()), "нет предупреждения в логе")
    return "False + предупреждение"


@step(id="ban_chat_member", group="members",
      title="ban_chat_member — НЕОБРАТИМО",
      covers=("ban_chat_member",), requires=("get_chat",),
      needs=("bot_is_admin", "is_group"), danger="destructive",
      eye="забаненный пропал из участников (вернуть его через API НЕЛЬЗЯ)")
def s_ban(ctx):
    raw = input("        РАЗБАНА В API MAX НЕТ. Введи user_id одноразового"
                " аккаунта-жертвы (пусто — пропустить): ").strip()
    ctx.require(raw.isdigit(), "жертва не указана")
    word = input(f"        Баним user_id={raw} НАВСЕГДА. Введи слово БАН: ").strip()
    ctx.require(word == "БАН", "не подтверждено словом")
    result = ctx.bot.ban_chat_member(ctx.chat_id, int(raw))
    ctx.check(result is True, f"вернул {result!r}")
    return f"забанен {raw}"


@step(id="remove_chat_member", group="members",
      title="api.remove_chat_member — мягкое удаление",
      requires=("get_chat",),
      needs=("bot_is_admin", "is_group"), danger="destructive",
      eye="участник удалён из чата (сможет вернуться сам)")
def s_remove_member(ctx):
    raw = input("        Мягкое удаление (человек сможет вернуться). Введи"
                " user_id (пусто — пропустить): ").strip()
    ctx.require(raw.isdigit(), "участник не указан")
    ctx.bot.api.remove_chat_member(ctx.chat_id, int(raw))
    return f"удалён {raw}"

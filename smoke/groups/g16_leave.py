"""leave_chat — самым последним шагом прогона, только в одноразовом чате."""
from runner import step


@step(id="leave_chat", group="leave", title="leave_chat — бот выходит",
      covers=("leave_chat",), requires=("get_me",),
      needs=("has_leave_chat",), danger="destructive",
      eye="бот пропал из списка участников ОДНОРАЗОВОГО чата (LEAVE_CHAT_ID)")
def s_leave(ctx):
    target = ctx.cfg["LEAVE_CHAT_ID"]
    ctx.require(target != ctx.chat_id,
                "LEAVE_CHAT_ID совпал с CHAT_ID — так нельзя")
    word = input(f"        Бот ВЫЙДЕТ из чата {target}. Введи слово ВЫХОД: ").strip()
    ctx.require(word == "ВЫХОД", "не подтверждено словом")
    ctx.bot.leave_chat(target)
    return f"вышел из {target}"

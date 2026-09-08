"""Заглушки и невозможное в MAX: предсказуемое падение — это OK.
Все шаги авто и безопасны (сеть не трогают)."""
from runner import step


@step(id="stub_actions", group="stubs",
      title="невозможные действия — NotImplementedError с причиной",
      covers=("send_poll", "send_dice", "send_invoice", "create_forum_topic",
              "set_message_reaction", "unban_chat_member",
              "answer_inline_query", "log_out"),
      requires=("get_me",))
def s_stub_actions(ctx):
    cases = {
        "send_poll": ("опрос",), "send_dice": (), "send_invoice": (),
        "create_forum_topic": ("тема",), "set_message_reaction": (),
        "unban_chat_member": (ctx.chat_id, 1),
        "answer_inline_query": ("id", []), "log_out": (),
    }
    for name, args in cases.items():
        try:
            getattr(ctx.bot, name)(*args)
            ctx.check(False, f"{name} не бросил NotImplementedError")
        except NotImplementedError as error:
            ctx.check("MAX" in str(error) or "разбан" in str(error).lower(),
                      f"{name}: текст без причины: {error}")
        except Exception as error:  # noqa: BLE001
            ctx.check(False, f"{name}: {type(error).__name__} вместо"
                             f" NotImplementedError")
    return f"проверено действий: {len(cases)}"


@step(id="stub_handlers", group="stubs",
      title="обработчики несуществующих событий — warn, бот жив",
      covers=("poll_handler", "inline_handler", "chat_boost_handler",
              "register_poll_handler"),
      requires=("get_me",))
def s_stub_handlers(ctx):
    @ctx.bot.poll_handler(func=lambda p: True)
    def on_poll(poll):
        pass

    @ctx.bot.inline_handler(func=lambda q: True)
    def on_inline(query):
        pass

    ctx.bot.register_poll_handler(lambda p: None, func=None)
    ctx.bot.chat_boost_handler()(lambda b: None)
    warnings = ctx.logs()
    ctx.check(len(warnings) >= 4, f"предупреждений {len(warnings)}, ждали >= 4")
    ctx.check(any("никогда не будет вызван" in w or "не сработают" in w
                  for w in warnings), "нет текста про «никогда не будет вызван»")
    return f"регистраций: 4, предупреждений: {len(warnings)}"


@step(id="stub_sticker_inputs", group="stubs",
      title="send_sticker(bytes/URL) — ValueError",
      covers=("send_sticker",), requires=("get_me",))
def s_stub_sticker(ctx):
    for bad in (b"\x89PNG...", "https://example.com/sticker.png"):
        try:
            ctx.bot.send_sticker(ctx.chat_id, bad)
            ctx.check(False, f"send_sticker({type(bad).__name__}) не бросил")
        except ValueError:
            pass
    return "оба ValueError"


@step(id="stub_media_urls", group="stubs",
      title="send_video/video_note/audio по URL — ValueError",
      covers=("send_video", "send_video_note", "send_audio"),
      requires=("get_me",))
def s_stub_media_urls(ctx):
    for name in ("send_video", "send_video_note", "send_audio"):
        try:
            getattr(ctx.bot, name)(ctx.chat_id, "https://example.com/f.mp4")
            ctx.check(False, f"{name}(URL) не бросил ValueError")
        except ValueError:
            pass
    return "URL для не-картинок отклоняются"


@step(id="stub_warn_content_types", group="stubs",
      title="content_types voice/animation — предупреждение",
      requires=("get_me",))
def s_stub_content_types(ctx):
    @ctx.bot.message_handler(content_types=["voice"])
    def on_voice(message):
        pass

    ctx.check(any("voice" in w for w in ctx.logs()),
              "нет предупреждения про voice")
    return "предупреждение о непорождаемом типе есть"


@step(id="stub_positional_error", group="stubs",
      title="MaxiBot(token, True) — TypeError о порядке",
      requires=("get_me",))
def s_stub_positional(ctx):
    import maxibot
    try:
        maxibot.MaxiBot(ctx.cfg["TOKEN"], True)
        ctx.check(False, "MaxiBot(token, True) не бросил TypeError")
    except TypeError:
        pass
    return "TypeError, как задокументировано"


@step(id="stub_not_implemented_yet", group="stubs",
      title="get_user_profile_photos/restrict — «пока не реализован»",
      requires=("get_me",))
def s_stub_not_yet(ctx):
    for name in ("get_user_profile_photos", "restrict_chat_member"):
        try:
            getattr(ctx.bot, name)(1, 2)
            ctx.check(False, f"{name} не бросил")
        except NotImplementedError as error:
            ctx.check("пока не реализован" in str(error),
                      f"{name}: нет пометки «пока не реализован»")
    return "оба честно «пока не реализован»"

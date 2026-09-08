"""
Обработчики и поллинг: отдельный экземпляр бота, человек пишет боту.
Таймаут ожидания -> SKIP (человек мог отойти), не FAIL.
"""
import threading
import time

from runner import step

EVENTS = []          # события из обработчиков (append атомарен под GIL)
BOT2 = {}            # bot2 и поток между шагами группы


def _events(kind):
    return [e for e in EVENTS if e["kind"] == kind]


def _mine(ctx, message):
    """Сообщение самого смоука? (бот может получать и свои отправки)"""
    real_id = getattr(getattr(message, "from_user", None), "real_id", None)
    return real_id == ctx.get("bot_user_id")


@step(id="polling_start", group="handlers",
      title="polling — поднимаем приёмник", covers=("polling", "message_handler",
      "callback_query_handler", "edited_message_handler", "comment_handler",
      "channel_post_handler", "answer_callback_query"),
      requires=("get_me",))
def s_polling_start(ctx):
    import maxibot
    from maxibot import apihelper

    apihelper.ENABLE_MIDDLEWARE = True
    bot2 = maxibot.MaxiBot(ctx.cfg["TOKEN"], skip_pending=True, threaded=True)

    class SmokeExceptionHandler(maxibot.ExceptionHandler):
        def handle(self, exception):
            EVENTS.append({"kind": "exception", "error": repr(exception)})
            return True

    bot2.exception_handler = SmokeExceptionHandler()

    @bot2.middleware_handler(update_types=["message_created"])
    def mw_typed(bot_instance, update):
        if update.message is not None:
            update.message.smoke_mw = True

    @bot2.middleware_handler()
    def mw_default(bot_instance, update):
        EVENTS.append({"kind": "mw_update", "type": update.update_type})

    @bot2.message_handler(commands=["smoke"])
    def on_command(message):
        EVENTS.append({"kind": "command", "text": message.text})

    @bot2.message_handler(regexp=r"смоук-\d+")
    def on_regexp(message):
        EVENTS.append({"kind": "regexp", "text": message.text})

    @bot2.message_handler(content_types=["photo"])
    def on_photo(message):
        token = message.photo[-1].file_id if message.photo else None
        EVENTS.append({"kind": "photo", "token": token})

    @bot2.message_handler(content_types=["sticker"])
    def on_sticker(message):
        code = None
        try:
            attachments = message.json["message"]["body"]["attachments"]
            code = attachments[0]["payload"]["code"]
        except Exception:
            pass
        EVENTS.append({"kind": "sticker", "code": code})

    @bot2.message_handler(func=lambda m: m.text is not None and len(m.text) > 20)
    def on_long(message):
        EVENTS.append({"kind": "long", "text": message.text})

    @bot2.message_handler(content_types=["text"])
    def on_text(message):
        EVENTS.append({
            "kind": "text", "text": message.text,
            "real_id": getattr(message.from_user, "real_id", None),
            "mw": getattr(message, "smoke_mw", False),
            "mine": _mine(ctx, message),
        })

    @bot2.edited_message_handler(content_types=["text"])
    def on_edited(message):
        EVENTS.append({"kind": "edited", "text": message.text})

    @bot2.callback_query_handler(func=lambda c: (c.data or "").startswith("smoke_"))
    def on_callback(call):
        EVENTS.append({"kind": "callback", "data": call.data, "id": call.id})
        answered = bot2.answer_callback_query(
            call.id, text=f"смоук видит нажатие [{ctx.run_id}]")
        EVENTS.append({"kind": "callback_answered", "ok": answered})

    @bot2.comment_handler(content_types=["text"])
    def on_comment(message):
        EVENTS.append({"kind": "comment", "text": message.text})

    @bot2.channel_post_handler(content_types=["text"])
    def on_post(message):
        EVENTS.append({"kind": "post", "text": message.text,
                       "mid": message.message_id,
                       "from_user_none": message.from_user is None})

    thread = threading.Thread(target=bot2.polling, daemon=True)
    thread.start()
    time.sleep(2)
    ctx.check(thread.is_alive(), "поток поллинга умер сразу после старта")
    BOT2["bot"] = bot2
    BOT2["thread"] = thread
    return "поллинг поднят (отдельный экземпляр бота)"


@step(id="message_handler_text", group="handlers",
      title="message_handler — текст от человека",
      requires=("polling_start",))
def s_text(ctx):
    got = ctx.wait_for(
        lambda: any(not e.get("mine") for e in _events("text")),
        "напиши боту в тестовом чате любой КОРОТКИЙ текст (до 20 символов)")
    ctx.require(got, "не дождались текста")
    event = next(e for e in _events("text") if not e.get("mine"))
    ctx.check(bool(event["text"]), "пустой text")
    ctx.check(event["mw"] is True, "typed-middleware не пометил сообщение")
    if event.get("real_id") and not ctx.cfg["PEER_USER_ID"]:
        print(f"        ПОДСКАЗКА: PEER_USER_ID = {event['real_id']}"
              "  <- впиши в конфиг, откроются шаги members")
    return f"получено: {event['text']!r}, real_id={event.get('real_id')}"


@step(id="message_handler_commands", group="handlers",
      title="message_handler(commands=['smoke'])", requires=("polling_start",))
def s_command(ctx):
    got = ctx.wait_for(lambda: _events("command"), "пришли боту команду /smoke")
    ctx.require(got, "не дождались /smoke")
    return f"командный обработчик сработал: {_events('command')[0]['text']!r}"


@step(id="message_handler_regexp", group="handlers",
      title="message_handler(regexp=...)", requires=("polling_start",))
def s_regexp(ctx):
    got = ctx.wait_for(lambda: _events("regexp"), "пришли текст: смоук-42")
    ctx.require(got, "не дождались смоук-42")
    return "regexp-обработчик сработал"


@step(id="message_handler_func", group="handlers",
      title="message_handler(func=len>20)", requires=("polling_start",))
def s_func(ctx):
    got = ctx.wait_for(lambda: _events("long"),
                       "пришли текст ДЛИННЕЕ 20 символов")
    ctx.require(got, "не дождались длинного текста")
    return "func-фильтр сработал"


@step(id="message_handler_photo", group="handlers",
      title="message_handler(content_types=['photo'])",
      requires=("polling_start",))
def s_photo(ctx):
    got = ctx.wait_for(lambda: _events("photo"), "пришли боту любое ФОТО")
    ctx.require(got, "не дождались фото")
    event = _events("photo")[0]
    ctx.check(bool(event["token"]), "у фото нет file_id")
    return "фото-обработчик сработал, токен есть"


@step(id="message_handler_sticker", group="handlers",
      title="message_handler(sticker) — добыча кода",
      requires=("polling_start",))
def s_sticker(ctx):
    got = ctx.wait_for(lambda: _events("sticker"), "пришли боту любой СТИКЕР")
    ctx.require(got, "не дождались стикера")
    code = _events("sticker")[0]["code"]
    ctx.check(bool(code), "код стикера не извлёкся")
    if code and not ctx.cfg["STICKER_CODE"]:
        print(f"        ПОДСКАЗКА: STICKER_CODE = \"{code}\""
              "  <- впиши в конфиг, откроется шаг send_sticker")
    return f"код стикера: {code}"


@step(id="edited_message_handler_live", group="handlers",
      title="edited_message_handler", requires=("message_handler_text",))
def s_edited(ctx):
    got = ctx.wait_for(lambda: _events("edited"),
                       "ОТРЕДАКТИРУЙ любое своё сообщение в чате")
    ctx.require(got, "не дождались правки")
    return f"правка получена: {_events('edited')[0]['text']!r}"


@step(id="callback_flow", group="handlers",
      title="callback_query + answer_callback_query",
      requires=("polling_start", "inline_keyboard"),
      eye="после нажатия у ТЕБЯ всплыло уведомление «смоук видит нажатие»")
def s_callback(ctx):
    got = ctx.wait_for(lambda: _events("callback"),
                       "нажми кнопку «Да …» на сообщении с кнопками выше")
    ctx.require(got, "не дождались нажатия")
    event = _events("callback")[0]
    ctx.check(event["data"].startswith("smoke_"), f"data={event['data']!r}")
    answered = ctx.wait_for(lambda: _events("callback_answered"), "секунду...", 10)
    ctx.check(answered and _events("callback_answered")[0]["ok"] is True,
              "answer_callback_query не вернул True")
    return f"нажатие {event['data']!r} получено и отвечено"


@step(id="next_step", group="handlers",
      title="register_next_step_handler + clear",
      covers=("register_next_step_handler", "clear_step_handler"),
      requires=("message_handler_text",))
def s_next_step(ctx):
    bot2 = BOT2["bot"]
    answers = []
    question = bot2.send_message(ctx.chat_id, ctx.tag("— как тебя зовут?"))
    bot2.register_next_step_handler(question, lambda m: answers.append(m.text))
    got = ctx.wait_for(lambda: answers, "ответь боту на вопрос (любой текст)")
    ctx.require(got, "не дождались ответа")
    first_answer = answers[0]
    # снятое ожидание не срабатывает
    question2 = bot2.send_message(ctx.chat_id, ctx.tag("— на это НЕ отвечай, жду 3 c"))
    bot2.register_next_step_handler(question2, lambda m: answers.append("ЛИШНЕЕ"))
    bot2.clear_step_handler(question2)
    time.sleep(3)
    ctx.check("ЛИШНЕЕ" not in answers, "clear_step_handler не снял ожидание")
    return f"ответ: {first_answer!r}; после clear — тишина"


@step(id="reply_registry", group="handlers",
      title="register_for_reply — ждём ответ на сообщение",
      covers=("register_for_reply",), requires=("message_handler_text",))
def s_reply_registry(ctx):
    bot2 = BOT2["bot"]
    replies = []
    target = bot2.send_message(ctx.chat_id, ctx.tag("— ОТВЕТЬ на это сообщение"
                                                    " (свайп/ответить)"))
    bot2.register_for_reply(target, lambda m: replies.append(m.text))
    got = ctx.wait_for(lambda: replies,
                       "ответь именно НА сообщение бота (через «Ответить»)")
    ctx.require(got, "не дождались ответа-реплая")
    return f"reply-обработчик сработал: {replies[0]!r}"


@step(id="middleware_check", group="handlers",
      title="middleware — общий и типизированный",
      requires=("message_handler_text",))
def s_middleware(ctx):
    updates = _events("mw_update")
    ctx.check(bool(updates), "общий middleware не вызывался")
    ctx.check(any(u["type"] == "message_created" for u in updates),
              "общий middleware не видел message_created")
    return f"middleware видел обновлений: {len(updates)}"


@step(id="exception_handler_live", group="handlers",
      title="ExceptionHandler — обработчик упал, поллинг жив",
      requires=("polling_start",))
def s_exception(ctx):
    bot2 = BOT2["bot"]

    # текстовое сообщение забрал бы catch-all on_text, поэтому роняем
    # обработчик НЕзанятого типа контента и скармливаем синтетическое
    # обновление через публичную точку пайплайна
    @bot2.message_handler(content_types=["location"])
    def on_crash(message):
        raise RuntimeError("смоук-падение обработчика")

    crash_update = {
        "update_type": "message_created",
        "timestamp": int(time.time() * 1000),
        "message": {
            "sender": {"user_id": 1, "first_name": "смоук", "name": "smoke"},
            "recipient": {"chat_id": ctx.chat_id, "chat_type": "chat",
                          "user_id": None},
            "timestamp": int(time.time() * 1000),
            "body": {"mid": "smoke.crash", "seq": 1, "text": None,
                     "attachments": [{"type": "location",
                                      "latitude": 55.75, "longitude": 37.61}]},
        },
    }
    before = len(_events("exception"))
    bot2.process_new_updates([crash_update])
    got = ctx.wait_for(lambda: len(_events("exception")) > before,
                       "секунду, ловим исключение...", 10)
    ctx.check(got, "ExceptionHandler.handle не вызван")
    ctx.check(BOT2["thread"].is_alive(), "поллинг умер от исключения")
    return "исключение поймано, поллинг жив"


@step(id="channel_post_live", group="handlers",
      title="channel_post_handler — пост в канале",
      requires=("polling_start",), needs=("has_channel",))
def s_channel_post(ctx):
    got = ctx.wait_for(lambda: _events("post"),
                       "опубликуй ЛЮБОЙ текстовый пост в канале"
                       f" (CHANNEL_ID={ctx.cfg['CHANNEL_ID']}, бот должен быть"
                       " админом канала)")
    ctx.require(got, "не дождались поста")
    event = _events("post")[0]
    ctx.check(event["from_user_none"], "у поста from_user не None")
    ctx.check(not any(e["kind"] == "text" and e["text"] == event["text"]
                      for e in EVENTS),
              "пост попал и в message_handler (не должен)")
    ctx.put("channel_post_mid", event["mid"])
    return f"пост получен, mid={event['mid']}"


@step(id="comments_flow", group="handlers",
      title="комментарии к посту: send/get/edit/delete + comment_handler",
      covers=("send_comment", "get_comments", "get_comment", "edit_comment",
              "delete_comment"),
      requires=("channel_post_live",), needs=("has_channel",),
      eye="под постом появился комментарий бота «привет из смоука»,"
          " затем текст сменился на «правка»")
def s_comments(ctx):
    bot2 = BOT2["bot"]
    post_mid = ctx.get("channel_post_mid")
    sent = bot2.send_comment(post_mid, ctx.tag("— привет из смоука"))
    ctx.check(bool(sent.message_id), "у комментария нет mid")
    comments = bot2.get_comments(post_mid)
    ctx.check(any(c.message_id == sent.message_id for c in comments),
              "своего комментария нет в get_comments")
    one = bot2.get_comment(post_mid, sent.message_id)
    ctx.check(one.message_id == sent.message_id, "get_comment не тот")
    edited = bot2.edit_comment(post_mid, sent.message_id, text=ctx.tag("— правка"))
    ctx.check(edited is True, f"edit_comment вернул {edited!r}")

    got = ctx.wait_for(lambda: _events("comment"),
                       "напиши СВОЙ комментарий под тем же постом")
    if got:
        ctx.check(bool(_events("comment")[0]["text"]), "пустой комментарий")
    else:
        ctx.note("человек не написал комментарий — comment_handler не проверен")
    deleted = bot2.delete_comment(post_mid, sent.message_id)
    ctx.check(deleted is True, f"delete_comment вернул {deleted!r}")
    return "send/get/edit/delete прошли" + ("" if got else " (comment_handler — без ответа человека)")


@step(id="polling_stop", group="handlers", title="stop — гасим поллинг",
      covers=("stop", "stop_polling"), requires=("polling_start",))
def s_polling_stop(ctx):
    bot2, thread = BOT2["bot"], BOT2["thread"]
    bot2.stop_polling()
    thread.join(35)
    ctx.check(not thread.is_alive(), "поток поллинга не завершился за 35 c")
    return "поллинг остановлен"


@step(id="infinity_polling_brief", group="handlers",
      title="infinity_polling — старт и стоп за 5 c",
      covers=("infinity_polling",), requires=("polling_stop",))
def s_infinity(ctx):
    import maxibot
    bot3 = maxibot.MaxiBot(ctx.cfg["TOKEN"], threaded=True)
    thread = threading.Thread(target=bot3.infinity_polling,
                              kwargs={"skip_pending": True}, daemon=True)
    thread.start()
    time.sleep(5)
    ctx.check(thread.is_alive(), "infinity_polling умер сразу")
    bot3.stop()
    thread.join(35)
    ctx.check(not thread.is_alive(), "infinity_polling не остановился")
    return "поднялся и остановился"

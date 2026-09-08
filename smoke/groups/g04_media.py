"""Медиа: фото/альбом/документ/видео/аудио и деградации MAX."""
from runner import step


@step(id="send_photo", group="media", title="send_photo — фото байтами",
      covers=("send_photo",), requires=("get_chat",), slow=True,
      eye="фото — цветной квадрат с номером шага, подпись со «smoke#…»")
def s_send_photo(ctx):
    png = ctx.assets.png(ctx.step_no)
    try:
        msg = ctx.bot.send_photo(ctx.chat_id, png, caption=ctx.tag())
    except Exception:
        backup = ctx.assets.jpg()
        if backup is None:
            raise
        ctx.note("PNG не принят — повтор с assets/photo.jpg")
        msg = ctx.bot.send_photo(ctx.chat_id, backup, caption=ctx.tag("(jpg)"))
    ctx.check(msg.content_type == "photo", f"content_type={msg.content_type!r}")
    token = msg.photo[-1].file_id if msg.photo else None
    ctx.check(bool(token), "у фото нет file_id (токена)")
    ctx.put("photo_mid", msg.message_id)
    ctx.put("photo_token", token)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_photo_url", group="media", title="send_photo — по URL",
      covers=("send_photo",), requires=("send_photo",), slow=True,
      eye="фото по ссылке (схема «из Telegram в MAX» из README)")
def s_send_photo_url(ctx):
    msg = ctx.bot.send_photo(ctx.chat_id, ctx.cfg["PHOTO_URL"], caption=ctx.tag("(url)"))
    ctx.check(msg.content_type == "photo", f"content_type={msg.content_type!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_photo_token", group="media", title="send_photo — по токену",
      covers=("send_photo",), requires=("send_photo",),
      eye="то же фото-квадрат ещё раз (переиспользован токен, без загрузки)")
def s_send_photo_token(ctx):
    msg = ctx.bot.send_photo(ctx.chat_id, ctx.get("photo_token"),
                             caption=ctx.tag("(token)"))
    ctx.check(msg.content_type == "photo", f"content_type={msg.content_type!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_media_group", group="media", title="send_media_group — альбом",
      covers=("send_media_group",), requires=("send_photo",), slow=True,
      eye="три разноцветных квадрата ОДНИМ альбомом")
def s_media_group(ctx):
    from maxibot.types import InputMedia
    media = [InputMedia("photo", ctx.assets.png(ctx.step_no + i))
             for i in range(3)]
    messages = ctx.bot.send_media_group(ctx.chat_id, media)
    ctx.check(isinstance(messages, list) and messages, f"вернул {messages!r}")
    for msg in messages or ():
        ctx.track_message(getattr(msg, "message_id", None))
    return f"сообщений в альбоме: {len(messages)}"


@step(id="send_document", group="media", title="send_document — txt байтами",
      covers=("send_document",), requires=("get_chat",), slow=True,
      eye="файл smoke-<runid>.txt в чате")
def s_send_document(ctx):
    payload = ctx.assets.txt(ctx.run_id)
    msg = ctx.bot.send_document(ctx.chat_id, payload, caption=ctx.tag(),
                                visible_file_name=f"smoke-{ctx.run_id}.txt")
    ctx.check(msg.content_type == "document", f"content_type={msg.content_type!r}")
    ctx.put("doc_mid", msg.message_id)
    ctx.put("doc_bytes", payload)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_video", group="media", title="send_video — mp4",
      covers=("send_video",), requires=("get_chat",), slow=True,
      eye="видео 2–3 секунды (пёстрая тестовая заставка) играет")
def s_send_video(ctx):
    clip = ctx.assets.mp4()
    ctx.require(clip is not None, "нет файла smoke/assets/clip.mp4")
    msg = ctx.bot.send_video(ctx.chat_id, clip, caption=ctx.tag())
    ctx.check(msg.content_type == "video", f"content_type={msg.content_type!r}")
    token = msg.video.file_id if msg.video else None
    ctx.put("video_token", token)
    ctx.put("video_mid", msg.message_id)
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_animation", group="media",
      title="send_animation — деградация в видео",
      covers=("send_animation",), requires=("send_video",), slow=True,
      eye="«гифка» пришла ОБЫЧНЫМ ВИДЕО — анимаций в MAX нет, это"
          " задокументированная деградация")
def s_send_animation(ctx):
    msg = ctx.bot.send_animation(ctx.chat_id, ctx.assets.mp4(), caption=ctx.tag())
    ctx.check(msg.content_type == "video",
              f"content_type={msg.content_type!r}, ждали 'video' (деградация)")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_video_note", group="media",
      title="send_video_note — деградация в видео",
      covers=("send_video_note",), requires=("send_video",), slow=True,
      eye="«кружок» пришёл ПРЯМОУГОЛЬНЫМ видео (кружков в MAX нет)")
def s_video_note(ctx):
    msg = ctx.bot.send_video_note(ctx.chat_id, ctx.assets.mp4())
    ctx.check(msg.content_type == "video", f"content_type={msg.content_type!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_audio", group="media", title="send_audio — mp3",
      covers=("send_audio",), requires=("get_chat",), slow=True,
      eye="аудио с плеером, звук слышен (гудок ~2.5 c)")
def s_send_audio(ctx):
    sound = ctx.assets.mp3()
    ctx.require(sound is not None, "нет файла smoke/assets/sound.mp3")
    msg = ctx.bot.send_audio(ctx.chat_id, sound, caption=ctx.tag())
    ctx.check(msg.content_type == "audio", f"content_type={msg.content_type!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_voice", group="media",
      title="send_voice — деградация в аудио",
      covers=("send_voice",), requires=("send_audio",), slow=True,
      eye="«голосовое» пришло ОБЫЧНЫМ аудио (голосовых у ботов MAX нет)")
def s_send_voice(ctx):
    msg = ctx.bot.send_voice(ctx.chat_id, ctx.assets.mp3())
    ctx.check(msg.content_type == "audio", f"content_type={msg.content_type!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"


@step(id="send_sticker", group="media", title="send_sticker — по коду",
      covers=("send_sticker",), requires=("get_chat",), needs=("has_sticker",),
      eye="стикер в чате")
def s_send_sticker(ctx):
    msg = ctx.bot.send_sticker(ctx.chat_id, ctx.cfg["STICKER_CODE"])
    ctx.check(msg.content_type == "sticker", f"content_type={msg.content_type!r}")
    ctx.track_message(msg.message_id)
    return f"mid={msg.message_id}"

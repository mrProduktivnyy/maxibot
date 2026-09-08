"""Файлы: get_file / download_file / get_video. Побайтовая сверка — главная
авто-проверка прогона."""
from runner import step


@step(id="get_file", group="files", title="get_file документа",
      covers=("get_file",), requires=("send_document",))
def s_get_file(ctx):
    msg = ctx.bot.get_message(ctx.get("doc_mid"))
    file_path = getattr(msg.document, "file_path", None) if msg.document else None
    ctx.require(file_path, "у документа нет file_path (MAX ещё обрабатывает?)")
    file = ctx.bot.get_file(file_path)
    ctx.check(bool(getattr(file, "file_path", None)), "File.file_path пуст")
    ctx.put("doc_url", file.file_path)
    return "URL получен"


@step(id="download_file_bytes", group="files",
      title="download_file — побайтовая сверка txt",
      covers=("download_file",), requires=("get_file",))
def s_download(ctx):
    payload = ctx.bot.download_file(ctx.get("doc_url"))
    ctx.check(payload == ctx.get("doc_bytes"),
              f"скачанное НЕ совпало с отправленным ({len(payload or b'')} байт"
              f" против {len(ctx.get('doc_bytes') or b'')})")
    return f"скачано {len(payload)} байт, совпало побайтово"


@step(id="get_file_url", group="files", title="get_file_url",
      covers=("get_file_url",), requires=("get_file",))
def s_get_file_url(ctx):
    url = ctx.bot.get_file_url(ctx.get("doc_url"))
    ctx.check(url == ctx.get("doc_url") or bool(url),
              "get_file_url ничего не вернул")
    return "ок"


@step(id="get_video", group="files", title="get_video по токену",
      covers=("get_video",), requires=("send_video",))
def s_get_video(ctx):
    token = ctx.get("video_token")
    ctx.require(token, "нет video_token (send_video не дал токен)")
    video = ctx.bot.get_video(token)
    ctx.check(video is not None, "get_video вернул None")
    return f"width={getattr(video, 'width', None)}, duration={getattr(video, 'duration', None)}"


@step(id="download_file_token_error", group="files",
      title="download_file(token) — ValueError",
      covers=("download_file",), requires=("send_photo",))
def s_download_token(ctx):
    try:
        ctx.bot.download_file(ctx.get("photo_token"))
    except ValueError:
        return "ValueError с подсказкой, как задокументировано"
    ctx.check(False, "скачивание по токену не отклонено")

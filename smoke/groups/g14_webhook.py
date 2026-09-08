"""Вебхуки: чтение подписок всегда, set/delete — только с WEBHOOK_URL."""
from runner import step


@step(id="get_webhook_info", group="webhook", title="get_webhook_info",
      covers=("get_webhook_info",), requires=("get_me",))
def s_webhook_info(ctx):
    info = ctx.bot.get_webhook_info()
    subs = (info or {}).get("subscriptions") if isinstance(info, dict) else None
    count = len(subs or [])
    if count:
        print("        [ВНИМАНИЕ] у бота уже есть webhook-подписки — они"
              " конкурируют с поллингом за обновления")
    return f"подписок: {count}"


@step(id="set_webhook_live", group="webhook", title="set_webhook + delete_webhook",
      covers=("set_webhook", "delete_webhook"), requires=("get_webhook_info",),
      needs=("has_webhook_url",))
def s_set_webhook(ctx):
    url = ctx.cfg["WEBHOOK_URL"]
    ctx.bot.set_webhook(url, secret=ctx.cfg["WEBHOOK_SECRET"] or None)
    info = ctx.bot.get_webhook_info()
    urls = [s.get("url") for s in (info or {}).get("subscriptions", [])]
    ctx.check(url in urls, f"подписка не появилась: {urls}")
    try:
        return f"подписка встала: {url}"
    finally:
        ctx.bot.delete_webhook(url=url)
        after = ctx.bot.get_webhook_info()
        remaining = [s.get("url") for s in (after or {}).get("subscriptions", [])]
        if url in remaining:
            print("        [ВНИМАНИЕ] delete_webhook не снял подписку!")
        else:
            ctx.restored.append("webhook-подписка снята")

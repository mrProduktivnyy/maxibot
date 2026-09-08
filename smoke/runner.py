"""
Ядро живого смоука: реестр шагов, контекст, разрешение RUN, статусы,
сводка. Шаги живут в smoke/groups/*.py и регистрируются декоратором
@step. Запуск — из smoke/main.py.
"""
import logging
import os
import sys
import time
import traceback
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import console

SMOKE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(SMOKE_DIR, "last_run.log")

REGISTRY = []          # шаги в порядке объявления
_STATUS = {}           # id шага -> статус ("OK/auto", "FAIL/eye", ...)

OK_STATUSES = ("OK/auto", "OK/eye")

# методы MaxiBot, осознанно не покрываемые живым прогоном (для сводки)
NOT_LIVE = {
    "start": "async-вариант, покрыт через polling",
    "start_webhook": "блокирующий сервер + публичный HTTPS",
    "run_webhooks": "обёртка start_webhook, юнит-тесты",
    "kick_chat_member": "тот же бан (алиас), юнит-тесты",
    "run_handler": "внутренняя точка, юнит-тесты",
    "remove_webhook": "снял бы чужие подписки бота — вручную",
    "set_webhook": "needs WEBHOOK_URL (группа webhook)",
    "delete_webhook": "needs WEBHOOK_URL (группа webhook)",
    "set_state": "FSM локальный, юнит-тесты (tests/test_states.py)",
    "get_state": "FSM локальный, юнит-тесты",
    "delete_state": "FSM локальный, юнит-тесты",
    "add_data": "FSM локальный, юнит-тесты",
    "retrieve_data": "FSM локальный, юнит-тесты",
    "reset_data": "FSM локальный, юнит-тесты",
    "enable_saving_states": "FSM локальный, юнит-тесты",
    "add_custom_filter": "локальная регистрация, юнит-тесты",
    "enable_save_next_step_handlers": "локальный pickle, юнит-тесты",
    "disable_save_next_step_handlers": "локальный pickle, юнит-тесты",
    "load_next_step_handlers": "локальный pickle, юнит-тесты",
    "enable_save_reply_handlers": "локальный pickle, юнит-тесты",
    "disable_save_reply_handlers": "локальный pickle, юнит-тесты",
    "load_reply_handlers": "локальный pickle, юнит-тесты",
    "clear_reply_handlers": "локальный реестр, юнит-тесты",
    "clear_reply_handlers_by_message_id": "локальный реестр, юнит-тесты",
    "register_for_reply_by_message_id": "покрыт шагом reply_registry через register_for_reply",
    "check_commands_input": "клиентский валидатор, юнит-тесты",
    "check_regexp_input": "клиентский валидатор, юнит-тесты",
    "chosen_inline_handler": "warn-стаб (инлайна в MAX нет), юнит-тесты",
    "register_inline_handler": "warn-стаб, юнит-тесты",
    "register_chosen_inline_handler": "warn-стаб, юнит-тесты",
    "get_user_profile_photos": "«пока не реализован», юнит-тесты",
    "restrict_chat_member": "«пока не реализован», юнит-тесты",
    "middleware_handler": "покрыт шагом middleware группы handlers",
    "process_new_updates": "покрыт всей группой handlers (поллинг)",
    "process_new_messages": "покрыт группой handlers",
    "process_new_edited_messages": "покрыт группой handlers",
    "process_new_callback_query": "покрыт группой handlers",
    "process_new_my_chat_member": "события членства — нужен второй человек, юнит-тесты",
    "process_new_chat_member": "события членства — юнит-тесты",
    "process_new_comments": "покрыт шагами comments группы handlers",
    "process_new_edited_comments": "юнит-тесты (tests/test_comments.py)",
    "process_new_removed_comments": "юнит-тесты",
    "my_chat_member_handler": "нужно живое добавление/удаление бота — вручную",
    "chat_member_handler": "нужен второй человек, юнит-тесты",
    "register_my_chat_member_handler": "юнит-тесты",
    "register_chat_member_handler": "юнит-тесты",
    "add_my_chat_member_handler": "юнит-тесты",
    "add_chat_member_handler": "юнит-тесты",
    "edited_comment_handler": "правка комментария — юнит-тесты",
    "register_edited_comment_handler": "юнит-тесты",
    "add_edited_comment_handler": "юнит-тесты",
    "removed_comment_handler": "юнит-тесты (нужно живое удаление комментария)",
    "register_removed_comment_handler": "юнит-тесты",
    "add_removed_comment_handler": "юнит-тесты",
    "register_comment_handler": "покрыт декоратором comment_handler",
    "add_comment_handler": "юнит-тесты",
    "add_channel_post_handler": "юнит-тесты",
    "add_edited_channel_post_handler": "юнит-тесты",
    "register_channel_post_handler": "юнит-тесты",
    "register_edited_channel_post_handler": "юнит-тесты",
    "edited_channel_post_handler": "нужна правка поста — юнит-тесты",
    "process_new_channel_posts": "юнит-тесты",
    "process_new_edited_channel_posts": "юнит-тесты",
    "register_message_handler": "покрыт декораторами, юнит-тесты",
    "register_callback_query_handler": "юнит-тесты",
    "add_message_handler": "юнит-тесты",
    "add_edited_message_handler": "юнит-тесты",
    "add_callback_query_handler": "юнит-тесты",
    "register_next_step_handler_by_chat_id": "покрыт шагом next_step",
    "clear_step_handler": "покрыт шагом next_step",
    "clear_step_handler_by_chat_id": "покрыт шагом next_step",
    "set_update_listener": "юнит-тесты (tests/test_pipeline.py)",
}


class SkipStep(Exception):
    """ctx.require не выполнен — шаг уходит в SKIP с причиной."""


class AbortRun(Exception):
    """Человек ответил q — досрочная сводка."""


class Step:
    def __init__(self, id, group, title, fn, covers, eye, requires, needs,
                 danger, slow):
        self.id = id
        self.group = group
        self.title = title
        self.fn = fn
        self.covers = tuple(covers)
        self.eye = eye
        self.requires = tuple(requires)
        self.needs = tuple(needs)
        self.danger = danger
        self.slow = slow


def step(id, group, title, covers=(), eye=None, requires=(), needs=(),
         danger=None, slow=False):
    def decorator(fn):
        REGISTRY.append(Step(id, group, title, fn, covers, eye, requires,
                             needs, danger, slow))
        return fn
    return decorator


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class Context:
    def __init__(self, cfg, bot, run_id, capture, log_fh):
        self.cfg = cfg
        self.bot = bot
        self.chat_id = cfg["CHAT_ID"]
        self.run_id = run_id
        self.step_no = 0
        self.step_id = ""
        self._capture = capture
        self._log_fh = log_fh
        self._store = {}
        self._fails = []
        self.conditions = {}
        self.restored = []       # что вернули как было (для сводки)
        self.created_mids = []   # для CLEANUP
        self.assets = __import__("assets")

    # --- артефакты ---
    def put(self, key, value):
        self._store[key] = value

    def get(self, key, default=None):
        return self._store.get(key, default)

    def track_message(self, mid):
        if mid:
            self.created_mids.append(mid)

    # --- проверки ---
    def check(self, cond, detail):
        if not cond:
            self._fails.append(detail)
            self.note(f"CHECK FAIL: {detail}")

    def require(self, cond, reason):
        if not cond:
            raise SkipStep(reason)

    def set_condition(self, name, value):
        self.conditions[name] = bool(value)

    # --- человек ---
    def ask(self, text):
        answer = input(f"        ВОПРОС: {text} [y/n]: ").strip().lower()
        return answer in ("y", "д", "да", "yes", "")

    def prepare(self, text):
        console.prepare(text)

    def wait_for(self, predicate, hint, timeout=None):
        timeout = timeout or self.cfg["INTERACTIVE_TIMEOUT"]
        return console.countdown_wait(predicate, hint, timeout)

    # --- лог ---
    def logs(self):
        return [r.getMessage() for r in self._capture.records]

    def note(self, text):
        self._log_fh.write(f"[{self.run_id} {self.step_id}] {text}\n")
        self._log_fh.flush()

    def tag(self, suffix=""):
        base = f"smoke#{self.run_id} [{self.step_no}] {self.step_id}"
        return f"{base} {suffix}".strip()


# ---------------------------------------------------------------------------

def _validate_registry():
    import maxibot
    ids = set()
    problems = []
    for entry in REGISTRY:
        if entry.id in ids:
            problems.append(f"дубль id шага: {entry.id}")
        ids.add(entry.id)
    for entry in REGISTRY:
        for req in entry.requires:
            if req not in ids:
                problems.append(f"{entry.id}: requires неизвестный шаг {req!r}")
        for name in entry.covers:
            if not hasattr(maxibot.MaxiBot, name) and not hasattr(maxibot, name):
                problems.append(f"{entry.id}: covers несуществующее имя {name!r}")
    if problems:
        for p in problems:
            console.say("[ОШИБКА РЕЕСТРА] " + p)
        sys.exit(2)


def _closure(wanted_ids):
    """Транзитивное замыкание requires; возвращает (нужные id, setup-множество)."""
    by_id = {s.id: s for s in REGISTRY}
    needed, queue = set(wanted_ids), list(wanted_ids)
    while queue:
        current = by_id[queue.pop()]
        for req in current.requires:
            if req not in needed:
                needed.add(req)
                queue.append(req)
    return needed, needed - set(wanted_ids)


def resolve_run(run_value):
    """RUN -> (список Step в порядке реестра, set setup-id) | 'list' | ошибка."""
    tokens = run_value if isinstance(run_value, (list, tuple)) else [run_value]
    tokens = [str(t).strip() for t in tokens if str(t).strip()]
    if tokens == ["list"]:
        return "list", set()
    if tokens == ["full"]:
        return list(REGISTRY), set()

    group_names = {s.group for s in REGISTRY}
    step_ids = {s.id for s in REGISTRY}
    wanted_steps = set()
    for token in tokens:
        if token in group_names:
            wanted_steps |= {s.id for s in REGISTRY if s.group == token}
        elif token in step_ids:
            wanted_steps.add(token)
        else:
            console.say(f"[ОШИБКА] RUN: не знаю группу/шаг {token!r}")
            console.say("Группы: " + " ".join(sorted(group_names)))
            console.say("Шаги: RUN = \"list\" напечатает полный список")
            sys.exit(2)

    needed, setup = _closure(wanted_steps)
    # preflight подмешивается всегда и первым (порядок реестра это даёт)
    preflight = {s.id for s in REGISTRY if s.group == "preflight"}
    ordered = [s for s in REGISTRY if s.id in needed or s.id in preflight]
    return ordered, setup


def print_registry():
    current_group = None
    for i, entry in enumerate(REGISTRY, 1):
        if entry.group != current_group:
            current_group = entry.group
            console.say(f"\n--- {current_group} ---")
        extras = []
        if entry.covers:
            extras.append("covers: " + ",".join(entry.covers))
        if entry.needs:
            extras.append("needs: " + ",".join(entry.needs))
        if entry.danger:
            extras.append("danger: " + entry.danger)
        console.say(f"[{i:3}] {entry.id:34} {'; '.join(extras)}")
    console.say(f"\nвсего шагов: {len(REGISTRY)}")


def _hint_for(error):
    from maxibot.exceptions import (MaxApiHTTPException,
                                    MaxApiNotReadyException,
                                    MaxApiRequestException)
    if isinstance(error, MaxApiHTTPException):
        code = getattr(error, "status_code", None)
        if code in (401, 403):
            return "проверь TOKEN / бот не участник или не админ чата"
        if code == 404:
            return "неверный CHAT_ID или сообщение удалено"
        if code == 429:
            return "rate limit MAX — увеличь PAUSE"
    if isinstance(error, MaxApiNotReadyException):
        return "MAX не дообработал вложение за отведённое время — попробуй файл поменьше"
    if isinstance(error, MaxApiRequestException):
        return f"код MAX: {error.error_code}"
    return ""


def _coverage(executed_steps):
    import maxibot
    covered = set()
    for entry in executed_steps:
        if _STATUS.get(entry.id) in OK_STATUSES + ("FAIL/auto", "FAIL/eye"):
            covered |= set(entry.covers)
    stub_names = (set(maxibot._MAX_IMPOSSIBLE_ACTIONS)
                  | set(maxibot._MAX_DEAD_HANDLER_DECORATORS)
                  | set(maxibot._MAX_DEAD_HANDLER_CALLS))
    baseline = {
        n for n in dir(maxibot.MaxiBot)
        if not n.startswith("_") and callable(getattr(maxibot.MaxiBot, n))
    }
    checkable = baseline - stub_names - set(NOT_LIVE)
    missed = sorted(checkable - covered)
    return len(covered & checkable), len(checkable), missed, len(stub_names)


def run(cfg_globals):
    defaults = dict(
        TOKEN="", CHAT_ID=0, RUN="full", CONFIRM="ask", PAUSE=1.0,
        DANGER_MUTATE=False, DANGER_DESTRUCTIVE=False, LEAVE_CHAT_ID=0,
        PEER_USER_ID=0, STICKER_CODE="", CHANNEL_ID=0, SECOND_CHAT_ID=0,
        BOT_USERNAME="", WEBHOOK_URL="", WEBHOOK_SECRET="", ADD_USER_ID=0,
        INTERACTIVE_TIMEOUT=120, CLEANUP=False, COLOR=False,
        PHOTO_URL=None,
    )
    cfg = {k: cfg_globals.get(k, v) for k, v in defaults.items()}
    if cfg["PHOTO_URL"] is None:
        import assets as assets_mod
        cfg["PHOTO_URL"] = assets_mod.PHOTO_URL_DEFAULT

    # local_config.py (в .gitignore) переопределяет константы — токен вне git
    local_path = os.path.join(SMOKE_DIR, "local_config.py")
    if os.path.isfile(local_path):
        local_ns = {}
        with open(local_path, encoding="utf-8") as fh:
            exec(fh.read(), local_ns)
        for key in defaults:
            if key in local_ns:
                cfg[key] = local_ns[key]
        console.say("[конфиг] найден smoke/local_config.py — константы переопределены")
    elif cfg["TOKEN"]:
        console.say("[ВНИМАНИЕ] TOKEN задан прямо в main.py — не закоммить его!"
                    " Лучше вынеси в smoke/local_config.py (он в .gitignore)")

    import groups  # noqa: F401  (регистрирует шаги)
    _validate_registry()

    resolved = resolve_run(cfg["RUN"])
    if resolved[0] == "list":
        print_registry()
        return 0
    plan_steps, setup_ids = resolved

    if not cfg["TOKEN"] or not cfg["CHAT_ID"]:
        console.header([
            "ЖИВОЙ СМОУК maxibot — нечего запускать: пусты TOKEN и/или CHAT_ID",
            "",
            "1. Получи токен бота у @MasterBot в MAX",
            "2. Добавь бота в тестовую ГРУППУ и дай ему права администратора",
            "3. Узнай id чата: напиши боту в группе что-нибудь и прогони",
            "   RUN=\"handlers\" — шаг message_handler печатает chat_id,",
            "   или посмотри в веб-версии MAX в адресной строке",
            "4. Впиши TOKEN и CHAT_ID в smoke/main.py (или в smoke/local_config.py,",
            "   он в .gitignore) и снова жми Run",
            "",
            "RUN=\"list\" покажет все группы и шаги без сети",
        ])
        return 2

    import maxibot
    run_id = uuid.uuid4().hex[:4]
    capture = LogCapture()
    logging.getLogger("maxibot").addHandler(capture)
    log_fh = open(LOG_PATH, "w", encoding="utf-8")
    log_fh.write(f"smoke#{run_id} старт {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    bot = maxibot.MaxiBot(cfg["TOKEN"], threaded=False)
    ctx = Context(cfg, bot, run_id, capture, log_fh)

    visual = sum(1 for s in plan_steps if s.eye)
    console.header([
        f"ЖИВОЙ СМОУК maxibot   прогон smoke#{run_id}",
        f"режим: {cfg['RUN']!r}   подтверждение: {cfg['CONFIRM']}",
        f"шагов: {len(plan_steps)} (визуальных {visual},"
        f" авто {len(plan_steps) - visual})",
        "Открой тестовый чат в MAX рядом с этим окном. Поехали.",
    ])

    checklist = []       # (номер, id, eye) для CONFIRM="checklist"
    started = time.time()
    executed = []
    try:
        for entry in plan_steps:
            ctx.step_no += 1
            ctx.step_id = entry.id
            ctx._fails = []
            capture.records = []
            number = f"[{ctx.step_no}/{len(plan_steps)}]"
            is_setup = entry.id in setup_ids
            title = entry.title + (" [setup]" if is_setup else "")

            # danger-гейты
            if entry.danger == "mutate" and not cfg["DANGER_MUTATE"]:
                _STATUS[entry.id] = "SKIP"
                console.say(f"{number} {title:44} [SKIP] DANGER_MUTATE = False")
                continue
            if entry.danger == "destructive" and not cfg["DANGER_DESTRUCTIVE"]:
                _STATUS[entry.id] = "SKIP"
                console.say(f"{number} {title:44} [SKIP] DANGER_DESTRUCTIVE = False")
                continue
            # условия preflight
            unmet = [n for n in entry.needs if not ctx.conditions.get(n)]
            if unmet:
                _STATUS[entry.id] = "SKIP"
                console.say(f"{number} {title:44} [SKIP] условие: {', '.join(unmet)}")
                continue
            # предпосылки
            blocked = [r for r in entry.requires
                       if _STATUS.get(r) not in OK_STATUSES]
            if blocked:
                _STATUS[entry.id] = "BLOCKED"
                console.say(f"{number} {title:44} [SKIP] предпосылка не прошла:"
                            f" {', '.join(blocked)}")
                continue

            if entry.slow:
                console.say(f"{number} {entry.title} — шаг небыстрый (вложение"
                            " обрабатывается на стороне MAX), жди")

            executed.append(entry)
            detail = ""
            try:
                attempts = 0
                while True:
                    try:
                        detail = entry.fn(ctx) or ""
                        break
                    except maxibot.MaxApiHTTPException as error:
                        if getattr(error, "status_code", None) == 429 and attempts < 3:
                            pause = 2 ** (attempts + 1)
                            console.say(f"        429 от MAX — пауза {pause} c и повтор")
                            time.sleep(pause)
                            attempts += 1
                            continue
                        raise
            except SkipStep as skip:
                _STATUS[entry.id] = "SKIP"
                console.say(f"{number} {title:44} [SKIP] {skip}")
                time.sleep(cfg["PAUSE"])
                continue
            except AbortRun:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as error:  # noqa: BLE001 — шаг не валит прогон
                _STATUS[entry.id] = "ERR"
                hint = _hint_for(error)
                text = str(error)[:200]
                console.say(f"{number} {title:44} [ERR] {type(error).__name__}: {text}")
                if hint:
                    console.say(f"        подсказка: {hint}")
                log_fh.write(f"\n--- ERR {entry.id} ---\n")
                log_fh.write(traceback.format_exc())
                log_fh.flush()
                time.sleep(cfg["PAUSE"])
                continue

            if ctx._fails:
                _STATUS[entry.id] = "FAIL/auto"
                console.say(f"{number} {title:44} [FAIL] auto")
                for fail in ctx._fails:
                    console.say(f"        - {fail}")
            elif entry.eye and not is_setup:
                if cfg["CONFIRM"] == "checklist":
                    _STATUS[entry.id] = "OK/eye"
                    checklist.append((ctx.step_no, entry.id, entry.eye))
                    console.say(f"{number} {title:44} [OK] api  {detail}")
                else:
                    console.say(f"{number} {title}")
                    if detail:
                        console.say(f"        API : ok  {detail}")
                    console.say(f"        ГЛАЗАМИ: {entry.eye}")
                    while True:
                        answer, comment = console.ask_eye(
                            ctx.step_no, len(plan_steps), entry.eye)
                        if answer == "?":
                            console.say(f"        подробнее: {entry.eye}")
                            if detail:
                                console.say(f"        ответ API: {detail}")
                            continue
                        break
                    if answer == "y":
                        _STATUS[entry.id] = "OK/eye"
                    elif answer == "n":
                        _STATUS[entry.id] = "FAIL/eye"
                        ctx._fails.append(f"глазами: {comment or 'не так'}")
                        _FAIL_NOTES[entry.id] = f"глазами: {comment or 'не так'}"
                    elif answer == "s":
                        _STATUS[entry.id] = "SKIP"
                    elif answer == "q":
                        raise AbortRun()
            else:
                _STATUS[entry.id] = "OK/auto"
                console.say(f"{number} {title:44} [OK] auto  {detail}")

            if _STATUS.get(entry.id) == "FAIL/auto":
                _FAIL_NOTES[entry.id] = "; ".join(ctx._fails)
            time.sleep(cfg["PAUSE"])

        # чек-лист по визуальным шагам
        if checklist and cfg["CONFIRM"] == "checklist":
            console.say("\n=== ЧЕК-ЛИСТ: сверь глазами в чате " + "=" * 34)
            for no, sid, eye in checklist:
                console.say(f"  {no:3}. {eye}")
            raw = input("Какие НЕ сошлись? Номера через запятую"
                        " (Enter — всё ок): ").strip()
            if raw:
                bad = {int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()}
                for no, sid, _ in checklist:
                    if no in bad:
                        _STATUS[sid] = "FAIL/eye"
                        _FAIL_NOTES[sid] = "глазами (чек-лист)"
    except KeyboardInterrupt:
        console.say("\n[прервано] сводка по пройденному:")
        _summary(cfg, run_id, started, executed, ctx)
        return 130
    except AbortRun:
        console.say("\n[остановлено по q] сводка по пройденному:")
    finally:
        if cfg["CLEANUP"] and ctx.created_mids:
            console.say(f"[cleanup] удаляю {len(ctx.created_mids)} сообщений...")
            bot.delete_messages(cfg["CHAT_ID"], ctx.created_mids)
        logging.getLogger("maxibot").removeHandler(capture)

    code = _summary(cfg, run_id, started, executed, ctx)
    log_fh.close()
    return code


_FAIL_NOTES = {}


def _summary(cfg, run_id, started, executed, ctx):
    minutes = int((time.time() - started) / 60)
    counts = {"OK/auto": 0, "OK/eye": 0, "FAIL/auto": 0, "FAIL/eye": 0,
              "ERR": 0, "SKIP": 0, "BLOCKED": 0}
    for status in _STATUS.values():
        counts[status] = counts.get(status, 0) + 1

    lines = [
        f"ИТОГИ smoke#{run_id}  ({cfg['RUN']!r}, ~{minutes} мин)",
        f"ок автоматически ....... {counts['OK/auto']}",
        f"ок глазами ............. {counts['OK/eye']}",
        f"ФЕЙЛОВ ................. {counts['FAIL/auto'] + counts['FAIL/eye']}",
        f"ошибок ................. {counts['ERR']}",
        f"пропущено .............. {counts['SKIP'] + counts['BLOCKED']}",
    ]
    fails = [(sid, note) for sid, note in _FAIL_NOTES.items()
             if _STATUS.get(sid, "").startswith("FAIL")]
    errs = [sid for sid, status in _STATUS.items() if status == "ERR"]
    if fails or errs:
        lines.append("")
        lines.append("ПРОБЛЕМЫ:")
        for sid, note in fails:
            lines.append(f"  {sid} — {note}")
        for sid in errs:
            lines.append(f"  {sid} — ERR (traceback в last_run.log)")
    if ctx.restored:
        lines.append("")
        lines.append("Восстановлено после прогона: " + ", ".join(ctx.restored))

    covered, total, missed, stubs = _coverage(executed)
    lines.append("")
    lines.append(f"ПОКРЫТИЕ МЕТОДОВ: {covered} из {total} живо-проверяемых"
                 f" (+{stubs} заглушек и {len(NOT_LIVE)} юнит-покрытых — вне зачёта)")
    if missed:
        lines.append("не тронуты в этом прогоне: " + ", ".join(missed[:12])
                     + (" ..." if len(missed) > 12 else ""))
    lines.append(f"Подробный лог: {LOG_PATH}")
    console.header(lines)
    return 1 if (fails or errs) else 0

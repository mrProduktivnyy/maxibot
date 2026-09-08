"""
Консоль смоука: печать шагов, вопросы y/n, ожидания. Только ASCII-маркеры
([OK] [FAIL] [SKIP] [ERR] [??]) — консоль PyCharm под Windows (cp1251)
ломает эмодзи и рамки. input() в окне Run работает штатно.
"""
import sys
import time

RULE = "=" * 71


def say(text: str = ""):
    print(text)
    sys.stdout.flush()


def header(lines):
    say(RULE)
    for line in lines:
        say("  " + line)
    say(RULE)


def ask_eye(step_no: int, total: int, text: str):
    """
    Вопрос «глазами» после шага. Возвращает (код, комментарий):
    y — да, n — нет (+комментарий), s — не смог посмотреть, q — стоп.
    ? печатает подсказку повторно (обрабатывается снаружи повтором).
    """
    while True:
        answer = input(
            "        Всё так? [y — да / n — нет / s — не смог посмотреть"
            " / ? — подробности / q — стоп]: "
        ).strip().lower()
        if answer in ("y", "д", "да", "yes", ""):
            return "y", ""
        if answer in ("n", "н", "нет", "no"):
            comment = input("        Что не так (одна строка в отчёт): ").strip()
            return "n", comment
        if answer == "s":
            return "s", ""
        if answer == "q":
            return "q", ""
        if answer == "?":
            return "?", ""
        say("        не понял ответ, ожидаю y / n / s / ? / q")


def prepare(text: str):
    """«Сейчас произойдёт X, смотри в чат» — ждём Enter."""
    input(f"        ГОТОВЬСЯ: {text}\n        Enter, когда смотришь в чат... ")


def countdown_wait(predicate, hint: str, timeout: float, poll: float = 0.5) -> bool:
    """
    Ожидание действия человека: печатает подсказку, опрашивает predicate,
    раз в 15 секунд напоминает, сколько осталось. True — дождались.
    """
    say(f"        ЖДУ: {hint}  (до {int(timeout)} c)")
    deadline = time.monotonic() + timeout
    next_reminder = time.monotonic() + 15
    while time.monotonic() < deadline:
        if predicate():
            return True
        if time.monotonic() >= next_reminder:
            left = int(deadline - time.monotonic())
            say(f"        ...ещё жду ({left} c осталось)")
            next_reminder = time.monotonic() + 15
        time.sleep(poll)
    return bool(predicate())

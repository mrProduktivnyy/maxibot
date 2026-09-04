"""
Проверка констант UpdateType и maxibot.util.update_types по документации
MAX: объект Update (dev.max.ru/docs-api/objects/Update) перечисляет ровно
18 типов обновлений, и message_removed среди них, а message_deleted — нет.

Запуск:
    python3 tests/test_update_types.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maxibot.types import UpdateType
from maxibot.util import update_types

DOCUMENTED = {
    "bot_added", "bot_removed", "bot_started", "bot_stopped", "chat_title_changed",
    "dialog_cleared", "dialog_muted", "dialog_unmuted", "dialog_removed",
    "message_created", "message_edited", "message_removed", "message_callback",
    "comment_created", "comment_edited", "comment_removed", "user_added", "user_removed",
}

# 1. util.update_types — ровно документированный список, без дубликатов
assert set(update_types) == DOCUMENTED and len(update_types) == len(DOCUMENTED), update_types
print('1 ok: util.update_types — 18 типов обновлений из документации MAX')

# 2. Каждая константа UpdateType — реальный тип MAX; фантомов нет
#    (MESSAGE_CHAT_CREATED, которого в документации не было, удалён)
constants = {name: value for name, value in vars(UpdateType).items() if name.isupper()}
for name, value in constants.items():
    assert value in DOCUMENTED, (name, value)
assert not hasattr(UpdateType, "MESSAGE_CHAT_CREATED")
assert UpdateType.MESSAGE_REMOVED == "message_removed"
assert UpdateType.MESSAGE_DELETED == "message_removed"  # прежнее имя: "message_deleted" MAX не присылает
print('2 ok: константы UpdateType соответствуют документации, фантомов нет')

# 3. У каждого документированного типа есть константа
assert DOCUMENTED <= set(constants.values()), DOCUMENTED - set(constants.values())
print('3 ok: у каждого типа обновления есть константа')

print('ALL OK')

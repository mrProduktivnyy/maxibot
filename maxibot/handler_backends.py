"""
Состояния FSM — как `telebot.handler_backends`.

Здесь живут `State` и `StatesGroup`, чтобы телеботовский импорт
переезжал заменой одного слова:

.. code-block:: python3

    from maxibot.handler_backends import State, StatesGroup

    class MyStates(StatesGroup):
        name = State()
        age = State()

Остальных обитателей telebot.handler_backends (BaseMiddleware,
SkipHandler, CancelUpdate, ContinueHandling, *HandlerBackend) в maxibot
пока нет: класс-middleware и продолжение обработки не реализованы,
а бэкенды next_step-хендлеров придут с персистентностью шагов.
"""


class State:
    """
    Одно состояние. Внутри :class:`StatesGroup` получает имя
    ``ИмяГруппы:имя_атрибута`` — оно и хранится в хранилище состояний.

    .. code-block:: python3

        class MyStates(StatesGroup):
            my_state = State()  # str(MyStates.my_state) == 'MyStates:my_state'
    """

    def __init__(self) -> None:
        self.name = None

    def __str__(self) -> str:
        return self.name


class StatesGroup:
    """
    Группа состояний: наследник объявляет атрибуты-:class:`State`,
    и при создании класса каждому проставляются `name`
    (``ИмяГруппы:имя_атрибута``) и `group` (сам класс). Список
    состояний группы — `cls._state_list` (как в telebot).
    """

    def __init_subclass__(cls) -> None:
        state_list = []
        for name, value in cls.__dict__.items():
            if (
                not name.startswith("__")
                and not callable(value)
                and isinstance(value, State)
            ):
                value.name = ":".join((cls.__name__, name))
                value.group = cls
                state_list.append(value)
        cls._state_list = state_list

    @property
    def state_list(self):
        return self._state_list

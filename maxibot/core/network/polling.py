import asyncio
import logging
import traceback

from typing import Callable, List, Optional, Dict, Any

# from api import Api

logger = logging.getLogger("maxibot")


class Polling:
    """
    Класс получения обновлений из API MAX через поллинг
    """

    def __init__(
        self,
        api,
        allowed_updates: Optional[List[str]] = None,
        on_error: Optional[Callable] = None,
    ):
        """
        Инициализация класса

        :param api: Клиент АПИ
        :type api: Api

        :param allowed_updates: Типы обновлений, которые нужно получать
        :type allowed_updates: Optional[List[str]]

        :param on_error: Колбэк отчёта об ошибке (exception, message) —
            MaxiBot передаёт сюда _report_exception, чтобы ошибки поллинга
            уходили в exception_handler; None — просто логирование
        :type on_error: Optional[Callable]
        """
        self.api = api
        self.allowed_updates = allowed_updates
        self.on_error = on_error
        self.is_running = False
        self.marker = None
        self.is_prev_add = False

    def stop(self):
        """
        Метод остановки поллинга
        """
        self.is_running = False

    def _report(self, exception: Exception, message: str):
        """
        Отчёт об ошибке: через on_error бота (exception_handler + логгер),
        без него — в логгер. Вызывается из except-блока.
        """
        if self.on_error is not None:
            self.on_error(exception, message)
        else:
            logger.error("%s: %s", message, exception)
            logger.debug("Exception traceback:\n%s", traceback.format_exc())

    async def loop(self, handler: Callable[[Dict[str, Any]], None]):
        """
        Главный цикл поллинга

        :param handler: Description
        :type handler: Callable[[Dict[str, Any]], None]
        """
        self.is_running = True
        logger.info("Starting polling loop")

        while self.is_running:
            try:
                updates_data = await self._get_updates()
                if "marker" in updates_data.keys():
                    self.marker = updates_data["marker"]
                updates = updates_data.get("updates", [])
                for update in updates:
                    try:
                        if update.get("update_type") == "bot_added" and self.is_prev_add:
                            continue
                        else:
                            if update.get("update_type") == "bot_added":
                                self.is_prev_add = True
                            else:
                                self.is_prev_add = False
                            handler(update)
                    except Exception as e:
                        self._report(e, "Error while processing update")

            except Exception as e:
                self._report(e, "Polling error")
                # пауза, чтобы при недоступности сети не крутиться в горячем
                # цикле с мгновенными повторами запроса
                await asyncio.sleep(3)

    async def _get_updates(self) -> Dict[str, Any]:
        """
        Метод получения обновлений по боту из API MAX

        :return: Description
        :rtype: Dict[str, Any]
        """
        params = {}
        if self.marker is not None:
            params["marker"] = self.marker
        updates_data = await asyncio.to_thread(
            self.api.get_updates,
            self.allowed_updates or [],
            params
        )
        return updates_data

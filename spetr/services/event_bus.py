"""
Barramento de eventos in-process assíncrono.
Permite comunicação completamente desacoplada entre os módulos.
"""
import asyncio
import inspect
import logging
from typing import Callable, Dict, List, Type, Any

logger = logging.getLogger("spetr.services.event_bus")


class EventBus:
    """Barramento de eventos in-memory desacoplado."""

    def __init__(self):
        self._subscribers: Dict[Type, List[Callable]] = {}

    def subscribe(self, event_type: Type, handler: Callable) -> None:
        """Inscreve um callback (síncrono ou assíncrono) para um tipo de evento."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)
            logger.debug(f"Subscrito handler {handler.__name__} para evento {event_type.__name__}")

    def unsubscribe(self, event_type: Type, handler: Callable) -> None:
        """Remove inscrição de um callback."""
        if event_type in self._subscribers and handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    async def publish(self, event: Any) -> None:
        """Publica um evento para todos os inscritos concorrentemente."""
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            return

        tasks = []
        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    tasks.append(self._run_async_handler(handler, event))
                else:
                    # Executa handler síncrono diretamente protegendo exceção
                    try:
                        handler(event)
                    except Exception as e:
                        logger.error(f"Erro no handler síncrono {handler.__name__}: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Erro ao disparar handler {handler}: {e}", exc_info=True)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_async_handler(self, handler: Callable, event: Any):
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Erro no handler assíncrono {handler.__name__}: {e}", exc_info=True)

"""
Controle de Taxa de Requisições (Pacing) e Semáforo de Concorrência.
Garante que o cliente não exceda 12 req/s e 15 conexões simultâneas (evita WAF TSE).
"""
import asyncio
import time
import logging

logger = logging.getLogger("spetr.collector.pacing")


class PacingManager:
    """
    Gerenciador de pacing de rede com semáforo de concorrência e limitador de taxa (Leaky Bucket).
    """

    def __init__(self, max_concurrent: int = 15, max_rate_per_sec: float = 12.0):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.intervalo_minimo = 1.0 / max_rate_per_sec
        self._ultimo_envio = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Adquire o semáforo e aguarda intervalo para respeitar o limite de req/s."""
        await self.semaphore.acquire()
        async with self._lock:
            agora = time.monotonic()
            decorrido = agora - self._ultimo_envio
            if decorrido < self.intervalo_minimo:
                espera = self.intervalo_minimo - decorrido
                await asyncio.sleep(espera)
            self._ultimo_envio = time.monotonic()

    def release(self) -> None:
        """Libera o semáforo."""
        self.semaphore.release()

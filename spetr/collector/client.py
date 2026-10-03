"""
Cliente HTTP assíncrono para a CDN do TSE com suporte a HTTP/2 e cache condicional.
"""
import asyncio
from typing import Dict, Any, Optional, Tuple
import httpx
import logging

from spetr.collector.pacing import PacingManager

logger = logging.getLogger("spetr.collector.client")


class TSEHttpClient:
    """Cliente HTTP com HTTP/2, conditional GET (304) e semáforo de concorrência."""

    def __init__(
        self,
        pacing: Optional[PacingManager] = None,
        timeout: float = 10.0
    ):
        self.pacing = pacing or PacingManager()
        self.timeout = timeout
        self._cache_headers: Dict[str, Dict[str, str]] = {} # url -> {"etag": ..., "last_modified": ...}
        self._cache_payloads: Dict[str, Dict[str, Any]] = {} # url -> payload json
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=True,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "User-Agent": "SPETR-Desktop/1.0 (Pesquisa Eleitoral Estatistica)",
                    "Accept-Encoding": "gzip, deflate",
                    "Accept": "application/json"
                }
            )
        return self._client

    async def fechar(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def fetch_json(self, url: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """
        Executa GET condicional na URL.
        Retorna (payload, foi_modificado).
        Se HTTP 304 (Not Modified), retorna (payload_em_cache, False).
        Se erro irrecuperável, retorna (None, False).
        """
        await self.pacing.acquire()
        client = await self.get_client()

        headers = {}
        if url in self._cache_headers:
            cache_info = self._cache_headers[url]
            if "last_modified" in cache_info:
                headers["If-Modified-Since"] = cache_info["last_modified"]
            if "etag" in cache_info:
                headers["If-None-Match"] = cache_info["etag"]

        try:
            for tentativa in range(3):
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 304:
                        # Conteúdo idêntico ao último ciclo
                        return self._cache_payloads.get(url), False

                    if resp.status_code == 200:
                        payload = resp.json()
                        self._cache_payloads[url] = payload

                        cache_hdr = {}
                        if "Last-Modified" in resp.headers:
                            cache_hdr["last_modified"] = resp.headers["Last-Modified"]
                        if "ETag" in resp.headers:
                            cache_hdr["etag"] = resp.headers["ETag"]
                        self._cache_headers[url] = cache_hdr

                        return payload, True

                    if resp.status_code in (429, 503):
                        # Pacing throttle ou sobrecarga temporária
                        await asyncio.sleep(1.0 * (tentativa + 1))
                        continue

                    # Outros status (404 por ex antes do início da apuração)
                    return None, False

                except httpx.TransportError:
                    if tentativa < 2:
                        await asyncio.sleep(1.0)
                        continue
                    raise

            return None, False

        except Exception as e:
            logger.warning(f"Falha ao consultar {url}: {e}")
            return self._cache_payloads.get(url), False
        finally:
            self.pacing.release()

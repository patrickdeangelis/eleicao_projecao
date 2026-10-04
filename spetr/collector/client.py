"""
Cliente HTTP assíncrono para a CDN do TSE com suporte a HTTP/2 e cache condicional.
"""
import asyncio
from typing import Dict, Any, NamedTuple, Optional
import httpx
import logging

from spetr.collector.pacing import PacingManager
from spetr.collector.jws import JWSVerifier, JWSInvalidoError

logger = logging.getLogger("spetr.collector.client")


class ResultadoFetch(NamedTuple):
    payload: Optional[Dict[str, Any]]
    modificado: bool
    falhou: bool  # True quando o payload (se houver) é cópia antiga do cache por falha na consulta


class TSEHttpClient:
    """Cliente HTTP com HTTP/2, conditional GET (304), pacing e verificação JWS opcional."""

    def __init__(
        self,
        pacing: Optional[PacingManager] = None,
        timeout: float = 10.0,
        verificador_jws: Optional[JWSVerifier] = None,
    ):
        self.pacing = pacing or PacingManager()
        self.timeout = timeout
        self.verificador_jws = verificador_jws
        self._cache_headers: Dict[str, Dict[str, str]] = {} # url -> {"etag": ..., "last_modified": ...}
        self._cache_payloads: Dict[str, Dict[str, Any]] = {} # url -> payload json
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": "SPETR-Desktop/1.0 (Pesquisa Eleitoral Estatistica)",
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json"
            }
            timeout = httpx.Timeout(self.timeout)
            try:
                self._client = httpx.AsyncClient(
                    http2=True,
                    timeout=timeout,
                    headers=headers
                )
            except ImportError:
                logger.warning("Pacote 'h2' ausente para HTTP/2; utilizando HTTP/1.1.")
                self._client = httpx.AsyncClient(
                    http2=False,
                    timeout=timeout,
                    headers=headers
                )
        return self._client


    async def fechar(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _decodificar(self, resp: httpx.Response, assinado: bool) -> Dict[str, Any]:
        if assinado:
            return self.verificador_jws.verificar(resp.text)
        return resp.json()

    async def fetch_json(self, url: str, verificar_assinatura: bool = True) -> ResultadoFetch:
        """
        Executa GET condicional na URL.
        - 200: (payload, True, False)
        - 304: (payload_em_cache, False, False)
        - falha: (payload_em_cache_ou_None, False, True)
        Com verificação JWS ativa, baixa o par '.jws' do arquivo '.json' e valida a assinatura.
        """
        assinado = verificar_assinatura and self.verificador_jws is not None and url.endswith(".json")
        url_req = url[: -len(".json")] + ".jws" if assinado else url

        client = await self.get_client()

        headers = {}
        if url_req in self._cache_headers:
            cache_info = self._cache_headers[url_req]
            if "last_modified" in cache_info:
                headers["If-Modified-Since"] = cache_info["last_modified"]
            if "etag" in cache_info:
                headers["If-None-Match"] = cache_info["etag"]

        for tentativa in range(3):
            # Cada tentativa (inclusive retentativas) passa pelo controle de taxa
            await self.pacing.acquire()
            try:
                resp = await client.get(url_req, headers=headers)
            except httpx.TransportError as e:
                if tentativa < 2:
                    await asyncio.sleep(1.0 * (tentativa + 1))
                    continue
                logger.warning(f"Falha de rede ao consultar {url_req}: {e}")
                break
            except Exception as e:
                # Erro inesperado (ex.: cabeçalho inválido) conta como falha desta URL,
                # sem derrubar o ciclo inteiro de coleta
                logger.warning(f"Erro ao consultar {url_req}: {e!r}")
                self._cache_headers.pop(url_req, None)
                break
            finally:
                self.pacing.release()

            if resp.status_code == 304:
                # Conteúdo idêntico ao último ciclo
                return ResultadoFetch(self._cache_payloads.get(url_req), False, False)

            if resp.status_code == 200:
                try:
                    payload = self._decodificar(resp, assinado)
                except JWSInvalidoError as e:
                    logger.error(f"Assinatura JWS rejeitada para {url_req}: {e}")
                    break
                except ValueError as e:
                    logger.warning(f"Resposta inválida de {url_req}: {e}")
                    break

                self._cache_payloads[url_req] = payload
                cache_hdr = {}
                for origem, destino in (("Last-Modified", "last_modified"), ("ETag", "etag")):
                    valor = resp.headers.get(origem)
                    # Só reaproveita validadores ASCII (o que o HTTP permite reenviar)
                    if valor and valor.isascii():
                        cache_hdr[destino] = valor
                self._cache_headers[url_req] = cache_hdr
                return ResultadoFetch(payload, True, False)

            if resp.status_code in (429, 503):
                # Pacing throttle ou sobrecarga temporária
                await asyncio.sleep(1.0 * (tentativa + 1))
                continue

            # Outros status (404 por ex antes do início da apuração)
            logger.debug(f"HTTP {resp.status_code} em {url_req}")
            break

        return ResultadoFetch(self._cache_payloads.get(url_req), False, True)

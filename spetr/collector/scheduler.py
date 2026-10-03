"""
Agendador de Coleta Escalonada (Tiered Polling Scheduler).
Coordena o ritmo de requisições:
- Tier 1: 27 UFs + 27 Capitais a cada 15 segundos
- Tier 2: ~127 Cidades > 100k a cada 30 segundos
"""
import asyncio
import datetime
from typing import Dict, List, Optional, Any
import logging

from spetr.domain.interfaces import ICollector, IEventBus
from spetr.collector.client import TSEHttpClient
from spetr.services.events import RawBatchReceivedEvent, CollectionErrorEvent

logger = logging.getLogger("spetr.collector.scheduler")


class TieredScheduler(ICollector):
    """
    Agendador de coleta escalonada de dados da CDN do TSE.
    """

    def __init__(
        self,
        event_bus: Optional[IEventBus] = None,
        http_client: Optional[TSEHttpClient] = None,
        base_url: str = "https://resultados.tse.jus.br",
        ano_eleicao: str = "2022",
        codigo_eleicao: str = "545",  # 2º turno presidencial de 2022 por padrão
        codigo_cargo: str = "0001",   # 0001 = Presidente
        intervalo_tier1: float = 15.0,
        intervalo_tier2: float = 30.0,
    ):
        self.bus = event_bus
        self.http_client = http_client or TSEHttpClient()
        self.base_url = base_url.rstrip("/")
        self.ano = ano_eleicao
        self.cod_eleicao = codigo_eleicao
        self.cod_cargo = codigo_cargo
        self.intervalo_tier1 = intervalo_tier1
        self.intervalo_tier2 = intervalo_tier2


        self.ufs: List[str] = [
            "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
            "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
            "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"
        ]
        # { "PB": ["20516", "19852"], ... }
        self.cidades_por_uf: Dict[str, List[str]] = {}
        self.capitais_por_uf: Dict[str, str] = {}

        self._rodando = False
        self._ciclo_contador = 0
        self._tarefa_loop: Optional[asyncio.Task] = None

    def configurar_alvos(
        self,
        cidades_por_uf: Dict[str, List[str]],
        capitais_por_uf: Dict[str, str]
    ) -> None:
        self.cidades_por_uf = cidades_por_uf
        self.capitais_por_uf = capitais_por_uf

    def url_uf(self, uf: str) -> str:
        u = uf.lower()
        return (
            f"{self.base_url}/oficial/ele{self.ano}/{self.cod_eleicao}/"
            f"dados-simplificados/{u}/{u}-c{self.cod_cargo}-e000{self.cod_eleicao}-r.json"
        )

    def url_municipio(self, uf: str, cod_mun: str) -> str:
        u = uf.lower()
        return (
            f"{self.base_url}/oficial/ele{self.ano}/{self.cod_eleicao}/"
            f"dados-simplificados/{u}/{u}{cod_mun}-c{self.cod_cargo}-e000{self.cod_eleicao}-r.json"
        )


    async def executar_ciclo_coleta(self, incluir_tier2: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        Executa um lote de consultas com semáforo e conditional caching.
        Retorna dicionário contendo os payloads brutos obtidos.
        """
        urls_tarefas = []

        # 1. Tier 1: Todas as 27 UFs
        for uf in self.ufs:
            chave = f"UF_{uf}"
            url = self.url_uf(uf)
            urls_tarefas.append((chave, url))

        # 2. Tier 1: Capitais
        for uf, cod_cap in self.capitais_por_uf.items():
            chave = f"MUN_{uf}_{cod_cap}"
            url = self.url_municipio(uf, cod_cap)
            urls_tarefas.append((chave, url))

        # 3. Tier 2: Cidades restantes > 100k
        if incluir_tier2:
            for uf, codigos in self.cidades_por_uf.items():
                cap = self.capitais_por_uf.get(uf)
                for cod in codigos:
                    if cod != cap:
                        chave = f"MUN_{uf}_{cod}"
                        url = self.url_municipio(uf, cod)
                        urls_tarefas.append((chave, url))

        async def consultar_item(chave: str, url: str):
            payload, modificado = await self.http_client.fetch_json(url)
            return chave, payload, modificado

        resultados = await asyncio.gather(*[consultar_item(k, u) for k, u in urls_tarefas])

        batch: Dict[str, Dict[str, Any]] = {}
        total_modificados = 0
        for chave, payload, modificado in resultados:
            if payload is not None:
                batch[chave] = payload
                if modificado:
                    total_modificados += 1

        return batch

    async def iniciar_loop(self) -> None:
        """Inicia o loop contínuo de polling com o agendamento escalonado."""
        self._rodando = True
        logger.info("Iniciando loop do TieredScheduler...")

        while self._rodando:
            self._ciclo_contador += 1
            # A cada 2 ciclos (a cada 30s), fazemos o Tier 2
            incluir_tier2 = (self._ciclo_contador % 2 == 0)

            try:
                batch = await self.executar_ciclo_coleta(incluir_tier2=incluir_tier2)
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if self.bus is not None and batch:
                    await self.bus.publish(
                        RawBatchReceivedEvent(
                            timestamp=ts,
                            ciclo_id=self._ciclo_contador,
                            total_arquivos=len(batch),
                            arquivos_modificados=len(batch),
                            payload_bruto=batch
                        )
                    )
            except Exception as e:
                logger.error(f"Erro no ciclo de coleta do scheduler: {e}", exc_info=True)
                if self.bus is not None:
                    await self.bus.publish(
                        CollectionErrorEvent(
                            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            origem="TieredScheduler",
                            mensagem=str(e)
                        )
                    )

            await asyncio.sleep(self.intervalo_tier1)

    def parar(self) -> None:
        """Sinaliza para parar o loop."""
        self._rodando = False

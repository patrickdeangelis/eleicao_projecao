"""
Agendador de Coleta Escalonada (Tiered Polling Scheduler).
Coordena o ritmo de requisições:
- Tier 1: UFs + Capitais a cada `intervalo_tier1` segundos
- Tier 2: demais cidades > 100k a cada `intervalo_tier2` segundos (o 1º ciclo sempre inclui o Tier 2)
- Exterior: as cidades do exterior (resultado por país) a cada `intervalo_exterior` segundos
- Subestratos: os municípios que dividem o interior de uma UF (ex.: Norte de MG) a cada
  `intervalo_subestratos` segundos; esse ciclo sempre inclui o Tier 2, para o agregador receber
  a UF, todas as cidades e o grupo no mesmo lote
- Arquivos de município com 100% das seções apuradas deixam de ser pedidos: o lote reaproveita a
  última cópia e o arquivo só é conferido de novo a cada `intervalo_reconferir` segundos
- Com todas as UFs em 100% das seções, faz `coletas_extras_apos_100` coletas a mais por segurança (relendo
  também os municípios já concluídos) e encerra o loop: a apuração terminou e não há por que seguir baixando
- Arquivo de município que responde 404 fica suspenso por `suspensao_404` segundos: muitos 404
  podem bloquear o IP no TSE (ex.: coleta iniciada antes de os arquivos serem publicados)

Formatos de URL suportados:
- "u" (Eleições 2024+, Resultado Unificado EA20):
  {base}/{ambiente}/ele{ano}/{eleicao}/dados/{uf}/{uf}{mun}-c{cargo:04}-e{eleicao:06}-u.json
- "r" (Eleições até 2022, Dados Simplificados):
  {base}/{ambiente}/ele{ano}/{eleicao}/dados-simplificados/{uf}/{uf}{mun}-c{cargo:04}-e{eleicao:06}-r.json
"""
import asyncio
import datetime
import time
from typing import Dict, List, Optional, Any
import logging

from spetr.domain.interfaces import ICollector, IEventBus
from spetr.collector.client import TSEHttpClient
from spetr.collector.parser import secoes_concluidas
from spetr.services.events import RawBatchReceivedEvent, CollectionErrorEvent, CollectionFinishedEvent

logger = logging.getLogger("spetr.collector.scheduler")

FORMATOS_VALIDOS = ("u", "r")


class TieredScheduler(ICollector):
    """
    Agendador de coleta escalonada de dados da CDN do TSE.
    """

    def __init__(
        self,
        event_bus: Optional[IEventBus] = None,
        http_client: Optional[TSEHttpClient] = None,
        base_url: str = "https://resultados.tse.jus.br",
        ano_eleicao: str = "2026",
        codigo_eleicao: Optional[str] = None,  # None = descobrir via ele-c.json (formato "u")
        codigo_cargo: str = "1",              # 1 = Presidente
        turno: int = 1,
        formato: str = "u",
        ambiente: str = "oficial",
        intervalo_tier1: float = 15.0,
        intervalo_tier2: float = 30.0,
        intervalo_exterior: float = 120.0,
        intervalo_subestratos: float = 60.0,
        intervalo_reconferir: float = 600.0,
        suspensao_404: float = 300.0,
        parar_ao_concluir: bool = True,
        coletas_extras_apos_100: int = 2,
    ):
        if formato not in FORMATOS_VALIDOS:
            raise ValueError(f"Formato inválido: '{formato}'. Opções: {FORMATOS_VALIDOS}")
        self.bus = event_bus
        self.http_client = http_client or TSEHttpClient()
        self.base_url = base_url.rstrip("/")
        self.ano = str(ano_eleicao)
        self.cod_eleicao = str(codigo_eleicao) if codigo_eleicao else None
        self.cod_cargo = str(int(codigo_cargo))
        self.turno = int(turno)
        self.formato = formato
        self.ambiente = ambiente.strip("/")
        self.intervalo_tier1 = intervalo_tier1
        self.intervalo_tier2 = intervalo_tier2
        self.intervalo_exterior = intervalo_exterior
        self.cidades_exterior: List[str] = []
        self._ultimo_exterior: Optional[float] = None
        self.intervalo_subestratos = intervalo_subestratos
        self.municipios_subestratos: Dict[str, List[str]] = {}
        self._ultimo_subestratos: Optional[float] = None
        self.intervalo_reconferir = intervalo_reconferir
        # chave do arquivo -> instante em que foi visto com 100% das seções
        self._concluidos: Dict[str, float] = {}
        self.requisicoes_poupadas = 0
        self.suspensao_404 = suspensao_404
        self._suspensos: Dict[str, float] = {}  # chave -> instante até quando não pedir
        self.parar_ao_concluir = parar_ao_concluir
        self.coletas_extras_apos_100 = coletas_extras_apos_100
        self._coletas_em_100 = 0  # coletas seguidas com todas as UFs em 100% (1 = a que viu o 100%)

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
        self._ultimo_tier2: Optional[float] = None
        self._tarefa_loop: Optional[asyncio.Task] = None

    def configurar_alvos(
        self,
        cidades_por_uf: Dict[str, List[str]],
        capitais_por_uf: Dict[str, str],
        cidades_exterior: Optional[List[str]] = None,
        municipios_subestratos: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self.cidades_por_uf = cidades_por_uf
        self.capitais_por_uf = capitais_por_uf
        self.cidades_exterior = list(cidades_exterior or [])
        self.municipios_subestratos = {uf: list(c) for uf, c in (municipios_subestratos or {}).items()}

    # ------------------------------------------------------------------ URLs

    @property
    def url_config_eleicoes(self) -> str:
        return f"{self.base_url}/{self.ambiente}/comum/config/ele-c.json"

    def _url_arquivo(self, uf: str, cod_mun: str = "") -> str:
        if self.cod_eleicao is None:
            raise RuntimeError("Código da eleição ainda não definido (use --eleicao ou aguarde a descoberta)")
        u = uf.lower()
        cargo = self.cod_cargo.zfill(4)
        eleicao6 = self.cod_eleicao.zfill(6)
        pasta = "dados" if self.formato == "u" else "dados-simplificados"
        return (
            f"{self.base_url}/{self.ambiente}/ele{self.ano}/{self.cod_eleicao}/{pasta}/{u}/"
            f"{u}{cod_mun}-c{cargo}-e{eleicao6}-{self.formato}.json"
        )

    def url_uf(self, uf: str) -> str:
        return self._url_arquivo(uf)

    def url_municipio(self, uf: str, cod_mun: str) -> str:
        return self._url_arquivo(uf, cod_mun)

    # ----------------------------------------------------- Descoberta (EA11)

    @staticmethod
    def escolher_eleicao(config: Dict[str, Any], ano: str, cargo: str, turno: int) -> Optional[str]:
        """Seleciona no ele-c.json (EA11) o código da eleição do ciclo/cargo/turno pedidos."""
        ciclo = f"ele{ano}"
        for pleito in config.get("pl", []):
            if pleito.get("c") != ciclo:
                continue
            for eleicao in pleito.get("e", []):
                if str(eleicao.get("t", "")) != str(turno):
                    continue
                cargos = {
                    str(cp.get("cd"))
                    for abr in eleicao.get("abr", [])
                    for cp in abr.get("cp", [])
                }
                if cargo in cargos:
                    return str(eleicao.get("cd"))
        return None

    async def resolver_eleicao(self) -> bool:
        """Garante que o código da eleição está definido. Retorna True se pronto para coletar."""
        if self.cod_eleicao is not None:
            return True
        resultado = await self.http_client.fetch_json(self.url_config_eleicoes, verificar_assinatura=False)
        if resultado.payload is None:
            logger.error(f"Não foi possível baixar {self.url_config_eleicoes} para descobrir a eleição.")
            return False
        cod = self.escolher_eleicao(resultado.payload, self.ano, self.cod_cargo, self.turno)
        if cod is None:
            logger.error(
                f"Nenhuma eleição em ele{self.ano} com cargo {self.cod_cargo} e turno {self.turno} "
                f"no arquivo de configuração. Informe --eleicao manualmente."
            )
            return False
        self.cod_eleicao = cod
        logger.info(f"Eleição descoberta via ele-c.json: {cod} (ele{self.ano}, cargo {self.cod_cargo}, {self.turno}º turno)")
        return True

    # ----------------------------------------------------------------- Coleta

    async def executar_ciclo_coleta(self, incluir_tier2: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        Executa um lote de consultas com semáforo e conditional caching.
        Retorna dicionário contendo os payloads brutos obtidos.
        """
        batch, _, _ = await self._coletar(incluir_tier2)
        return batch

    async def _coletar(self, incluir_tier2: bool, incluir_exterior: bool = False, incluir_subestratos: bool = False):
        urls_tarefas = []

        # 1. Tier 1: Todas as UFs (+ exterior)
        for uf in self.ufs:
            urls_tarefas.append((f"UF_{uf}", self.url_uf(uf)))

        # 2. Tier 1: Capitais
        for uf, cod_cap in self.capitais_por_uf.items():
            urls_tarefas.append((f"MUN_{uf}_{cod_cap}", self.url_municipio(uf, cod_cap)))

        # 3. Tier 2: Cidades restantes > 100k
        if incluir_tier2:
            for uf, codigos in self.cidades_por_uf.items():
                cap = self.capitais_por_uf.get(uf)
                for cod in codigos:
                    if cod != cap:
                        urls_tarefas.append((f"MUN_{uf}_{cod}", self.url_municipio(uf, cod)))

        # 4. Cidades do exterior (não entram na projeção; só no detalhamento por país)
        if incluir_exterior:
            for cod in self.cidades_exterior:
                urls_tarefas.append((f"MUN_ZZ_{cod}", self.url_municipio("ZZ", cod)))

        # 5. Municípios que dividem o interior das UFs subestratificadas
        if incluir_subestratos:
            for uf, codigos in self.municipios_subestratos.items():
                for cod in codigos:
                    urls_tarefas.append((f"MUN_{uf}_{cod}", self.url_municipio(uf, cod)))

        agora = time.monotonic()
        a_pedir, reaproveitados = [], []
        for chave, url in urls_tarefas:
            if self._suspensos.get(chave, 0.0) > agora:
                payload = self.http_client.payload_em_cache(url)
                if payload is not None:
                    reaproveitados.append((chave, payload))
                continue
            visto = self._concluidos.get(chave)
            if visto is not None and agora - visto < self.intervalo_reconferir:
                payload = self.http_client.payload_em_cache(url)
                if payload is not None:
                    reaproveitados.append((chave, payload))
                    continue
            a_pedir.append((chave, url))
        self.requisicoes_poupadas += len(reaproveitados)

        async def consultar_item(chave: str, url: str):
            return chave, await self.http_client.fetch_json(url)

        resultados = await asyncio.gather(*[consultar_item(k, u) for k, u in a_pedir])

        batch: Dict[str, Dict[str, Any]] = {}
        total_modificados = 0
        falhas: List[str] = []
        suspensos_agora = []
        for chave, res in resultados:
            if res.falhou and res.status == 404 and chave.startswith("MUN_"):
                self._suspensos[chave] = time.monotonic() + self.suspensao_404
                suspensos_agora.append(chave)
            if res.falhou:
                falhas.append(chave)
            if res.payload is not None:
                batch[chave] = res.payload
                if res.modificado:
                    total_modificados += 1
                # Só arquivos de município param de ser pedidos; UFs são sempre consultadas
                if chave.startswith("MUN_") and not res.falhou:
                    if secoes_concluidas(res.payload):
                        self._concluidos.setdefault(chave, time.monotonic())
                        if time.monotonic() - self._concluidos[chave] >= self.intervalo_reconferir:
                            self._concluidos[chave] = time.monotonic()
                    else:
                        self._concluidos.pop(chave, None)
        for chave, payload in reaproveitados:
            batch[chave] = payload
        if suspensos_agora:
            logger.warning(
                f"{len(suspensos_agora)} arquivo(s) de município com HTTP 404 suspensos por "
                f"{self.suspensao_404:.0f}s: {', '.join(suspensos_agora[:5])}{'...' if len(suspensos_agora) > 5 else ''}"
            )

        return batch, total_modificados, falhas

    async def iniciar_loop(self) -> None:
        """Inicia o loop contínuo de polling com o agendamento escalonado."""
        self._rodando = True
        logger.info("Iniciando loop do TieredScheduler...")

        while self._rodando:
            try:
                if not await self.resolver_eleicao():
                    await self._publicar_erro("Código da eleição indefinido; nova tentativa no próximo ciclo")
                    await asyncio.sleep(self.intervalo_tier1)
                    continue

                self._ciclo_contador += 1
                agora = time.monotonic()
                incluir_tier2 = (
                    self._ultimo_tier2 is None
                    or agora - self._ultimo_tier2 >= self.intervalo_tier2 - 0.5
                )
                incluir_subestratos = bool(self.municipios_subestratos) and (
                    self._ultimo_subestratos is None
                    or agora - self._ultimo_subestratos >= self.intervalo_subestratos - 0.5
                )
                if incluir_subestratos:
                    self._ultimo_subestratos = agora
                    incluir_tier2 = True
                if incluir_tier2:
                    self._ultimo_tier2 = agora
                incluir_exterior = bool(self.cidades_exterior) and (
                    self._ultimo_exterior is None or agora - self._ultimo_exterior >= self.intervalo_exterior - 0.5
                )
                if incluir_exterior:
                    self._ultimo_exterior = agora

                batch, modificados, falhas = await self._coletar(incluir_tier2, incluir_exterior, incluir_subestratos)
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if falhas:
                    sem_dados = [k for k in falhas if k not in batch]
                    logger.warning(
                        f"Ciclo {self._ciclo_contador}: {len(falhas)} arquivo(s) falharam "
                        f"({len(sem_dados)} sem nenhum dado em cache): {', '.join(falhas[:10])}"
                        f"{'...' if len(falhas) > 10 else ''}"
                    )
                    await self._publicar_erro(
                        f"{len(falhas)} arquivo(s) falharam no ciclo {self._ciclo_contador}; "
                        f"{len(sem_dados)} sem dado algum"
                    )

                if self.bus is not None and batch:
                    await self.bus.publish(
                        RawBatchReceivedEvent(
                            timestamp=ts,
                            ciclo_id=self._ciclo_contador,
                            total_arquivos=len(batch),
                            arquivos_modificados=modificados,
                            payload_bruto=batch
                        )
                    )

                if self.parar_ao_concluir:
                    if self._todas_ufs_concluidas(batch, falhas):
                        self._coletas_em_100 += 1
                        if self._coletas_em_100 == 1:
                            # Coletas extras releem tudo, inclusive os municípios que já estavam concluídos
                            self._concluidos.clear()
                            logger.info(f"Apuração em 100%: mais {self.coletas_extras_apos_100} coleta(s) de segurança e a coleta encerra.")
                        if self._coletas_em_100 > self.coletas_extras_apos_100:
                            await self._publicar_encerramento(ts)
                            self._rodando = False
                            break
                    else:
                        self._coletas_em_100 = 0
            except Exception as e:
                logger.error(f"Erro no ciclo de coleta do scheduler: {e}", exc_info=True)
                await self._publicar_erro(str(e))

            await asyncio.sleep(self.intervalo_tier1)

    def _todas_ufs_concluidas(self, batch: Dict[str, Dict[str, Any]], falhas: List[str]) -> bool:
        """True quando o arquivo de cada UF veio (sem falha neste ciclo) com 100% das seções apuradas."""
        for uf in self.ufs:
            chave = f"UF_{uf}"
            if chave in falhas or not secoes_concluidas(batch.get(chave)):
                return False
        return True

    async def _publicar_encerramento(self, ts: str) -> None:
        mensagem = "Apuração em 100%: coleta encerrada"
        logger.info(f"{mensagem} (ciclo {self._ciclo_contador}, após {self.coletas_extras_apos_100} coleta(s) extra(s)).")
        if self.bus is not None:
            await self.bus.publish(CollectionFinishedEvent(timestamp=ts, ciclo_id=self._ciclo_contador, mensagem=mensagem))

    async def _publicar_erro(self, mensagem: str) -> None:
        if self.bus is not None:
            await self.bus.publish(
                CollectionErrorEvent(
                    timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    origem="TieredScheduler",
                    mensagem=mensagem
                )
            )

    def parar(self) -> None:
        """Sinaliza para parar o loop."""
        self._rodando = False

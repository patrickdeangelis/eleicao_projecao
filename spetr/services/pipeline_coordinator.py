"""
Coordenador do Pipeline Analítico do SPETR.
Inicializa e liga os componentes através do EventBus e carrega os metadados iniciais.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
import logging

from spetr.domain.entities import EstratoEleitoral, Candidato
from spetr.domain.value_objects import TipoEstrato
from spetr.services.event_bus import EventBus
from spetr.services.events import ProjectionCalculatedEvent, RawBatchReceivedEvent, StrataNormalizedEvent
from spetr.aggregator.vector_subtraction import VectorAggregator
from spetr.stats_engine.monte_carlo import MonteCarloProjectionEngine
from spetr.storage.database import SQLiteDatabase
from spetr.storage.repository import ElectionRepository
from spetr.collector.client import TSEHttpClient
from spetr.collector.scheduler import TieredScheduler

logger = logging.getLogger("spetr.services.coordinator")

DATA_DIR = Path(__file__).parent.parent / "data"


class PipelineCoordinator:
    """Orquestrador do ciclo analítico do SPETR."""

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        db_path: str = "spetr_eleicoes.sqlite",
        num_simulacoes: int = 10000,
        tse_base_url: str = "https://resultados.tse.jus.br",
        ano_eleicao: str = "2026",
        codigo_eleicao: Optional[str] = None,
        codigo_cargo: str = "1",
        turno: int = 1,
        formato: str = "u",
        ambiente: str = "oficial",
        http_client: Optional[TSEHttpClient] = None,
        intervalo_tier1: float = 15.0,
        intervalo_tier2: float = 30.0,
        intervalo_exterior: float = 120.0,
        intervalo_subestratos: float = 60.0,
        rotulo_eleicao: Optional[str] = None,
    ):
        self.bus = event_bus or EventBus()
        self.db = SQLiteDatabase(db_path)
        self.scheduler = TieredScheduler(
            event_bus=self.bus,
            http_client=http_client,
            base_url=tse_base_url,
            ano_eleicao=ano_eleicao,
            codigo_eleicao=codigo_eleicao,
            codigo_cargo=codigo_cargo,
            turno=turno,
            formato=formato,
            ambiente=ambiente,
            intervalo_tier1=intervalo_tier1,
            intervalo_tier2=intervalo_tier2,
            intervalo_exterior=intervalo_exterior,
            intervalo_subestratos=intervalo_subestratos,
        )
        self.repo = ElectionRepository(
            self.db,
            event_bus=self.bus,
            eleicao=rotulo_eleicao or f"{ambiente}/ele{ano_eleicao}/{codigo_eleicao or 'auto'}/c{codigo_cargo}/t{turno}",
        )
        self.aggregator = VectorAggregator(event_bus=self.bus)
        self.engine = MonteCarloProjectionEngine(event_bus=self.bus, num_simulacoes=num_simulacoes)


        self._carregar_metadados_iniciais()

    async def desligar(self) -> None:
        """Para a coleta e desconecta os componentes do barramento (troca de modo sem reiniciar)."""
        self.scheduler.parar()
        self.bus.unsubscribe(RawBatchReceivedEvent, self.aggregator.ao_receber_lote_bruto)
        self.bus.unsubscribe(StrataNormalizedEvent, self.engine.ao_receber_estratos_normalizados)
        self.bus.unsubscribe(StrataNormalizedEvent, self.repo._ao_normalizar_estratos)
        self.bus.unsubscribe(ProjectionCalculatedEvent, self.repo._ao_calcular_projecao)
        await self.scheduler.http_client.fechar()

    @staticmethod
    def _cidades_por_grupo(cfg: Dict, cidades_uf: List[str]) -> Dict[str, List[str]]:
        """
        Cidades grandes da UF por grupo: as listadas em cada grupo e, no resto, todas as demais.
        Vazio se a configuração não lista cidades (a UF só subestratifica o interior).
        """
        listadas = {ch: list(g.get("cidades", {})) for ch, g in cfg["grupos"].items()}
        if not any(listadas.values()):
            return {}
        usadas = {c for cods in listadas.values() for c in cods}
        fora = [c for c in usadas if c not in cidades_uf]
        if fora:
            raise ValueError(f"Subestratos: cidades fora da lista de cidades grandes da UF: {fora}")
        listadas[cfg["resto"]["chave"]] = [c for c in cidades_uf if c not in usadas]
        return listadas

    def _carregar_metadados_iniciais(self) -> None:
        """Carrega arquivos JSON de UFs, cidades > 100k e priors."""
        ufs_file = DATA_DIR / "ufs_metadados.json"
        cidades_file = DATA_DIR / "cidades_100k.json"
        priors_file = DATA_DIR / "priors_eleicao.json"
        municipios_file = DATA_DIR / "municipios_meta.json"
        exterior_file = DATA_DIR / "exterior_cidades.json"
        subestratos_file = DATA_DIR / "subestratos.json"

        cidades_por_uf: Dict[str, List[str]] = {}
        capitais_por_uf: Dict[str, str] = {}
        ufs_data = {}
        priors_data = {}

        if ufs_file.exists():
            with open(ufs_file, "r", encoding="utf-8") as f:
                ufs_data = json.load(f)
            for uf, d in ufs_data.items():
                if "capital_cod" in d:
                    capitais_por_uf[uf] = d["capital_cod"]

        if cidades_file.exists():
            with open(cidades_file, "r", encoding="utf-8") as f:
                cidades_por_uf = json.load(f)

        municipios_meta: Dict[str, Dict] = {}
        if municipios_file.exists():
            with open(municipios_file, "r", encoding="utf-8") as f:
                municipios_meta = json.load(f)

        if priors_file.exists():
            with open(priors_file, "r", encoding="utf-8") as f:
                priors_data = json.load(f)

        exterior: Dict[str, Dict] = {}
        if exterior_file.exists():
            with open(exterior_file, "r", encoding="utf-8") as f:
                exterior = json.load(f)

        subestratos: Dict[str, Dict] = {}
        if subestratos_file.exists():
            with open(subestratos_file, "r", encoding="utf-8") as f:
                subestratos = json.load(f)
        # Só subestratifica UFs que já têm cidades estratificadas (o Interior vem da subtração)
        subestratos = {uf: cfg for uf, cfg in subestratos.items() if cidades_por_uf.get(uf)}

        # Configura o agregador e o coletor
        self.aggregator.configurar_cidades(cidades_por_uf)
        self.aggregator.configurar_exterior(exterior)
        cidades_sub = {uf: self._cidades_por_grupo(cfg, cidades_por_uf[uf]) for uf, cfg in subestratos.items()}
        self.aggregator.configurar_subestratos({
            uf: {"grupos": {ch: list(g["municipios"]) for ch, g in cfg["grupos"].items()}, "resto": cfg["resto"]["chave"],
                 "cidades": cidades_sub[uf]}
            for uf, cfg in subestratos.items()
        })
        self.scheduler.configurar_alvos(
            cidades_por_uf, capitais_por_uf, cidades_exterior=list(exterior),
            municipios_subestratos={uf: [c for g in cfg["grupos"].values() for c in g["municipios"]]
                                    for uf, cfg in subestratos.items()},
        )

        # Monta a lista de estratos para o motor estatístico

        estratos: List[EstratoEleitoral] = []
        priors_especiais = priors_data.get("priors_especiais", {})
        # Priors que não cobrem todos os candidatos do pleito são ignorados pelo motor
        priors_padrao = priors_data.get("priors_padrao", {})

        for uf, d_uf in ufs_data.items():
            codigos_cidades = cidades_por_uf.get(uf, [])
            total_eleit_uf = d_uf.get("eleitores", 1000000)
            total_sec_uf = d_uf.get("secoes", 3000)

            if codigos_cidades:
                # Estratos de cidades com eleitorado oficial (municipios_meta.json). Para cidade
                # sem cadastro, estimamos capital = 35% e demais = 10% da UF, reescalando para que
                # as cidades nunca somem mais de 70% do estado. (Só vale até chegar o dado do TSE.)
                capital = capitais_por_uf.get(uf)
                pesos = {cod: (0.35 if cod == capital else 0.10) for cod in codigos_cidades}
                escala = min(1.0, 0.70 / sum(pesos.values()))
                eleitores_cidades_soma = 0
                secoes_cidades_soma = 0
                for cod in codigos_cidades:
                    eid = f"{uf}_{cod}"
                    prior = priors_especiais.get(eid, priors_padrao)
                    meta_mun = municipios_meta.get(eid)
                    if meta_mun:
                        eleit_cid = int(meta_mun["eleitores"])
                        sec_cid = int(meta_mun["secoes"])
                        self.engine.nomes_estratos[eid] = meta_mun["nome"].title()
                    else:
                        eleit_cid = int(total_eleit_uf * pesos[cod] * escala)
                        sec_cid = int(total_sec_uf * pesos[cod] * escala)
                    eleitores_cidades_soma += eleit_cid
                    secoes_cidades_soma += sec_cid

                    estratos.append(
                        EstratoEleitoral(
                            id=eid,
                            uf=uf,
                            nome=self.engine.nomes_estratos.get(eid, f"{uf} - Município {cod}"),
                            eleitores_aptos=eleit_cid,
                            secoes_totais=sec_cid,
                            tipo=TipoEstrato.CAPITAL if cod == capitais_por_uf.get(uf) else TipoEstrato.GRANDE_CIDADE,
                            prior_alpha=prior
                        )
                    )

                # Estrato Interior Remanescente
                eid_int = f"{uf}_INTERIOR"
                self.engine.nomes_estratos[eid_int] = f"Interior ({uf})"
                prior_int = priors_especiais.get(eid_int, priors_padrao)
                eleit_int = max(1000, total_eleit_uf - eleitores_cidades_soma)
                sec_int = max(10, total_sec_uf - secoes_cidades_soma)
                estratos.append(
                    EstratoEleitoral(
                        id=eid_int,
                        uf=uf,
                        nome=f"{uf} - Interior Remanescente",
                        eleitores_aptos=eleit_int,
                        secoes_totais=sec_int,
                        tipo=TipoEstrato.INTERIOR_REMANESCENTE,
                        prior_alpha=prior_int
                    )
                )

                # Subestratos do interior (grupos listados + resto = Interior - grupos)
                cfg_sub = subestratos.get(uf)
                if cfg_sub:
                    eleit_grupos = sec_grupos = 0
                    partes = []
                    for chave, g in cfg_sub["grupos"].items():
                        el = sum(int(m.get("eleitores", 0)) for m in g["municipios"].values())
                        sc = sum(int(m.get("secoes", 0)) for m in g["municipios"].values())
                        eleit_grupos += el
                        sec_grupos += sc
                        partes.append((chave, g["nome"], el, sc))
                    resto = cfg_sub["resto"]
                    partes.append((resto["chave"], resto["nome"], max(1000, eleit_int - eleit_grupos), max(10, sec_int - sec_grupos)))
                    for chave, nome, el, sc in partes:
                        eid_sub = VectorAggregator.id_subestrato(uf, chave)
                        self.engine.nomes_estratos[eid_sub] = f"{nome} ({uf})"
                        estratos.append(EstratoEleitoral(
                            id=eid_sub, uf=uf, nome=f"{uf} - {nome}", eleitores_aptos=max(1000, el),
                            secoes_totais=max(10, sc), tipo=TipoEstrato.SUBESTRATO_INTERIOR, prior_alpha=prior_int,
                        ))
                    # Cidades grandes agrupadas pela região do grupo (ex.: Cidades Norte × Cidades Sul)
                    nomes_grupos = {ch: g["nome"] for ch, g in cfg_sub["grupos"].items()}
                    nomes_grupos[resto["chave"]] = resto["nome"]
                    for chave, cods in cidades_sub.get(uf, {}).items():
                        if not cods:
                            continue
                        el = sum(int(municipios_meta.get(f"{uf}_{c}", {}).get("eleitores", 0)) for c in cods)
                        sc = sum(int(municipios_meta.get(f"{uf}_{c}", {}).get("secoes", 0)) for c in cods)
                        nome = nomes_grupos[chave].replace("Interior", "Cidades grandes")
                        eid_cid = VectorAggregator.id_cidades_grupo(uf, chave)
                        self.engine.nomes_estratos[eid_cid] = f"{nome} ({uf})"
                        estratos.append(EstratoEleitoral(
                            id=eid_cid, uf=uf, nome=f"{uf} - {nome}", eleitores_aptos=max(1000, el),
                            secoes_totais=max(10, sc), tipo=TipoEstrato.SUBESTRATO_CIDADES,
                            prior_alpha=priors_especiais.get(eid_cid, priors_padrao),
                        ))
            else:
                eid_tot = f"{uf}_TOTAL"
                estratos.append(
                    EstratoEleitoral(
                        id=eid_tot,
                        uf=uf,
                        nome=f"{uf} - Total",
                        eleitores_aptos=total_eleit_uf,
                        secoes_totais=total_sec_uf,
                        tipo=TipoEstrato.ESTADO_TOTAL,
                        prior_alpha=priors_padrao
                    )
                )

        self.engine.inicializar_estratos(estratos)
        self.engine.inicializar_ufs(
            {uf: {"eleitores": d.get("eleitores", 0), "secoes": d.get("secoes", 0)} for uf, d in ufs_data.items()},
            prior_padrao=priors_padrao,
        )
        logger.info(f"Pipeline inicializado com {len(estratos)} estratos pré-configurados.")

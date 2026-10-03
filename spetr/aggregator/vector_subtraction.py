"""
Módulo de Decomposição Vetorial e Agregação Estratificada.
Implementa a regra algébrica:
Interior Remanescente(UF) = Total(UF) - Σ Cidades > 100k(UF)
"""
from typing import Dict, List, Any, Optional
import datetime
import logging

from spetr.domain.entities import SnapshotParcial
from spetr.domain.interfaces import IAggregator, IEventBus
from spetr.collector.parser import parse_tse_json
from spetr.services.events import RawBatchReceivedEvent, StrataNormalizedEvent

logger = logging.getLogger("spetr.aggregator.vector_subtraction")


class VectorAggregator:
    """
    Agregador que implementa o isolamento do interior dos estados por subtração vetorial.
    """

    def __init__(
        self,
        event_bus: Optional[IEventBus] = None,
        cidades_100k_map: Optional[Dict[str, List[str]]] = None
    ):
        """
        cidades_100k_map: dicionário { "PB": ["20516", "19852"], ... }
        mapeando UFs para a lista de códigos de municípios > 100k eleitores.
        """
        self.bus = event_bus
        # Se não fornecido, será carregado dinamicamente ou populado
        self.cidades_por_uf: Dict[str, List[str]] = cidades_100k_map or {}
        # Armazena último estado conhecido de cada entidade para lidar com 304 Not Modified
        self._cache_uf_raw: Dict[str, Dict[str, Any]] = {}
        self._cache_mun_raw: Dict[str, Dict[str, Any]] = {}

        if self.bus is not None:
            self.bus.subscribe(RawBatchReceivedEvent, self.ao_receber_lote_bruto)

    def configurar_cidades(self, cidades_por_uf: Dict[str, List[str]]) -> None:
        self.cidades_por_uf = cidades_por_uf

    async def ao_receber_lote_bruto(self, evento: RawBatchReceivedEvent) -> None:
        """Handler do EventBus para processamento automático de novo lote."""
        try:
            snapshots = self.processar_lote_bruto(evento.payload_bruto, evento.timestamp)
            if self.bus is not None:
                await self.bus.publish(
                    StrataNormalizedEvent(
                        timestamp=evento.timestamp,
                        ciclo_id=evento.ciclo_id,
                        snapshots=snapshots
                    )
                )
        except Exception as e:
            logger.error(f"Erro ao processar lote no VectorAggregator: {e}", exc_info=True)

    def processar_lote_bruto(
        self,
        arquivos_brutos: Dict[str, Dict[str, Any]],
        timestamp: Optional[str] = None
    ) -> Dict[str, SnapshotParcial]:
        """
        Recebe um dicionário onde as chaves são:
        - "UF_{uf}" para totais de estados (ex: "UF_PB", "UF_SP")
        - "MUN_{uf}_{cod_mun}" para cidades > 100k (ex: "MUN_PB_20516")
        Retorna dicionário de SnapshotParcial para cada estrato.
        """
        ts = timestamp or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Atualiza cache interno de arquivos recebidos
        for chave, payload in arquivos_brutos.items():
            if chave.startswith("UF_"):
                uf = chave.replace("UF_", "").upper()
                parsed = parse_tse_json(payload, uf=uf)
                self._cache_uf_raw[uf] = parsed
            elif chave.startswith("MUN_"):
                partes = chave.split("_")
                if len(partes) >= 3:
                    uf = partes[1].upper()
                    cod_mun = partes[2]
                    parsed = parse_tse_json(payload, uf=uf, cod_mun=cod_mun)
                    self._cache_mun_raw[f"{uf}_{cod_mun}"] = parsed

        snapshots: Dict[str, SnapshotParcial] = {}

        # 2. Decomposição para cada UF
        for uf, dados_uf in self._cache_uf_raw.items():
            codigos_cidades = self.cidades_por_uf.get(uf, [])

            # Acumuladores de todas as cidades > 100k desta UF
            sum_sec_total = 0
            sum_sec_apuradas = 0
            sum_eleitores = 0
            sum_comp = 0
            sum_abst = 0
            sum_val = 0
            sum_brancos = 0
            sum_nulos = 0
            sum_cands: Dict[str, int] = {}

            cidades_processadas = []

            for cod_mun in codigos_cidades:
                chave_mun = f"{uf}_{cod_mun}"
                if chave_mun in self._cache_mun_raw:
                    dados_mun = self._cache_mun_raw[chave_mun]
                    cidades_processadas.append(cod_mun)

                    sec_tot = dados_mun["secoes_total"]
                    sec_apu = dados_mun["secoes_apuradas"]
                    eleit = dados_mun["eleitores"]
                    comp = dados_mun["comparecimento"]
                    abst = dados_mun["abstencao"]
                    val = dados_mun["votos_validos"]
                    branc = dados_mun["votos_brancos"]
                    nulo = dados_mun["votos_nulos"]
                    cands = dados_mun["candidatos_votos"]

                    sum_sec_total += sec_tot
                    sum_sec_apuradas += sec_apu
                    sum_eleitores += eleit
                    sum_comp += comp
                    sum_abst += abst
                    sum_val += val
                    sum_brancos += branc
                    sum_nulos += nulo

                    for num_cand, votos in cands.items():
                        sum_cands[num_cand] = sum_cands.get(num_cand, 0) + votos

                    # Snapshot individual da grande cidade
                    estrato_id_cid = f"{uf}_{cod_mun}"
                    snapshots[estrato_id_cid] = SnapshotParcial(
                        estrato_id=estrato_id_cid,
                        timestamp=ts,
                        secoes_total=sec_tot,
                        secoes_apuradas=sec_apu,
                        eleitores_aptos=eleit,
                        comparecimento=comp,
                        abstencao=abst,
                        votos_validos=val,
                        votos_brancos=branc,
                        votos_nulos=nulo,
                        votos_candidatos=dict(cands)
                    )

            # Se existirem cidades > 100k nesta UF, calculamos o Interior Remanescente
            if codigos_cidades:
                int_sec_tot = max(0, dados_uf["secoes_total"] - sum_sec_total)
                int_sec_apu = max(0, dados_uf["secoes_apuradas"] - sum_sec_apuradas)
                int_eleit = max(0, dados_uf["eleitores"] - sum_eleitores)
                int_comp = max(0, dados_uf["comparecimento"] - sum_comp)
                int_abst = max(0, dados_uf["abstencao"] - sum_abst)
                int_val = max(0, dados_uf["votos_validos"] - sum_val)
                int_brancos = max(0, dados_uf["votos_brancos"] - sum_brancos)
                int_nulos = max(0, dados_uf["votos_nulos"] - sum_nulos)

                int_cands: Dict[str, int] = {}
                for num_cand, votos_uf in dados_uf["candidatos_votos"].items():
                    votos_cidades = sum_cands.get(num_cand, 0)
                    int_cands[num_cand] = max(0, votos_uf - votos_cidades)

                estrato_id_interior = f"{uf}_INTERIOR"
                snapshots[estrato_id_interior] = SnapshotParcial(
                    estrato_id=estrato_id_interior,
                    timestamp=ts,
                    secoes_total=int_sec_tot,
                    secoes_apuradas=int_sec_apu,
                    eleitores_aptos=int_eleit,
                    comparecimento=int_comp,
                    abstencao=int_abst,
                    votos_validos=int_val,
                    votos_brancos=int_brancos,
                    votos_nulos=int_nulos,
                    votos_candidatos=int_cands
                )
            else:
                # UF sem decomposição (ex: DF ou se nenhuma cidade > 100k configurada)
                estrato_id_total = f"{uf}_TOTAL"
                snapshots[estrato_id_total] = SnapshotParcial(
                    estrato_id=estrato_id_total,
                    timestamp=ts,
                    secoes_total=dados_uf["secoes_total"],
                    secoes_apuradas=dados_uf["secoes_apuradas"],
                    eleitores_aptos=dados_uf["eleitores"],
                    comparecimento=dados_uf["comparecimento"],
                    abstencao=dados_uf["abstencao"],
                    votos_validos=dados_uf["votos_validos"],
                    votos_brancos=dados_uf["votos_brancos"],
                    votos_nulos=dados_uf["votos_nulos"],
                    votos_candidatos=dict(dados_uf["candidatos_votos"])
                )

        return snapshots

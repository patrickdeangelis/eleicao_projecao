"""
Módulo de Decomposição Vetorial e Agregação Estratificada.
Implementa a regra algébrica:
Interior Remanescente(UF) = Total(UF) - Σ Cidades > 100k(UF)
"""
from typing import Dict, List, Any, Optional, Set
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
        # Último conjunto consistente de snapshots por UF e cidades já recebidas por UF
        self._snapshots_por_uf: Dict[str, Dict[str, SnapshotParcial]] = {}
        self._cidades_vistas: Dict[str, Set[str]] = {}
        self._candidatos_meta: Dict[str, Dict[str, Any]] = {}
        self.subtracoes_negativas = 0
        self._rejeicoes_seguidas: Dict[str, int] = {}
        # Após N lotes inconsistentes seguidos, aceita truncado para a UF não ficar congelada
        self.max_rejeicoes_seguidas = 3

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
                        snapshots=snapshots,
                        candidatos_meta=dict(self._candidatos_meta)
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
        Retorna o último snapshot consistente de cada estrato conhecido.

        Consistência: o Interior (= Total UF - Σ cidades) só é recalculado quando o lote traz
        a UF junto com todas as cidades dela que já foram vistas. Caso contrário, os estratos
        da UF mantêm o último cálculo consistente, evitando que o avanço das cidades (com dados
        antigos no lote) seja atribuído ao Interior.
        """
        ts = timestamp or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Parsing apenas do que veio neste lote
        ufs_lote: Dict[str, Dict[str, Any]] = {}
        muns_lote: Dict[str, Dict[str, Any]] = {}
        for chave, payload in arquivos_brutos.items():
            if chave.startswith("UF_"):
                uf = chave.replace("UF_", "").upper()
                parsed = parse_tse_json(payload, uf=uf)
                parsed["votos_anulados"] = sum(parsed.get("candidatos_anulados", {}).values())
                ufs_lote[uf] = parsed
                self._candidatos_meta.update(parsed.get("candidatos_meta", {}))
            elif chave.startswith("MUN_"):
                partes = chave.split("_")
                if len(partes) >= 3:
                    uf = partes[1].upper()
                    cod_mun = partes[2]
                    parsed = parse_tse_json(payload, uf=uf, cod_mun=cod_mun)
                    parsed["votos_anulados"] = sum(parsed.get("candidatos_anulados", {}).values())
                    muns_lote[f"{uf}_{cod_mun}"] = parsed
                    self._candidatos_meta.update(parsed.get("candidatos_meta", {}))

        # 2. Decomposição para cada UF presente no lote
        ufs_negativas: List[str] = []
        for uf, dados_uf in ufs_lote.items():
            codigos_cidades = self.cidades_por_uf.get(uf, [])

            if not codigos_cidades:
                # UF sem decomposição (ex: DF ou se nenhuma cidade > 100k configurada)
                self._registrar_snapshots(uf, {f"{uf}_TOTAL": self._snapshot(f"{uf}_TOTAL", ts, dados_uf)})
                continue

            ja_vistas = self._cidades_vistas.get(uf, set())
            faltando = [c for c in ja_vistas if f"{uf}_{c}" not in muns_lote]
            if faltando:
                logger.debug(
                    f"{uf}: lote sem {len(faltando)} cidade(s) já conhecida(s); mantendo último cálculo consistente."
                )
                continue

            cidades_lote = [c for c in codigos_cidades if f"{uf}_{c}" in muns_lote]
            novos: Dict[str, SnapshotParcial] = {}

            campos = ("secoes_total", "secoes_apuradas", "eleitores", "comparecimento",
                      "abstencao", "votos_validos", "votos_brancos", "votos_nulos", "votos_anulados")
            somas = {c: 0 for c in campos}
            sum_cands: Dict[str, int] = {}

            for cod_mun in cidades_lote:
                dados_mun = muns_lote[f"{uf}_{cod_mun}"]
                for c in campos:
                    somas[c] += dados_mun[c]
                for num_cand, votos in dados_mun["candidatos_votos"].items():
                    sum_cands[num_cand] = sum_cands.get(num_cand, 0) + votos
                eid = f"{uf}_{cod_mun}"
                novos[eid] = self._snapshot(eid, ts, dados_mun)

            # Interior Remanescente por subtração vetorial
            negativos: List[str] = []

            def sub(nome: str, total: int, parcial: int) -> int:
                diff = total - parcial
                if diff < 0:
                    negativos.append(f"{nome}({diff})")
                return max(0, diff)

            interior = {c: sub(c, dados_uf[c], somas[c]) for c in campos}
            int_cands = {
                num: sub(f"cand_{num}", votos_uf, sum_cands.get(num, 0))
                for num, votos_uf in dados_uf["candidatos_votos"].items()
            }
            if negativos:
                self.subtracoes_negativas += 1
                seguidas = self._rejeicoes_seguidas.get(uf, 0) + 1
                self._rejeicoes_seguidas[uf] = seguidas
                tem_anterior = uf in self._snapshots_por_uf
                if seguidas < self.max_rejeicoes_seguidas:
                    # Arquivos de momentos diferentes (UF mais antiga que as cidades): o Interior
                    # sairia distorcido. Mantém o último cálculo consistente (ou nenhum, se não houver).
                    ufs_negativas.append(f"{uf}[{', '.join(negativos[:3])}] descartada")
                    continue
                ufs_negativas.append(
                    f"{uf}[{', '.join(negativos[:3])}] aceita truncada após {seguidas} ciclos"
                    f"{'' if tem_anterior else ' (sem cálculo anterior)'}"
                )
            else:
                self._rejeicoes_seguidas[uf] = 0

            eid_int = f"{uf}_INTERIOR"
            novos[eid_int] = SnapshotParcial(
                estrato_id=eid_int,
                timestamp=ts,
                secoes_total=interior["secoes_total"],
                secoes_apuradas=interior["secoes_apuradas"],
                eleitores_aptos=interior["eleitores"],
                comparecimento=interior["comparecimento"],
                abstencao=interior["abstencao"],
                votos_validos=interior["votos_validos"],
                votos_brancos=interior["votos_brancos"],
                votos_nulos=interior["votos_nulos"],
                votos_candidatos=int_cands,
                votos_anulados=interior["votos_anulados"],
            )

            nao_vistas = [c for c in codigos_cidades if f"{uf}_{c}" not in muns_lote]
            if nao_vistas:
                logger.debug(f"{uf}: {len(nao_vistas)} cidade(s) ainda sem dados, contabilizadas no Interior.")

            self._cidades_vistas[uf] = ja_vistas | set(cidades_lote)
            self._registrar_snapshots(uf, novos)

        if ufs_negativas:
            logger.warning(
                f"Subtração Interior = UF - cidades negativa em {len(ufs_negativas)} UF(s) "
                f"(provável defasagem entre arquivos UF e município): {'; '.join(ufs_negativas)}"
            )

        snapshots: Dict[str, SnapshotParcial] = {}
        for por_uf in self._snapshots_por_uf.values():
            snapshots.update(por_uf)
        return snapshots

    def _registrar_snapshots(self, uf: str, novos: Dict[str, SnapshotParcial]) -> None:
        # Substitui todos os estratos da UF de uma vez (o conjunto de cidades pode ter mudado)
        self._snapshots_por_uf[uf] = novos

    @staticmethod
    def _snapshot(estrato_id: str, ts: str, d: Dict[str, Any]) -> SnapshotParcial:
        return SnapshotParcial(
            estrato_id=estrato_id,
            timestamp=ts,
            secoes_total=d["secoes_total"],
            secoes_apuradas=d["secoes_apuradas"],
            eleitores_aptos=d["eleitores"],
            comparecimento=d["comparecimento"],
            abstencao=d["abstencao"],
            votos_validos=d["votos_validos"],
            votos_brancos=d["votos_brancos"],
            votos_nulos=d["votos_nulos"],
            votos_candidatos=dict(d["candidatos_votos"]),
            votos_anulados=d.get("votos_anulados", 0),
        )

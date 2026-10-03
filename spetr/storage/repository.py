"""
Repositório de Dados do SPETR.
Implementa a interface IRepository para persistência e recuperação histórica.
"""
import json
from typing import List, Optional, Dict, Any
import logging

from spetr.domain.entities import (
    SnapshotParcial,
    ResultadoProjecao,
    ProjecaoCandidato,
)
from spetr.domain.value_objects import StatusCall
from spetr.domain.interfaces import IRepository, IEventBus
from spetr.storage.database import SQLiteDatabase
from spetr.services.events import ProjectionCalculatedEvent, StrataNormalizedEvent

logger = logging.getLogger("spetr.storage.repository")


class ElectionRepository(IRepository):
    """Repositório de persistência SQLite com suporte a Time-Travel."""

    def __init__(self, db: SQLiteDatabase, event_bus: Optional[IEventBus] = None):
        self.db = db
        self.bus = event_bus

        if self.bus is not None:
            self.bus.subscribe(ProjectionCalculatedEvent, self._ao_calcular_projecao)
            self.bus.subscribe(StrataNormalizedEvent, self._ao_normalizar_estratos)

    async def _ao_calcular_projecao(self, evento: ProjectionCalculatedEvent) -> None:
        try:
            self.salvar_projecao(evento.resultado)
        except Exception as e:
            logger.error(f"Erro ao salvar projeção no banco: {e}", exc_info=True)

    async def _ao_normalizar_estratos(self, evento: StrataNormalizedEvent) -> None:
        try:
            self.salvar_snapshots(list(evento.snapshots.values()))
        except Exception as e:
            logger.error(f"Erro ao salvar snapshots no banco: {e}", exc_info=True)

    def salvar_snapshots(self, snapshots: List[SnapshotParcial]) -> None:
        """Insere lote de snapshots em transação atômica."""
        if not snapshots:
            return

        conn = self.db.get_connection()
        sql = """
            INSERT INTO snapshots_apuracao (
                estrato_id, timestamp, secoes_total, secoes_apuradas,
                eleitores_aptos, comparecimento, abstencao, votos_validos,
                votos_brancos, votos_nulos, votos_candidatos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                s.estrato_id,
                s.timestamp,
                s.secoes_total,
                s.secoes_apuradas,
                s.eleitores_aptos,
                s.comparecimento,
                s.abstencao,
                s.votos_validos,
                s.votos_brancos,
                s.votos_nulos,
                json.dumps(s.votos_candidatos)
            )
            for s in snapshots
        ]
        with conn:
            conn.executemany(sql, rows)

    def salvar_projecao(self, p: ResultadoProjecao) -> None:
        """Insere resultado de projeção calculado."""
        conn = self.db.get_connection()
        sql = """
            INSERT INTO projecoes_historico (
                timestamp, ciclo_id, total_secoes, secoes_apuradas,
                perc_secoes, total_eleitores, total_validos_apurados,
                total_validos_projetados, status_call, vencedor_projetado,
                lider_margem, tempo_computacao_ms, candidatos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cands_json = json.dumps([
            {
                "numero": c.numero,
                "nome": c.nome,
                "partido": c.partido,
                "cor_hex": c.cor_hex,
                "votos_apurados": c.votos_apurados,
                "perc_apurado": c.perc_apurado,
                "media_projetada": c.media_projetada,
                "perc_projetado": c.perc_projetado,
                "ic_inferior_95": c.ic_inferior_95,
                "ic_superior_95": c.ic_superior_95,
                "prob_vitoria": c.prob_vitoria,
            }
            for c in p.candidatos
        ])

        with conn:
            conn.execute(sql, (
                p.timestamp,
                p.ciclo_id,
                p.total_secoes,
                p.secoes_apuradas,
                p.perc_secoes_apuradas,
                p.total_eleitores,
                p.total_validos_apurados,
                p.total_validos_projetados,
                p.status_call.value if isinstance(p.status_call, StatusCall) else str(p.status_call),
                p.vencedor_projetado,
                p.lider_margem,
                p.tempo_computacao_ms,
                cands_json
            ))

    def obter_historico_projecoes(self, limite: int = 100) -> List[ResultadoProjecao]:
        """Recupera as últimas projeções calculadas."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM projecoes_historico 
            ORDER BY id DESC LIMIT ?
            """,
            (limite,)
        )
        rows = cursor.fetchall()
        resultados = []
        for r in reversed(rows):
            resultados.append(self._row_to_projecao(r))
        return resultados

    def obter_projecao_em_tempo(self, timestamp: str) -> Optional[ResultadoProjecao]:
        """Busca a projeção mais próxima antes ou no instante timestamp (Time-Travel)."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM projecoes_historico
            WHERE timestamp <= ?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (timestamp,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_projecao(row)

    def _row_to_projecao(self, r: Any) -> ResultadoProjecao:
        cands_data = json.loads(r["candidatos_json"])
        candidatos = [
            ProjecaoCandidato(
                numero=c["numero"],
                nome=c["nome"],
                partido=c["partido"],
                cor_hex=c["cor_hex"],
                votos_apurados=c["votos_apurados"],
                perc_apurado=c["perc_apurado"],
                media_projetada=c["media_projetada"],
                perc_projetado=c["perc_projetado"],
                ic_inferior_95=c["ic_inferior_95"],
                ic_superior_95=c["ic_superior_95"],
                prob_vitoria=c["prob_vitoria"]
            )
            for c in cands_data
        ]

        status_str = r["status_call"]
        try:
            status_enum = StatusCall(status_str)
        except ValueError:
            status_enum = StatusCall.INDEFINIDO

        return ResultadoProjecao(
            timestamp=r["timestamp"],
            ciclo_id=r["ciclo_id"],
            total_secoes=r["total_secoes"],
            secoes_apuradas=r["secoes_apuradas"],
            perc_secoes_apuradas=r["perc_secoes"],
            total_eleitores=r["total_eleitores"],
            total_validos_apurados=r["total_validos_apurados"],
            total_validos_projetados=r["total_validos_projetados"],
            candidatos=candidatos,
            status_call=status_enum,
            vencedor_projetado=r["vencedor_projetado"],
            lider_margem=r["lider_margem"],
            tempo_computacao_ms=r["tempo_computacao_ms"]
        )

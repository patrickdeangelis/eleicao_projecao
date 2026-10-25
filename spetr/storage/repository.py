"""
Repositório de Dados do SPETR.
Implementa a interface IRepository para persistência e recuperação histórica.
"""
import asyncio
import json
import uuid
from typing import List, Optional, Dict, Any
import logging

from spetr.domain.entities import (
    SnapshotParcial,
    ResultadoProjecao,
    ProjecaoCandidato,
)
from spetr.domain.value_objects import CHAVES_RESUMO_ANALISE, StatusCall
from spetr.domain.interfaces import IRepository, IEventBus
from spetr.storage.database import SQLiteDatabase
from spetr.services.events import ProjectionCalculatedEvent, StrataNormalizedEvent

logger = logging.getLogger("spetr.storage.repository")

# json_object(...) do resumo da análise, calculado pelo SQLite (sem decodificar a análise inteira)
SQL_RESUMO_ANALISE = "json_object(" + ", ".join(
    f"'{k}', json(json_extract(analise_json, '$.{k}'))" for k in CHAVES_RESUMO_ANALISE
) + ")"

# Retenção do histórico: a análise completa (180–340 KB por ciclo) só interessa nos ciclos recentes
# e de tempos em tempos; nos demais fica o resumo usado pelas curvas e pelo time-travel.
ANALISES_RECENTES = 60       # ciclos mais novos da execução mantidos completos
ANALISE_COMPLETA_A_CADA = 20 # além dos recentes, um ciclo a cada N continua completo
COMPACTAR_A_CADA = 10        # roda a compactação a cada N projeções salvas


class ElectionRepository(IRepository):
    """Repositório de persistência SQLite com suporte a Time-Travel."""

    def __init__(
        self,
        db: SQLiteDatabase,
        event_bus: Optional[IEventBus] = None,
        eleicao: str = "",
        execucao_id: Optional[str] = None,
    ):
        """
        eleicao: identifica o pleito (ambiente/ano/código/cargo/turno). O time-travel busca
                 em todas as execuções do mesmo pleito.
        execucao_id: identifica esta execução do programa. O histórico mostra só a execução atual.
        """
        self.db = db
        self.bus = event_bus
        self.eleicao = eleicao
        self.execucao_id = execucao_id or uuid.uuid4().hex[:12]
        self._salvas = 0
        # Último valor gravado de cada estrato: só grava o que mudou (antes eram ~300 linhas por ciclo, mesmo parado)
        self._ultimo_snapshot: Dict[str, tuple] = {}

        if self.bus is not None:
            self.bus.subscribe(ProjectionCalculatedEvent, self._ao_calcular_projecao)
            self.bus.subscribe(StrataNormalizedEvent, self._ao_normalizar_estratos)

    async def _ao_calcular_projecao(self, evento: ProjectionCalculatedEvent) -> None:
        try:
            await asyncio.to_thread(self.salvar_projecao, evento.resultado)
        except Exception as e:
            logger.error(f"Erro ao salvar projeção no banco: {e}", exc_info=True)
            return
        self._salvas += 1
        if self._salvas % COMPACTAR_A_CADA == 0:
            try:
                await asyncio.to_thread(self.compactar_analises)
                await asyncio.to_thread(self.db.get_connection().execute, "PRAGMA wal_checkpoint(PASSIVE)")
            except Exception as e:
                logger.error(f"Erro ao compactar análises antigas: {e}", exc_info=True)

    async def _ao_normalizar_estratos(self, evento: StrataNormalizedEvent) -> None:
        try:
            await asyncio.to_thread(self.salvar_snapshots, list(evento.snapshots.values()))
        except Exception as e:
            logger.error(f"Erro ao salvar snapshots no banco: {e}", exc_info=True)

    def salvar_snapshots(self, snapshots: List[SnapshotParcial]) -> None:
        """Insere lote de snapshots em transação atômica."""
        if not snapshots:
            return

        mudados = []
        for s in snapshots:
            chave = (s.secoes_apuradas, s.votos_validos, s.comparecimento, s.secoes_total,
                     tuple(sorted(s.votos_candidatos.items())))
            if self._ultimo_snapshot.get(s.estrato_id) != chave:
                self._ultimo_snapshot[s.estrato_id] = chave
                mudados.append(s)
        snapshots = mudados
        if not snapshots:
            return

        conn = self.db.get_connection()
        sql = """
            INSERT INTO snapshots_apuracao (
                estrato_id, timestamp, secoes_total, secoes_apuradas,
                eleitores_aptos, comparecimento, abstencao, votos_validos,
                votos_brancos, votos_nulos, votos_candidatos_json,
                eleicao, execucao_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(s.votos_candidatos),
                self.eleicao,
                self.execucao_id,
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
                lider_margem, tempo_computacao_ms, candidatos_json,
                eleicao, execucao_id, prob_segundo_turno, ufs_sem_dados_json, analise_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                "prob_lideranca": c.prob_lideranca,
                "vice": c.vice,
                "coligacao": c.coligacao,
                "composicao": c.composicao,
                "nome_completo": c.nome_completo,
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
                cands_json,
                self.eleicao,
                self.execucao_id,
                p.prob_segundo_turno,
                json.dumps(p.ufs_sem_dados),
                json.dumps(p.analise, separators=(",", ":")),
            ))

    def compactar_analises(self, manter_recentes: int = ANALISES_RECENTES, a_cada: int = ANALISE_COMPLETA_A_CADA) -> int:
        """
        Troca a análise completa dos ciclos antigos desta execução pelo resumo (as mesmas chaves que
        o histórico já lê). Mantém completos os `manter_recentes` últimos ciclos e um a cada `a_cada`.
        Idempotente: só toca linhas que ainda têm a análise completa. Retorna as linhas compactadas.
        """
        conn = self.db.get_connection()
        with conn:
            cur = conn.execute(
                f"""
                UPDATE projecoes_historico SET analise_json = {SQL_RESUMO_ANALISE}
                WHERE execucao_id = ?
                  AND id < COALESCE((SELECT id FROM projecoes_historico WHERE execucao_id = ?
                                     ORDER BY id DESC LIMIT 1 OFFSET ?), 0)
                  AND ciclo_id % ? != 0
                  AND json_type(analise_json, '$.estratos') IS NOT NULL
                """,
                (self.execucao_id, self.execucao_id, max(0, manter_recentes - 1), a_cada),
            )
        return cur.rowcount

    def adotar_execucoes_anteriores(self) -> int:
        """
        Para execuções com id fixo (hospedagem): reúne sob esta execução o histórico gravado antes por
        outras execuções do mesmo pleito, de modo que reiniciar o servidor não zere o painel.
        Retorna as projeções adotadas.
        """
        conn = self.db.get_connection()
        with conn:
            cur = conn.execute(
                "UPDATE projecoes_historico SET execucao_id = ? WHERE eleicao = ? AND execucao_id != ?",
                (self.execucao_id, self.eleicao, self.execucao_id),
            )
            conn.execute(
                "UPDATE snapshots_apuracao SET execucao_id = ? WHERE eleicao = ? AND execucao_id != ?",
                (self.execucao_id, self.eleicao, self.execucao_id),
            )
        return cur.rowcount

    def ultimo_ciclo(self) -> int:
        """Maior ciclo já gravado por esta execução (0 se nenhum), para a contagem continuar após um reinício."""
        linha = self.db.get_connection().execute(
            "SELECT MAX(ciclo_id) FROM projecoes_historico WHERE execucao_id = ?", (self.execucao_id,)
        ).fetchone()
        return int(linha[0] or 0)

    def obter_historico_projecoes(self, limite: int = 100, so_com_votos: bool = False) -> List[ResultadoProjecao]:
        """Recupera as últimas projeções calculadas."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT *, {SQL_RESUMO_ANALISE} AS analise_resumo
            FROM projecoes_historico
            WHERE execucao_id = ?{' AND total_validos_apurados > 0' if so_com_votos else ''}
            ORDER BY id DESC LIMIT ?
            """,
            (self.execucao_id, limite)
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
            WHERE eleicao = ? AND timestamp <= ?
            ORDER BY timestamp DESC, id DESC LIMIT 1
            """,
            (self.eleicao, timestamp)
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
                prob_vitoria=c["prob_vitoria"],
                prob_lideranca=c.get("prob_lideranca", 0.0),
                vice=c.get("vice", ""),
                coligacao=c.get("coligacao", ""),
                composicao=c.get("composicao", ""),
                nome_completo=c.get("nome_completo", ""),
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
            tempo_computacao_ms=r["tempo_computacao_ms"],
            prob_segundo_turno=r["prob_segundo_turno"],
            ufs_sem_dados=json.loads(r["ufs_sem_dados_json"]),
            # No histórico só o resumo é extraído (SQLite JSON1), evitando decodificar a análise inteira
            analise=json.loads(r["analise_resumo"] if "analise_resumo" in r.keys() else r["analise_json"]),
        )

"""
Gerenciador de Conexão com SQLite em modo WAL (Write-Ahead Logging).
Thread-safe e de alta performance para concorrência leitura/escrita.
"""
import sqlite3
import threading
from pathlib import Path
import logging

logger = logging.getLogger("spetr.storage.database")

SCHEMA_FILE = Path(__file__).parent / "schema.sql"

# Colunas acrescentadas depois da primeira versão do schema: (tabela, coluna, definição)
MIGRACOES = [
    ("snapshots_apuracao", "eleicao", "TEXT NOT NULL DEFAULT ''"),
    ("snapshots_apuracao", "execucao_id", "TEXT NOT NULL DEFAULT ''"),
    ("projecoes_historico", "eleicao", "TEXT NOT NULL DEFAULT ''"),
    ("projecoes_historico", "execucao_id", "TEXT NOT NULL DEFAULT ''"),
    ("projecoes_historico", "prob_segundo_turno", "REAL NOT NULL DEFAULT 0"),
    ("projecoes_historico", "ufs_sem_dados_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("projecoes_historico", "analise_json", "TEXT NOT NULL DEFAULT '{}'"),
]

INDICES_POS_MIGRACAO = [
    "CREATE INDEX IF NOT EXISTS idx_projecoes_eleicao_ts ON projecoes_historico (eleicao, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_projecoes_execucao ON projecoes_historico (execucao_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_execucao ON snapshots_apuracao (execucao_id, id)",
]


class SQLiteDatabase:
    """Gerenciador de conexão SQLite WAL."""

    def __init__(self, db_path: str = "spetr_eleicoes.sqlite"):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._inicializar_banco()

    def get_connection(self) -> sqlite3.Connection:
        """Retorna uma conexão específica para a thread atual."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self.db_path,
                timeout=30.0,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            # Ativa modo WAL e otimizações de I/O
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA cache_size=-64000;")  # 64MB de cache de memória
            conn.execute("PRAGMA temp_store=MEMORY;")
            self._local.conn = conn
        return self._local.conn

    def _inicializar_banco(self) -> None:
        """Cria as tabelas e índices caso não existam."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            conn.executescript(schema_sql)
            for tabela, coluna, definicao in MIGRACOES:
                existentes = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
                if coluna not in existentes:
                    conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")
                    logger.info(f"Migração: coluna {tabela}.{coluna} adicionada")
            for ddl in INDICES_POS_MIGRACAO:
                conn.execute(ddl)
            conn.commit()
            conn.close()
            logger.info(f"Banco de dados SQLite inicializado em WAL mode: {self.db_path}")

    def close(self) -> None:
        """Fecha a conexão da thread atual."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

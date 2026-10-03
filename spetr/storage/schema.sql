-- Schema do banco SQLite para o SPETR (WAL Mode)

CREATE TABLE IF NOT EXISTS snapshots_apuracao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    estrato_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    secoes_total INTEGER NOT NULL,
    secoes_apuradas INTEGER NOT NULL,
    eleitores_aptos INTEGER NOT NULL,
    comparecimento INTEGER NOT NULL,
    abstencao INTEGER NOT NULL,
    votos_validos INTEGER NOT NULL,
    votos_brancos INTEGER NOT NULL,
    votos_nulos INTEGER NOT NULL,
    votos_candidatos_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_snapshots_estrato_ts 
ON snapshots_apuracao (estrato_id, timestamp);

CREATE TABLE IF NOT EXISTS projecoes_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ciclo_id INTEGER NOT NULL,
    total_secoes INTEGER NOT NULL,
    secoes_apuradas INTEGER NOT NULL,
    perc_secoes REAL NOT NULL,
    total_eleitores INTEGER NOT NULL,
    total_validos_apurados INTEGER NOT NULL,
    total_validos_projetados INTEGER NOT NULL,
    status_call TEXT NOT NULL,
    vencedor_projetado TEXT,
    lider_margem REAL NOT NULL,
    tempo_computacao_ms REAL NOT NULL,
    candidatos_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_projecoes_ciclo 
ON projecoes_historico (ciclo_id);

CREATE INDEX IF NOT EXISTS idx_projecoes_ts 
ON projecoes_historico (timestamp);

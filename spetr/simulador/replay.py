"""
Replay de uma apuração real a partir dos Boletins de Urna (preparados por scripts/preparar_replay.py).

O relógio começa às 17h de Brasília (horário em que o TSE passa a divulgar). Boletins recebidos
antes disso entram todos às 17h. A cada avanço, o relógio anda alguns minutos da noite real e o
servidor do simulador passa a entregar os arquivos de UF e de município com os votos das seções
que o TSE já tinha recebido naquele horário, no mesmo formato "dados simplificados" do TSE.

Roda no servidor local de replay (criar_app_simulador), que espelha os arquivos da CDN do TSE.
"""
import datetime
import gzip
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from spetr.caminhos import pasta_replays
from spetr.simulador.servidor import EstadoApuracao, _agora_http

# (segundos entre avanços, minutos da noite real por avanço)
VELOCIDADES_REPLAY = {
    "lenta": (4.0, 2),
    "normal": (4.0, 5),
    "rapida": (3.0, 10),
}
HORA_DIVULGACAO = 17  # horário de Brasília em que os resultados começam a ser divulgados


def listar_replays() -> Dict[str, str]:
    """{fonte: rótulo} dos replays já preparados na pasta de dados."""
    saida = {}
    for nome in sorted(os.listdir(pasta_replays())):
        if nome.endswith(".json.gz") and "_parcial" not in nome:
            fonte = nome[: -len(".json.gz")]
            ano, turno = fonte.split("_")
            saida[fonte] = f"{ano} · {turno[0]}º turno · Presidente"
    return saida


class EstadoReplay(EstadoApuracao):
    """Estado de um replay: relógio (minutos desde as 17h) e votos recebidos até ali."""

    def __init__(self, fonte: str, velocidade: str = "normal", pasta: Optional[str] = None):
        if velocidade not in VELOCIDADES_REPLAY:
            raise ValueError(f"Velocidade desconhecida: {velocidade!r}")
        caminho = Path(pasta or pasta_replays()) / f"{fonte}.json.gz"
        if not caminho.exists():
            raise ValueError(f"Replay {fonte!r} não preparado. Rode: python scripts/preparar_replay.py "
                             f"--ano {fonte.split('_')[0]} --turno {fonte.split('_')[-1][0]}")
        with gzip.open(caminho, "rt", encoding="utf-8") as f:
            dados = json.load(f)
        self.fonte = fonte
        self.ano = str(dados["ano"])
        self.turno = int(dados["turno"])
        self.eleicao = str(dados["eleicao"])
        self.velocidade = velocidade
        self.velocidade_segundos, self.minutos_por_passo = VELOCIDADES_REPLAY[velocidade]
        self.cenario = f"replay-{fonte}"
        self.descricao = f"Replay real · {self.ano} · {self.turno}º turno · boletins de urna do TSE"
        self.pausado = False
        self.versao_ciclo = 1
        self.ultima_modificacao = _agora_http()
        self.candidatos = [{"n": c["n"], "nm": c["nm"], "cc": c.get("partido", ""), "dvt": "Válido"}
                           for c in dados["candidatos"]]

        t0 = datetime.datetime.strptime(dados["t0"], "%Y-%m-%d %H:%M")
        self.inicio = t0.replace(hour=HORA_DIVULGACAO, minute=0) if t0.hour < HORA_DIVULGACAO else t0
        deslocamento = int((self.inicio - t0).total_seconds() // 60)
        self.eventos = np.array(dados["eventos"], dtype=np.int64)
        self.eventos[:, 0] = np.maximum(0, self.eventos[:, 0] - deslocamento)  # minutos desde as 17h
        ordem = np.argsort(self.eventos[:, 0], kind="stable")
        self.eventos = self.eventos[ordem]

        self.municipios = dados["municipios"]  # [uf, cod, nome, secoes, aptos]
        self.por_uf: Dict[str, List[Dict[str, Any]]] = {}
        for mi, (uf, cod, _nome, _sec, _apt) in enumerate(self.municipios):
            self.por_uf.setdefault(uf, []).append({"id": f"{uf}_{cod}", "tipo": "cidade", "mi": mi})

        # Fim "útil" do relógio: 99,9% das seções recebidas; o resto entra no último passo
        secoes = np.cumsum(self.eventos[:, 2])
        k = int(np.searchsorted(secoes, 0.999 * secoes[-1]))
        self.minuto_util = max(1, int(self.eventos[min(k, len(self.eventos) - 1), 0]))
        self.minuto_final = int(self.eventos[-1, 0])
        self.secoes_total = int(secoes[-1])
        self.progresso_global = 0.0
        self.passo_progresso = self.minutos_por_passo / self.minuto_util
        self._cache_minuto: Optional[int] = None
        self._cache_estado: Optional[np.ndarray] = None

    # ------------------------------------------------------------ relógio

    @property
    def minuto(self) -> int:
        if self.progresso_global >= 1.0:
            return self.minuto_final
        return int(round(self.progresso_global * self.minuto_util))

    def _marcar_mudanca(self) -> None:
        self.versao_ciclo += 1
        self.ultima_modificacao = _agora_http()

    def avancar(self, delta: Optional[float] = None) -> None:
        d = delta if delta is not None else self.passo_progresso
        self.progresso_global = min(1.0, max(0.0, self.progresso_global + d))
        self._marcar_mudanca()

    def definir(self, fracao: float) -> None:
        self.progresso_global = min(1.0, max(0.0, fracao))
        self._marcar_mudanca()

    def resetar(self) -> None:
        self.definir(0.0)

    # ------------------------------------------------------------ dados

    def _estado(self) -> np.ndarray:
        """Matriz (municípios × campos) com o acumulado recebido até o minuto atual."""
        m = self.minuto
        if self._cache_minuto != m:
            k = int(np.searchsorted(self.eventos[:, 0], m, side="right"))
            est = np.zeros((len(self.municipios), self.eventos.shape[1] - 2), dtype=np.int64)
            np.add.at(est, self.eventos[:k, 1], self.eventos[:k, 2:])
            self._cache_minuto, self._cache_estado = m, est
        return self._cache_estado

    def unidades_da_uf(self, uf: str) -> List[Dict[str, Any]]:
        return self.por_uf.get(uf, [])

    def apurar_unidade(self, uf: str, u: Dict[str, Any]) -> Dict[str, Any]:
        linha = self._estado()[u["mi"]]
        _uf, _cod, _nome, secoes, aptos = self.municipios[u["mi"]]
        return {
            "secoes": int(secoes), "apuradas": int(linha[0]), "eleitores": int(aptos),
            "comparecimento": int(linha[2]), "abstencao": int(linha[3]),
            "brancos": int(linha[4]), "nulos": int(linha[5]), "votos": [int(v) for v in linha[6:]],
        }

    def resumo(self) -> Dict[str, Any]:
        recebidas = int(self._estado()[:, 0].sum())
        horario = self.inicio + datetime.timedelta(minutes=self.minuto)
        return {
            "progresso": round(recebidas / max(1, self.secoes_total) * 100.0, 2),
            "horario": horario.strftime("%d/%m %H:%M"),
            "pausado": self.pausado,
            "ciclo": self.versao_ciclo,
            "ultima_modificacao": self.ultima_modificacao,
            "cenario": self.cenario,
            "velocidade": self.velocidade,
            "candidatos": self.candidatos,
        }

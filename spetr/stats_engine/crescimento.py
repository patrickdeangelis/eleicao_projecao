"""
Projeção extra por razão de crescimento (por estrato e subestrato).

Não participa do Monte Carlo nem da chamada da disputa: é uma leitura à parte, para comparar
com a projeção principal. Para cada estrato:

    razão_k  = votos que o candidato k ganhou na janela recente / eleitores dessas seções
    final_k  = votos_k apurados + razão_k × eleitores ainda não computados

A janela recente são as seções apuradas desde que o estrato tinha `janela` (fração das seções)
a menos do que tem agora. Com poucas seções novas na janela (menos de `min_secoes`), usa a razão
acumulada desde o início. Eleitores das seções apuradas = comparecimento + abstenção do arquivo.
"""
from typing import Any, Dict, List, Optional, Tuple

from spetr.domain.entities import SnapshotParcial

Ponto = Tuple[int, int, Dict[str, int]]  # (seções apuradas, eleitores computados, votos por candidato)


class ProjecaoCrescimento:
    def __init__(self, janela: float = 0.15, min_secoes: int = 5):
        self.janela = janela
        self.min_secoes = min_secoes
        self.historico: Dict[str, List[Ponto]] = {}

    def registrar(self, snapshots: Dict[str, SnapshotParcial]) -> None:
        """Guarda o estado de cada estrato quando ele muda."""
        for eid, snap in snapshots.items():
            ponto: Ponto = (snap.secoes_apuradas, snap.comparecimento + snap.abstencao, dict(snap.votos_candidatos))
            hist = self.historico.setdefault(eid, [])
            if hist and ponto[0] < hist[-1][0]:
                # Apuração recuou (correção do TSE ou nova sessão): recomeça a série do estrato
                hist.clear()
            if not hist or hist[-1][0] != ponto[0] or hist[-1][2] != ponto[2]:
                hist.append(ponto)

    def estrato(self, eid: str, snap: SnapshotParcial) -> Optional[Dict[str, Any]]:
        """Projeção de um estrato, ou None se ainda não há seção apurada."""
        if snap.secoes_apuradas <= 0:
            return None
        atual = (snap.secoes_apuradas, snap.comparecimento + snap.abstencao, dict(snap.votos_candidatos))
        hist = self.historico.get(eid) or [atual]
        limite = snap.secoes_apuradas - self.janela * snap.secoes_total
        anteriores = [p for p in hist if p[0] <= limite]
        base: Ponto = anteriores[-1] if anteriores else (0, 0, {})
        tipo = "recente" if anteriores else "acumulado"
        if atual[0] - base[0] < self.min_secoes or atual[1] - base[1] <= 0:
            base, tipo = (0, 0, {}), "acumulado"
        d_eleitores = atual[1] - base[1]
        if d_eleitores <= 0:
            return None
        razao = {n: max(0.0, (v - base[2].get(n, 0)) / d_eleitores) for n, v in atual[2].items()}
        eleitores_faltantes = max(0, snap.eleitores_aptos - snap.comparecimento - snap.abstencao) if snap.secoes_faltantes else 0
        projetado = {n: v + razao[n] * eleitores_faltantes for n, v in atual[2].items()}
        return {
            "razao_por_eleitor": razao,
            "eleitores_faltantes": eleitores_faltantes,
            "secoes_janela": atual[0] - base[0],
            "base": tipo,
            "votos_projetados": projetado,
        }

    def projetar(self, snapshots: Dict[str, SnapshotParcial], numeros: List[str]) -> Dict[str, Any]:
        """Projeção agregada (nacional e por UF) e detalhada por estrato."""
        def pct(votos: Dict[str, float]) -> Dict[str, float]:
            tot = sum(votos.values())
            return {n: round(votos.get(n, 0.0) / tot * 100.0, 3) if tot > 0 else 0.0 for n in numeros}

        nacional = {n: 0.0 for n in numeros}
        por_uf: Dict[str, Dict[str, float]] = {}
        estratos: Dict[str, Any] = {}
        for eid, snap in snapshots.items():
            r = self.estrato(eid, snap)
            if r is None:
                continue
            votos = {n: float(r["votos_projetados"].get(n, 0.0)) for n in numeros}
            uf = eid.split("_")[0]
            alvo = por_uf.setdefault(uf, {n: 0.0 for n in numeros})
            for n in numeros:
                nacional[n] += votos[n]
                alvo[n] += votos[n]
            apurados = {n: float(snap.votos_candidatos.get(n, 0)) for n in numeros}
            estratos[eid] = {
                "pct": pct(votos),
                "pct_apurado": pct(apurados),
                "razao_por_eleitor": {n: round(r["razao_por_eleitor"].get(n, 0.0), 5) for n in numeros},
                "eleitores_faltantes": int(r["eleitores_faltantes"]),
                "secoes_janela": int(r["secoes_janela"]),
                "base": r["base"],
            }
        return {
            "nacional": pct(nacional),
            "votos_nacionais": {n: int(round(v)) for n, v in nacional.items()},
            "ufs": {uf: pct(v) for uf, v in por_uf.items()},
            "estratos": estratos,
        }

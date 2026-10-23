"""
Modelos extras de projeção, lado a lado com o Monte Carlo (aba Modelos).

Nenhum deles participa do Monte Carlo, do intervalo ou da chamada da disputa: são leituras à parte,
calculadas sobre os mesmos estratos e os mesmos votos que faltam (`votos_rem_esperados`).

- Estimador direto: votos apurados + % atual de cada estrato × votos que faltam nele. É o centro do
  Monte Carlo sem incerteza: serve de linha de base para ver o que o modelo acrescenta.
- Swing sobre uma eleição de referência: parte do resultado de cada estrato numa eleição anterior
  (ex.: o 1º turno, para projetar o 2º) e estima, só com o que já foi apurado, a mudança nacional de cada
  candidato (swing proporcional, em escala logarítmica, por máxima verossimilhança). Os votos que faltam
  em cada estrato seguem a referência deslocada por esse swing, misturada com o % atual do estrato.
  Usa resultados de eleição, nunca pesquisas.
"""
import gzip
import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger("spetr.stats_engine.modelos_extras")

# (ano, turno) da eleição em curso -> replay preparado (boletins de urna) usado como referência.
# Os candidatos são casados pelo número (no 1º turno de 2026 contra 2022, é uma comparação por partido).
REFERENCIAS = {
    ("2026", 2): "2026_1t",
    ("2026", 1): "2022_1t",
    ("2022", 2): "2022_1t",
}

# Pseudo-votos que a referência (já deslocada pelo swing) vale frente ao % atual de cada estrato
PESO_REFERENCIA = 20000.0


def _agregar(estrato_ids: Sequence[str], votos: np.ndarray, numeros: Sequence[str]) -> Dict[str, Any]:
    """Nacional e por UF (% e votos) a partir dos votos finais projetados por estrato (H, K)."""
    def pct(v: np.ndarray) -> Dict[str, float]:
        tot = float(v.sum())
        return {n: round(float(x) / tot * 100.0, 3) if tot > 0 else 0.0 for n, x in zip(numeros, v)}

    por_uf: Dict[str, np.ndarray] = {}
    for eid, linha in zip(estrato_ids, votos):
        por_uf.setdefault(eid.split("_")[0], np.zeros(len(numeros)))
        por_uf[eid.split("_")[0]] += linha
    total = votos.sum(axis=0)
    return {
        "nacional": pct(total),
        "votos_nacionais": {n: int(round(float(x))) for n, x in zip(numeros, total)},
        "ufs": {uf: pct(v) for uf, v in por_uf.items()},
    }


def projetar_direto(estrato_ids: Sequence[str], votos_obs: np.ndarray, restantes: np.ndarray,
                    numeros: Sequence[str]) -> Dict[str, Any]:
    """Votos apurados + % atual de cada estrato × votos que faltam. Estrato sem voto usa o % nacional apurado."""
    obs_nacional = votos_obs.sum(axis=0)
    media = obs_nacional / obs_nacional.sum() if obs_nacional.sum() > 0 else np.full(len(numeros), 1.0 / len(numeros))
    n_h = votos_obs.sum(axis=1, keepdims=True)
    share = np.where(n_h > 0, votos_obs / np.where(n_h == 0, 1.0, n_h), media[None, :])
    return _agregar(estrato_ids, votos_obs + share * restantes[:, None], numeros)


# ---------------------------------------------------------------- eleição de referência

class ReferenciaEleitoral:
    """Votos de uma eleição anterior por município, remontados nos estratos do SPETR."""

    def __init__(self, fonte: str, numeros: Sequence[str], municipios: Dict[Tuple[str, str], np.ndarray],
                 cidades_por_uf: Dict[str, List[str]], subestratos: Dict[str, Dict[str, Any]]):
        self.fonte = fonte
        self.numeros = list(numeros)
        self.municipios = municipios
        self.cidades_por_uf = cidades_por_uf
        self.subestratos = subestratos
        self._total_uf: Dict[str, np.ndarray] = {}
        for (uf, _cod), v in municipios.items():
            self._total_uf[uf] = self._total_uf.get(uf, 0) + v
        self._cache: Dict[str, Optional[np.ndarray]] = {}

    def _soma(self, uf: str, codigos) -> np.ndarray:
        zero = np.zeros(len(self.numeros))
        return sum((self.municipios.get((uf, c), zero) for c in codigos), zero)

    def _interior(self, uf: str) -> np.ndarray:
        return self._total_uf.get(uf, np.zeros(len(self.numeros))) - self._soma(uf, self.cidades_por_uf.get(uf, []))

    def vetor(self, eid: str) -> Optional[np.ndarray]:
        """Votos da referência no estrato (um por número de candidato da referência), ou None se não há."""
        if eid in self._cache:
            return self._cache[eid]
        uf, _, resto = eid.partition("_")
        v: Optional[np.ndarray]
        if uf not in self._total_uf:
            v = None
        elif resto.isdigit():
            v = self.municipios.get((uf, resto))
        elif resto in ("TOTAL", "SEM_DADOS"):
            v = self._total_uf[uf]
        elif resto == "INTERIOR":
            v = self._interior(uf)
        elif resto.startswith(("SUB_", "CID_")):
            cfg = self.subestratos.get(uf)
            chave = resto[4:]
            if cfg is None:
                v = None
            elif resto.startswith("CID_"):
                v = self._soma(uf, cfg.get("cidades", {}).get(chave, []))
            elif chave in cfg.get("grupos", {}):
                v = self._soma(uf, cfg["grupos"][chave])
            else:  # o "resto" do interior: Interior − grupos listados
                v = self._interior(uf) - sum((self._soma(uf, c) for c in cfg.get("grupos", {}).values()),
                                             np.zeros(len(self.numeros)))
        else:
            v = None
        self._cache[eid] = v
        return v


def carregar_referencia(ano: str, turno: int, cidades_por_uf: Dict[str, List[str]],
                        subestratos: Dict[str, Dict[str, Any]], pasta: Optional[str] = None,
                        fonte: Optional[str] = None) -> Optional[ReferenciaEleitoral]:
    """Lê o replay de referência da eleição (ano, turno), se estiver preparado; senão None."""
    fonte = fonte or REFERENCIAS.get((str(ano), int(turno)))
    if fonte is None:
        return None
    if pasta is None:
        from spetr import caminhos
        pasta = caminhos.pasta_replays()
    caminho = os.path.join(pasta, f"{fonte}.json.gz")
    if not os.path.exists(caminho):
        logger.info(f"Referência {fonte} não preparada ({caminho}); o modelo de swing fica indisponível.")
        return None
    with gzip.open(caminho, "rt", encoding="utf-8") as f:
        dados = json.load(f)
    numeros = [c["n"] for c in dados["candidatos"]]
    eventos = np.array(dados["eventos"], dtype=np.int64)
    por_mun = np.zeros((len(dados["municipios"]), len(numeros)), dtype=np.int64)
    np.add.at(por_mun, eventos[:, 1], eventos[:, 8:8 + len(numeros)])
    municipios = {(m[0], m[1]): por_mun[i].astype(np.float64) for i, m in enumerate(dados["municipios"])}
    logger.info(f"Referência {fonte}: {len(municipios)} municípios, {len(numeros)} candidatos")
    return ReferenciaEleitoral(fonte, numeros, municipios, cidades_por_uf, subestratos)


# ------------------------------------------------------------------------------ swing

def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=1, keepdims=True)


def estimar_swing(obs: np.ndarray, ref: np.ndarray, iteracoes: int = 40) -> np.ndarray:
    """
    Swing nacional por candidato (escala log) que melhor explica os votos apurados dado o % de referência
    de cada estrato: máxima verossimilhança multinomial por Newton, com uma pequena penalidade (ridge) para
    candidatos sem voto não irem ao infinito.
    obs: (H, K) votos apurados · ref: (H, K) % de referência (cada linha soma 1).
    """
    n_h = obs.sum(axis=1)
    ridge = max(1.0, 1e-4 * float(n_h.sum()))
    logr = np.log(np.clip(ref, 1e-9, None))
    delta = np.zeros(obs.shape[1])
    for _ in range(iteracoes):
        p = _softmax(logr + delta[None, :])
        grad = (obs - n_h[:, None] * p).sum(axis=0) - ridge * delta
        hess = ridge * np.eye(len(delta))
        for h in range(obs.shape[0]):
            if n_h[h] > 0:
                hess += n_h[h] * (np.diag(p[h]) - np.outer(p[h], p[h]))
        passo = np.linalg.solve(hess, grad)
        escala = min(1.0, 1.0 / max(1e-12, float(np.abs(passo).max())))
        delta = np.clip(delta + escala * passo, -4.0, 4.0)
        if np.abs(passo).max() < 1e-7:
            break
    return delta - delta.mean()


def projetar_swing(referencia: ReferenciaEleitoral, estrato_ids: Sequence[str], votos_obs: np.ndarray,
                   restantes: np.ndarray, numeros: Sequence[str], peso_referencia: float = PESO_REFERENCIA
                   ) -> Optional[Dict[str, Any]]:
    """Projeção por swing sobre a referência. None se a referência não cobre nenhum estrato apurado."""
    K = len(numeros)
    obs_nacional = votos_obs.sum(axis=0)
    if obs_nacional.sum() <= 0:
        return None
    atual = obs_nacional / obs_nacional.sum()
    idx_ref = {n: i for i, n in enumerate(referencia.numeros)}

    # % de referência de cada estrato; candidato sem referência entra com o % nacional atual (neutro)
    H = len(estrato_ids)
    ref = np.zeros((H, K))
    tem_ref = np.zeros(H, dtype=bool)
    for h, eid in enumerate(estrato_ids):
        v = referencia.vetor(eid)
        if v is None or v.sum() <= 0:
            continue
        linha = np.array([v[idx_ref[n]] / v.sum() if n in idx_ref else atual[k] for k, n in enumerate(numeros)])
        ref[h] = linha / linha.sum()
        tem_ref[h] = True
    if not tem_ref.any():
        return None
    peso_h = np.where(tem_ref, votos_obs.sum(axis=1) + restantes, 0.0)
    media_ref = (ref * peso_h[:, None]).sum(axis=0)
    media_ref = media_ref / media_ref.sum() if media_ref.sum() > 0 else atual
    ref[~tem_ref] = media_ref

    apurados = tem_ref & (votos_obs.sum(axis=1) > 0)
    if not apurados.any():
        return None
    delta = estimar_swing(votos_obs[apurados], ref[apurados])

    # Estrato: referência + swing, misturada com o % apurado dele (peso crescente com os votos já contados)
    p_swing = _softmax(np.log(np.clip(ref, 1e-9, None)) + delta[None, :])
    n_h = votos_obs.sum(axis=1, keepdims=True)
    share_obs = np.where(n_h > 0, votos_obs / np.where(n_h == 0, 1.0, n_h), p_swing)
    w = peso_referencia / (peso_referencia + n_h)
    p_final = w * p_swing + (1.0 - w) * share_obs

    resultado = _agregar(estrato_ids, votos_obs + p_final * restantes[:, None], numeros)
    base = _agregar(estrato_ids, votos_obs + ref * restantes[:, None], numeros)
    cobertura = float(votos_obs[tem_ref].sum() / max(1.0, votos_obs.sum()))
    resultado.update({
        "sem_swing": base["nacional"],
        "delta": {n: round(float(d), 4) for n, d in zip(numeros, delta)},
        "referencia": referencia.fonte,
        "cobertura": round(cobertura, 4),
    })
    return resultado


# ------------------------------------------------------------- tendência temporal por estrato

def projetar_tendencia(historico: Dict[str, List[Tuple[int, int, Dict[str, int]]]], snapshots: Dict[str, Any],
                       estrato_ids: Sequence[str], votos_obs: np.ndarray, restantes: np.ndarray,
                       numeros: Sequence[str], janela: float = 0.30, min_pontos: int = 4,
                       limite: float = 0.06) -> Dict[str, Any]:
    """
    Tendência do % de cada candidato nos votos que chegaram por último em cada estrato.

    Com a série do estrato (eleitores computados e votos acumulados a cada atualização), calcula o % em cada
    novo bloco de votos, ajusta uma reta pelos blocos mais recentes (últimos `janela` dos eleitores computados,
    com pelo menos `min_pontos` blocos) e usa o valor da reta no meio do que falta como % dos votos restantes.
    A extrapolação fica a no máximo `limite` do % atual (os blocos são pequenos e ruidosos). Estrato sem
    série suficiente usa o % atual (como o estimador direto).
    """
    K = len(numeros)
    H = len(estrato_ids)
    final = votos_obs.copy()
    usados = 0
    for h, eid in enumerate(estrato_ids):
        n_h = votos_obs[h].sum()
        atual = votos_obs[h] / n_h if n_h > 0 else None
        if atual is None:
            continue
        pred = atual
        pontos = historico.get(eid) or []
        snap = snapshots.get(eid)
        if len(pontos) >= min_pontos + 1 and snap is not None and restantes[h] > 0:
            c = np.array([p[1] for p in pontos], dtype=np.float64)       # eleitores computados (acumulado)
            v = np.array([[p[2].get(n, 0) for n in numeros] for p in pontos], dtype=np.float64)
            dv = np.diff(v, axis=0)
            dc = np.diff(c)
            ok = (dc > 0) & (dv.sum(axis=1) > 0)
            if ok.sum() >= min_pontos:
                meio = (c[:-1] + c[1:]) / 2.0
                corte = c[-1] * (1.0 - janela)
                sel = ok & (meio >= corte)
                if sel.sum() < min_pontos:                                 # poucos blocos recentes: usa os últimos
                    idx = np.where(ok)[0][-min_pontos:]
                    sel = np.zeros_like(ok)
                    sel[idx] = True
                x, w = meio[sel], dv[sel].sum(axis=1)
                y = dv[sel] / dv[sel].sum(axis=1, keepdims=True)           # % de cada candidato em cada bloco
                aptos = max(float(snap.eleitores_aptos), c[-1])
                x_alvo = c[-1] + (aptos - c[-1]) / 2.0                     # meio do que falta
                if np.ptp(x) > 0:
                    xm = np.average(x, weights=w)
                    sxx = np.average((x - xm) ** 2, weights=w)
                    inclin = np.average((x - xm)[:, None] * (y - np.average(y, axis=0, weights=w)), axis=0, weights=w) / sxx
                    base = np.average(y, axis=0, weights=w)
                    prev = base + inclin * (x_alvo - xm)
                    prev = np.clip(prev, atual - limite, atual + limite)
                    prev = np.clip(prev, 0.0, 1.0)
                    if prev.sum() > 0:
                        pred = prev / prev.sum()
                        usados += 1
        final[h] = votos_obs[h] + pred * restantes[h]
    resultado = _agregar(estrato_ids, final, numeros)
    resultado["estratos_com_tendencia"] = usados
    return resultado


# ------------------------------------------------------ Bayes empírico hierárquico (encolhimento)

def projetar_hierarquico(estrato_ids: Sequence[str], votos_obs: np.ndarray, restantes: np.ndarray,
                         numeros: Sequence[str]) -> Dict[str, Any]:
    """
    Modelo hierárquico normal-normal, ajustado por Bayes empírico (forma fechada): o % de cada estrato é uma
    observação ruidosa (variância binomial p(1−p)/n) de um % verdadeiro que varia entre os estratos da mesma UF
    em torno da média da UF, com variância entre estratos τ² estimada por momentos, por candidato. O % de cada
    estrato é encolhido para a média da UF com peso τ²/(τ²+variância amostral): estratos com poucos votos
    contados aprendem mais com os vizinhos; estratos grandes ficam com o próprio %. Os votos que faltam seguem o
    % encolhido de cada estrato.
    """
    H, K = votos_obs.shape
    n_h = votos_obs.sum(axis=1)
    ufs = np.array([eid.split("_")[0] for eid in estrato_ids])
    com_voto = n_h > 0
    tem_uf = {uf: np.where((ufs == uf) & com_voto)[0] for uf in np.unique(ufs)}
    theta = np.zeros((H, K))
    for k in range(K):
        s = np.where(com_voto, votos_obs[:, k] / np.where(n_h == 0, 1.0, n_h), 0.0)
        nacional = votos_obs[:, k].sum() / max(1.0, n_h.sum())
        # variância amostral com o % nacional (com o do próprio estrato, 0% ou 100% daria variância zero)
        var = np.where(com_voto, max(nacional * (1 - nacional), 1e-4) / np.where(n_h == 0, 1.0, n_h), np.inf)
        # τ² por momentos: variação do % em torno da média da UF que excede a esperada pelo acaso
        excesso, peso = 0.0, 0.0
        for uf, idx in tem_uf.items():
            if len(idx) < 2:
                continue
            mu = np.average(s[idx], weights=n_h[idx])
            excesso += float((n_h[idx] * ((s[idx] - mu) ** 2 - var[idx])).sum())
            peso += float(n_h[idx].sum())
        tau2 = max(1e-5, excesso / peso) if peso > 0 else 1e-3
        for h in range(H):
            idx = tem_uf.get(ufs[h])
            mu = np.average(s[idx], weights=n_h[idx]) if idx is not None and len(idx) else nacional
            if not com_voto[h]:
                theta[h, k] = mu
            else:
                b = tau2 / (tau2 + var[h])
                theta[h, k] = mu + b * (s[h] - mu)
    theta = np.clip(theta, 1e-9, None)
    theta = theta / theta.sum(axis=1, keepdims=True)
    return _agregar(estrato_ids, votos_obs + theta * restantes[:, None], numeros)


# -------------------------------------------------------------- limites e consenso

def limites_matematicos(votos_obs: np.ndarray, restantes_maximos: float, numeros: Sequence[str]) -> Dict[str, Dict[str, float]]:
    """% final mínimo e máximo de cada candidato: todo voto que pode faltar vai para os outros ou para ele."""
    obs = votos_obs.sum(axis=0)
    total = float(obs.sum())
    teto = total + float(restantes_maximos)
    if teto <= 0:
        return {}
    return {n: {"min": round(float(o) / teto * 100.0, 3), "max": round((float(o) + restantes_maximos) / teto * 100.0, 3)}
            for n, o in zip(numeros, obs)}


def consenso(estimativas: Dict[str, Dict[str, float]], numeros: Sequence[str]) -> Optional[Dict[str, Any]]:
    """Média, mediana e extremos do % de cada candidato entre os modelos informados ({modelo: {número: %}})."""
    modelos = {m: e for m, e in estimativas.items() if e}
    if len(modelos) < 2:
        return None
    mat = np.array([[e.get(n, 0.0) for n in numeros] for e in modelos.values()], dtype=np.float64)
    return {
        "media": {n: round(float(x), 3) for n, x in zip(numeros, mat.mean(axis=0))},
        "mediana": {n: round(float(x), 3) for n, x in zip(numeros, np.median(mat, axis=0))},
        "minimo": {n: round(float(x), 3) for n, x in zip(numeros, mat.min(axis=0))},
        "maximo": {n: round(float(x), 3) for n, x in zip(numeros, mat.max(axis=0))},
        "modelos": list(modelos),
    }

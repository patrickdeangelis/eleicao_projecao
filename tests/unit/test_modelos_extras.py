"""
Modelos extras da aba Modelos (estimador direto e swing sobre eleição de referência) e a parada da coleta em 100%.
"""
import asyncio
import gzip
import json

import numpy as np
import pytest

from spetr.collector.scheduler import TieredScheduler
from spetr.services.event_bus import EventBus
from spetr.services.events import CollectionFinishedEvent, RawBatchReceivedEvent
from spetr.stats_engine.modelos_extras import (
    ReferenciaEleitoral, carregar_referencia, estimar_swing, projetar_direto, projetar_swing,
)


def test_estimador_direto_aplica_o_percentual_atual_ao_que_falta():
    ids = ["SP_1", "SP_INTERIOR"]
    obs = np.array([[60.0, 40.0], [30.0, 70.0]])
    rest = np.array([100.0, 0.0])
    r = projetar_direto(ids, obs, rest, ["13", "22"])
    # SP_1 faltam 100 votos no % atual (60/40); o interior está completo
    assert r["votos_nacionais"] == {"13": 150, "22": 150}
    assert r["ufs"]["SP"]["13"] == pytest.approx(50.0, abs=0.001)


def test_estimador_direto_estrato_sem_voto_usa_o_percentual_nacional():
    r = projetar_direto(["A_1", "B_1"], np.array([[80.0, 20.0], [0.0, 0.0]]), np.array([0.0, 100.0]), ["13", "22"])
    assert r["votos_nacionais"] == {"13": 160, "22": 40}


def _referencia(tmp_path=None):
    # Eleição anterior: SP (cidade 1 + interior 2) e BA (cidade 3 + interior 4), candidatos 13 e 22
    municipios = {("SP", "00001"): np.array([600.0, 400.0]), ("SP", "00002"): np.array([300.0, 700.0]),
                  ("BA", "00003"): np.array([700.0, 300.0]), ("BA", "00004"): np.array([500.0, 500.0])}
    return ReferenciaEleitoral("2026_1t", ["13", "22"], municipios,
                               {"SP": ["00001"], "BA": ["00003"]}, {})


def test_referencia_remonta_os_estratos_do_spetr():
    ref = _referencia()
    assert ref.vetor("SP_00001").tolist() == [600, 400]
    assert ref.vetor("SP_INTERIOR").tolist() == [300, 700]       # UF − cidades
    assert ref.vetor("BA_TOTAL").tolist() == [1200, 800]
    assert ref.vetor("SP_SEM_DADOS").tolist() == [900, 1100]
    assert ref.vetor("RJ_INTERIOR") is None                      # UF fora da referência


def test_referencia_subestratos_e_cidades_agrupadas():
    municipios = {("MG", "1"): np.array([10.0, 0.0]), ("MG", "2"): np.array([0.0, 20.0]),
                  ("MG", "3"): np.array([5.0, 5.0]), ("MG", "4"): np.array([1.0, 1.0])}
    ref = ReferenciaEleitoral("x", ["13", "22"], municipios, {"MG": ["1", "2"]},
                              {"MG": {"grupos": {"NORTE": ["3"]}, "resto": "SUL", "cidades": {"NORTE": ["1"], "SUL": ["2"]}}})
    assert ref.vetor("MG_SUB_NORTE").tolist() == [5, 5]
    assert ref.vetor("MG_SUB_SUL").tolist() == [1, 1]            # Interior − Norte
    assert ref.vetor("MG_CID_NORTE").tolist() == [10, 0]
    assert ref.vetor("MG_CID_SUL").tolist() == [0, 20]


def test_estimar_swing_recupera_a_mudanca_nacional():
    ref = np.array([[0.6, 0.4], [0.3, 0.7], [0.7, 0.3]])
    delta_real = np.array([0.5, -0.5])
    p = np.exp(np.log(ref) + delta_real)
    p /= p.sum(axis=1, keepdims=True)
    obs = p * 10000
    d = estimar_swing(obs, ref)
    # só a diferença entre candidatos é identificável: 1,0 em log
    assert d[0] - d[1] == pytest.approx(1.0, abs=0.01)


def test_swing_acerta_onde_a_parcial_e_enviesada():
    ref = _referencia()
    ids = ["SP_00001", "SP_INTERIOR", "BA_00003", "BA_INTERIOR"]
    # Verdade: todo estrato se move 8 pontos em direção ao 13 (swing uniforme)
    ref_pct = np.array([[0.6, 0.4], [0.3, 0.7], [0.7, 0.3], [0.5, 0.5]])
    verdade = ref_pct + np.array([0.08, -0.08])
    totais = np.array([1000.0, 1000.0, 1000.0, 1000.0])
    # Apurado: cidades quase completas; o interior de SP mal começou e as primeiras urnas dele favorecem o 13
    # (viés de ordem: o que falta lá é bem mais 22 do que o apurado)
    apurado_frac = np.array([0.9, 0.05, 0.9, 0.5])
    vies = np.array([[0.0, 0.0], [0.25, -0.25], [0.0, 0.0], [0.0, 0.0]])
    obs = (verdade + vies) * (totais * apurado_frac)[:, None]
    rest = totais * (1 - apurado_frac)
    r = projetar_swing(ref, ids, obs, rest, ["13", "22"], peso_referencia=20000.0)
    direto = projetar_direto(ids, obs, rest, ["13", "22"])
    final_real = obs.sum(axis=0) + (verdade * rest[:, None]).sum(axis=0)
    final_real = final_real / final_real.sum() * 100
    assert r["referencia"] == "2026_1t" and r["cobertura"] == 1.0
    assert abs(r["nacional"]["13"] - final_real[0]) < abs(direto["nacional"]["13"] - final_real[0])
    assert r["delta"]["13"] > r["delta"]["22"]                   # o 13 ganhou em relação à referência
    assert r["sem_swing"]["13"] < r["nacional"]["13"]            # o swing empurra a projeção para o 13


def test_swing_sem_cobertura_da_referencia_nao_projeta():
    ref = _referencia()
    assert projetar_swing(ref, ["RJ_1"], np.array([[10.0, 5.0]]), np.array([10.0]), ["13", "22"]) is None


def test_swing_candidato_sem_referencia_nao_quebra():
    ref = _referencia()
    ids = ["SP_00001", "BA_00003"]
    r = projetar_swing(ref, ids, np.array([[50.0, 30.0, 20.0], [60.0, 25.0, 15.0]]), np.array([50.0, 40.0]), ["13", "22", "99"])
    assert r is not None and sum(r["nacional"].values()) == pytest.approx(100.0, abs=0.01)


def test_carregar_referencia_le_o_replay_preparado(tmp_path):
    dados = {
        "ano": "2026", "turno": 1, "eleicao": "6257", "t0": "2026-10-04 16:50",
        "candidatos": [{"n": "13", "nm": "A", "partido": "PT"}, {"n": "22", "nm": "B", "partido": "PL"}],
        "municipios": [["SP", "71072", "SAO PAULO", 10, 4000], ["SP", "99001", "INTERIOR", 5, 2000]],
        "eventos": [[0, 0, 5, 2000, 1600, 400, 10, 10, 700, 800], [10, 0, 5, 2000, 1600, 400, 10, 10, 100, 200],
                    [5, 1, 5, 2000, 1600, 400, 10, 10, 300, 600]],
    }
    with gzip.open(tmp_path / "2026_1t.json.gz", "wt", encoding="utf-8") as f:
        json.dump(dados, f)
    ref = carregar_referencia("2026", 2, {"SP": ["71072"]}, {}, pasta=str(tmp_path))
    assert ref.fonte == "2026_1t"
    assert ref.vetor("SP_71072").tolist() == [800, 1000]          # soma dos eventos do município
    assert ref.vetor("SP_INTERIOR").tolist() == [300, 600]
    assert carregar_referencia("2026", 1, {}, {}, pasta=str(tmp_path)) is None   # 2022_1t não preparado
    assert carregar_referencia("2018", 1, {}, {}, pasta=str(tmp_path)) is None   # sem referência definida


def test_motor_publica_estimador_direto_e_swing():
    from spetr.domain.entities import SnapshotParcial
    from spetr.stats_engine.monte_carlo import MonteCarloProjectionEngine

    def snap(eid, apuradas, v13, v22, total=100):
        return SnapshotParcial(estrato_id=eid, timestamp="", secoes_total=total, secoes_apuradas=apuradas,
                               eleitores_aptos=total * 400, comparecimento=apuradas * 320, abstencao=apuradas * 80,
                               votos_validos=v13 + v22, votos_brancos=0, votos_nulos=0, votos_candidatos={"13": v13, "22": v22})
    eng = MonteCarloProjectionEngine(num_simulacoes=300, seed=1)
    eng.referencia = _referencia()
    snaps = {"SP_00001": snap("SP_00001", 80, 18000, 12000), "SP_INTERIOR": snap("SP_INTERIOR", 20, 3000, 6000)}
    a = eng.calcular(snaps, num_simulacoes=300).analise
    assert set(a["modelos"]["estimador_direto"]) == {"normal", "subestratificado"}
    assert a["modelos"]["swing"]["normal"]["referencia"] == "2026_1t"
    assert set(a["direto_versoes"]) == {"normal", "subestratificado"} and "swing_versoes" in a

    eng2 = MonteCarloProjectionEngine(num_simulacoes=300, seed=1)   # sem referência: só o estimador direto
    a2 = eng2.calcular(snaps, num_simulacoes=300).analise
    assert "swing" not in a2["modelos"] and "estimador_direto" in a2["modelos"]


# ------------------------------------------------------------ coleta para em 100%

def _uf_concluida():
    return {"s": "10", "st": "10", "e": "4000", "c": "3000", "a": "1000", "vv": "2900", "vb": "50", "vn": "50",
            "cand": [{"n": "13", "vap": "1500"}, {"n": "22", "vap": "1400"}]}


def _uf_parcial():
    return {**_uf_concluida(), "st": "7"}


@pytest.mark.asyncio
async def test_coleta_faz_duas_coletas_extras_em_100_e_encerra():
    bus = EventBus()
    lotes, fim = [], []

    async def ao_lote(e):
        lotes.append(e)

    async def ao_fim(e):
        fim.append(e)

    bus.subscribe(RawBatchReceivedEvent, ao_lote)
    bus.subscribe(CollectionFinishedEvent, ao_fim)
    sch = TieredScheduler(event_bus=bus, codigo_eleicao="1", formato="r", intervalo_tier1=0.01)
    chamadas = []

    async def coletar(incluir_tier2, incluir_exterior=False, incluir_subestratos=False):
        chamadas.append(1)
        return {f"UF_{uf}": _uf_concluida() for uf in sch.ufs}, 0, []

    sch._coletar = coletar
    await asyncio.wait_for(sch.iniciar_loop(), timeout=5)
    assert len(chamadas) == 3                  # a que viu o 100% + 2 de segurança
    assert len(lotes) == 3 and len(fim) == 1   # todas as coletas viram projeção; depois a coleta para
    assert "coleta encerrada" in fim[0].mensagem and sch._rodando is False


@pytest.mark.asyncio
async def test_coleta_nao_para_enquanto_alguma_uf_nao_esta_em_100():
    sch = TieredScheduler(codigo_eleicao="1", formato="r", intervalo_tier1=0.01)
    chamadas = []

    async def coletar(incluir_tier2, incluir_exterior=False, incluir_subestratos=False):
        chamadas.append(1)
        lote = {f"UF_{uf}": _uf_concluida() for uf in sch.ufs}
        if len(chamadas) <= 2:
            lote["UF_SP"] = _uf_parcial()
        if len(chamadas) == 3:
            return lote, 0, ["UF_BA"]          # falha de rede numa UF não conta como 100%
        return lote, 0, []

    sch._coletar = coletar
    await asyncio.wait_for(sch.iniciar_loop(), timeout=5)
    assert len(chamadas) == 6                  # 2 parciais + 1 com falha + 3 em 100%


@pytest.mark.asyncio
async def test_replay_nao_encerra_a_coleta_em_100():
    sch = TieredScheduler(codigo_eleicao="1", formato="r", intervalo_tier1=0.01, parar_ao_concluir=False)
    chamadas = []

    async def coletar(incluir_tier2, incluir_exterior=False, incluir_subestratos=False):
        chamadas.append(1)
        if len(chamadas) == 8:
            sch.parar()
        return {f"UF_{uf}": _uf_concluida() for uf in sch.ufs}, 0, []

    sch._coletar = coletar
    await asyncio.wait_for(sch.iniciar_loop(), timeout=5)
    assert len(chamadas) == 8


# ------------------------------------------------ tendência, Bayes hierárquico, limites, consenso

def test_limites_matematicos():
    from spetr.stats_engine.modelos_extras import limites_matematicos
    obs = np.array([[600.0, 300.0], [200.0, 100.0]])        # 13: 800 · 22: 400
    lim = limites_matematicos(obs, 300.0, ["13", "22"])
    assert lim["13"] == {"min": pytest.approx(800 / 1500 * 100, abs=0.001), "max": pytest.approx(1100 / 1500 * 100, abs=0.001)}
    assert lim["22"]["min"] < lim["22"]["max"] <= 100.0
    assert limites_matematicos(np.zeros((1, 2)), 0.0, ["13", "22"]) == {}


def test_consenso_media_mediana_e_extremos():
    from spetr.stats_engine.modelos_extras import consenso
    c = consenso({"a": {"13": 40.0}, "b": {"13": 50.0}, "c": {"13": 60.0}, "vazio": {}}, ["13"])
    assert c["media"]["13"] == 50.0 and c["mediana"]["13"] == 50.0
    assert c["minimo"]["13"] == 40.0 and c["maximo"]["13"] == 60.0 and c["modelos"] == ["a", "b", "c"]
    assert consenso({"a": {"13": 40.0}}, ["13"]) is None     # um modelo só não é consenso


def test_hierarquico_encolhe_estrato_pequeno_para_a_media_da_uf():
    from spetr.stats_engine.modelos_extras import projetar_hierarquico
    ids = ["SP_1", "SP_2", "SP_3", "SP_4"]
    # Três estratos grandes com ~50% e um minúsculo com 100% (só 4 votos contados): o hierárquico não confia nele
    obs = np.array([[5000.0, 5000.0], [5100.0, 4900.0], [4900.0, 5100.0], [4.0, 0.0]])
    rest = np.array([0.0, 0.0, 0.0, 10000.0])
    h = projetar_hierarquico(ids, obs, rest, ["13", "22"])
    d = projetar_direto(ids, obs, rest, ["13", "22"])
    assert d["votos_nacionais"]["13"] == 25004                # o direto extrapola os 100% do estrato minúsculo
    assert h["nacional"]["13"] < d["nacional"]["13"]          # o hierárquico puxa para ~50% da UF
    assert h["nacional"]["13"] == pytest.approx(50.0, abs=3.0)


def test_hierarquico_estrato_grande_fica_com_o_proprio_percentual():
    from spetr.stats_engine.modelos_extras import projetar_hierarquico
    ids = ["SP_1", "SP_2"]
    obs = np.array([[90000.0, 10000.0], [10000.0, 90000.0]])  # estratos muito diferentes e enormes
    rest = np.array([1000.0, 1000.0])
    h = projetar_hierarquico(ids, obs, rest, ["13", "22"])
    assert h["votos_nacionais"]["13"] == pytest.approx(90000 + 10000 + 900 + 100, abs=60)


def test_tendencia_extrapola_a_deriva_dos_ultimos_blocos():
    from spetr.domain.entities import SnapshotParcial
    from spetr.stats_engine.modelos_extras import projetar_tendencia
    # Cada bloco de 1000 eleitores computados traz 1 ponto percentual a menos para o 13 (50%, 49%, ... )
    hist, v13, v22, c = [], 0, 0, 0
    for i in range(10):
        c += 1000
        v13 += 500 - 10 * i
        v22 += 500 + 10 * i
        hist.append((i + 1, c, {"13": v13, "22": v22}))
    snap = SnapshotParcial(estrato_id="SP_1", timestamp="", secoes_total=100, secoes_apuradas=10, eleitores_aptos=20000,
                           comparecimento=c, abstencao=0, votos_validos=v13 + v22, votos_brancos=0, votos_nulos=0,
                           votos_candidatos={"13": v13, "22": v22})
    obs = np.array([[v13, v22]], dtype=float)
    rest = np.array([10000.0])
    t = projetar_tendencia({"SP_1": hist}, {"SP_1": snap}, ["SP_1"], obs, rest, ["13", "22"])
    d = projetar_direto(["SP_1"], obs, rest, ["13", "22"])
    assert t["estratos_com_tendencia"] == 1
    assert t["nacional"]["13"] < d["nacional"]["13"]          # a tendência é de queda do 13
    # sem série suficiente, cai no estimador direto
    t2 = projetar_tendencia({}, {"SP_1": snap}, ["SP_1"], obs, rest, ["13", "22"])
    assert t2["nacional"] == d["nacional"] and t2["estratos_com_tendencia"] == 0


def test_motor_publica_todos_os_modelos_extras_e_o_resumo_do_historico():
    from spetr.domain.entities import SnapshotParcial
    from spetr.stats_engine.monte_carlo import MonteCarloProjectionEngine

    def snap(eid, apuradas, v13, v22, total=100):
        return SnapshotParcial(estrato_id=eid, timestamp="", secoes_total=total, secoes_apuradas=apuradas,
                               eleitores_aptos=total * 400, comparecimento=apuradas * 320, abstencao=apuradas * 80,
                               votos_validos=v13 + v22, votos_brancos=0, votos_nulos=0, votos_candidatos={"13": v13, "22": v22})
    eng = MonteCarloProjectionEngine(num_simulacoes=400, seed=1)
    eng.referencia = _referencia()
    for passo in (30, 50, 70):          # alimenta a série dos estratos (tendência e crescimento)
        snaps = {"SP_00001": snap("SP_00001", passo, 600 * passo, 400 * passo), "SP_INTERIOR": snap("SP_INTERIOR", passo // 2, 200 * passo, 400 * passo)}
        a = eng.calcular(snaps, num_simulacoes=400).analise
    m = a["modelos"]
    for chave in ("estimador_direto", "swing", "tendencia", "hierarquico", "crescimento_curto", "crescimento_longo", "consenso"):
        assert set(m[chave]) == {"normal", "subestratificado"}, chave
    assert m["mc_regional"]["status_call"] and m["bayes_puro"]["nacional"]["13"]["ic"][0] <= m["bayes_puro"]["nacional"]["13"]["pct"]
    # O "Bayes puro" (sem choques nem limite de concentração) é bem mais confiante que o Meu Modelo
    amplo = lambda x: x["ic"][1] - x["ic"][0]
    principal = a["subestratificacao"]["versoes"]["subestratificado"]["nacional"]["13"] if "subestratificacao" in a else None
    if principal:
        assert amplo(m["bayes_puro"]["nacional"]["13"]) < amplo(principal)
    assert "13" in m["limites"] and m["limites"]["13"]["min"] <= m["limites"]["13"]["max"]
    assert set(m["consenso"]["normal"]) >= {"media", "mediana", "minimo", "maximo", "modelos"}
    r = a["modelos_resumo"]
    assert set(r) == {"tendencia", "hierarquico", "crescimento_curto", "crescimento_longo", "consenso", "mc_regional", "bayes_puro"}
    assert "13" in r["mc_regional"]["_"] and "13" in r["tendencia"]["normal"]

"""
Testes da subestratificação do interior (ex.: MG Norte × Sul), da projeção extra por razão de
crescimento e do reaproveitamento de arquivos de município já 100% apurados.
"""
import httpx
import numpy as np
import pytest

from spetr.aggregator.vector_subtraction import VectorAggregator
from spetr.collector.client import TSEHttpClient
from spetr.collector.pacing import PacingManager
from spetr.collector.scheduler import TieredScheduler
from spetr.domain.entities import SnapshotParcial
from spetr.stats_engine.crescimento import ProjecaoCrescimento
from spetr.stats_engine.monte_carlo import MonteCarloProjectionEngine


def _arq(s, st, e, c, a, v13, v22):
    return {"s": str(s), "st": str(st), "e": str(e), "c": str(c), "a": str(a),
            "vv": str(v13 + v22), "vb": "0", "vn": "0",
            "cand": [{"n": "13", "vap": str(v13)}, {"n": "22", "vap": str(v22)}]}


def _lote(norte_apurado=True):
    # MG = BH + Interior; Interior = Norte (2 municípios) + Sul
    lote = {
        "UF_MG": _arq(1000, 500, 300000, 160000, 40000, 90000, 60000),
        "MUN_MG_41238": _arq(300, 150, 90000, 50000, 10000, 20000, 25000),
    }
    if norte_apurado:
        lote["MUN_MG_47015"] = _arq(100, 50, 30000, 15000, 5000, 9000, 4000)
        lote["MUN_MG_47016"] = _arq(100, 40, 30000, 12000, 3000, 7000, 3000)
    return lote


def _agregador():
    ag = VectorAggregator(cidades_100k_map={"MG": ["41238"]})
    ag.configurar_subestratos({"MG": {"grupos": {"NORTE": ["47015", "47016"]}, "resto": "SUL"}})
    return ag


def test_interior_dividido_em_norte_e_sul_por_subtracao():
    snaps = _agregador().processar_lote_bruto(_lote())
    interior, norte, sul = snaps["MG_INTERIOR"], snaps["MG_SUB_NORTE"], snaps["MG_SUB_SUL"]
    assert norte.secoes_total == 200 and norte.secoes_apuradas == 90
    assert norte.votos_candidatos == {"13": 16000, "22": 7000}
    assert interior.votos_candidatos == {"13": 70000, "22": 35000}
    assert sul.votos_candidatos == {"13": 54000, "22": 28000}
    assert sul.secoes_apuradas == interior.secoes_apuradas - norte.secoes_apuradas


def test_lote_sem_os_municipios_do_grupo_mantem_a_divisao_anterior():
    ag = _agregador()
    antes = ag.processar_lote_bruto(_lote())
    lote = _lote(norte_apurado=False)
    lote["UF_MG"] = _arq(1000, 700, 300000, 220000, 60000, 130000, 80000)
    depois = ag.processar_lote_bruto(lote)
    # O Interior avança, mas Norte/Sul ficam no último cálculo coerente (o avanço do Norte
    # não pode ser atribuído ao Sul)
    assert depois["MG_INTERIOR"].votos_candidatos != antes["MG_INTERIOR"].votos_candidatos
    assert depois["MG_SUB_SUL"] == antes["MG_SUB_SUL"]
    assert depois["MG_SUB_NORTE"] == antes["MG_SUB_NORTE"]


def test_motor_projeta_as_duas_versoes_e_a_principal_define_os_estratos():
    snaps = _agregador().processar_lote_bruto(_lote())
    eng = MonteCarloProjectionEngine(num_simulacoes=500, seed=1)
    eng.inicializar_ufs({"MG": {"eleitores": 300000, "secoes": 1000}})
    r = eng.calcular(snaps, num_simulacoes=500)
    sub = r.analise["subestratificacao"]
    assert sub["versao_principal"] == "subestratificado"
    assert set(sub["versoes"]) == {"subestratificado", "normal"}
    ids = {e["id"] for e in r.analise["estratos"]}
    assert {"MG_SUB_NORTE", "MG_SUB_SUL"} <= ids and "MG_INTERIOR" not in ids
    assert set(r.analise["versoes_resumo"]["normal"]) == {"nacional", "MG"}

    eng.versao_principal = "normal"
    r2 = eng.calcular(snaps, num_simulacoes=500)
    ids2 = {e["id"] for e in r2.analise["estratos"]}
    assert "MG_INTERIOR" in ids2 and "MG_SUB_NORTE" not in ids2


def test_sem_subestratos_nao_ha_comparacao_de_versoes():
    ag = VectorAggregator(cidades_100k_map={"MG": ["41238"]})
    snaps = ag.processar_lote_bruto(_lote())
    eng = MonteCarloProjectionEngine(num_simulacoes=300, seed=1)
    r = eng.calcular(snaps, num_simulacoes=300)
    assert "subestratificacao" not in r.analise
    assert "crescimento" in r.analise


def _snap(apuradas, computados, v13, v22, total=100, eleitores=10000):
    return SnapshotParcial(
        estrato_id="X_INTERIOR", timestamp="", secoes_total=total, secoes_apuradas=apuradas,
        eleitores_aptos=eleitores, comparecimento=int(computados * 0.8), abstencao=computados - int(computados * 0.8),
        votos_validos=v13 + v22, votos_brancos=0, votos_nulos=0, votos_candidatos={"13": v13, "22": v22})


def test_crescimento_usa_a_razao_por_eleitor_da_janela_recente():
    c = ProjecaoCrescimento(janela=0.15, min_secoes=5)
    # Primeiras 50 seções: 5000 eleitores, 60/40; seções seguintes (50→70): 2000 eleitores, 30/70
    c.registrar({"X": _snap(50, 5000, 2400, 1600)})
    atual = _snap(70, 7000, 2400 + 480, 1600 + 1120)
    c.registrar({"X": atual})
    r = c.estrato("X", atual)
    assert r["base"] == "recente" and r["secoes_janela"] == 20
    assert r["razao_por_eleitor"]["13"] == pytest.approx(480 / 2000)
    assert r["eleitores_faltantes"] == 3000
    assert r["votos_projetados"]["22"] == pytest.approx(2720 + 1120 / 2000 * 3000)


def test_crescimento_sem_janela_usa_a_razao_acumulada():
    c = ProjecaoCrescimento(janela=0.15, min_secoes=5)
    atual = _snap(10, 1000, 300, 500)
    c.registrar({"X": atual})
    r = c.estrato("X", atual)
    assert r["base"] == "acumulado"
    assert r["razao_por_eleitor"]["22"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_arquivo_de_municipio_concluido_nao_e_pedido_de_novo(monkeypatch):
    pedidos = []

    def responder(req):
        pedidos.append(req.url.path)
        if "mg41238" in req.url.path:
            return httpx.Response(200, json=_arq(300, 300, 90000, 70000, 20000, 30000, 35000))
        return httpx.Response(200, json=_arq(1000, 500, 300000, 160000, 40000, 90000, 60000))

    cliente = TSEHttpClient(pacing=PacingManager(max_rate_per_sec=1000))
    cliente._client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    sch = TieredScheduler(http_client=cliente, base_url="http://x", codigo_eleicao="1", formato="u")
    sch.ufs = ["MG"]
    sch.configurar_alvos({"MG": ["41238"]}, {"MG": "41238"})

    lote1, _, _ = await sch._coletar(incluir_tier2=True)
    lote2, _, _ = await sch._coletar(incluir_tier2=True)
    assert sum("mg41238" in p for p in pedidos) == 1        # concluído: não pede de novo
    assert sum(p.endswith("mg-c0001-e000001-u.json") for p in pedidos) == 2  # UF sempre
    assert lote2["MUN_MG_41238"] == lote1["MUN_MG_41238"]   # mas o lote traz a última cópia
    assert sch.requisicoes_poupadas == 1

    sch.intervalo_reconferir = 0                              # hora de reconferir
    await sch._coletar(incluir_tier2=True)
    assert sum("mg41238" in p for p in pedidos) == 2


@pytest.mark.asyncio
async def test_municipio_com_404_fica_suspenso():
    pedidos = []

    def responder(req):
        pedidos.append(req.url.path)
        if "mg47015" in req.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json=_arq(1000, 500, 300000, 160000, 40000, 90000, 60000))

    cliente = TSEHttpClient(pacing=PacingManager(max_rate_per_sec=1000))
    cliente._client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    sch = TieredScheduler(http_client=cliente, base_url="http://x", codigo_eleicao="1", formato="u")
    sch.ufs = ["MG"]
    sch.configurar_alvos({}, {}, municipios_subestratos={"MG": ["47015"]})

    await sch._coletar(incluir_tier2=True, incluir_subestratos=True)
    await sch._coletar(incluir_tier2=True, incluir_subestratos=True)
    assert sum("mg47015" in p for p in pedidos) == 1   # 404 uma vez, depois suspenso
    sch._suspensos = {k: 0.0 for k in sch._suspensos}  # fim da suspensão
    await sch._coletar(incluir_tier2=True, incluir_subestratos=True)
    assert sum("mg47015" in p for p in pedidos) == 2


def test_replay_entrega_arquivos_na_ordem_de_recebimento(tmp_path):
    import gzip
    import json
    from spetr.simulador.replay import EstadoReplay

    dados = {
        "versao": 1, "ano": "2022", "turno": 2, "cargo": 1, "eleicao": "545", "t0": "2022-10-30 16:50",
        "candidatos": [{"n": "13", "nm": "LULA", "partido": "PT"}, {"n": "22", "nm": "JAIR BOLSONARO", "partido": "PL"}],
        "municipios": [["MG", "41238", "BELO HORIZONTE", 3, 900], ["MG", "47015", "JANAÚBA", 1, 300]],
        # minuto (desde t0), município, seções, aptos, comparecimento, abstenção, brancos, nulos, votos 13, votos 22
        "eventos": [[5, 1, 1, 300, 250, 50, 5, 5, 160, 80],      # antes das 17h: entra às 17h
                    [20, 0, 2, 600, 500, 100, 10, 10, 200, 280],
                    [80, 0, 1, 300, 240, 60, 4, 6, 100, 130]],
    }
    with gzip.open(tmp_path / "2022_2t.json.gz", "wt", encoding="utf-8") as f:
        json.dump(dados, f)
    est = EstadoReplay("2022_2t", "normal", pasta=str(tmp_path))
    assert est.inicio.hour == 17 and est.eleicao == "545"
    mg = est.somar([est.apurar_unidade("MG", u) for u in est.unidades_da_uf("MG")])
    assert mg["apuradas"] == 1 and mg["votos"] == [160, 80] and mg["eleitores"] == 1200
    est.definir(1.0)
    mg = est.somar([est.apurar_unidade("MG", u) for u in est.unidades_da_uf("MG")])
    assert mg["apuradas"] == 4 and mg["votos"] == [460, 490]
    payload = est.gerar_payload(mg)
    assert payload["st"] == "4" and payload["cand"][0]["st"] in ("Eleito", "Não eleito")


# ---------------------------------------------- cidades grandes agrupadas por região

def _lote_cidades():
    # MG = BH (sul) + Montes Claros (norte) + Interior (Norte: 47015, 47016; Sul: o resto)
    return {
        "UF_MG": _arq(1400, 700, 400000, 220000, 60000, 130000, 90000),
        "MUN_MG_41238": _arq(300, 150, 90000, 50000, 10000, 20000, 25000),
        "MUN_MG_45535": _arq(100, 50, 40000, 22000, 3000, 9000, 8000),
        "MUN_MG_47015": _arq(100, 50, 30000, 15000, 5000, 9000, 4000),
        "MUN_MG_47016": _arq(100, 40, 30000, 12000, 3000, 7000, 3000),
    }


def _agregador_cidades():
    ag = VectorAggregator(cidades_100k_map={"MG": ["41238", "45535"]})
    ag.configurar_subestratos({"MG": {
        "grupos": {"NORTE": ["47015", "47016"]}, "resto": "SUL",
        "cidades": {"NORTE": ["45535"], "SUL": ["41238"]},
    }})
    return ag


def test_cidades_grandes_agrupadas_por_regiao_e_fecham_com_a_uf():
    snaps = _agregador_cidades().processar_lote_bruto(_lote_cidades())
    cn, cs = snaps["MG_CID_NORTE"], snaps["MG_CID_SUL"]
    assert cn.votos_candidatos == snaps["MG_45535"].votos_candidatos
    assert cs.votos_candidatos == snaps["MG_41238"].votos_candidatos
    # As quatro partes recompõem a UF
    partes = [snaps[k] for k in ("MG_CID_NORTE", "MG_CID_SUL", "MG_SUB_NORTE", "MG_SUB_SUL")]
    uf = _lote_cidades()["UF_MG"]
    assert sum(p.secoes_total for p in partes) == int(uf["s"])
    assert sum(p.secoes_apuradas for p in partes) == int(uf["st"])
    assert sum(p.votos_candidatos["13"] for p in partes) == sum(
        int(c["vap"]) for c in uf["cand"] if c["n"] == "13")


def test_versao_subestratificada_usa_quatro_estratos_em_mg_e_a_normal_as_cidades():
    snaps = _agregador_cidades().processar_lote_bruto(_lote_cidades())
    normal, sub, ufs_sub = MonteCarloProjectionEngine.separar_versoes(snaps)
    assert ufs_sub == ["MG"]
    assert set(sub) == {"MG_CID_NORTE", "MG_CID_SUL", "MG_SUB_NORTE", "MG_SUB_SUL"}
    assert set(normal) == {"MG_41238", "MG_45535", "MG_INTERIOR"}

    eng = MonteCarloProjectionEngine(num_simulacoes=300, seed=1)
    eng.inicializar_ufs({"MG": {"eleitores": 300000, "secoes": 1400}})
    r = eng.calcular(snaps, num_simulacoes=300)
    tipos = {e["id"]: e["tipo"] for e in r.analise["estratos"]}
    assert tipos["MG_CID_NORTE"] == "SUBESTRATO_CIDADES" and tipos["MG_SUB_NORTE"] == "SUBESTRATO"
    assert "MG_41238" not in tipos and "MG_INTERIOR" not in tipos


def test_lote_sem_alguma_cidade_do_grupo_mantem_a_divisao_anterior():
    ag = _agregador_cidades()
    antes = ag.processar_lote_bruto(_lote_cidades())
    lote = _lote_cidades()
    del lote["MUN_MG_45535"]
    depois = ag.processar_lote_bruto(lote)
    assert depois["MG_CID_NORTE"] == antes["MG_CID_NORTE"]
    assert depois["MG_CID_SUL"] == antes["MG_CID_SUL"]


# ---------------------------------------------- aba Modelos: crescimento nas duas versões

def test_crescimento_nas_duas_versoes_no_pais_inteiro():
    snaps = _agregador_cidades().processar_lote_bruto(_lote_cidades())
    eng = MonteCarloProjectionEngine(num_simulacoes=300, seed=1)
    eng.inicializar_ufs({"MG": {"eleitores": 300000, "secoes": 1400}})
    a = eng.calcular(snaps, num_simulacoes=300).analise
    cr = a["modelos"]["crescimento"]
    assert set(cr) == {"normal", "subestratificado"}
    assert cr["subestratificado"]["nacional"] == a["crescimento_nacional"]  # principal = subestratificada
    assert set(cr["normal"]["ufs"]) == {"MG"} and "MG" in cr["normal"]["ufs_detalhe"]
    det = cr["subestratificado"]["ufs_detalhe"]["MG"]
    assert det["estratos_recentes"] + det["estratos_acumulados"] == 4  # 4 estratos de MG
    assert set(a["crescimento_versoes"]) == {"normal", "subestratificado"}

    # O Monte Carlo não muda por causa do crescimento
    eng2 = MonteCarloProjectionEngine(num_simulacoes=300, seed=1)
    eng2.inicializar_ufs({"MG": {"eleitores": 300000, "secoes": 1400}})
    r2 = eng2.calcular(snaps, num_simulacoes=300)
    assert [c.perc_projetado for c in r2.candidatos] == [c.perc_projetado for c in
        MonteCarloProjectionEngine(num_simulacoes=300, seed=1).calcular(snaps, num_simulacoes=300).candidatos]


def test_sem_subestratos_as_duas_versoes_de_crescimento_coincidem():
    ag = VectorAggregator(cidades_100k_map={"MG": ["41238"]})
    snaps = ag.processar_lote_bruto(_lote())
    a = MonteCarloProjectionEngine(num_simulacoes=300, seed=1).calcular(snaps, num_simulacoes=300).analise
    cr = a["modelos"]["crescimento"]
    assert cr["normal"]["nacional"] == cr["subestratificado"]["nacional"] == a["crescimento_nacional"]

"""
Testes de regressão para as correções da auditoria:
URLs 2026, regra de maioria absoluta, calibração da incerteza, UFs sem dados,
consistência do Interior, cliente HTTP/pacing, JWS e persistência por execução.
"""
import base64
import dataclasses
import json
import os
import sqlite3
import tempfile

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from spetr.aggregator.vector_subtraction import VectorAggregator
from spetr.api.routes import setup_routes
from spetr.api.sse_broadcaster import SSEBroadcaster
from spetr.collector.client import TSEHttpClient
from spetr.collector.jws import JWSVerifier, JWSInvalidoError
from spetr.collector.pacing import PacingManager
from spetr.collector.scheduler import TieredScheduler
from spetr.domain.entities import SnapshotParcial
from spetr.domain.value_objects import StatusCall
from spetr.stats_engine.monte_carlo import MonteCarloProjectionEngine
from spetr.storage.database import SQLiteDatabase
from spetr.storage.repository import ElectionRepository


# ---------------------------------------------------------------- helpers

def _snapshots(ufs, pct, shares, secs=2000, eleit=600000):
    out = {}
    for uf in ufs:
        eid = f"{uf}_TOTAL"
        st = int(secs * pct)
        comp = int(st * 300 * 0.8)
        val = int(comp * 0.95)
        out[eid] = SnapshotParcial(
            estrato_id=eid, timestamp="t", secoes_total=secs, secoes_apuradas=st,
            eleitores_aptos=eleit, comparecimento=comp, abstencao=st * 300 - comp,
            votos_validos=val, votos_brancos=0, votos_nulos=0,
            votos_candidatos={n: int(val * s) for n, s in shares.items()},
        )
    return out


UFS = ["SP", "MG", "RJ", "BA", "PR", "RS", "PE", "CE"]


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _assinar(chave: Ed25519PrivateKey, kid: str, payload: dict) -> str:
    cab = _b64url(json.dumps({"alg": "EdDSA", "kid": kid}).encode())
    dados = _b64url(json.dumps(payload).encode())
    sig = _b64url(chave.sign(f"{cab}.{dados}".encode()))
    return f"{cab}.{dados}.{sig}"


# ------------------------------------------------------- 1. URLs / EA11

def test_urls_formato_2026_unificado():
    s = TieredScheduler(ano_eleicao="2026", codigo_eleicao="21270", codigo_cargo="1", formato="u")
    assert s.url_uf("AC") == (
        "https://resultados.tse.jus.br/oficial/ele2026/21270/dados/ac/ac-c0001-e021270-u.json"
    )
    assert s.url_municipio("AC", "01120").endswith("/dados/ac/ac01120-c0001-e021270-u.json")


@pytest.mark.parametrize("eleicao", ["544", "545"])
def test_urls_formato_2022_simplificado_inalterado(eleicao):
    s = TieredScheduler(ano_eleicao="2022", codigo_eleicao=eleicao, codigo_cargo="0001", formato="r")
    assert s.url_uf("PB") == (
        f"https://resultados.tse.jus.br/oficial/ele2022/{eleicao}/dados-simplificados/pb/"
        f"pb-c0001-e{eleicao.zfill(6)}-r.json"
    )


def test_descoberta_da_eleicao_pelo_ele_c_json():
    path = "docs/tse_oficial/ele-c.json"
    if not os.path.exists(path):
        pytest.skip("ele-c.json oficial não disponível localmente")
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    assert TieredScheduler.escolher_eleicao(config, "2026", "1", 1) == "21270"
    assert TieredScheduler.escolher_eleicao(config, "2030", "1", 1) is None


# ---------------------------------------- 2. Maioria absoluta (1º turno)

def test_primeiro_turno_sem_maioria_nao_declara_vitoria():
    shares = {"13": 0.35, "22": 0.30}
    outros = [str(n) for n in range(40, 51)]
    shares.update({n: 0.35 / len(outros) for n in outros})
    eng = MonteCarloProjectionEngine(num_simulacoes=4000, seed=1)
    r = eng.calcular(_snapshots(UFS, 0.6, shares))

    lider = r.candidatos[0]
    assert lider.numero == "13"
    assert lider.prob_lideranca > 0.99      # quase certo em 1º lugar...
    assert lider.prob_vitoria < 0.01        # ...mas sem chance de maioria absoluta
    assert r.status_call == StatusCall.SEGUNDO_TURNO_PROJETADO
    assert r.vencedor_projetado is None
    assert r.prob_segundo_turno > 0.99


def test_matematicamente_eleito_exige_maioria_dos_validos():
    # 99% apurado, líder com 45% contra 13 adversários: lidera com folga, mas não tem maioria
    shares = {"13": 0.45, "22": 0.20}
    shares.update({str(n): 0.35 / 10 for n in range(40, 50)})
    eng = MonteCarloProjectionEngine(num_simulacoes=2000, seed=2)
    r = eng.calcular(_snapshots(UFS, 0.99, shares))
    assert r.status_call != StatusCall.MATEMATICAMENTE_ELEITO

    eng2 = MonteCarloProjectionEngine(num_simulacoes=2000, seed=2)
    r2 = eng2.calcular(_snapshots(UFS, 0.99, {"13": 0.70, "22": 0.30}))
    assert r2.status_call == StatusCall.MATEMATICAMENTE_ELEITO
    assert r2.vencedor_projetado == "13"


# ------------------------------------------- 3. Calibração da incerteza

def test_empate_tecnico_no_inicio_nao_e_chamado():
    eng = MonteCarloProjectionEngine(num_simulacoes=10000, seed=3)
    r = eng.calcular(_snapshots(UFS, 0.10, {"13": 0.504, "22": 0.496}))
    lider = r.candidatos[0]
    assert 0.5 < lider.prob_vitoria < 0.9
    assert lider.ic_superior_95 - lider.ic_inferior_95 > 1.0  # IC com largura realista (> 1 p.p.)
    assert r.status_call == StatusCall.INDEFINIDO


def test_incerteza_diminui_com_a_apuracao():
    larguras = []
    for pct in (0.10, 0.50, 0.95):
        eng = MonteCarloProjectionEngine(num_simulacoes=4000, seed=4)
        c = eng.calcular(_snapshots(UFS, pct, {"13": 0.52, "22": 0.48})).candidatos[0]
        larguras.append(c.ic_superior_95 - c.ic_inferior_95)
    assert larguras[0] > larguras[1] > larguras[2]


# ------------------------------------------------------ 7. UFs sem dados

def test_uf_sem_dados_entra_na_projecao_e_bloqueia_chamada():
    eng = MonteCarloProjectionEngine(num_simulacoes=2000, seed=5)
    eng.inicializar_ufs({uf: {"eleitores": 600000, "secoes": 2000} for uf in UFS + ["ZZ"]})
    r = eng.calcular(_snapshots(UFS, 0.9, {"13": 0.60, "22": 0.40}))
    assert r.ufs_sem_dados == ["ZZ"]
    assert r.status_call != StatusCall.VITORIA_PROJETADA
    # O eleitorado da UF sem dados entra no total projetado
    assert r.total_eleitores == 600000 * (len(UFS) + 1)


# ---------------------------------------- 6. Consistência do Interior

def _payload(s, st, validos, v13):
    return {
        "s": str(s), "st": str(st), "e": str(s * 300), "c": str(st * 240), "a": str(st * 60),
        "vvc": str(validos), "vb": "0", "vn": "0",
        "cand": [{"n": "13", "vap": str(v13)}, {"n": "22", "vap": str(validos - v13)}],
    }


def test_interior_nao_absorve_avanco_das_cidades_com_dado_antigo():
    agg = VectorAggregator(cidades_100k_map={"PB": ["20516", "19852"]})
    lote1 = {
        "UF_PB": _payload(10000, 2000, 400000, 260000),
        "MUN_PB_20516": _payload(2000, 400, 80000, 43200),
        "MUN_PB_19852": _payload(1000, 200, 40000, 19400),
    }
    snaps1 = agg.processar_lote_bruto(lote1)
    interior1 = snaps1["PB_INTERIOR"]
    assert interior1.secoes_apuradas == 2000 - 400 - 200

    # Lote 2 (só Tier 1): UF e capital avançaram, Campina Grande não veio
    lote2 = {
        "UF_PB": _payload(10000, 3000, 600000, 380000),
        "MUN_PB_20516": _payload(2000, 900, 180000, 97200),
    }
    snaps2 = agg.processar_lote_bruto(lote2)
    assert snaps2["PB_INTERIOR"] == interior1      # mantém o último cálculo consistente
    assert snaps2["PB_20516"].secoes_apuradas == 400

    # Lote 3 completo: recalcula com tudo do mesmo ciclo
    lote3 = dict(lote2, MUN_PB_19852=_payload(1000, 500, 100000, 48500))
    snaps3 = agg.processar_lote_bruto(lote3)
    assert snaps3["PB_INTERIOR"].secoes_apuradas == 3000 - 900 - 500


# ------------------------------------------- Cliente HTTP / pacing / JWS

class _PacingContador(PacingManager):
    def __init__(self):
        super().__init__(max_rate_per_sec=1000.0)
        self.aquisicoes = 0

    async def acquire(self):
        self.aquisicoes += 1
        await super().acquire()


@pytest.mark.asyncio
async def test_retentativas_passam_pelo_pacing_e_falha_e_sinalizada(monkeypatch):
    async def sem_espera(_):
        return None
    monkeypatch.setattr("spetr.collector.client.asyncio.sleep", sem_espera)

    pacing = _PacingContador()
    cliente = TSEHttpClient(pacing=pacing)
    cliente._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(503)))
    res = await cliente.fetch_json("http://x/a.json")
    assert pacing.aquisicoes == 3
    assert res.falhou and res.payload is None


@pytest.mark.asyncio
async def test_cliente_verifica_jws_e_rejeita_adulterado():
    chave = Ed25519PrivateKey.generate()
    x = _b64url(chave.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    verificador = JWSVerifier("kid-teste", x)
    payload = {"s": {"ts": "10", "st": "5"}}

    pedidos = []

    def responder(req):
        pedidos.append(str(req.url))
        return httpx.Response(200, text=_assinar(chave, "kid-teste", payload))

    cliente = TSEHttpClient(pacing=PacingManager(max_rate_per_sec=1000.0), verificador_jws=verificador)
    cliente._client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    res = await cliente.fetch_json("http://x/ac-c0001-e021270-u.json")
    assert pedidos == ["http://x/ac-c0001-e021270-u.jws"]
    assert res.payload == payload and not res.falhou

    cab, dados, sig = _assinar(chave, "kid-teste", payload).split(".")
    adulterado = f"{cab}.{_b64url(json.dumps({'s': {'ts': '99'}}).encode())}.{sig}"
    with pytest.raises(JWSInvalidoError):
        verificador.verificar(adulterado)
    with pytest.raises(JWSInvalidoError):
        verificador.verificar(_assinar(chave, "outro-kid", payload))


def test_chaves_oficiais_do_tse_carregam():
    assert JWSVerifier.do_ambiente("oficial").kid == "sNbt9Q_fLS65zE1_ZLNV-XRRwPY"
    assert JWSVerifier.do_ambiente("desenvolvimento").kid == "pEGrlis0i8vO2Bz7Ergwr0MnKfg"


# ------------------------------------------------------- Persistência

def test_historico_isolado_por_execucao_e_migracao_de_banco_antigo():
    eng = MonteCarloProjectionEngine(num_simulacoes=500, seed=6)
    resultado = eng.calcular(_snapshots(["SP"], 0.5, {"13": 0.5, "22": 0.5}))

    with tempfile.TemporaryDirectory() as tmp:
        caminho = os.path.join(tmp, "antigo.sqlite")
        # Banco no schema antigo (sem colunas novas)
        conn = sqlite3.connect(caminho)
        conn.execute("""CREATE TABLE projecoes_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, ciclo_id INTEGER NOT NULL,
            total_secoes INTEGER NOT NULL, secoes_apuradas INTEGER NOT NULL, perc_secoes REAL NOT NULL,
            total_eleitores INTEGER NOT NULL, total_validos_apurados INTEGER NOT NULL,
            total_validos_projetados INTEGER NOT NULL, status_call TEXT NOT NULL, vencedor_projetado TEXT,
            lider_margem REAL NOT NULL, tempo_computacao_ms REAL NOT NULL, candidatos_json TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()
        conn.close()

        db = SQLiteDatabase(caminho)
        repo_a = ElectionRepository(db, eleicao="oficial/ele2026/x", execucao_id="a")
        repo_b = ElectionRepository(db, eleicao="oficial/ele2026/x", execucao_id="b")
        repo_outra = ElectionRepository(db, eleicao="mock", execucao_id="c")
        repo_a.salvar_projecao(resultado)
        repo_outra.salvar_projecao(resultado)

        assert len(repo_a.obter_historico_projecoes()) == 1
        assert repo_b.obter_historico_projecoes() == []
        # Time-travel enxerga execuções anteriores do mesmo pleito, nunca de outro pleito
        assert repo_b.obter_projecao_em_tempo("9999") is not None
        assert ElectionRepository(db, eleicao="outro").obter_projecao_em_tempo("9999") is None


def test_setup_routes_nao_duplica_rotas():
    b = SSEBroadcaster()
    r1 = setup_routes(b)
    r2 = setup_routes(b)
    assert len(r1.routes) == len(r2.routes) == 10


def test_lote_com_defasagem_entre_uf_e_cidades_e_descartado():
    agg = VectorAggregator(cidades_100k_map={"PB": ["20516", "19852"]})
    lote1 = {
        "UF_PB": _payload(10000, 2000, 400000, 260000),
        "MUN_PB_20516": _payload(2000, 400, 80000, 43200),
        "MUN_PB_19852": _payload(1000, 200, 40000, 19400),
    }
    interior1 = agg.processar_lote_bruto(lote1)["PB_INTERIOR"]

    # UF gerada antes das cidades: as cidades já somam mais seções do que a UF registra
    defasado = {
        "UF_PB": _payload(10000, 2100, 420000, 270000),
        "MUN_PB_20516": _payload(2000, 1500, 300000, 162000),
        "MUN_PB_19852": _payload(1000, 800, 160000, 77600),
    }
    snaps = agg.processar_lote_bruto(defasado)
    assert snaps["PB_INTERIOR"] == interior1  # descartado: mantém o último cálculo consistente
    assert snaps["PB_20516"].secoes_apuradas == 400

    # Persistindo por 3 ciclos, aceita (truncado) para a UF não congelar
    agg.processar_lote_bruto(defasado)
    snaps3 = agg.processar_lote_bruto(defasado)
    assert snaps3["PB_20516"].secoes_apuradas == 1500


def test_analise_do_painel_traz_ufs_regioes_estratos_e_distribuicoes():
    eng = MonteCarloProjectionEngine(num_simulacoes=1000, seed=7)
    shares = {"13": 0.42, "22": 0.40, "45": 0.10, "30": 0.08}
    r = eng.calcular(_snapshots(UFS, 0.3, shares))
    a = r.analise
    assert {u["uf"] for u in a["ufs"]} == set(UFS)
    assert {x["regiao"] for x in a["regioes"]} == {"Sudeste", "Nordeste", "Sul"}
    assert len(a["estratos"]) == len(UFS)
    for u in a["ufs"]:
        assert abs(sum(u["proj_pct"].values()) - 100.0) < 0.1
        assert abs(sum(u["prob_lider"].values()) - 1.0) < 1e-6
    assert set(a["distribuicao_final"]) >= {"13", "22"}
    assert abs(sum(a["distribuicao_final"]["13"]["freq"]) - 1.0) < 1e-3
    assert abs(sum(a["prob_top2"].values()) - 2.0) < 0.01  # duas vagas no 2º turno
    n = a["nacional"]
    assert n["votos_validos"] == sum(s.votos_validos for s in _snapshots(UFS, 0.3, shares).values())
    f = a["faltam"]
    assert f["validos_restantes_esperados"] > 0 and f["lider"] == r.candidatos[0].numero


def test_sem_votos_apurados_lista_candidatos_sem_projecao():
    eng = MonteCarloProjectionEngine(num_simulacoes=500, seed=8)
    r = eng.calcular(
        _snapshots(UFS, 0.0, {"13": 0.5, "22": 0.5}),
        candidatos_meta={"13": {"nome": "LULA", "partido": "PT", "vice": "GERALDO ALCKMIN"},
                         "22": {"nome": "FLAVIO BOLSONARO", "partido": "PL"}},
    )
    assert [c.nome for c in r.candidatos] == ["FLAVIO BOLSONARO", "LULA"]
    assert all(c.votos_apurados == 0 and c.perc_projetado == 0 and c.prob_vitoria == 0 for c in r.candidatos)
    assert r.candidatos[1].vice == "GERALDO ALCKMIN"
    assert r.status_call == StatusCall.INDEFINIDO and r.vencedor_projetado is None
    assert r.analise["aguardando"] is True
    assert r.total_secoes == 2000 * len(UFS)


def test_arquivo_real_do_tse_traz_nome_de_urna_vice_e_coligacao():
    import os
    from spetr.collector.parser import parse_tse_json
    caminho = "tests/fixtures/sp-c0001-e006257-u.json"
    if not os.path.exists(caminho):
        pytest.skip("fixture do TSE ausente")
    with open(caminho, encoding="utf-8") as f:
        p = parse_tse_json(json.load(f), "SP")
    assert len(p["candidatos_votos"]) == 12
    lula = p["candidatos_meta"]["13"]
    assert lula["nome"] == "LULA"
    assert lula["nome_completo"] == "LUIZ INÁCIO LULA DA SILVA"
    assert lula["vice"] == "GERALDO ALCKMIN"
    assert lula["coligacao"] == "BRASIL PRONTO PRA MAIS"
    assert "PT" in lula["composicao"]
    flavio = p["candidatos_meta"]["22"]
    assert flavio["nome"] == "FLAVIO BOLSONARO" and flavio["partido"] == "PL" and flavio["coligacao"] == ""


def test_data_http_do_simulador_independe_do_locale():
    import locale
    from spetr.simulador.servidor import _agora_http
    anterior = locale.setlocale(locale.LC_ALL)
    try:
        locale.setlocale(locale.LC_ALL, "pt_BR.UTF-8")
    except locale.Error:
        pytest.skip("locale pt_BR indisponível")
    try:
        data = _agora_http()
    finally:
        locale.setlocale(locale.LC_ALL, anterior)
    assert data.isascii() and data.endswith("GMT")
    assert data[:3] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@pytest.mark.asyncio
async def test_validador_de_cache_nao_ascii_nao_quebra_a_coleta():
    pedidos = []

    def responder(req):
        pedidos.append(dict(req.headers))
        return httpx.Response(
            200, json={"s": "10"},
            headers=[(b"Last-Modified", "sáb, 03 out 2026 23:57:43 GMT".encode("latin-1")), (b"ETag", b'W/"1"')],
        )

    cliente = TSEHttpClient(pacing=PacingManager(max_rate_per_sec=1000.0))
    cliente._client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    primeiro = await cliente.fetch_json("http://x/a.json")
    segundo = await cliente.fetch_json("http://x/a.json")
    assert not primeiro.falhou and not segundo.falhou
    assert "if-modified-since" not in pedidos[1]          # data inválida descartada
    assert pedidos[1].get("if-none-match") == 'W/"1"'     # ETag válido continua sendo usado


@pytest.mark.asyncio
async def test_erro_inesperado_em_uma_url_vira_falha_e_nao_excecao():
    def responder(req):
        raise ValueError("cabeçalho inválido")

    cliente = TSEHttpClient(pacing=PacingManager(max_rate_per_sec=1000.0))
    cliente._client = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    res = await cliente.fetch_json("http://x/a.json")
    assert res.falhou and res.payload is None


def test_compactacao_mantem_recentes_e_resumo_dos_antigos():
    eng = MonteCarloProjectionEngine(num_simulacoes=500, seed=6)
    base = eng.calcular(_snapshots(["SP"], 0.5, {"13": 0.5, "22": 0.5}))
    assert "estratos" in base.analise

    with tempfile.TemporaryDirectory() as tmp:
        repo = ElectionRepository(SQLiteDatabase(os.path.join(tmp, "c.sqlite")), eleicao="x", execucao_id="a")
        outra = ElectionRepository(repo.db, eleicao="x", execucao_id="b")
        for ciclo in range(1, 31):
            r = dataclasses.replace(base, ciclo_id=ciclo)
            repo.salvar_projecao(r)
            outra.salvar_projecao(r)

        n = repo.compactar_analises(manter_recentes=5, a_cada=10)
        assert n > 0
        assert repo.compactar_analises(manter_recentes=5, a_cada=10) == 0  # idempotente

        conn = repo.db.get_connection()
        completos = {c for (c,) in conn.execute(
            "SELECT ciclo_id FROM projecoes_historico WHERE execucao_id='a' AND json_type(analise_json,'$.estratos') IS NOT NULL")}
        assert completos == {10, 20, 30, 26, 27, 28, 29}
        # outra execução não é tocada
        assert conn.execute(
            "SELECT COUNT(*) FROM projecoes_historico WHERE execucao_id='b' AND json_type(analise_json,'$.estratos') IS NOT NULL"
        ).fetchone()[0] == 30
        # histórico (resumo) continua igual e o ciclo compactado ainda carrega
        hist = repo.obter_historico_projecoes()
        assert len(hist) == 30 and hist[0].analise["nacional"] == base.analise["nacional"]


def test_arquivo_de_cidade_vazio_e_de_outro_dia_nao_conta_como_defasagem():
    """Arquivos de teste do TSE (gerados dias antes) não podem travar a UF que já tem votos."""
    agg = VectorAggregator(cidades_100k_map={"PB": ["20516"]})

    def com_data(p, dg, hg):
        return {**p, "dg": dg, "hg": hg}

    lote = {
        "UF_PB": com_data(_payload(10000, 2000, 400000, 260000), "25/10/2026", "17:07:00"),
        # Cidade sem nenhuma seção apurada, arquivo de 12 dias antes
        "MUN_PB_20516": com_data(_payload(2000, 0, 0, 0), "13/10/2026", "17:43:48"),
    }
    snaps = agg.processar_lote_bruto(lote)
    assert agg.defasagens_detectadas == 0
    assert snaps["PB_INTERIOR"].secoes_apuradas == 2000  # tudo no Interior, sem congelar em zero


def test_historico_sobrevive_a_reinicio_com_execucao_fixa():
    from spetr.storage.database import SQLiteDatabase
    from spetr.storage.repository import ElectionRepository

    eng = MonteCarloProjectionEngine(num_simulacoes=200, seed=1)
    r = eng.calcular(_snapshots(["SP"], 0.5, {"13": 0.5, "22": 0.5}))
    with tempfile.TemporaryDirectory() as tmp:
        db = SQLiteDatabase(os.path.join(tmp, "h.sqlite"))
        pleito = "oficial/ele2026/auto/c1/t2"
        # Servidor antes do reinício (id aleatório) e outro pleito que não deve ser tocado
        antes = ElectionRepository(db, eleicao=pleito, execucao_id="antigo")
        for ciclo in (1, 2, 3):
            antes.salvar_projecao(dataclasses.replace(r, ciclo_id=ciclo, timestamp=f"2026-10-25 17:0{ciclo}:00"))
        ElectionRepository(db, eleicao="outro", execucao_id="x").salvar_projecao(r)

        depois = ElectionRepository(db, eleicao=pleito, execucao_id="publico-2026-t2-c1")
        assert depois.obter_historico_projecoes() == []
        assert depois.adotar_execucoes_anteriores() == 3
        assert [h.ciclo_id for h in depois.obter_historico_projecoes()] == [1, 2, 3]
        assert depois.ultimo_ciclo() == 3
        assert len(ElectionRepository(db, eleicao="outro", execucao_id="x").obter_historico_projecoes()) == 1

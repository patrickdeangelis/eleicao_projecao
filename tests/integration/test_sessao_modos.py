"""
Sessão do SPETR: tela inicial, simulação local embutida e troca de modo.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from spetr.api.server import create_api_app
from spetr.services.event_bus import EventBus
from spetr.services.events import ProjectionCalculatedEvent, RawBatchReceivedEvent, StrataNormalizedEvent
from spetr.services.sessao import ELEICOES_PRONTAS, ErroSessao, SessaoSPETR


@pytest.mark.asyncio
async def test_replay_gera_projecao_e_pode_ser_encerrado(tmp_path, replay_sintetico):
    bus = EventBus()
    resultados = []

    async def capturar(evento):
        resultados.append(evento.resultado)

    bus.subscribe(ProjectionCalculatedEvent, capturar)
    sessao = SessaoSPETR(bus, db_path=str(tmp_path / "sessao.sqlite"), num_simulacoes=500)

    desc = await sessao.iniciar("replay", {"fonte": replay_sintetico, "velocidade": "rapida"})
    assert desc["ativa"] and desc["modo"] == "replay"
    assert desc["simulador_url"].startswith("http://127.0.0.1:")
    assert desc["eleicao"]["replay"] is True
    sessao.simulador.estado.definir(0.5)

    for _ in range(400):
        if any(r.perc_secoes_apuradas > 0 for r in resultados):
            break
        await asyncio.sleep(0.1)
    r = next((r for r in reversed(resultados) if r.perc_secoes_apuradas > 0), None)
    assert r is not None, "o replay não produziu projeção"
    assert {c.numero for c in r.candidatos} == {"13", "22"}
    assert r.analise["nacional"]["votos_validos"] > 0
    assert sessao.repo.obter_historico_projecoes()

    await sessao.parar()
    assert not sessao.ativa and sessao.simulador is None
    # Componentes do pipeline saem do barramento (a próxima sessão não recebe eventos duplicados)
    assert not bus._subscribers.get(RawBatchReceivedEvent)
    assert not bus._subscribers.get(StrataNormalizedEvent)


@pytest.mark.asyncio
async def test_opcoes_invalidas_nao_iniciam_sessao(tmp_path):
    sessao = SessaoSPETR(EventBus(), db_path=str(tmp_path / "s.sqlite"))
    for modo, opcoes in [
        ("real", {"ano": "20x6"}),
        ("real", {"turno": 3}),
        ("real", {"ano": "2024", "formato": "r"}),  # formato 'r' exige o código da eleição
        ("real", {"tse_url": "ftp://x"}),
        ("replay", {"fonte": "1900_1t"}),
        ("simulado", {}),
        ("outro", {}),
    ]:
        with pytest.raises(ErroSessao):
            await sessao.iniciar(modo, opcoes)
        assert not sessao.ativa


@pytest.mark.asyncio
async def test_2022_sem_replay_preparado_nao_inicia_sessao(tmp_path, monkeypatch):
    # 2022 usa o replay local dos boletins; sem ele a sessão não pode iniciar (independe da máquina)
    monkeypatch.setattr("spetr.services.sessao.listar_replays", lambda: {})
    sessao = SessaoSPETR(EventBus(), db_path=str(tmp_path / "s.sqlite"))
    with pytest.raises(ErroSessao):
        await sessao.iniciar("real", {"ano": "2022", "turno": 1})
    assert not sessao.ativa


@pytest.mark.asyncio
async def test_coleta_real_usa_padroes_e_descoberta_automatica(tmp_path):
    sessao = SessaoSPETR(EventBus(), db_path=str(tmp_path / "s.sqlite"))
    # Sem rede no teste: só verifica a configuração montada (o loop de coleta é cancelado em seguida)
    desc = await sessao.iniciar("real", {"turno": 1})
    try:
        sch = sessao.coordinator.scheduler
        assert desc["modo"] == "real"
        assert sch.base_url == "https://resultados.tse.jus.br"
        assert sch.ano == "2026" and sch.formato == "u" and sch.cod_eleicao is None
    finally:
        await sessao.parar()


def test_raiz_leva_a_tela_inicial_sem_sessao_e_bloqueia_outras_origens(tmp_path):
    bus = EventBus()
    sessao = SessaoSPETR(bus, db_path=str(tmp_path / "s.sqlite"))
    with TestClient(create_api_app(event_bus=bus, sessao=sessao)) as cliente:
        r = cliente.get("/", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == "/inicio"
        inicio = cliente.get("/inicio").text
        assert '<select name="ano">' in inicio and "Coleta real" in inicio

        info = cliente.get("/api/v1/sessao").json()
        assert info["ativa"] is False
        assert info["opcoes"]["padroes_reais"]["ano"] == "2026"

        bloqueado = cliente.post(
            "/api/v1/sessao/iniciar", json={"modo": "replay"}, headers={"Origin": "http://site-qualquer.example"}
        )
        assert bloqueado.status_code == 403
        texto = cliente.post(
            "/api/v1/sessao/iniciar", content='{"modo": "replay"}', headers={"Content-Type": "text/plain"}
        )
        assert texto.status_code in (415, 422)
        assert not sessao.ativa


def test_eleicoes_prontas_incluem_2026_como_padrao_e_os_dois_turnos_de_2022():
    opcoes_2022 = {(e["turno"], e["eleicao"]) for e in ELEICOES_PRONTAS if e["ano"] == "2022"}
    assert opcoes_2022 == {(1, "544"), (2, "545")}
    assert {e["ano"] for e in ELEICOES_PRONTAS} == {"2022", "2026"}
    assert ELEICOES_PRONTAS[0]["ano"] == "2026"


@pytest.mark.asyncio
@pytest.mark.parametrize("turno, codigo", [(1, "544"), (2, "545")])
async def test_coleta_2022_alimenta_o_pipeline_pelo_replay_real(tmp_path, turno, codigo):
    sessao = SessaoSPETR(EventBus(), db_path=str(tmp_path / f"{turno}.sqlite"))
    desc = await sessao.iniciar("real", {"ano": "2022", "turno": turno, "eleicao": codigo})
    try:
        assert desc["modo"] == "replay"
        assert desc["eleicao"]["ano"] == "2022"
        assert desc["eleicao"]["turno"] == turno
        assert sessao.simulador.estado.eleicao == codigo
    finally:
        await sessao.parar()


def test_arquivos_do_painel_sempre_revalidados(tmp_path):
    bus = EventBus()
    with TestClient(create_api_app(event_bus=bus, sessao=SessaoSPETR(bus, db_path=str(tmp_path / "s.sqlite")))) as cliente:
        r = cliente.get("/static/js/app.js")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        assert cliente.get("/static/js/app.js", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_exterior_por_cidade_e_pais():
    import json, logging
    from pathlib import Path
    from spetr.services.pipeline_coordinator import PipelineCoordinator

    dados = Path("spetr/data")
    exterior = json.loads((dados / "exterior_cidades.json").read_text(encoding="utf-8"))
    ufs = json.loads((dados / "ufs_metadados.json").read_text(encoding="utf-8"))
    assert len(exterior) == 186 and all(c["pais"] and c["continente"] for c in exterior.values())
    assert sum(c["eleitores"] for c in exterior.values()) == ufs["ZZ"]["eleitores"]

    def arquivo(secoes, apuradas, v13, v22, v70):
        return {"s": str(secoes), "st": str(apuradas), "e": str(secoes * 300), "c": str(apuradas * 240),
                "a": str(apuradas * 60), "vv": str(v13 + v22 + v70), "vb": "0", "vn": "0",
                "cand": [{"n": "13", "vap": str(v13)}, {"n": "22", "vap": str(v22)}, {"n": "70", "vap": str(v70)}]}

    logging.disable(logging.WARNING)
    pipe = PipelineCoordinator(db_path=":memory:", num_simulacoes=500)
    assert len(pipe.scheduler.cidades_exterior) == 186
    lote, total = {}, [0, 0, 0, 0, 0]
    for i, cod in enumerate(sorted(exterior)):
        parcial = (3, 2, 90 + i % 7, 60 + i % 5, 1 if i % 40 == 0 else 0)
        lote[f"MUN_ZZ_{cod}"] = arquivo(*parcial)
        total = [a + b for a, b in zip(total, parcial)]
    lote["UF_ZZ"] = arquivo(*total)
    snaps = pipe.aggregator.processar_lote_bruto(lote)
    r = pipe.engine.calcular(snaps, num_simulacoes=500, candidatos_meta=pipe.aggregator._candidatos_meta,
                             exterior=pipe.aggregator.exterior_detalhado())
    ext = r.analise["exterior"]
    zz = next(u for u in r.analise["ufs"] if u["uf"] == "ZZ")
    assert len(ext) == 186 and len({c["pais"] for c in ext}) > 100
    assert sum(c["votos_validos"] for c in ext) == zz["votos_validos"]   # cidades somam o total do exterior
    assert "ZZ_INTERIOR" not in snaps                                      # exterior não vira estrato de cidades
    # Nanicos: percentuais com 3 casas (não somem no arredondamento)
    menor = min(r.candidatos, key=lambda c: c.perc_apurado)
    assert menor.perc_apurado > 0 and round(menor.perc_apurado, 3) == menor.perc_apurado

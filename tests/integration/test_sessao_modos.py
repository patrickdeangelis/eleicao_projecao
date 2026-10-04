"""
Sessão do SPETR: tela inicial, simulação local embutida e troca de modo.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from spetr.api.server import create_api_app
from spetr.services.event_bus import EventBus
from spetr.services.events import ProjectionCalculatedEvent, RawBatchReceivedEvent, StrataNormalizedEvent
from spetr.services.sessao import ErroSessao, SessaoSPETR


@pytest.mark.asyncio
async def test_simulacao_local_gera_projecao_e_pode_ser_encerrada(tmp_path):
    bus = EventBus()
    resultados = []

    async def capturar(evento):
        resultados.append(evento.resultado)

    bus.subscribe(ProjectionCalculatedEvent, capturar)
    sessao = SessaoSPETR(bus, db_path=str(tmp_path / "sessao.sqlite"), num_simulacoes=500)

    desc = await sessao.iniciar("simulado", {"cenario": "1t", "velocidade": "rapida", "inicio": 30})
    assert desc["ativa"] and desc["modo"] == "simulado"
    assert desc["simulador_url"].startswith("http://127.0.0.1:")

    for _ in range(400):
        if resultados:
            break
        await asyncio.sleep(0.1)
    assert resultados, "a simulação não produziu projeção"
    r = resultados[-1]
    numeros = {c.numero for c in r.candidatos}
    assert {"99", "88", "45"} <= numeros
    assert "77" not in numeros  # candidato "Anulado sub judice" fica fora dos válidos
    assert r.perc_secoes_apuradas > 0
    assert r.analise["nacional"]["votos_anulados"] > 0
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
        ("real", {"ano": "2022", "formato": "r"}),  # formato 'r' exige o código da eleição
        ("real", {"tse_url": "ftp://x"}),
        ("simulado", {"cenario": "3t"}),
        ("simulado", {"inicio": 150}),
        ("outro", {}),
    ]:
        with pytest.raises(ErroSessao):
            await sessao.iniciar(modo, opcoes)
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
        assert "Coleta real" in cliente.get("/inicio").text

        info = cliente.get("/api/v1/sessao").json()
        assert info["ativa"] is False
        assert info["opcoes"]["padroes_reais"]["ano"] == "2026"

        bloqueado = cliente.post(
            "/api/v1/sessao/iniciar", json={"modo": "simulado"}, headers={"Origin": "http://site-qualquer.example"}
        )
        assert bloqueado.status_code == 403
        texto = cliente.post(
            "/api/v1/sessao/iniciar", content='{"modo": "simulado"}', headers={"Content-Type": "text/plain"}
        )
        assert texto.status_code in (415, 422)
        assert not sessao.ativa


def test_arquivos_do_painel_sempre_revalidados(tmp_path):
    bus = EventBus()
    with TestClient(create_api_app(event_bus=bus, sessao=SessaoSPETR(bus, db_path=str(tmp_path / "s.sqlite")))) as cliente:
        r = cliente.get("/static/js/app.js")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        assert cliente.get("/static/js/app.js", headers={"If-None-Match": r.headers["etag"]}).status_code == 304


def test_simulacao_configuravel_percentuais_e_velocidade():
    from spetr.simulador import EstadoSimulacao, descrever_perfis
    perfil = descrever_perfis()["virada"]
    assert set(perfil["ajustes"]["regioes"]) == {"N", "NE", "CO", "SE", "S", "EX"}
    ne = perfil["ajustes"]["regioes"]["NE"]
    assert abs(sum(ne["percentuais"].values()) - 100) < 0.2 and ne["velocidade"] > 1

    ajustes = {"regioes": {
        "NE": {"percentuais": {"99": 70, "88": 30}, "velocidade": 4},
        "SE": {"percentuais": {"99": 35, "88": 65}, "velocidade": 0.3},
    }}
    e = EstadoSimulacao("2t", ajustes=ajustes)
    previa = e.previa((0.3,))
    assert abs(previa["final_regioes"]["NE"]["99"] - 70) < 2      # percentuais respeitados
    assert previa["ritmo"]["0.3"]["regioes"]["NE"] > 70            # Nordeste rápido
    assert previa["ritmo"]["0.3"]["regioes"]["SE"] < 15            # Sudeste lento
    e.progresso_global = 1.0
    assert all(p["apuradas"] == p["secoes"] for p in
               (e.apurar_unidade(uf, u) for uf in ("BA", "SP") for u in e.unidades_da_uf(uf)))  # todos chegam a 100%

    for invalido in (
        {"regioes": {"NE": {"percentuais": {"99": 60, "88": 30}}}},   # não soma 100
        {"regioes": {"NE": {"velocidade": 9}}},                        # fora do limite
        {"regioes": {"XX": {"velocidade": 1}}},                        # região inexistente
        {"regioes": {"NE": {"percentuais": {"12": 100}}}},             # candidato inexistente
    ):
        with pytest.raises(ValueError):
            EstadoSimulacao("2t", ajustes=invalido)


@pytest.mark.asyncio
async def test_sessao_inicia_simulacao_personalizada(tmp_path):
    sessao = SessaoSPETR(EventBus(), db_path=str(tmp_path / "s.sqlite"), num_simulacoes=500)
    ajustes = {"regioes": {"NE": {"percentuais": {"99": 70, "88": 30}, "velocidade": 3}}}
    desc = await sessao.iniciar("simulado", {"cenario": "2t", "ajustes": ajustes})
    try:
        assert desc["eleicao"]["personalizado"] is True
        assert sessao.simulador.estado.perfil["apuracao"]["NE"] == ("razao", 3.0)
        assert desc["eleicao"]["turno"] == 2
    finally:
        await sessao.parar()
    with pytest.raises(ErroSessao):
        await sessao.iniciar("simulado", {"cenario": "2t", "ajustes": {"regioes": {"NE": {"velocidade": 0}}}})


def test_previa_da_simulacao_pela_api(tmp_path):
    bus = EventBus()
    with TestClient(create_api_app(event_bus=bus, sessao=SessaoSPETR(bus, db_path=str(tmp_path / "s.sqlite")))) as cliente:
        ok = cliente.post("/api/v1/simulador/previa", json={"cenario": "virada"})
        assert ok.status_code == 200 and ok.json()["final"]["88"] > ok.json()["final"]["99"]
        ruim = cliente.post("/api/v1/simulador/previa", json={"cenario": "virada", "ajustes": {"regioes": {"NE": {"velocidade": 99}}}})
        assert ruim.status_code == 422

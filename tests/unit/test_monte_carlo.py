"""
Testes unitários de performance e consistência do motor Monte Carlo.
"""
import time
import pytest
from spetr.stats_engine.monte_carlo import MonteCarloProjectionEngine
from spetr.domain.entities import EstratoEleitoral, SnapshotParcial, Candidato
from spetr.domain.value_objects import TipoEstrato, StatusCall


def test_monte_carlo_performance_e_convergencia():
    engine = MonteCarloProjectionEngine(num_simulacoes=10000, seed=42)

    candidatos = [
        Candidato(numero="13", nome="Lula", sigla_partido="PT"),
        Candidato(numero="22", nome="Bolsonaro", sigla_partido="PL"),
    ]
    engine.configurar_candidatos(candidatos)

    # Cria 3 estratos representando uma miniatura realista (ex: Paraíba)
    estratos = [
        EstratoEleitoral(
            id="PB_20516", uf="PB", nome="João Pessoa",
            eleitores_aptos=560000, secoes_totais=2000,
            tipo=TipoEstrato.CAPITAL, prior_alpha={"13": 0.54, "22": 0.46}
        ),
        EstratoEleitoral(
            id="PB_19852", uf="PB", nome="Campina Grande",
            eleitores_aptos=290000, secoes_totais=1000,
            tipo=TipoEstrato.GRANDE_CIDADE, prior_alpha={"13": 0.485, "22": 0.515}
        ),
        EstratoEleitoral(
            id="PB_INTERIOR", uf="PB", nome="Interior",
            eleitores_aptos=2150000, secoes_totais=7000,
            tipo=TipoEstrato.INTERIOR_REMANESCENTE, prior_alpha={"13": 0.75, "22": 0.25}
        ),
    ]
    engine.inicializar_estratos(estratos)

    # Simula apuração de 20% das urnas (200 de 1000 em CG, 400 de 2000 em JP, 1400 de 7000 no Interior)
    snapshots = {
        "PB_20516": SnapshotParcial(
            estrato_id="PB_20516", timestamp="17:30",
            secoes_total=2000, secoes_apuradas=400,
            eleitores_aptos=560000, comparecimento=90000, abstencao=22000,
            votos_validos=80000, votos_brancos=5000, votos_nulos=5000,
            votos_candidatos={"13": 43200, "22": 36800} # 54% x 46%
        ),
        "PB_19852": SnapshotParcial(
            estrato_id="PB_19852", timestamp="17:30",
            secoes_total=1000, secoes_apuradas=200,
            eleitores_aptos=290000, comparecimento=46000, abstencao=12000,
            votos_validos=40000, votos_brancos=3000, votos_nulos=3000,
            votos_candidatos={"13": 19400, "22": 20600} # 48.5% x 51.5%
        ),
        "PB_INTERIOR": SnapshotParcial(
            estrato_id="PB_INTERIOR", timestamp="17:30",
            secoes_total=7000, secoes_apuradas=1400,
            eleitores_aptos=2150000, comparecimento=340000, abstencao=90000,
            votos_validos=300000, votos_brancos=20000, votos_nulos=20000,
            votos_candidatos={"13": 225000, "22": 75000} # 75% x 25%
        ),
    }

    t0 = time.perf_counter()
    resultado = engine.calcular(snapshots, num_simulacoes=10000, ciclo_id=1)
    duracao_ms = (time.perf_counter() - t0) * 1000.0

    # Validação de performance RNF-01: cálculo em menos de 200 ms
    assert duracao_ms < 200.0, f"Tempo de Monte Carlo muito alto: {duracao_ms:.1f}ms"

    # Validação da projeção
    lula_proj = next(c for c in resultado.candidatos if c.numero == "13")
    bolso_proj = next(c for c in resultado.candidatos if c.numero == "22")

    # No agregado com interior pesando ~71%, Lula deve projetar entre 67% e 70%
    assert 66.0 <= lula_proj.perc_projetado <= 72.0
    assert lula_proj.ic_inferior_95 < lula_proj.perc_projetado < lula_proj.ic_superior_95
    assert lula_proj.prob_vitoria == 1.0  # Com essa liderança na PB, probabilidade é 100%

    # Status deve ser Vitória Projetada
    assert resultado.status_call in (StatusCall.VITORIA_PROJETADA, StatusCall.MATEMATICAMENTE_ELEITO)
    assert resultado.vencedor_projetado == "13"

"""
Testes unitários para o módulo matemático Dirichlet-Multinomial.
"""
import numpy as np
import pytest
from spetr.stats_engine.bayesian_dirichlet import (
    calcular_parametros_posteriores,
    amostrar_proporcoes_monte_carlo,
)


def test_calcular_parametros_posteriores():
    # H=2 estratos, K=2 candidatos
    prior_alphas = np.array([
        [150.0, 150.0],
        [200.0, 100.0]
    ])
    votos_obs = np.array([
        [1000.0, 800.0],
        [500.0, 500.0]
    ])

    post = calcular_parametros_posteriores(prior_alphas, votos_obs)
    assert np.allclose(post, [
        [1150.0, 950.0],
        [700.0, 600.0]
    ])


def test_amostragem_monte_carlo_k2():
    # H=3 estratos, K=2 candidatos
    alphas = np.array([
        [540.0, 460.0],
        [485.0, 515.0],
        [700.0, 300.0]
    ])
    rng = np.random.default_rng(123)
    amostras = amostrar_proporcoes_monte_carlo(alphas, num_simulacoes=5000, rng=rng)

    assert amostras.shape == (5000, 3, 2)
    # Soma de p_A + p_B deve ser sempre 1.0
    somas = amostras.sum(axis=2)
    assert np.allclose(somas, 1.0)

    # Médias devem ser muito próximas a alpha_k / sum(alpha)
    medias = amostras.mean(axis=0)
    esperado_estrato_0 = 540.0 / 1000.0
    assert abs(medias[0, 0] - esperado_estrato_0) < 0.01

    esperado_estrato_2 = 700.0 / 1000.0
    assert abs(medias[2, 0] - esperado_estrato_2) < 0.01


def test_amostragem_monte_carlo_k3():
    # H=2 estratos, K=3 candidatos
    alphas = np.array([
        [400.0, 300.0, 300.0],
        [500.0, 250.0, 250.0]
    ])
    rng = np.random.default_rng(456)
    amostras = amostrar_proporcoes_monte_carlo(alphas, num_simulacoes=5000, rng=rng)

    assert amostras.shape == (5000, 2, 3)
    somas = amostras.sum(axis=2)
    assert np.allclose(somas, 1.0)

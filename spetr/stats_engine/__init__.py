"""
Módulo de Motor Estatístico e Simulação de Monte Carlo.
"""
from spetr.stats_engine.monte_carlo import MonteCarloProjectionEngine
from spetr.stats_engine.bayesian_dirichlet import (
    calcular_parametros_posteriores,
    amostrar_proporcoes_monte_carlo,
)

__all__ = [
    "MonteCarloProjectionEngine",
    "calcular_parametros_posteriores",
    "amostrar_proporcoes_monte_carlo",
]

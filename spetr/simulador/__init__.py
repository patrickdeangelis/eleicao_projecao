"""
Simulador local de apuração (espelho da CDN do TSE com dados fictícios).
"""
from spetr.simulador.servidor import (
    ANO_SIMULADO,
    CENARIOS,
    DESCRICAO_CENARIOS,
    ELEICAO_SIMULADA,
    VELOCIDADES,
    EstadoSimulacao,
    SimuladorLocal,
    criar_app_simulador,
)

__all__ = [
    "ANO_SIMULADO",
    "CENARIOS",
    "DESCRICAO_CENARIOS",
    "ELEICAO_SIMULADA",
    "VELOCIDADES",
    "EstadoSimulacao",
    "SimuladorLocal",
    "criar_app_simulador",
]

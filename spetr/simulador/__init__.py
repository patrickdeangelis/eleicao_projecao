"""
Replay local de uma apuração real (espelho da CDN do TSE alimentado pelos boletins de urna).
"""
from spetr.simulador.servidor import EstadoApuracao, SimuladorLocal, criar_app_simulador

__all__ = ["EstadoApuracao", "SimuladorLocal", "criar_app_simulador"]

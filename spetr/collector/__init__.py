"""
Módulo de Coleta e Ingestão de Dados do TSE.
"""
from spetr.collector.pacing import PacingManager
from spetr.collector.client import TSEHttpClient
from spetr.collector.parser import parse_tse_json, parse_float_br, parse_int_br
from spetr.collector.scheduler import TieredScheduler

__all__ = [
    "PacingManager",
    "TSEHttpClient",
    "parse_tse_json",
    "parse_float_br",
    "parse_int_br",
    "TieredScheduler",
]

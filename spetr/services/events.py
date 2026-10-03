"""
Eventos tipados e imutáveis trafegados pelo EventBus.
"""
from dataclasses import dataclass
from typing import Dict, Any, List
from spetr.domain.entities import SnapshotParcial, ResultadoProjecao


@dataclass(frozen=True)
class RawBatchReceivedEvent:
    timestamp: str
    ciclo_id: int
    total_arquivos: int
    arquivos_modificados: int
    payload_bruto: Dict[str, Dict[str, Any]]


@dataclass(frozen=True)
class StrataNormalizedEvent:
    timestamp: str
    ciclo_id: int
    snapshots: Dict[str, SnapshotParcial]


@dataclass(frozen=True)
class ProjectionCalculatedEvent:
    timestamp: str
    ciclo_id: int
    resultado: ResultadoProjecao


@dataclass(frozen=True)
class CollectionErrorEvent:
    timestamp: str
    origem: str
    mensagem: str
    codigo_status: int = 0

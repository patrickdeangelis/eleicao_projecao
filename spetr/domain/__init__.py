"""
Módulo de Domínio do SPETR.
Entidades, Value Objects e Interfaces abstratas sem dependências externas.
"""
from spetr.domain.entities import (
    Candidato,
    EstratoEleitoral,
    SnapshotParcial,
    ProjecaoCandidato,
    ResultadoProjecao,
)
from spetr.domain.value_objects import UF, StatusCall, Cargo
from spetr.domain.interfaces import (
    IProjectionEngine,
    IAggregator,
    IRepository,
    ICollector,
    IEventBus,
)

__all__ = [
    "Candidato",
    "EstratoEleitoral",
    "SnapshotParcial",
    "ProjecaoCandidato",
    "ResultadoProjecao",
    "UF",
    "StatusCall",
    "Cargo",
    "IProjectionEngine",
    "IAggregator",
    "IRepository",
    "ICollector",
    "IEventBus",
]

"""
Módulo de Serviços do SPETR.
"""
from spetr.services.event_bus import EventBus
from spetr.services.events import (
    RawBatchReceivedEvent,
    StrataNormalizedEvent,
    ProjectionCalculatedEvent,
    CollectionErrorEvent,
)
from spetr.services.pipeline_coordinator import PipelineCoordinator

__all__ = [
    "EventBus",
    "RawBatchReceivedEvent",
    "StrataNormalizedEvent",
    "ProjectionCalculatedEvent",
    "CollectionErrorEvent",
    "PipelineCoordinator",
]

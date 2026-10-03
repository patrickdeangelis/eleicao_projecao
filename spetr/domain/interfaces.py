"""
Contratos abstratos (Protocols) do SPETR.
Seguem o Princípio da Inversão de Dependência (DIP).
"""
from typing import Protocol, Dict, List, Optional, Any, Callable, Type, runtime_checkable
from spetr.domain.entities import EstratoEleitoral, SnapshotParcial, ResultadoProjecao


@runtime_checkable
class IProjectionEngine(Protocol):
    """Contrato do motor probabilístico de projeção."""

    def inicializar_estratos(self, estratos: List[EstratoEleitoral]) -> None:
        """Configura os estratos, eleitorados e priors de cada estrato."""
        ...

    def calcular(
        self,
        snapshots: Dict[str, SnapshotParcial],
        num_simulacoes: int = 10000,
        ciclo_id: int = 1
    ) -> ResultadoProjecao:
        """Executa a simulação de Monte Carlo com atualização bayesiana."""
        ...


@runtime_checkable
class IAggregator(Protocol):
    """Contrato do módulo que calcula os estratos remanescentes (Interior = Total - Cidades)."""

    def processar_lote_bruto(
        self,
        arquivos_brutos: Dict[str, Dict[str, Any]],
        timestamp: str
    ) -> Dict[str, SnapshotParcial]:
        """Retorna o dicionário de snapshots de todos os 181 estratos computados."""
        ...


@runtime_checkable
class IRepository(Protocol):
    """Contrato do repositório de persistência e auditoria."""

    def salvar_snapshots(self, snapshots: List[SnapshotParcial]) -> None:
        """Grava em lote os snapshots apurados no ciclo."""
        ...

    def salvar_projecao(self, projecao: ResultadoProjecao) -> None:
        """Grava o resultado da projeção calculada."""
        ...

    def obter_historico_projecoes(self, limite: int = 100) -> List[ResultadoProjecao]:
        """Retorna histórico de projeções para gráficos de evolução temporal."""
        ...

    def obter_projecao_em_tempo(self, timestamp: str) -> Optional[ResultadoProjecao]:
        """Suporte a Time-Travel Replay."""
        ...


@runtime_checkable
class ICollector(Protocol):
    """Contrato do coletor de rede do TSE."""

    async def executar_ciclo_coleta(self) -> Dict[str, Dict[str, Any]]:
        """Realiza requisições com pacing seguro e conditional caching."""
        ...


@runtime_checkable
class IEventBus(Protocol):
    """Contrato do barramento de eventos em memória."""

    def subscribe(self, event_type: Type, handler: Callable) -> None:
        ...

    async def publish(self, event: Any) -> None:
        ...

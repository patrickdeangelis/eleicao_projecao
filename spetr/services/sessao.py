"""
Sessão de execução do SPETR: escolhe entre coleta real na CDN do TSE e simulação local,
inicia o pipeline correspondente e permite trocar de modo sem reiniciar o aplicativo.
"""
import asyncio
import datetime
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from spetr.collector.client import TSEHttpClient
from spetr.collector.jws import CHAVES_TSE, JWSVerifier
from spetr.collector.pacing import PacingManager
from spetr.services.event_bus import EventBus
from spetr.services.pipeline_coordinator import PipelineCoordinator
from spetr.simulador import (
    ANO_SIMULADO,
    CENARIOS,
    DESCRICAO_CENARIOS,
    ELEICAO_SIMULADA,
    VELOCIDADES,
    EstadoSimulacao,
    SimuladorLocal,
)

logger = logging.getLogger("spetr.services.sessao")

MODOS = ("real", "simulado")
TSE_PADRAO = "https://resultados.tse.jus.br"


class ErroSessao(ValueError):
    """Opções inválidas para iniciar uma sessão."""


class SessaoSPETR:
    """Controla qual pipeline está ativo (real ou simulado)."""

    def __init__(
        self,
        event_bus: EventBus,
        db_path: str = "spetr_eleicoes.sqlite",
        num_simulacoes: int = 10000,
        padroes_reais: Optional[Dict[str, Any]] = None,
    ):
        self.bus = event_bus
        self.db_path = db_path
        self.num_simulacoes = num_simulacoes
        # Valores pré-preenchidos na tela inicial para a coleta real (vêm da linha de comando)
        self.padroes_reais: Dict[str, Any] = {
            "tse_url": TSE_PADRAO, "ano": "2026", "eleicao": "", "cargo": "1", "turno": 1,
            "ambiente": "oficial", "formato": "", "jws": "",
            **(padroes_reais or {}),
        }
        self.coordinator: Optional[PipelineCoordinator] = None
        self.simulador: Optional[SimuladorLocal] = None
        self.modo: Optional[str] = None
        self.info: Dict[str, Any] = {}
        self.iniciada_em: Optional[str] = None
        self._tarefa: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self.ao_mudar: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None

    @property
    def ativa(self) -> bool:
        return self.coordinator is not None

    @property
    def repo(self):
        return self.coordinator.repo if self.coordinator else None

    def descrever(self) -> Dict[str, Any]:
        return {
            "ativa": self.ativa,
            "modo": self.modo,
            "iniciada_em": self.iniciada_em,
            "eleicao": self.info,
            "simulador_url": self.simulador.url if self.simulador else None,
            "opcoes": {
                "padroes_reais": self.padroes_reais,
                "cenarios": DESCRICAO_CENARIOS,
                "velocidades": {k: f"+{p * 100:.0f}% a cada {s:.0f}s" for k, (s, p) in VELOCIDADES.items()},
                "jws": list(CHAVES_TSE),
            },
        }

    # ------------------------------------------------------------- ciclo

    async def iniciar(self, modo: str, opcoes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        opcoes = opcoes or {}
        if modo not in MODOS:
            raise ErroSessao(f"Modo inválido: {modo!r}. Use 'real' ou 'simulado'.")
        async with self._lock:
            await self._parar_sem_lock(notificar=False)
            if modo == "simulado":
                await self._iniciar_simulado(opcoes)
            else:
                self._iniciar_real(opcoes)
            self.modo = modo
            self.iniciada_em = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._tarefa = asyncio.create_task(self.coordinator.scheduler.iniciar_loop())
            logger.info(f"Sessão iniciada no modo '{modo}': {self.info}")
        await self._notificar()
        return self.descrever()

    async def parar(self) -> Dict[str, Any]:
        async with self._lock:
            await self._parar_sem_lock(notificar=False)
        await self._notificar()
        return self.descrever()

    async def _parar_sem_lock(self, notificar: bool) -> None:
        if self.coordinator is not None:
            await self.coordinator.desligar()
        if self._tarefa is not None:
            self._tarefa.cancel()
            try:
                await self._tarefa
            except (asyncio.CancelledError, Exception):
                pass
        if self.simulador is not None:
            await self.simulador.parar()
        self.coordinator = None
        self.simulador = None
        self._tarefa = None
        self.modo = None
        self.info = {}
        self.iniciada_em = None

    async def _notificar(self) -> None:
        if self.ao_mudar is not None:
            await self.ao_mudar(self.descrever())

    # ----------------------------------------------------------- modos

    async def _iniciar_simulado(self, opcoes: Dict[str, Any]) -> None:
        cenario = str(opcoes.get("cenario") or "1t")
        velocidade = str(opcoes.get("velocidade") or "normal")
        if cenario not in CENARIOS:
            raise ErroSessao(f"Cenário inválido: {cenario!r}")
        if velocidade not in VELOCIDADES:
            raise ErroSessao(f"Velocidade inválida: {velocidade!r}")
        try:
            inicio = float(opcoes.get("inicio") or 0.0)
        except (TypeError, ValueError):
            raise ErroSessao("Percentual inicial inválido")
        if not 0.0 <= inicio <= 100.0:
            raise ErroSessao("Percentual inicial deve estar entre 0 e 100")

        self.simulador = SimuladorLocal(EstadoSimulacao(cenario, velocidade, inicio / 100.0))
        url = await self.simulador.iniciar()
        # Servidor local: sem risco de bloqueio, então a coleta pode ser bem mais rápida
        cliente = TSEHttpClient(pacing=PacingManager(max_concurrent=32, max_rate_per_sec=400.0))
        self.coordinator = PipelineCoordinator(
            event_bus=self.bus, db_path=self.db_path, num_simulacoes=self.num_simulacoes,
            tse_base_url=url, ano_eleicao=ANO_SIMULADO, codigo_eleicao=ELEICAO_SIMULADA,
            codigo_cargo="1", turno=2 if cenario == "2t" else 1, formato="r", ambiente="oficial",
            http_client=cliente, intervalo_tier1=4.0, intervalo_tier2=4.0,
            rotulo_eleicao=f"simulado/{cenario}",
        )
        self.info = {
            "mock": True, "simulado": True, "cenario": cenario, "descricao": DESCRICAO_CENARIOS[cenario],
            "velocidade": velocidade, "turno": 2 if cenario == "2t" else 1, "cargo": "1",
            "fonte": url, "simulacoes": self.num_simulacoes,
        }

    def _iniciar_real(self, opcoes: Dict[str, Any]) -> None:
        cfg = {**self.padroes_reais, **{k: v for k, v in opcoes.items() if v not in (None, "")}}
        ano = str(cfg["ano"]).strip()
        if not ano.isdigit() or len(ano) != 4:
            raise ErroSessao(f"Ano inválido: {ano!r}")
        eleicao = str(cfg.get("eleicao") or "").strip() or None
        if eleicao is not None and not eleicao.isdigit():
            raise ErroSessao(f"Código de eleição inválido: {eleicao!r}")
        try:
            turno = int(cfg.get("turno") or 1)
        except (TypeError, ValueError):
            raise ErroSessao("Turno inválido")
        if turno not in (1, 2):
            raise ErroSessao("Turno deve ser 1 ou 2")
        cargo = str(cfg.get("cargo") or "1").strip()
        if not cargo.isdigit():
            raise ErroSessao(f"Cargo inválido: {cargo!r}")
        tse_url = str(cfg.get("tse_url") or TSE_PADRAO).strip().rstrip("/")
        if not tse_url.startswith(("http://", "https://")):
            raise ErroSessao("URL da CDN deve começar com http:// ou https://")
        ambiente = str(cfg.get("ambiente") or "oficial").strip().strip("/")
        if not ambiente or ".." in ambiente:
            raise ErroSessao(f"Ambiente inválido: {ambiente!r}")
        formato = str(cfg.get("formato") or "").strip() or ("u" if int(ano) >= 2024 else "r")
        if formato not in ("u", "r"):
            raise ErroSessao("Formato deve ser 'u' ou 'r'")
        if formato == "r" and eleicao is None:
            raise ErroSessao("No formato 'r' (até 2022) o código da eleição é obrigatório")
        jws = str(cfg.get("jws") or "").strip() or None
        if jws is not None and jws not in CHAVES_TSE:
            raise ErroSessao(f"Chave JWS inválida: {jws!r}")
        if jws and formato != "u":
            raise ErroSessao("A verificação JWS só se aplica ao formato 'u' (2024+)")

        verificador = JWSVerifier.do_ambiente(jws) if jws else None
        self.coordinator = PipelineCoordinator(
            event_bus=self.bus, db_path=self.db_path, num_simulacoes=self.num_simulacoes,
            tse_base_url=tse_url, ano_eleicao=ano, codigo_eleicao=eleicao, codigo_cargo=cargo,
            turno=turno, formato=formato, ambiente=ambiente,
            http_client=TSEHttpClient(verificador_jws=verificador),
        )
        self.info = {
            "mock": False, "simulado": False, "ano": ano, "codigo": eleicao, "cargo": cargo, "turno": turno,
            "formato": formato, "ambiente": ambiente, "fonte": tse_url, "jws": jws,
            "simulacoes": self.num_simulacoes,
        }

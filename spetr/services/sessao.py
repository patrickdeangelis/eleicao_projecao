"""
Sessão de execução do SPETR: escolhe entre coleta real na CDN do TSE e replay de uma apuração
real (boletins de urna), inicia o pipeline correspondente e permite trocar de modo sem reiniciar
o aplicativo.
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
from spetr.simulador import SimuladorLocal
from spetr.simulador.replay import VELOCIDADES_REPLAY, EstadoReplay, listar_replays

logger = logging.getLogger("spetr.services.sessao")

MODOS = ("real", "replay")
TSE_PADRAO = "https://resultados.tse.jus.br"


class ErroSessao(ValueError):
    """Opções inválidas para iniciar uma sessão."""


# Eleições exibidas no combobox da tela inicial. Para 2022, a coleta usa o replay local dos boletins;
# para 2026, o código vazio é descoberto pelo ele-c.json.
ELEICOES_PRONTAS = [
    {"id": "2026-2t", "rotulo": "2026 · 2º turno · Presidente (código automático)", "ano": "2026", "turno": 2, "eleicao": ""},
    {"id": "2026-1t", "rotulo": "2026 · 1º turno · Presidente (6257)", "ano": "2026", "turno": 1, "eleicao": "6257"},
    {"id": "2022-1t", "rotulo": "2022 · 1º turno · Presidente (544)", "ano": "2022", "turno": 1, "eleicao": "544"},
    {"id": "2022-2t", "rotulo": "2022 · 2º turno · Presidente (545)", "ano": "2022", "turno": 2, "eleicao": "545"},
]


class SessaoSPETR:
    """Controla qual pipeline está ativo (coleta real ou replay)."""

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
                "jws": list(CHAVES_TSE),
                "eleicoes_prontas": ELEICOES_PRONTAS,
                "replays": listar_replays(),
                "velocidades_replay": {k: f"+{m} min da noite real a cada {s:.0f}s" for k, (s, m) in VELOCIDADES_REPLAY.items()},
            },
        }

    # ------------------------------------------------------------- ciclo

    async def iniciar(self, modo: str, opcoes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        opcoes = opcoes or {}
        if modo not in MODOS:
            raise ErroSessao(f"Modo inválido: {modo!r}. Use 'real' ou 'replay'.")
        async with self._lock:
            await self._parar_sem_lock(notificar=False)
            if modo == "replay":
                await self._iniciar_replay(opcoes)
            elif str(opcoes.get("ano") or self.padroes_reais.get("ano")) == "2022":
                try:
                    turno = int(opcoes.get("turno") or self.padroes_reais.get("turno") or 1)
                except (TypeError, ValueError):
                    raise ErroSessao("Turno inválido")
                await self._iniciar_replay({"fonte": f"2022_{turno}t", "velocidade": "normal"})
                modo = "replay"
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

    async def _iniciar_replay(self, opcoes: Dict[str, Any]) -> None:
        fonte = str(opcoes.get("fonte") or "")
        velocidade = str(opcoes.get("velocidade") or "normal")
        if fonte not in listar_replays():
            raise ErroSessao(f"Replay não preparado: {fonte!r}. Use scripts/preparar_replay.py")
        try:
            estado = EstadoReplay(fonte, velocidade)
        except ValueError as e:
            raise ErroSessao(str(e))
        self.simulador = SimuladorLocal(estado)
        url = await self.simulador.iniciar()
        cliente = TSEHttpClient(pacing=PacingManager(max_concurrent=32, max_rate_per_sec=400.0))
        self.coordinator = PipelineCoordinator(
            event_bus=self.bus, db_path=self.db_path, num_simulacoes=self.num_simulacoes,
            tse_base_url=url, ano_eleicao=estado.ano, codigo_eleicao=estado.eleicao,
            codigo_cargo="1", turno=estado.turno, formato="r", ambiente="oficial",
            http_client=cliente, intervalo_tier1=3.0, intervalo_tier2=3.0, intervalo_exterior=6.0,
            intervalo_subestratos=6.0, rotulo_eleicao=f"replay/{fonte}", referencia="auto",
            parar_ao_concluir=False,  # no replay o usuário pode voltar a 0% e rever a apuração
        )
        self.info = {
            "replay": True, "cenario": f"replay-{fonte}", "ano": estado.ano,
            "descricao": estado.descricao, "velocidade": velocidade, "turno": estado.turno, "cargo": "1",
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
            http_client=TSEHttpClient(
                verificador_jws=verificador,
                # Limite do TSE: 100 req/s por IP (bloqueio de 10 min). 50 req/s deixa folga, e a maioria das
                # respostas é 304 (ETag), então o ciclo completo cabe em poucos segundos.
                pacing=PacingManager(max_concurrent=40, max_rate_per_sec=50.0),
            ),
            intervalo_tier1=10.0, intervalo_tier2=20.0, intervalo_exterior=60.0, intervalo_subestratos=30.0,
            referencia="auto",
        )
        self.info = {
            "ano": ano, "codigo": eleicao, "cargo": cargo, "turno": turno,
            "formato": formato, "ambiente": ambiente, "fonte": tse_url, "jws": jws,
            "simulacoes": self.num_simulacoes,
        }

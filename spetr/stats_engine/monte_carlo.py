"""
Motor de Simulação de Monte Carlo e Inferência Estatística.
Executa 10.000 eleições sintéticas em tempo real vetorizadas com NumPy.
"""
import time
from typing import Dict, List, Optional
import numpy as np
import logging

from spetr.domain.entities import (
    Candidato,
    EstratoEleitoral,
    SnapshotParcial,
    ProjecaoCandidato,
    ResultadoProjecao,
)
from spetr.domain.value_objects import StatusCall, TipoEstrato
from spetr.domain.interfaces import IProjectionEngine, IEventBus
from spetr.services.events import StrataNormalizedEvent, ProjectionCalculatedEvent
from spetr.stats_engine.bayesian_dirichlet import (
    calcular_parametros_posteriores,
    amostrar_proporcoes_monte_carlo,
)

logger = logging.getLogger("spetr.stats_engine.monte_carlo")


class MonteCarloProjectionEngine:
    """
    Motor Monte Carlo vetorizado para cálculo de projeção eleitoral.
    Cumpre a interface IProjectionEngine e se conecta opcionalmente ao EventBus.
    """

    def __init__(
        self,
        event_bus: Optional[IEventBus] = None,
        num_simulacoes: int = 10000,
        peso_prior_n0: float = 300.0,  # Equivalente a ~300 votos prévios de inércia por estrato
        seed: Optional[int] = 42
    ):
        self.bus = event_bus
        self.num_simulacoes = num_simulacoes
        self.peso_prior_n0 = peso_prior_n0
        self.rng = np.random.default_rng(seed)

        self.estratos: Dict[str, EstratoEleitoral] = {}
        self.candidatos: List[Candidato] = []
        self.candidato_indices: Dict[str, int] = {}

        if self.bus is not None:
            self.bus.subscribe(StrataNormalizedEvent, self.ao_receber_estratos_normalizados)

    def inicializar_estratos(self, estratos: List[EstratoEleitoral]) -> None:
        """Registra a lista de estratos com seus eleitorados e priors."""
        self.estratos = {e.id: e for e in estratos}

    def configurar_candidatos(self, candidatos: List[Candidato]) -> None:
        """Define os candidatos que participam do pleito."""
        self.candidatos = list(candidatos)
        self.candidato_indices = {c.numero: i for i, c in enumerate(self.candidatos)}

    async def ao_receber_estratos_normalizados(self, evento: StrataNormalizedEvent) -> None:
        """Handler do EventBus que roda a projeção quando um novo lote de estratos chega."""
        try:
            resultado = self.calcular(
                snapshots=evento.snapshots,
                num_simulacoes=self.num_simulacoes,
                ciclo_id=evento.ciclo_id,
                candidatos_meta=evento.candidatos_meta
            )
            if self.bus is not None:
                await self.bus.publish(
                    ProjectionCalculatedEvent(
                        timestamp=evento.timestamp,
                        ciclo_id=evento.ciclo_id,
                        resultado=resultado
                    )
                )
        except Exception as e:
            logger.error(f"Erro ao calcular projeção no MonteCarloProjectionEngine: {e}", exc_info=True)

    def calcular(
        self,
        snapshots: Dict[str, SnapshotParcial],
        num_simulacoes: int = 10000,
        ciclo_id: int = 1,
        candidatos_meta: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> ResultadoProjecao:
        """
        Executa a projeção probabilística sobre os estratos fornecidos.
        """
        inicio_t = time.perf_counter()

        # Identifica os números de candidatos presentes nos snapshots recebidos
        cand_nums_no_lote = set()
        for snap in snapshots.values():
            cand_nums_no_lote.update(snap.votos_candidatos.keys())

        cands_atuais = set(self.candidato_indices.keys())

        # Se os candidatos do lote forem diferentes dos atuais (ou se atuais estiver vazio)
        if cand_nums_no_lote and cand_nums_no_lote != cands_atuais:
            cands_ordenados = sorted(list(cand_nums_no_lote))
            meta = candidatos_meta or {}
            novos_candidatos = []
            cores_default = ["#38BDF8", "#F43F5E", "#EAB308", "#10B981", "#A855F7", "#F97316"]
            for i, num in enumerate(cands_ordenados):
                c_info = meta.get(num, {})
                nome = c_info.get("nome", f"Candidato {num}")
                partido = c_info.get("partido", "PART")
                # Cores padrão para números conhecidos
                if num == "13":
                    cor = "#EF4444"
                elif num == "22":
                    cor = "#22C55E"
                else:
                    cor = cores_default[i % len(cores_default)]

                novos_candidatos.append(
                    Candidato(numero=num, nome=nome, sigla_partido=partido, cor_hex=cor)
                )
            self.configurar_candidatos(novos_candidatos)
        elif not self.candidatos:
            # Fallback seguro caso ainda não haja votos apurados em nenhum estrato
            cands_ordenados = ["13", "22"]
            self.candidatos = [
                Candidato(numero="13", nome="Candidato 13", sigla_partido="PT", cor_hex="#EF4444"),
                Candidato(numero="22", nome="Candidato 22", sigla_partido="PL", cor_hex="#22C55E"),
            ]
            self.candidato_indices = {c.numero: i for i, c in enumerate(self.candidatos)}


        K = len(self.candidatos)
        estrato_ids = list(snapshots.keys())
        H = len(estrato_ids)

        if H == 0:
            # Sem dados ainda
            return self._resultado_vazio(ciclo_id)

        # Matrizes de cálculo
        # Shape: (H, K)
        prior_alphas = np.zeros((H, K), dtype=np.float64)
        votos_obs = np.zeros((H, K), dtype=np.float64)
        votos_rem_esperados = np.zeros(H, dtype=np.float64)

        total_secoes = 0
        secoes_apuradas = 0
        total_eleitores = 0

        for h, eid in enumerate(estrato_ids):
            snap = snapshots[eid]
            estrato_meta = self.estratos.get(eid)

            total_secoes += snap.secoes_total
            secoes_apuradas += snap.secoes_apuradas
            eleitores_estrato = snap.eleitores_aptos if snap.eleitores_aptos > 0 else (
                estrato_meta.eleitores_aptos if estrato_meta else snap.secoes_total * 350
            )
            total_eleitores += eleitores_estrato

            # 1. Configura prior alpha
            for num_cand, k in self.candidato_indices.items():
                if estrato_meta and estrato_meta.prior_alpha and num_cand in estrato_meta.prior_alpha:
                    prior_prop = estrato_meta.prior_alpha[num_cand]
                else:
                    prior_prop = 1.0 / K
                # Peso n0 do prior
                prior_alphas[h, k] = max(0.5, prior_prop * self.peso_prior_n0)

            # 2. Votos observados
            for num_cand, k in self.candidato_indices.items():
                votos_obs[h, k] = snap.votos_candidatos.get(num_cand, 0)

            # 3. Estimativa de votos válidos faltantes no estrato
            sec_faltantes = max(0, snap.secoes_total - snap.secoes_apuradas)
            if snap.secoes_total > 0:
                eleit_por_secao = eleitores_estrato / snap.secoes_total
            else:
                eleit_por_secao = 350.0

            # Taxa de comparecimento e validade com encolhimento bayesiano
            if snap.secoes_apuradas > 0 and snap.comparecimento > 0:
                taxa_comp_obs = snap.comparecimento / (snap.comparecimento + max(1, snap.abstencao))
                taxa_val_obs = snap.votos_validos / max(1, snap.comparecimento)
                peso_obs = min(1.0, snap.secoes_apuradas / 30.0)
                comp_est = peso_obs * taxa_comp_obs + (1.0 - peso_obs) * 0.795
                val_est = peso_obs * taxa_val_obs + (1.0 - peso_obs) * 0.950
            else:
                comp_est = 0.795
                val_est = 0.950

            votos_rem_esperados[h] = sec_faltantes * eleit_por_secao * comp_est * val_est

        # 4. Atualização Bayesiana dos hiperparâmetros
        alphas_post = calcular_parametros_posteriores(prior_alphas, votos_obs)

        # 5. Amostragem de Monte Carlo
        # proporcoes_amostradas: (M, H, K)
        proporcoes_amostradas = amostrar_proporcoes_monte_carlo(
            alphas_post,
            num_simulacoes=num_simulacoes,
            rng=self.rng
        )

        # 6. Projeção dos votos remanescentes
        # rem_esperados shape (H, 1) broadcasted to (M, H, K)
        votos_rem_matrix = votos_rem_esperados[np.newaxis, :, np.newaxis]
        votos_rem_simulados = proporcoes_amostradas * votos_rem_matrix

        # Votos observados shape (1, H, K)
        votos_obs_matrix = votos_obs[np.newaxis, :, :]

        # Total simulado por estrato: (M, H, K)
        votos_totais_simulados_estratos = votos_obs_matrix + votos_rem_simulados

        # Agregação Nacional: soma sobre todos os estratos H -> shape: (M, K)
        votos_nacionais_simulados = votos_totais_simulados_estratos.sum(axis=1)

        # Total de votos válidos simulados por iteração -> shape: (M, 1)
        total_validos_simulados = votos_nacionais_simulados.sum(axis=1, keepdims=True)
        total_validos_simulados = np.where(total_validos_simulados == 0, 1.0, total_validos_simulados)

        # Proporções nacionais simuladas em porcentagem: (M, K)
        perc_nacionais_simulados = (votos_nacionais_simulados / total_validos_simulados) * 100.0

        # 7. Métricas de Resumo e Estatísticas
        votos_validos_apurados = int(votos_obs.sum())
        total_validos_proj_medio = int(votos_nacionais_simulados.mean())
        perc_secoes_total = (secoes_apuradas / max(1, total_secoes)) * 100.0

        projecoes_candidatos: List[ProjecaoCandidato] = []
        means_proj = []

        for k, cand in enumerate(self.candidatos):
            v_obs_cand = int(votos_obs[:, k].sum())
            perc_obs_cand = (v_obs_cand / max(1, votos_validos_apurados)) * 100.0

            cand_samples = perc_nacionais_simulados[:, k]
            mean_pct = float(np.mean(cand_samples))
            ic_low = float(np.percentile(cand_samples, 2.5))
            ic_high = float(np.percentile(cand_samples, 97.5))
            media_votos = int(np.mean(votos_nacionais_simulados[:, k]))

            # Probabilidade de vitória
            # Candidato k teve mais votos que todos os outros no sorteio m
            outros_indices = [j for j in range(K) if j != k]
            if outros_indices:
                max_outros = np.max(perc_nacionais_simulados[:, outros_indices], axis=1)
                prob_vit = float(np.mean(cand_samples > max_outros))
            else:
                prob_vit = 1.0

            means_proj.append((mean_pct, cand.numero))

            projecoes_candidatos.append(
                ProjecaoCandidato(
                    numero=cand.numero,
                    nome=cand.nome,
                    partido=cand.sigla_partido,
                    cor_hex=cand.cor_hex,
                    votos_apurados=v_obs_cand,
                    perc_apurado=round(perc_obs_cand, 2),
                    media_projetada=media_votos,
                    perc_projetado=round(mean_pct, 2),
                    ic_inferior_95=round(ic_low, 2),
                    ic_superior_95=round(ic_high, 2),
                    prob_vitoria=round(prob_vit, 4)
                )
            )

        # Ordena candidatos por projeção percentual decrescente
        projecoes_candidatos.sort(key=lambda c: c.perc_projetado, reverse=True)
        means_proj.sort(reverse=True)

        lider_cand = projecoes_candidatos[0]
        segundo_cand = projecoes_candidatos[1] if len(projecoes_candidatos) > 1 else None
        lider_margem = round(lider_cand.perc_projetado - (segundo_cand.perc_projetado if segundo_cand else 0.0), 2)

        # 8. Regra de Chamada (Call Decision)
        status_call = StatusCall.INDEFINIDO
        vencedor_projetado = None

        # Verificação matemática: se votos apurados do líder superam a metade de todos os válidos possíveis
        votos_faltantes_max = float(votos_rem_esperados.sum() * 1.05) # margem de segurança de comparecimento
        if segundo_cand and lider_cand.votos_apurados > (segundo_cand.votos_apurados + votos_faltantes_max):
            status_call = StatusCall.MATEMATICAMENTE_ELEITO
            vencedor_projetado = lider_cand.numero
        elif lider_cand.prob_vitoria >= 0.995 and perc_secoes_total >= 10.0:
            status_call = StatusCall.VITORIA_PROJETADA
            vencedor_projetado = lider_cand.numero
        elif lider_cand.ic_inferior_95 > 50.1 and perc_secoes_total >= 5.0:
            status_call = StatusCall.VITORIA_PROJETADA
            vencedor_projetado = lider_cand.numero

        tempo_ms = (time.perf_counter() - inicio_t) * 1000.0

        return ResultadoProjecao(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            ciclo_id=ciclo_id,
            total_secoes=total_secoes,
            secoes_apuradas=secoes_apuradas,
            perc_secoes_apuradas=round(perc_secoes_total, 2),
            total_eleitores=total_eleitores,
            total_validos_apurados=votos_validos_apurados,
            total_validos_projetados=total_validos_proj_medio,
            candidatos=projecoes_candidatos,
            status_call=status_call,
            vencedor_projetado=vencedor_projetado,
            lider_margem=lider_margem,
            tempo_computacao_ms=round(tempo_ms, 2)
        )

    def _resultado_vazio(self, ciclo_id: int) -> ResultadoProjecao:
        return ResultadoProjecao(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            ciclo_id=ciclo_id,
            total_secoes=0,
            secoes_apuradas=0,
            perc_secoes_apuradas=0.0,
            total_eleitores=0,
            total_validos_apurados=0,
            total_validos_projetados=0,
            candidatos=[],
            status_call=StatusCall.INDEFINIDO,
            vencedor_projetado=None,
            lider_margem=0.0,
            tempo_computacao_ms=0.0
        )

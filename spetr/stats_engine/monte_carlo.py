"""
Motor de Simulação de Monte Carlo e Inferência Estatística.
Executa 10.000 eleições sintéticas em tempo real vetorizadas com NumPy.

Fontes de incerteza modeladas sobre os votos ainda não apurados:
1. Proporções por estrato ~ Dirichlet(prior + observado), com concentração limitada
   (`concentracao_max`): as urnas restantes de um estrato não são uma amostra aleatória
   das já apuradas, então milhões de votos observados não podem gerar certeza absoluta.
2. Choque comum por UF e choque nacional (log-normais, correlacionando estratos), que
   representam vieses sistemáticos de ordem de apuração.
3. Incerteza no comparecimento/validade dos votos restantes.

Subestratificação: quando o agregador publica subestratos de uma UF (ex.: MG_SUB_NORTE e
MG_SUB_SUL no lugar de MG_INTERIOR), o motor projeta as duas versões (normal e subestratificada).
A `versao_principal` define os números e a chamada; a outra vai para a comparação no painel.
"""
import asyncio
import time
from typing import Any, Dict, List, Optional
import numpy as np
import logging

from spetr.domain.entities import (
    Candidato,
    EstratoEleitoral,
    SnapshotParcial,
    ProjecaoCandidato,
    ResultadoProjecao,
)
from spetr.domain.value_objects import REGIAO_POR_UF, StatusCall, TipoEstrato
from spetr.domain.interfaces import IEventBus
from spetr.services.events import StrataNormalizedEvent, ProjectionCalculatedEvent
from spetr.stats_engine.crescimento import ProjecaoCrescimento
from spetr.stats_engine.bayesian_dirichlet import (
    calcular_parametros_posteriores,
    limitar_concentracao,
    amostrar_proporcoes_monte_carlo,
)

logger = logging.getLogger("spetr.stats_engine.monte_carlo")

CORES_DEFAULT = ["#38BDF8", "#F43F5E", "#EAB308", "#10B981", "#A855F7", "#F97316"]
COMPARECIMENTO_PADRAO = 0.795
VALIDADE_PADRAO = 0.950
VERSOES = ("subestratificado", "normal")


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
        seed: Optional[int] = 42,
        concentracao_max: float = 2000.0,   # ~1,1 p.p. de desvio por estrato num 50/50
        # Choques sobre os votos restantes (viés de ordem de apuração). Calibrados no replay do
        # 1º turno de 2026: com 0,04/0,03 o IC 95% continha o resultado em só ~60% dos instantes.
        sigma_uf: float = 0.06,             # choque log-proporção comum a cada UF
        sigma_nacional: float = 0.06,       # choque log-proporção comum ao país
        sigma_comparecimento: float = 0.03, # incerteza relativa nos votos válidos restantes
        exige_maioria: bool = True,         # vitória exige > 50% dos válidos (Presidente/Governador)
        limiar_prob_call: float = 0.995,
        perc_minimo_call: float = 10.0,
        tamanho_lote_sim: int = 2000,
    ):
        self.bus = event_bus
        self.num_simulacoes = num_simulacoes
        self.peso_prior_n0 = peso_prior_n0
        self.rng = np.random.default_rng(seed)
        self.concentracao_max = concentracao_max
        self.sigma_uf = sigma_uf
        self.sigma_nacional = sigma_nacional
        self.sigma_comparecimento = sigma_comparecimento
        self.exige_maioria = exige_maioria
        self.limiar_prob_call = limiar_prob_call
        self.perc_minimo_call = perc_minimo_call
        self.tamanho_lote_sim = tamanho_lote_sim
        self.versao_principal = "subestratificado"
        self.crescimento = ProjecaoCrescimento()

        self.estratos: Dict[str, EstratoEleitoral] = {}
        self.ufs_meta: Dict[str, Dict[str, int]] = {}
        self.prior_padrao: Dict[str, float] = {}
        self.nomes_estratos: Dict[str, str] = {}
        self.candidatos: List[Candidato] = []
        self.candidato_indices: Dict[str, int] = {}

        if self.bus is not None:
            self.bus.subscribe(StrataNormalizedEvent, self.ao_receber_estratos_normalizados)

    def inicializar_estratos(self, estratos: List[EstratoEleitoral]) -> None:
        """Registra a lista de estratos com seus eleitorados e priors."""
        self.estratos = {e.id: e for e in estratos}

    def inicializar_ufs(
        self,
        ufs_meta: Dict[str, Dict[str, int]],
        prior_padrao: Optional[Dict[str, float]] = None
    ) -> None:
        """
        Registra o universo de UFs ({uf: {"eleitores": n, "secoes": n}}).
        UFs sem nenhum dado recebido entram na projeção como um estrato sem apuração
        (projetado pelo prior), em vez de desaparecerem do total nacional.
        """
        self.ufs_meta = dict(ufs_meta)
        self.prior_padrao = dict(prior_padrao or {})

    def configurar_candidatos(self, candidatos: List[Candidato]) -> None:
        """Define os candidatos que participam do pleito."""
        self.candidatos = list(candidatos)
        self.candidato_indices = {c.numero: i for i, c in enumerate(self.candidatos)}

    async def ao_receber_estratos_normalizados(self, evento: StrataNormalizedEvent) -> None:
        """Handler do EventBus que roda a projeção quando um novo lote de estratos chega."""
        try:
            # Cálculo pesado fora do loop de eventos para não travar API/SSE
            resultado = await asyncio.to_thread(
                self.calcular,
                snapshots=evento.snapshots,
                num_simulacoes=self.num_simulacoes,
                ciclo_id=evento.ciclo_id,
                candidatos_meta=evento.candidatos_meta,
                exterior=evento.exterior,
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

    def _atualizar_candidatos(self, numeros: set, candidatos_meta: Optional[Dict[str, Dict[str, Any]]]) -> None:
        if not numeros or numeros == set(self.candidato_indices.keys()):
            return
        meta = candidatos_meta or {}
        novos = []
        for i, num in enumerate(sorted(numeros)):
            c_info = meta.get(num, {})
            if num == "13":
                cor = "#EF4444"
            elif num == "22":
                cor = "#22C55E"
            else:
                cor = CORES_DEFAULT[i % len(CORES_DEFAULT)]
            novos.append(Candidato(
                numero=num,
                nome=c_info.get("nome", f"Candidato {num}"),
                sigla_partido=c_info.get("partido", ""),
                cor_hex=cor,
                vice=c_info.get("vice", ""),
                coligacao=c_info.get("coligacao", ""),
                composicao=c_info.get("composicao", ""),
                nome_completo=c_info.get("nome_completo", ""),
            ))
        self.configurar_candidatos(novos)

    def _media_prior(self, prior: Dict[str, float], media_nacional: np.ndarray) -> np.ndarray:
        """Prior configurado se cobrir todos os candidatos; senão, a média nacional observada."""
        if prior and all(num in prior for num in self.candidato_indices):
            v = np.array([prior[c.numero] for c in self.candidatos], dtype=np.float64)
            if v.sum() > 0:
                return v / v.sum()
        return media_nacional

    @staticmethod
    def separar_versoes(snapshots: Dict[str, SnapshotParcial]):
        """(normal, subestratificado, UFs subestratificadas) a partir dos estratos publicados."""
        ufs_sub = sorted({eid.split("_")[0] for eid in snapshots if "_SUB_" in eid})
        ufs_cid = {eid.split("_")[0] for eid in snapshots if "_CID_" in eid}
        normal = {k: v for k, v in snapshots.items() if "_SUB_" not in k and "_CID_" not in k}
        # UF com cidades agrupadas por região: só os estratos _SUB_ e _CID_ (sem Interior nem cidades soltas)
        sub = {k: v for k, v in snapshots.items()
               if not (k.endswith("_INTERIOR") and k.split("_")[0] in ufs_sub)
               and not (k.split("_")[0] in ufs_cid and "_SUB_" not in k and "_CID_" not in k)}
        return normal, sub, ufs_sub

    def calcular(
        self,
        snapshots: Dict[str, SnapshotParcial],
        num_simulacoes: int = 10000,
        ciclo_id: int = 1,
        candidatos_meta: Optional[Dict[str, Dict[str, Any]]] = None,
        exterior: Optional[List[Dict[str, Any]]] = None,
    ) -> ResultadoProjecao:
        """
        Executa a projeção probabilística sobre os estratos fornecidos, na versão principal; com
        subestratos, também na outra versão (comparação) e, sempre, a projeção por crescimento.
        """
        inicio_t = time.perf_counter()

        cand_nums_no_lote = set()
        for snap in snapshots.values():
            cand_nums_no_lote.update(snap.votos_candidatos.keys())
        self._atualizar_candidatos(cand_nums_no_lote, candidatos_meta)
        self.crescimento.registrar(snapshots)

        normal, sub, ufs_sub = self.separar_versoes(snapshots)
        versoes = {"normal": normal, "subestratificado": sub}
        principal = self.versao_principal if ufs_sub else "normal"
        resultado, extras = self._projetar(versoes[principal], num_simulacoes, ciclo_id, ufs_sub)
        analise = resultado.analise
        if exterior:
            analise["exterior"] = exterior
        if analise.get("aguardando") or not resultado.candidatos:
            return resultado

        numeros = [c.numero for c in self.candidatos]
        cresc = self.crescimento.projetar(versoes[principal], numeros)
        analise["crescimento"] = cresc
        analise["crescimento_nacional"] = cresc["nacional"]

        # Crescimento nas duas versões, no país inteiro (aba Modelos); sem subestratos as versões coincidem
        cresc_por_versao = {principal: cresc}
        if ufs_sub:
            outra = "normal" if principal == "subestratificado" else "subestratificado"
            res_outra, extras_outra = self._projetar(versoes[outra], num_simulacoes, ciclo_id, ufs_sub, analise_completa=False)
            cresc_outra = self.crescimento.projetar(versoes[outra], numeros)
            cresc_por_versao[outra] = cresc_outra
            comparacao = {
                principal: self._resumo_versao(resultado, extras, versoes[principal], ufs_sub, cresc),
                outra: self._resumo_versao(res_outra, extras_outra, versoes[outra], ufs_sub, cresc_outra),
            }
            analise["subestratificacao"] = {"versao_principal": principal, "ufs": ufs_sub, "versoes": comparacao}
            analise["versoes_resumo"] = {
                v: {"nacional": {n: d["pct"] for n, d in c["nacional"].items()},
                    **{uf: {n: d["pct"] for n, d in c["ufs"][uf].items()} for uf in ufs_sub}}
                for v, c in comparacao.items()
            }

        for v in VERSOES:
            cresc_por_versao.setdefault(v, cresc)
        analise["crescimento_versoes"] = {v: c["nacional"] for v, c in cresc_por_versao.items()}
        analise["modelos"] = {
            "crescimento": {
                v: {k: c[k] for k in ("nacional", "votos_nacionais", "ufs", "ufs_detalhe")}
                for v, c in cresc_por_versao.items()
            },
        }

        tempo_ms = (time.perf_counter() - inicio_t) * 1000.0
        object.__setattr__(resultado, "tempo_computacao_ms", round(tempo_ms, 2))
        return resultado

    def _resumo_versao(self, res: ResultadoProjecao, extras: Dict[str, Any], snaps: Dict[str, SnapshotParcial],
                       ufs_sub: List[str], cresc: Dict[str, Any]) -> Dict[str, Any]:
        """Números de uma versão para a comparação normal × subestratificado."""
        nums = [c.numero for c in self.candidatos]
        ufs = {}
        for uf in ufs_sub:
            am = extras["uf_amostras"].get(uf)
            if am is None:
                continue
            ufs[uf] = {
                n: {"pct": round(float(am[:, k].mean()), 3),
                    "ic": [round(float(np.percentile(am[:, k], 2.5)), 3), round(float(np.percentile(am[:, k], 97.5)), 3)],
                    "prob_lider": round(float((am.argmax(axis=1) == k).mean()), 4),
                    "crescimento": cresc["ufs"].get(uf, {}).get(n)}
                for k, n in enumerate(nums)
            }
        estratos = []
        for eid, snap in sorted(snaps.items()):
            uf = eid.split("_")[0]
            if uf not in ufs_sub:
                continue
            tot = sum(snap.votos_candidatos.get(n, 0) for n in nums)
            estratos.append({
                "id": eid, "nome": self._nome_estrato(eid), "tipo": self._tipo_estrato(eid),
                "secoes_total": snap.secoes_total, "secoes_apuradas": snap.secoes_apuradas,
                "eleitores_aptos": snap.eleitores_aptos,
                "pct_apurado": {n: round(snap.votos_candidatos.get(n, 0) / tot * 100.0, 3) if tot else 0.0 for n in nums},
                "crescimento": cresc["estratos"].get(eid, {}).get("pct"),
            })
        return {
            "nacional": {c.numero: {"pct": c.perc_projetado, "ic": [c.ic_inferior_95, c.ic_superior_95],
                                    "prob_vitoria": c.prob_vitoria} for c in res.candidatos},
            "ufs": ufs,
            "estratos": estratos,
            "status_call": res.status_call.value,
            "vencedor_projetado": res.vencedor_projetado,
        }

    def _projetar(
        self,
        snapshots: Dict[str, SnapshotParcial],
        num_simulacoes: int,
        ciclo_id: int,
        ufs_detalhe: List[str],
        analise_completa: bool = True,
    ):
        """Monte Carlo sobre um conjunto de estratos. Retorna (resultado, extras)."""
        inicio_t = time.perf_counter()
        extras: Dict[str, Any] = {"uf_amostras": {}}

        if not snapshots or not self.candidatos:
            # Sem dados ainda (nenhum candidato com voto conhecido)
            return self._resultado_vazio(ciclo_id), extras

        # UFs do universo que ainda não têm nenhum dado: estrato sem apuração
        snapshots = dict(snapshots)
        ufs_com_dados = {eid.split("_")[0] for eid in snapshots}
        ufs_sem_dados = sorted(uf for uf in self.ufs_meta if uf not in ufs_com_dados)
        for uf in ufs_sem_dados:
            m = self.ufs_meta[uf]
            eid = f"{uf}_SEM_DADOS"
            snapshots[eid] = SnapshotParcial(
                estrato_id=eid, timestamp="", secoes_total=int(m.get("secoes", 0)), secoes_apuradas=0,
                eleitores_aptos=int(m.get("eleitores", 0)), comparecimento=0, abstencao=0,
                votos_validos=0, votos_brancos=0, votos_nulos=0, votos_candidatos={}
            )
        if ufs_sem_dados:
            logger.warning(f"{len(ufs_sem_dados)} UF(s) sem dados, projetadas só pelo prior: {', '.join(ufs_sem_dados)}")

        K = len(self.candidatos)
        estrato_ids = list(snapshots.keys())
        H = len(estrato_ids)

        votos_obs = np.zeros((H, K), dtype=np.float64)
        for h, eid in enumerate(estrato_ids):
            for num_cand, k in self.candidato_indices.items():
                votos_obs[h, k] = snapshots[eid].votos_candidatos.get(num_cand, 0)

        obs_nacional = votos_obs.sum(axis=0)
        media_nacional = obs_nacional / obs_nacional.sum() if obs_nacional.sum() > 0 else np.full(K, 1.0 / K)

        prior_alphas = np.zeros((H, K), dtype=np.float64)
        votos_rem_esperados = np.zeros(H, dtype=np.float64)
        votos_rem_maximos = np.zeros(H, dtype=np.float64)

        total_secoes = 0
        secoes_apuradas = 0
        total_eleitores = 0

        for h, eid in enumerate(estrato_ids):
            snap = snapshots[eid]
            estrato_meta = self.estratos.get(eid)

            if eid.endswith("_SEM_DADOS"):
                prior = self.prior_padrao
            else:
                total_secoes += snap.secoes_total
                secoes_apuradas += snap.secoes_apuradas
                prior = estrato_meta.prior_alpha if estrato_meta else {}

            eleitores_estrato = snap.eleitores_aptos if snap.eleitores_aptos > 0 else (
                estrato_meta.eleitores_aptos if estrato_meta else snap.secoes_total * 350
            )
            total_eleitores += eleitores_estrato

            # 1. Prior (média x peso n0)
            prior_alphas[h] = np.maximum(0.5, self._media_prior(prior, media_nacional) * self.peso_prior_n0)

            # 2. Votos válidos esperados nas seções faltantes
            sec_faltantes = max(0, snap.secoes_total - snap.secoes_apuradas)
            eleit_por_secao = eleitores_estrato / snap.secoes_total if snap.secoes_total > 0 else 350.0

            # Taxa de comparecimento e validade com encolhimento bayesiano
            if snap.secoes_apuradas > 0 and snap.comparecimento > 0:
                taxa_comp_obs = snap.comparecimento / (snap.comparecimento + max(1, snap.abstencao))
                taxa_val_obs = snap.votos_validos / max(1, snap.comparecimento)
                peso_obs = min(1.0, snap.secoes_apuradas / 30.0)
                comp_est = peso_obs * taxa_comp_obs + (1.0 - peso_obs) * COMPARECIMENTO_PADRAO
                val_est = peso_obs * taxa_val_obs + (1.0 - peso_obs) * VALIDADE_PADRAO
            else:
                comp_est = COMPARECIMENTO_PADRAO
                val_est = VALIDADE_PADRAO

            votos_rem_esperados[h] = sec_faltantes * eleit_por_secao * comp_est * val_est

            # 3. Limite superior conservador dos votos restantes: o maior entre os eleitores
            #    ainda não computados e o eleitorado proporcional às seções faltantes
            #    (protege contra comparecimento/abstenção inconsistentes no arquivo)
            if sec_faltantes == 0:
                votos_rem_maximos[h] = 0.0
            else:
                nao_computados = max(0.0, eleitores_estrato - snap.comparecimento - snap.abstencao)
                por_secoes = eleit_por_secao * sec_faltantes
                votos_rem_maximos[h] = max(nao_computados, por_secoes)

        # Antes do primeiro voto apurado não há o que projetar (o resultado seria só o prior):
        # publica os candidatos já cadastrados nos arquivos do TSE, zerados e sem projeção
        if obs_nacional.sum() <= 0:
            return self._resultado_aguardando(ciclo_id, snapshots, total_secoes, total_eleitores, ufs_sem_dados), extras

        # 4. Atualização Bayesiana + limite de concentração (sobredispersão)
        alphas_post = limitar_concentracao(
            calcular_parametros_posteriores(prior_alphas, votos_obs),
            self.concentracao_max
        )

        # 5. Simulação em lotes (limita memória com muitos candidatos), agregando por UF
        ufs_estratos = [eid.split("_")[0] for eid in estrato_ids]
        ufs_unicas, idx_uf = np.unique(ufs_estratos, return_inverse=True)
        U = len(ufs_unicas)
        onehot_uf = np.zeros((H, U), dtype=np.float64)
        onehot_uf[np.arange(H), idx_uf] = 1.0
        obs_uf = onehot_uf.T @ votos_obs  # (U, K)

        votos_nacionais_simulados = np.empty((num_simulacoes, K), dtype=np.float64)
        soma_pct_uf = np.zeros((U, K))
        soma_votos_uf = np.zeros((U, K))
        lideranca_uf = np.zeros((U, K))
        idx_detalhe = {uf: int(np.where(ufs_unicas == uf)[0][0]) for uf in ufs_detalhe if uf in ufs_unicas}
        amostras_uf = {uf: np.empty((num_simulacoes, K)) for uf in idx_detalhe}
        for ini in range(0, num_simulacoes, self.tamanho_lote_sim):
            m = min(self.tamanho_lote_sim, num_simulacoes - ini)
            props = amostrar_proporcoes_monte_carlo(alphas_post, num_simulacoes=m, rng=self.rng)  # (m, H, K)

            if self.sigma_uf > 0 or self.sigma_nacional > 0:
                log_p = np.log(np.clip(props, 1e-12, None))
                log_p += self.rng.normal(0.0, self.sigma_uf, size=(m, U, K))[:, idx_uf, :]
                log_p += self.rng.normal(0.0, self.sigma_nacional, size=(m, 1, K))
                log_p -= log_p.max(axis=2, keepdims=True)
                np.exp(log_p, out=log_p)
                log_p /= log_p.sum(axis=2, keepdims=True)
                props = log_p

            s = self.sigma_comparecimento
            fator_comp = np.exp(self.rng.normal(-0.5 * s * s, s, size=(m, H))) if s > 0 else 1.0
            votos_rem = votos_rem_esperados[np.newaxis, :] * fator_comp  # (m, H)

            props *= votos_rem[:, :, np.newaxis]                            # votos restantes (m, H, K)
            votos_uf = np.matmul(props.transpose(0, 2, 1), onehot_uf)        # (m, K, U)
            votos_uf += obs_uf.T[np.newaxis, :, :]
            votos_nacionais_simulados[ini:ini + m] = votos_uf.sum(axis=2)

            tot_uf = votos_uf.sum(axis=1, keepdims=True)
            pct_uf = votos_uf / np.where(tot_uf == 0, 1.0, tot_uf)
            soma_pct_uf += pct_uf.sum(axis=0).T
            soma_votos_uf += votos_uf.sum(axis=0).T
            for uf, u in idx_detalhe.items():
                amostras_uf[uf][ini:ini + m] = pct_uf[:, :, u] * 100.0
            lider_sim = pct_uf.argmax(axis=1)                               # (m, U)
            for k in range(K):
                lideranca_uf[:, k] += (lider_sim == k).sum(axis=0)

        total_validos_simulados = votos_nacionais_simulados.sum(axis=1, keepdims=True)
        total_validos_simulados = np.where(total_validos_simulados == 0, 1.0, total_validos_simulados)
        perc_nacionais_simulados = (votos_nacionais_simulados / total_validos_simulados) * 100.0

        # 6. Métricas de Resumo e Estatísticas
        votos_validos_apurados = int(obs_nacional.sum())
        total_validos_proj_medio = int(votos_nacionais_simulados.sum(axis=1).mean())
        perc_secoes_total = (secoes_apuradas / max(1, total_secoes)) * 100.0

        maximo_simulado = perc_nacionais_simulados.max(axis=1)
        if K >= 2:
            segundo_simulado = np.partition(perc_nacionais_simulados, K - 2, axis=1)[:, K - 2]
            prob_top2 = (perc_nacionais_simulados >= segundo_simulado[:, np.newaxis]).mean(axis=0)
        else:
            prob_top2 = np.ones(K)
        prob_segundo_turno = float(np.mean(maximo_simulado <= 50.0)) if self.exige_maioria and K > 1 else 0.0

        projecoes_candidatos: List[ProjecaoCandidato] = []
        for k, cand in enumerate(self.candidatos):
            v_obs_cand = int(obs_nacional[k])
            perc_obs_cand = (v_obs_cand / max(1, votos_validos_apurados)) * 100.0

            cand_samples = perc_nacionais_simulados[:, k]
            outros_indices = [j for j in range(K) if j != k]
            if outros_indices:
                max_outros = np.max(perc_nacionais_simulados[:, outros_indices], axis=1)
                prob_lider = float(np.mean(cand_samples > max_outros))
            else:
                prob_lider = 1.0
            prob_maioria = float(np.mean(cand_samples > 50.0))

            projecoes_candidatos.append(
                ProjecaoCandidato(
                    numero=cand.numero,
                    nome=cand.nome,
                    partido=cand.sigla_partido,
                    cor_hex=cand.cor_hex,
                    votos_apurados=v_obs_cand,
                    perc_apurado=round(perc_obs_cand, 3),
                    media_projetada=int(np.mean(votos_nacionais_simulados[:, k])),
                    perc_projetado=round(float(np.mean(cand_samples)), 3),
                    ic_inferior_95=round(float(np.percentile(cand_samples, 2.5)), 3),
                    ic_superior_95=round(float(np.percentile(cand_samples, 97.5)), 3),
                    prob_vitoria=round(prob_maioria if self.exige_maioria else prob_lider, 4),
                    prob_lideranca=round(prob_lider, 4),
                    **self._dados_cadastrais(cand),
                )
            )

        # Ordena candidatos por projeção percentual decrescente
        projecoes_candidatos.sort(key=lambda c: c.perc_projetado, reverse=True)

        lider_cand = projecoes_candidatos[0]
        segundo_cand = projecoes_candidatos[1] if len(projecoes_candidatos) > 1 else None
        lider_margem = round(lider_cand.perc_projetado - (segundo_cand.perc_projetado if segundo_cand else 0.0), 2)

        # 7. Regra de Chamada (Call Decision)
        status_call = StatusCall.INDEFINIDO
        vencedor_projetado = None

        votos_max_rem = float(votos_rem_maximos.sum())
        lider_obs = lider_cand.votos_apurados
        maior_obs = float(obs_nacional.max())
        if self.exige_maioria:
            # Mesmo que todo voto restante vá para os adversários, o líder mantém > 50%
            eleito_mat = lider_obs > (votos_validos_apurados - lider_obs) + votos_max_rem
            # Ninguém alcança 50% nem recebendo todos os votos restantes
            segundo_turno_mat = K > 1 and 2 * maior_obs + votos_max_rem <= votos_validos_apurados
        else:
            eleito_mat = segundo_cand is not None and lider_obs > segundo_cand.votos_apurados + votos_max_rem
            segundo_turno_mat = False

        # Chamadas estatísticas exigem todas as UFs com dados reais
        pode_projetar = not ufs_sem_dados and perc_secoes_total >= self.perc_minimo_call

        if eleito_mat:
            status_call = StatusCall.MATEMATICAMENTE_ELEITO
            vencedor_projetado = lider_cand.numero
        elif segundo_turno_mat:
            status_call = StatusCall.SEGUNDO_TURNO_PROJETADO
        elif pode_projetar and lider_cand.prob_vitoria >= self.limiar_prob_call:
            status_call = StatusCall.VITORIA_PROJETADA
            vencedor_projetado = lider_cand.numero
        elif pode_projetar and self.exige_maioria and prob_segundo_turno >= self.limiar_prob_call:
            status_call = StatusCall.SEGUNDO_TURNO_PROJETADO

        extras["uf_amostras"] = amostras_uf
        analise = {} if not analise_completa else self._montar_analise(
            snapshots=snapshots,
            estrato_ids=estrato_ids,
            votos_obs=votos_obs,
            votos_rem_esperados=votos_rem_esperados,
            votos_rem_maximos=votos_rem_maximos,
            ufs_unicas=list(ufs_unicas),
            idx_uf=idx_uf,
            media_pct_uf=soma_pct_uf / num_simulacoes * 100.0,
            media_votos_uf=soma_votos_uf / num_simulacoes,
            prob_lider_uf=lideranca_uf / num_simulacoes,
            perc_sim=perc_nacionais_simulados,
            prob_top2=prob_top2,
            projecoes=projecoes_candidatos,
            ufs_sem_dados=ufs_sem_dados,
        )

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
            tempo_computacao_ms=round(tempo_ms, 2),
            prob_segundo_turno=round(prob_segundo_turno, 4),
            ufs_sem_dados=ufs_sem_dados,
            analise=analise,
        ), extras

    # ------------------------------------------------------------------ painel

    def _tipo_estrato(self, eid: str) -> str:
        if eid.endswith("_INTERIOR"):
            return "INTERIOR"
        if "_CID_" in eid:
            return "SUBESTRATO_CIDADES"
        if "_SUB_" in eid:
            return "SUBESTRATO"
        if eid.endswith("_TOTAL"):
            return "UF_INTEIRA"
        if eid.endswith("_SEM_DADOS"):
            return "SEM_DADOS"
        meta = self.estratos.get(eid)
        if meta is not None and meta.tipo == TipoEstrato.CAPITAL:
            return "CAPITAL"
        return "GRANDE_CIDADE"

    def _nome_estrato(self, eid: str) -> str:
        if eid in self.nomes_estratos:
            return self.nomes_estratos[eid]
        uf, _, resto = eid.partition("_")
        if resto == "INTERIOR":
            return f"Interior {uf}"
        if resto in ("TOTAL", "SEM_DADOS"):
            return uf
        if resto.startswith("CID_"):
            return f"Cidades {resto[4:].title()} ({uf})"
        if resto.startswith("SUB_"):
            return f"Interior {resto[4:].title()} ({uf})"
        return f"{uf} {resto}"

    @staticmethod
    def _histograma(amostras: np.ndarray, passo: float, minimo: float, maximo: float) -> Dict[str, Any]:
        lo = np.floor(minimo / passo) * passo
        hi = np.ceil(maximo / passo) * passo + passo
        bordas = np.arange(lo, hi + passo / 2, passo)
        contagem, _ = np.histogram(amostras, bins=bordas)
        return {"inicio": round(float(lo), 4), "passo": passo, "freq": (contagem / max(1, len(amostras))).round(5).tolist()}

    def _montar_analise(
        self, snapshots, estrato_ids, votos_obs, votos_rem_esperados, votos_rem_maximos,
        ufs_unicas, idx_uf, media_pct_uf, media_votos_uf, prob_lider_uf, perc_sim, prob_top2,
        projecoes, ufs_sem_dados,
    ) -> Dict[str, Any]:
        """Monta os dados do painel: números reais, projeções por UF/região/estrato e distribuições."""
        nums = [c.numero for c in self.candidatos]
        campos = ("secoes_total", "secoes_apuradas", "eleitores_aptos", "comparecimento", "abstencao",
                  "votos_validos", "votos_brancos", "votos_nulos", "votos_anulados")

        def vazio():
            return {c: 0 for c in campos}

        def votos_dict(vetor):
            return {n: int(round(v)) for n, v in zip(nums, vetor)}

        # Estratos (a heurística: capitais, grandes cidades e interior remanescente)
        estratos = []
        por_uf: Dict[str, Dict[str, int]] = {}
        por_tipo: Dict[str, Dict[str, Any]] = {}
        for h, eid in enumerate(estrato_ids):
            snap = snapshots[eid]
            uf = eid.split("_")[0]
            tipo = self._tipo_estrato(eid)
            reais = {c: int(getattr(snap, c)) for c in campos}
            estratos.append({
                "id": eid, "uf": uf, "tipo": tipo, "nome": self._nome_estrato(eid),
                **reais,
                "votos": votos_dict(votos_obs[h]),
                "restantes_esperados": int(votos_rem_esperados[h]),
            })
            alvo = por_uf.setdefault(uf, vazio())
            agg_tipo = por_tipo.setdefault(tipo, {**vazio(), "votos": np.zeros(len(nums)), "restantes_esperados": 0.0})
            for c in campos:
                alvo[c] += reais[c]
                agg_tipo[c] += reais[c]
            agg_tipo["votos"] += votos_obs[h]
            agg_tipo["restantes_esperados"] += votos_rem_esperados[h]

        rem_uf = np.zeros(len(ufs_unicas))
        rem_max_uf = np.zeros(len(ufs_unicas))
        np.add.at(rem_uf, idx_uf, votos_rem_esperados)
        np.add.at(rem_max_uf, idx_uf, votos_rem_maximos)
        obs_uf = np.zeros((len(ufs_unicas), len(nums)))
        np.add.at(obs_uf, idx_uf, votos_obs)

        ufs = []
        regioes: Dict[str, Dict[str, Any]] = {}
        for u, uf in enumerate(ufs_unicas):
            reais = por_uf[uf]
            regiao = REGIAO_POR_UF.get(uf, "Outros")
            ufs.append({
                "uf": uf, "regiao": regiao, "sem_dados": uf in ufs_sem_dados,
                **reais,
                "votos": votos_dict(obs_uf[u]),
                "proj_pct": {n: round(float(v), 2) for n, v in zip(nums, media_pct_uf[u])},
                "prob_lider": {n: round(float(v), 4) for n, v in zip(nums, prob_lider_uf[u])},
                "restantes_esperados": int(rem_uf[u]),
            })
            r = regioes.setdefault(regiao, {**vazio(), "votos": np.zeros(len(nums)), "proj_votos": np.zeros(len(nums)), "restantes_esperados": 0.0})
            for c in campos:
                r[c] += reais[c]
            r["votos"] += obs_uf[u]
            r["proj_votos"] += media_votos_uf[u]
            r["restantes_esperados"] += rem_uf[u]

        def finalizar(d: Dict[str, Any]) -> Dict[str, Any]:
            out = {c: int(d[c]) for c in campos}
            out["votos"] = votos_dict(d["votos"])
            out["restantes_esperados"] = int(d["restantes_esperados"])
            if "proj_votos" in d:
                tot = d["proj_votos"].sum()
                out["proj_pct"] = {n: round(float(v / tot * 100.0), 2) if tot > 0 else 0.0 for n, v in zip(nums, d["proj_votos"])}
            return out

        # Nacional (números reais apurados) — exclui estratos sintéticos sem dados
        nac = vazio()
        for e in estratos:
            if e["tipo"] != "SEM_DADOS":
                for c in campos:
                    nac[c] += e[c]
        comp = nac["comparecimento"]
        nacional = {
            **nac,
            "pct_secoes": round(nac["secoes_apuradas"] / max(1, nac["secoes_total"]) * 100.0, 2),
            "pct_comparecimento": round(comp / max(1, comp + nac["abstencao"]) * 100.0, 2),
            "pct_abstencao": round(nac["abstencao"] / max(1, comp + nac["abstencao"]) * 100.0, 2),
            "pct_brancos": round(nac["votos_brancos"] / max(1, comp) * 100.0, 2),
            "pct_nulos": round(nac["votos_nulos"] / max(1, comp) * 100.0, 2),
            "pct_validos": round(nac["votos_validos"] / max(1, comp) * 100.0, 2),
            "pct_anulados": round(nac["votos_anulados"] / max(1, comp) * 100.0, 2),
        }

        # O que falta
        T = float(votos_obs.sum())
        R = float(votos_rem_esperados.sum())
        faltam: Dict[str, Any] = {
            "validos_restantes_esperados": int(R),
            "votos_restantes_maximos": int(votos_rem_maximos.sum()),
            "validos_finais_esperados": int(T + R),
        }
        if projecoes:
            lider = projecoes[0]
            L = float(lider.votos_apurados)
            faltam["lider"] = lider.numero
            faltam["lider_precisa_pct_restantes"] = round((0.5 * (T + R) - L) / R * 100.0, 2) if R > 0 else None
            if len(projecoes) > 1:
                seg = projecoes[1]
                S = float(seg.votos_apurados)
                faltam["segundo"] = seg.numero
                faltam["diferenca_votos_apurados"] = int(L - S)
                faltam["segundo_precisa_vantagem_pp_restantes"] = round((L - S) / R * 100.0, 2) if R > 0 else None

        # Distribuições simuladas do % final: os 2 primeiros e quem tiver chance real de ir ao 2º turno
        distribuicoes = {}
        idx_por_num = {c.numero: k for k, c in enumerate(self.candidatos)}
        topo = [p.numero for p in projecoes[:2]] + [
            p.numero for p in projecoes[2:] if prob_top2[idx_por_num[p.numero]] >= 0.01
        ]
        topo = topo[:4]
        for n in topo:
            amostras = perc_sim[:, idx_por_num[n]]
            lo, hi = float(amostras.min()), float(amostras.max())
            passo = max(0.01, round((hi - lo) / 40.0, 3))
            distribuicoes[n] = self._histograma(amostras, passo, lo, hi)
        margem = None
        if len(topo) >= 2:
            dif = perc_sim[:, idx_por_num[topo[0]]] - perc_sim[:, idx_por_num[topo[1]]]
            passo = max(0.01, round((float(dif.max()) - float(dif.min())) / 50.0, 3))
            margem = {**self._histograma(dif, passo, float(dif.min()), float(dif.max())),
                      "lider": topo[0], "segundo": topo[1],
                      "prob_positiva": round(float((dif > 0).mean()), 4)}

        return {
            "nacional": nacional,
            "faltam": faltam,
            "prob_top2": {c.numero: round(float(prob_top2[k]), 4) for k, c in enumerate(self.candidatos)},
            "ufs": ufs,
            "regioes": [{"regiao": nome, **finalizar(d)} for nome, d in sorted(regioes.items())],
            "tipos_estrato": [{"tipo": t, **finalizar(d)} for t, d in sorted(por_tipo.items())],
            "estratos": estratos,
            "distribuicao_final": distribuicoes,
            "distribuicao_margem": margem,
        }

    @staticmethod
    def _dados_cadastrais(cand: Candidato) -> Dict[str, str]:
        return {
            "vice": cand.vice,
            "coligacao": cand.coligacao,
            "composicao": cand.composicao,
            "nome_completo": cand.nome_completo,
        }

    def _resultado_aguardando(self, ciclo_id, snapshots, total_secoes, total_eleitores, ufs_sem_dados) -> ResultadoProjecao:
        candidatos = [
            ProjecaoCandidato(
                numero=c.numero, nome=c.nome, partido=c.sigla_partido, cor_hex=c.cor_hex,
                votos_apurados=0, perc_apurado=0.0, media_projetada=0, perc_projetado=0.0,
                ic_inferior_95=0.0, ic_superior_95=0.0, prob_vitoria=0.0,
                **self._dados_cadastrais(c),
            )
            for c in sorted(self.candidatos, key=lambda c: c.nome)
        ]
        reais = [s for eid, s in snapshots.items() if not eid.endswith("_SEM_DADOS")]
        nacional = {
            "secoes_total": sum(s.secoes_total for s in reais),
            "secoes_apuradas": sum(s.secoes_apuradas for s in reais),
            "eleitores_aptos": sum(s.eleitores_aptos for s in reais),
        }
        return ResultadoProjecao(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            ciclo_id=ciclo_id,
            total_secoes=total_secoes,
            secoes_apuradas=nacional["secoes_apuradas"],
            perc_secoes_apuradas=0.0,
            total_eleitores=total_eleitores,
            total_validos_apurados=0,
            total_validos_projetados=0,
            candidatos=candidatos,
            status_call=StatusCall.INDEFINIDO,
            vencedor_projetado=None,
            lider_margem=0.0,
            tempo_computacao_ms=0.0,
            ufs_sem_dados=ufs_sem_dados,
            analise={"aguardando": True, "nacional": nacional},
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

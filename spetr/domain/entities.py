"""
Entidades puras do domínio do SPETR.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from spetr.domain.value_objects import StatusCall, TipoEstrato


@dataclass(frozen=True)
class Candidato:
    numero: str
    nome: str
    sigla_partido: str
    cor_hex: str = "#2563EB"
    vice: str = ""
    coligacao: str = ""
    composicao: str = ""
    nome_completo: str = ""


@dataclass(frozen=True)
class EstratoEleitoral:
    id: str                                  # ex: "PB_INTERIOR", "PB_20516" (João Pessoa)
    uf: str                                  # ex: "PB"
    nome: str                                # ex: "Paraíba - Interior Remanescente"
    eleitores_aptos: int
    secoes_totais: int
    tipo: TipoEstrato
    prior_alpha: Dict[str, float] = field(default_factory=dict) # {num_cand: alpha}
    peso_nacional: float = 0.0

    @property
    def eleitores_por_secao(self) -> float:
        if self.secoes_totais <= 0:
            return 0.0
        return self.eleitores_aptos / self.secoes_totais


@dataclass(frozen=True)
class SnapshotParcial:
    estrato_id: str
    timestamp: str
    secoes_total: int
    secoes_apuradas: int
    eleitores_aptos: int
    comparecimento: int
    abstencao: int
    votos_validos: int
    votos_brancos: int
    votos_nulos: int
    votos_candidatos: Dict[str, int]         # {num_cand: votos_nominais}
    votos_anulados: int = 0                  # votos de candidatos com destinação "Anulado"/"sub judice"

    @property
    def perc_secoes_apuradas(self) -> float:
        if self.secoes_total <= 0:
            return 0.0
        return min(100.0, (self.secoes_apuradas / self.secoes_total) * 100.0)

    @property
    def secoes_faltantes(self) -> int:
        return max(0, self.secoes_total - self.secoes_apuradas)

    @property
    def taxa_comparecimento(self) -> float:
        total = self.comparecimento + self.abstencao
        if total <= 0:
            return 0.795  # média histórica brasileira padrão (~79.5%)
        return self.comparecimento / total


@dataclass(frozen=True)
class ProjecaoCandidato:
    numero: str
    nome: str
    partido: str
    cor_hex: str
    votos_apurados: int
    perc_apurado: float                      # % apurado no momento (sobre votos válidos)
    media_projetada: int                     # Votos válidos esperados no final
    perc_projetado: float                    # % final esperado (E[p])
    ic_inferior_95: float                    # Percentil 2.5%
    ic_superior_95: float                    # Percentil 97.5%
    prob_vitoria: float                      # P(eleito): P(p > 50% dos válidos) quando exige maioria absoluta
    prob_lideranca: float = 0.0              # P(terminar em 1º lugar)
    vice: str = ""
    coligacao: str = ""
    composicao: str = ""
    nome_completo: str = ""


@dataclass(frozen=True)
class ResultadoProjecao:
    timestamp: str
    ciclo_id: int
    total_secoes: int
    secoes_apuradas: int
    perc_secoes_apuradas: float
    total_eleitores: int
    total_validos_apurados: int
    total_validos_projetados: int
    candidatos: List[ProjecaoCandidato]
    status_call: StatusCall
    vencedor_projetado: Optional[str]
    lider_margem: float                      # Diferença percentual projetada entre 1º e 2º
    tempo_computacao_ms: float
    prob_segundo_turno: float = 0.0          # P(ninguém atingir maioria absoluta)
    ufs_sem_dados: List[str] = field(default_factory=list)  # UFs projetadas só pelo prior
    analise: Dict[str, Any] = field(default_factory=dict)   # painel: nacional, UFs, regiões, estratos, distribuições

"""
Atualização Bayesiana Conjugada Dirichlet-Multinomial.
Otimizado com NumPy para execução em sub-milissegundos.
"""
from typing import Dict, List, Tuple
import numpy as np


def calcular_parametros_posteriores(
    prior_alphas: np.ndarray,      # shape: (H, K)
    votos_observados: np.ndarray    # shape: (H, K)
) -> np.ndarray:
    """
    Atualiza os hiperparâmetros da distribuição de Dirichlet:
    alpha_post = alpha_prior + y_obs
    """
    return prior_alphas + votos_observados


def limitar_concentracao(alphas: np.ndarray, concentracao_max: float) -> np.ndarray:
    """
    Reescala cada linha para que sum_k alpha_{h,k} <= concentracao_max, preservando a média.
    Modela sobredispersão: as urnas restantes não são amostra aleatória das já apuradas.
    """
    if concentracao_max is None or concentracao_max <= 0:
        return alphas
    soma = alphas.sum(axis=1, keepdims=True)
    fator = np.minimum(1.0, concentracao_max / np.where(soma == 0, 1.0, soma))
    return np.maximum(alphas * fator, 1e-3)


def amostrar_proporcoes_monte_carlo(
    alphas_post: np.ndarray,        # shape: (H, K)
    num_simulacoes: int = 10000,
    rng: np.random.Generator = None
) -> np.ndarray:
    """
    Gera amostras de proporções de voto p_h ~ Dirichlet(alpha_post).
    Para K=2 candidatos, usa a distribuição Beta vetorizada (muito mais rápida).
    Retorna array de shape: (num_simulacoes, H, K)
    """
    if rng is None:
        rng = np.random.default_rng()

    H, K = alphas_post.shape

    if K == 2:
        # Vetorizado via Beta: p_A ~ Beta(a1, a2), p_B = 1 - p_A
        # shape de saída do beta: (num_simulacoes, H)
        a = alphas_post[:, 0]
        b = alphas_post[:, 1]
        p_A = rng.beta(a, b, size=(num_simulacoes, H))
        p_B = 1.0 - p_A

        # Empilha em (num_simulacoes, H, 2)
        amostras = np.stack([p_A, p_B], axis=2)
        return amostras
    else:
        # Caso geral K > 2: Amostragem via variáveis Gamma
        # X_{h,k} ~ Gamma(alpha_{h,k}, 1), p_{h,k} = X_{h,k} / sum_k X_{h,k}
        gamma_samples = rng.gamma(alphas_post, scale=1.0, size=(num_simulacoes, H, K))
        soma = gamma_samples.sum(axis=2, keepdims=True)
        # Evita divisão por zero
        soma = np.where(soma == 0, 1e-9, soma)
        return gamma_samples / soma

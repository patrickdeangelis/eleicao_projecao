"""
Testes unitários para o agregador de subtração vetorial.
Validação empírica do caso Paraíba:
Interior(PB) = Total(PB) - João Pessoa(20516) - Campina Grande(19852).
"""
import pytest
from spetr.aggregator.vector_subtraction import VectorAggregator


def test_subtracao_vetorial_caso_paraiba():
    cidades_map = {
        "PB": ["20516", "19852"]  # JP e CG
    }
    aggregator = VectorAggregator(cidades_100k_map=cidades_map)

    # Payloads mockados no formato TSE simplificado
    dados_brutos = {
        # Total PB: 10.000 seções, 1.000.000 válidos apurados (Lula: 650k, Bolso: 350k)
        "UF_PB": {
            "s": "10000", "st": "5000", "e": "3000000", "c": "2400000", "a": "600000",
            "vvc": "1000000", "vb": "50000", "vn": "50000",
            "cand": [
                {"n": "13", "vap": "650000", "pvap": "65,00"},
                {"n": "22", "vap": "350000", "pvap": "35,00"}
            ]
        },
        # João Pessoa (20516): 2.000 seções, 200.000 válidos apurados (Lula: 108k [54%], Bolso: 92k [46%])
        "MUN_PB_20516": {
            "s": "2000", "st": "1000", "e": "560000", "c": "450000", "a": "110000",
            "vvc": "200000", "vb": "10000", "vn": "10000",
            "cand": [
                {"n": "13", "vap": "108000", "pvap": "54,00"},
                {"n": "22", "vap": "92000", "pvap": "46,00"}
            ]
        },
        # Campina Grande (19852): 1.000 seções, 100.000 válidos apurados (Lula: 48.5k [48.5%], Bolso: 51.5k [51.5%])
        "MUN_PB_19852": {
            "s": "1000", "st": "500", "e": "290000", "c": "230000", "a": "60000",
            "vvc": "100000", "vb": "5000", "vn": "5000",
            "cand": [
                {"n": "13", "vap": "48500", "pvap": "48,50"},
                {"n": "22", "vap": "51500", "pvap": "51,50"}
            ]
        }
    }

    snapshots = aggregator.processar_lote_bruto(dados_brutos)

    # Deve gerar 3 estratos: JP, CG e o Interior Remanescente
    assert "PB_20516" in snapshots
    assert "PB_19852" in snapshots
    assert "PB_INTERIOR" in snapshots

    jp = snapshots["PB_20516"]
    cg = snapshots["PB_19852"]
    interior = snapshots["PB_INTERIOR"]

    # Verificações de João Pessoa
    assert jp.secoes_total == 2000
    assert jp.secoes_apuradas == 1000
    assert jp.votos_candidatos["13"] == 108000
    assert jp.votos_candidatos["22"] == 92000

    # Verificações de Campina Grande
    assert cg.secoes_total == 1000
    assert cg.secoes_apuradas == 500
    assert cg.votos_candidatos["13"] == 48500
    assert cg.votos_candidatos["22"] == 51500

    # Verificações do Interior Remanescente
    # Seções totais = 10.000 - (2.000 + 1.000) = 7.000
    assert interior.secoes_total == 7000
    # Seções apuradas = 5.000 - (1.000 + 500) = 3.500
    assert interior.secoes_apuradas == 3500
    # Eleitores aptos = 3.000.000 - (560.000 + 290.000) = 2.150.000
    assert interior.eleitores_aptos == 2150000
    # Votos válidos = 1.000.000 - (200.000 + 100.000) = 700.000
    assert interior.votos_validos == 700000

    # Votos Lula no interior = 650.000 - (108.000 + 48.500) = 493.500 (70.5%)
    assert interior.votos_candidatos["13"] == 493500
    # Votos Bolsonaro no interior = 350.000 - (92.000 + 51.500) = 206.500 (29.5%)
    assert interior.votos_candidatos["22"] == 206500

    # Validação do paradoxo estatístico comprovado:
    pct_lula_jp = jp.votos_candidatos["13"] / jp.votos_validos
    pct_lula_cg = cg.votos_candidatos["13"] / cg.votos_validos
    pct_lula_interior = interior.votos_candidatos["13"] / interior.votos_validos

    assert pct_lula_cg < 0.50  # Bolsonaro venceu em Campina Grande
    assert pct_lula_jp > 0.53  # Lula venceu em João Pessoa
    assert pct_lula_interior > 0.70  # Lula venceu massivamente no Sertão/Interior

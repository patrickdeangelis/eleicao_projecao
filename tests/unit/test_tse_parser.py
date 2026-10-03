"""
Testes unitários para o parser de JSON do TSE.
"""
import pytest
from spetr.collector.parser import parse_float_br, parse_int_br, parse_tse_json


def test_parse_float_br():
    assert parse_float_br("50,12") == 50.12
    assert parse_float_br("0,05") == 0.05
    assert parse_float_br("1.250,50") == 1250.50
    assert parse_float_br(48.5) == 48.5
    assert parse_float_br(None) == 0.0
    assert parse_float_br("") == 0.0


def test_parse_int_br():
    assert parse_int_br("1.250.400") == 1250400
    assert parse_int_br("350") == 350
    assert parse_int_br(1000) == 1000
    assert parse_int_br(None) == 0
    assert parse_int_br("") == 0


def test_parse_tse_json_payload():
    mock_payload = {
        "dg": "30/10/2022",
        "hg": "17:15:00",
        "s": "10.000",
        "st": "2.500",
        "pst": "25,00",
        "e": "3.000.000",
        "c": "2.400.000",
        "a": "600.000",
        "vvc": "2.200.000",
        "vb": "100.000",
        "vn": "100.000",
        "cand": [
            {
                "n": "13",
                "nm": "Lula",
                "cc": "PT",
                "vap": "1.200.000",
                "pvap": "54,55",
                "st": "2º turno"
            },
            {
                "n": "22",
                "nm": "Bolsonaro",
                "cc": "PL",
                "vap": "1.000.000",
                "pvap": "45,45",
                "st": "2º turno"
            }
        ]
    }

    parsed = parse_tse_json(mock_payload, uf="PB")

    assert parsed["uf"] == "PB"
    assert parsed["secoes_total"] == 10000
    assert parsed["secoes_apuradas"] == 2500
    assert parsed["pst"] == 25.0
    assert parsed["votos_validos"] == 2200000
    assert parsed["candidatos_votos"]["13"] == 1200000
    assert parsed["candidatos_votos"]["22"] == 1000000
    assert parsed["candidatos_meta"]["13"]["nome"] == "Lula"

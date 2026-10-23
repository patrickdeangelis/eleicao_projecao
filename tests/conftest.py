"""Fixtures compartilhadas dos testes."""
import gzip
import json

import pytest

# (UF, código TSE da cidade grande, fração de votos do 13): cidades que estão em spetr/data/cidades_100k.json
_UFS_FIXTURE = (("SP", "71072", 0.45), ("BA", "38490", 0.62))
_PASSOS = 6


@pytest.fixture
def replay_sintetico(tmp_path, monkeypatch):
    """
    Replay minúsculo (SP e BA: uma cidade grande e dois municípios de interior em cada) gravado numa
    pasta temporária, no formato de scripts/preparar_replay.py. Permite testar sessão, coleta e pipeline
    sem rede e sem os boletins reais. Retorna o nome da fonte ("2026_1t").
    """
    municipios, eventos = [], []
    for uf, cidade, p13 in _UFS_FIXTURE:
        for cod, nome, secoes in ((cidade, "CIDADE GRANDE", 60), ("90001", "INTERIOR A", 24), ("90002", "INTERIOR B", 30)):
            indice = len(municipios)
            municipios.append([uf, cod, nome, secoes, secoes * 400])
            por_passo = secoes // _PASSOS
            for passo in range(_PASSOS):
                s = por_passo + (secoes - por_passo * _PASSOS if passo == _PASSOS - 1 else 0)
                validos = 312 * s
                v13 = round(validos * (p13 + (0.02 if cod == "90001" else 0.0)))
                eventos.append([passo * 10, indice, s, 400 * s, 320 * s, 80 * s, 3 * s, 5 * s, v13, validos - v13])
    dados = {
        "versao": 1, "ano": "2026", "turno": 1, "cargo": 1, "eleicao": "6257", "t0": "2026-10-04 16:50",
        "candidatos": [{"n": "13", "nm": "CANDIDATO A", "partido": "PA"}, {"n": "22", "nm": "CANDIDATO B", "partido": "PB"}],
        "municipios": municipios, "eventos": sorted(eventos),
    }
    with gzip.open(tmp_path / "2026_1t.json.gz", "wt", encoding="utf-8") as f:
        json.dump(dados, f)
    monkeypatch.setattr("spetr.simulador.replay.pasta_replays", lambda: str(tmp_path))
    return "2026_1t"

"""
Parser de payloads JSON oficiais do TSE.
Trata conversões numéricas brasileiras (vírgula decimal) e campos nulos/omissos.
"""
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger("spetr.collector.parser")


def parse_float_br(val: Any) -> float:
    """Converte '50,12' ou 50.12 para float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_int_br(val: Any) -> int:
    """Converte '1.250' ou '1250' ou 1250 para int."""
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val).strip().replace(".", "").replace(",", "")
    try:
        return int(s)
    except ValueError:
        return 0


def parse_tse_json(raw: Dict[str, Any], uf: str, cod_mun: Optional[str] = None) -> Dict[str, Any]:
    """
    Normaliza a estrutura bruta de um arquivo dados-simplificados do TSE.
    """
    secoes_total = parse_int_br(raw.get("s", 0))
    secoes_apuradas = parse_int_br(raw.get("st", 0))
    eleitores = parse_int_br(raw.get("e", 0))
    comparecimento = parse_int_br(raw.get("c", 0))
    abstencao = parse_int_br(raw.get("a", 0))
    votos_validos = parse_int_br(raw.get("vvc", raw.get("vv", 0)))
    votos_brancos = parse_int_br(raw.get("vb", 0))
    votos_nulos = parse_int_br(raw.get("vn", 0))
    pst = parse_float_br(raw.get("pst", 0.0))

    # Parsing dos candidatos
    candidatos = {}
    candidatos_meta = {}
    for c in raw.get("cand", []):
        numero = str(c.get("n", "")).strip()
        if not numero:
            continue
        votos = parse_int_br(c.get("vap", 0))
        pvap = parse_float_br(c.get("pvap", 0.0))
        nome = str(c.get("nm", c.get("nmu", numero))).strip()
        partido = str(c.get("cc", c.get("p", ""))).split("-")[0].strip()
        status = str(c.get("st", "")).strip()

        candidatos[numero] = votos
        candidatos_meta[numero] = {
            "nome": nome,
            "partido": partido,
            "votos": votos,
            "pvap": pvap,
            "status": status,
        }

    return {
        "uf": uf.upper(),
        "cod_mun": cod_mun,
        "timestamp_tse": f"{raw.get('dg', '')} {raw.get('hg', '')}".strip(),
        "secoes_total": secoes_total,
        "secoes_apuradas": secoes_apuradas,
        "pst": pst,
        "eleitores": eleitores,
        "comparecimento": comparecimento,
        "abstencao": abstencao,
        "votos_validos": votos_validos,
        "votos_brancos": votos_brancos,
        "votos_nulos": votos_nulos,
        "candidatos_votos": candidatos,
        "candidatos_meta": candidatos_meta,
    }

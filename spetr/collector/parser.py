"""
Parser universal de payloads JSON oficiais do TSE.
Compatível tanto com o formato plano de 'Dados Simplificados' (-r.json)
quanto com o novo formato 'Resultado Unificado' / EA20 (-u.json).
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
    Normaliza qualquer formato JSON oficial do TSE (Dados Simplificados ou EA20 Unificado).
    """
    if not isinstance(raw, dict):
        return {}

    # 1. Parsing de Seções (compatível com chave flat 's'/'st' ou dict EA20 's': {'ts', 'st'})
    s_raw = raw.get("s", 0)
    if isinstance(s_raw, dict):
        secoes_total = parse_int_br(s_raw.get("ts", s_raw.get("s", 0)))
        secoes_apuradas = parse_int_br(s_raw.get("st", 0))
        pst = parse_float_br(s_raw.get("pst", 0.0))
    else:
        secoes_total = parse_int_br(s_raw)
        secoes_apuradas = parse_int_br(raw.get("st", 0))
        pst = parse_float_br(raw.get("pst", 0.0))

    # 2. Parsing de Eleitorado e Comparecimento (compatível com flat ou dict EA20 'e': {'te', 'c', 'a'})
    e_raw = raw.get("e", 0)
    if isinstance(e_raw, dict):
        eleitores = parse_int_br(e_raw.get("te", e_raw.get("e", 0)))
        comparecimento = parse_int_br(e_raw.get("c", 0))
        abstencao = parse_int_br(e_raw.get("a", 0))
    else:
        eleitores = parse_int_br(e_raw)
        comparecimento = parse_int_br(raw.get("c", 0))
        abstencao = parse_int_br(raw.get("a", 0))

    # 3. Parsing de Votos Válidos, Brancos e Nulos (compatível com flat ou dict EA20 'v': {'vvc', 'vb', 'vn'})
    v_raw = raw.get("v")
    if isinstance(v_raw, dict):
        votos_validos = parse_int_br(v_raw.get("vvc", v_raw.get("vv", 0)))
        votos_brancos = parse_int_br(v_raw.get("vb", 0))
        votos_nulos = parse_int_br(v_raw.get("vn", v_raw.get("tvn", 0)))
    else:
        votos_validos = parse_int_br(raw.get("vvc", raw.get("vv", 0)))
        votos_brancos = parse_int_br(raw.get("vb", 0))
        votos_nulos = parse_int_br(raw.get("vn", 0))

    # 4. Parsing de Candidatos (compatível com flat 'cand' ou hierárquico EA20 carg -> agr -> par -> cand)
    candidatos = {}
    candidatos_meta = {}

    def registrar_candidato(c: Dict[str, Any], default_partido: str = ""):
        numero = str(c.get("n", "")).strip()
        if not numero:
            return
        votos = parse_int_br(c.get("vap", 0))
        pvap = parse_float_br(c.get("pvap", 0.0))
        nome = str(c.get("nm", c.get("nmu", numero))).strip()
        partido = str(c.get("sgp", c.get("cc", c.get("p", default_partido)))).split("-")[0].strip()
        status = str(c.get("st", "")).strip()

        candidatos[numero] = votos
        candidatos_meta[numero] = {
            "nome": nome,
            "partido": partido,
            "votos": votos,
            "pvap": pvap,
            "status": status,
        }

    # Formato A: lista direta na raiz 'cand'
    if "cand" in raw and isinstance(raw["cand"], list):
        for c in raw["cand"]:
            registrar_candidato(c)

    # Formato B: aninhado no padrão unificado EA20 'carg'
    elif "carg" in raw and isinstance(raw["carg"], list):
        for cargo in raw["carg"]:
            # agr = coligações / federações
            for agr in cargo.get("agr", []):
                for par in agr.get("par", []):
                    sg_partido = par.get("sg", "")
                    for c in par.get("cand", []):
                        registrar_candidato(c, default_partido=sg_partido)

    # Timestamp de geração
    dg = raw.get("dg", "")
    hg = raw.get("hg", "")
    timestamp_tse = f"{dg} {hg}".strip()

    return {
        "uf": uf.upper(),
        "cod_mun": cod_mun,
        "timestamp_tse": timestamp_tse,
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

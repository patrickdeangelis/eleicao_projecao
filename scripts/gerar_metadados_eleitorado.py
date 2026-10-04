"""
Gera os metadados de estratificação do SPETR a partir de dados oficiais do TSE:

- Eleitorado por local de votação (dados abertos):
  https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_{ANO}.zip
  -> eleitores e seções por município e por UF
- Arquivo de configuração de municípios (EA12), ex.: docs/tse_oficial/mun-e021270-cm.json
  -> nomes e capitais (flag "c": "s")

Saídas em spetr/data/:
- ufs_metadados.json   {uf: {nome, capital_cod, capital_nome, eleitores, secoes}}
- cidades_100k.json    {uf: [cod_tse, ...]}  municípios com eleitorado >= limiar (capitais sempre incluídas)
- municipios_meta.json {"UF_COD": {nome, eleitores, secoes}} dos municípios estratificados

Uso:
    python scripts/gerar_metadados_eleitorado.py <pasta_ou_csv_BRASIL> [--config-mun docs/tse_oficial/mun-e021270-cm.json] [--limiar 100000]
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "spetr" / "data"

NOMES_UF = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
    "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins", "ZZ": "Exterior",
}


def localizar_csvs(origem: Path):
    if origem.is_file():
        return [origem]
    brasil = sorted(origem.glob("*_BRASIL.csv"))
    if brasil:
        return brasil
    return sorted(p for p in origem.glob("*.csv"))


def agregar(csvs):
    """Soma eleitores (QT_ELEITOR_ELEICAO_FEDERAL) e conta seções principais por município."""
    mun = defaultdict(lambda: {"eleitores": 0, "secoes": 0, "nome": ""})
    for caminho in csvs:
        with open(caminho, encoding="latin-1", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row.get("DS_SITU_SECAO", "ATIVO").strip().upper() != "ATIVO":
                    continue
                chave = (row["SG_UF"].strip().upper(), row["CD_MUNICIPIO"].strip().zfill(5))
                m = mun[chave]
                m["nome"] = row["NM_MUNICIPIO"].strip()
                m["eleitores"] += int(row["QT_ELEITOR_ELEICAO_FEDERAL"] or 0)
                # Seções agregadas são apuradas junto com a principal: não contam como seção própria
                if row.get("CD_TIPO_SECAO_AGREGADA", "1").strip() == "1":
                    m["secoes"] += 1
    return mun


def carregar_capitais(config_mun: Path):
    with open(config_mun, encoding="utf-8") as f:
        cfg = json.load(f)
    capitais, nomes = {}, {}
    for abr in cfg.get("abr", []):
        uf = abr["cd"].upper()
        for mu in abr.get("mu", []):
            nomes[(uf, mu["cd"])] = mu["nm"]
            if mu.get("c") == "s":
                capitais[uf] = mu["cd"]
    return capitais, nomes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("origem", type=Path, help="Pasta extraída do zip do TSE ou o CSV _BRASIL")
    ap.add_argument("--config-mun", type=Path, default=Path("docs/tse_oficial/mun-e021270-cm.json"))
    ap.add_argument("--limiar", type=int, default=100_000)
    args = ap.parse_args()

    csvs = localizar_csvs(args.origem)
    if not csvs:
        sys.exit(f"Nenhum CSV encontrado em {args.origem}")
    mun = agregar(csvs)
    capitais, nomes_cfg = carregar_capitais(args.config_mun)

    ufs = defaultdict(lambda: {"eleitores": 0, "secoes": 0})
    for (uf, _), m in mun.items():
        ufs[uf]["eleitores"] += m["eleitores"]
        ufs[uf]["secoes"] += m["secoes"]

    ufs_meta, cidades, mun_meta = {}, {}, {}
    for uf in sorted(ufs):
        d = {"nome": NOMES_UF.get(uf, uf), "eleitores": ufs[uf]["eleitores"], "secoes": ufs[uf]["secoes"]}
        cap = capitais.get(uf)
        if cap:
            d["capital_cod"] = cap
            d["capital_nome"] = mun.get((uf, cap), {}).get("nome") or nomes_cfg.get((uf, cap), "")
        ufs_meta[uf] = d

        selecionadas = [
            cod for (u, cod), m in mun.items()
            if u == uf and uf != "ZZ" and (m["eleitores"] >= args.limiar or cod == cap)
        ]
        selecionadas.sort(key=lambda cod: -mun[(uf, cod)]["eleitores"])
        if selecionadas:
            cidades[uf] = selecionadas
            for cod in selecionadas:
                m = mun[(uf, cod)]
                mun_meta[f"{uf}_{cod}"] = {"nome": m["nome"], "eleitores": m["eleitores"], "secoes": m["secoes"]}

    for nome, conteudo in (
        ("ufs_metadados.json", ufs_meta),
        ("cidades_100k.json", cidades),
        ("municipios_meta.json", mun_meta),
    ):
        with open(DATA_DIR / nome, "w", encoding="utf-8") as f:
            json.dump(conteudo, f, ensure_ascii=False, indent=1)

    total = sum(d["eleitores"] for d in ufs_meta.values())
    n_cid = sum(len(v) for v in cidades.values())
    print(f"Eleitorado total: {total:,} | seções: {sum(d['secoes'] for d in ufs_meta.values()):,}")
    print(f"Municípios estratificados: {n_cid} (limiar {args.limiar:,} eleitores + capitais)")


if __name__ == "__main__":
    main()

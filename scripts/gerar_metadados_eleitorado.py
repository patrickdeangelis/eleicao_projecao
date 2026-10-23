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


# Exterior: o TSE trata cada cidade com seção eleitoral no exterior como um "município" da UF ZZ,
# sem informar o país. País e continente de cada uma (nomes como no TSE):
_PAISES = {
    "África": {
        "Costa do Marfim": ["ABIDJÃ"], "Nigéria": ["ABUJA", "LAGOS"], "Gana": ["ACCRA"], "Etiópia": ["ADIS ABEBA"],
        "Argélia": ["ARGEL"], "Mali": ["BAMAKO"], "Guiné-Bissau": ["BISSAU"], "República do Congo": ["BRAZZAVILLE"],
        "Egito": ["CAIRO"], "África do Sul": ["CIDADE DO CABO", "PRETÓRIA"], "Guiné": ["CONACRI"], "Benin": ["COTONOU"],
        "Senegal": ["DACAR"], "Tanzânia": ["DAR ES SALAAM"], "Botsuana": ["GABORONE"], "Zimbábue": ["HARARE"],
        "Camarões": ["IAUNDÊ"], "República Democrática do Congo": ["KINSHASA"], "Gabão": ["LIBREVILLE"],
        "Malaui": ["LILONGUE"], "Togo": ["LOMÉ"], "Angola": ["LUANDA"], "Zâmbia": ["LUSACA"],
        "Guiné Equatorial": ["MALABO"], "Moçambique": ["MAPUTO"], "Quênia": ["NAIRÓBI"], "Cabo Verde": ["PRAIA"],
        "Marrocos": ["RABAT"], "São Tomé e Príncipe": ["SÃO TOMÉ"], "Líbia": ["TRÍPOLI"], "Tunísia": ["TUNIS"],
        "Burkina Faso": ["UAGADUGU"], "Namíbia": ["WINDHOEK"],
    },
    "América do Sul": {
        "Uruguai": ["ARTIGAS", "CHUY", "MONTEVIDÉU", "RIO BRANCO", "RIVERA"],
        "Paraguai": ["ASSUNÇÃO", "CIUDAD DEL ESTE", "CONCEPCIÓN", "ENCARNACIÓN", "PEDRO JUAN CABALLERO", "SALTO DEL GUAIRÁ"],
        "Colômbia": ["BOGOTÁ"], "Argentina": ["BUENOS AIRES", "CÓRDOBA", "MENDOZA", "PASO LOS LIBRES", "PUERTO IGUAZÚ"],
        "Guiana Francesa": ["CAIENA", "ST GEORGES DE LOYAPOCK"],
        "Venezuela": ["CARACAS", "CIUDAD GUAYANA", "SANTA ELENA DE UAIRÉN"],
        "Bolívia": ["COBIJA", "COCHABAMBA", "LA PAZ", "PUERTO QUIJARRO", "SANTA CRUZ DE LA SIERRA"],
        "Guiana": ["GEORGETOWN"], "Peru": ["IQUITOS", "LIMA"], "Suriname": ["PARAMARIBO"], "Equador": ["QUITO"],
        "Chile": ["SANTIAGO"],
    },
    "América do Norte": {
        "Estados Unidos": ["ATLANTA", "BOSTON", "CHICAGO", "HARTFORD", "HOUSTON", "LOS ANGELES", "MIAMI", "NOVA YORK",
                           "ORLANDO", "SÃO FRANCISCO", "WASHINGTON"],
        "Canadá": ["MONTREAL", "OTTAWA", "TORONTO", "VANCOUVER"], "México": ["MEXICO"],
    },
    "América Central e Caribe": {
        "Belize": ["BELMOPAN"], "Barbados": ["BRIDGETOWN"], "Santa Lúcia": ["CASTRIES"], "Guatemala": ["GUATEMALA"],
        "Cuba": ["HAVANA"], "Jamaica": ["KINGSTON-JAMAICA"], "Nicarágua": ["MANÁGUA"], "Bahamas": ["NASSAU"],
        "Panamá": ["PANAMA"], "Trinidad e Tobago": ["PORT OF SPAIN"], "Haiti": ["PORTO PRÍNCIPE"],
        "Antígua e Barbuda": ["SAINT JOHNS"], "República Dominicana": ["SÃO DOMINGOS"], "Costa Rica": ["SÃO JOSÉ"],
        "El Salvador": ["SÃO SALVADOR"], "Honduras": ["TEGUCIGALPA"],
    },
    "Europa": {
        "Países Baixos": ["AMSTERDÃ"], "Turquia": ["ANCARA", "ISTAMBUL"], "Grécia": ["ATENAS"],
        "Espanha": ["BARCELONA", "MADRI"], "Sérvia": ["BELGRADO"], "Alemanha": ["BERLIM", "FRANKFURT", "MUNIQUE"],
        "Eslováquia": ["BRATISLAVA"], "Bélgica": ["BRUXELAS"], "Romênia": ["BUCARESTE"], "Hungria": ["BUDAPESTE"],
        "Dinamarca": ["COPENHAGUE"], "Irlanda": ["DUBLIN"], "Reino Unido": ["EDIMBURGO", "LONDRES"],
        "Suécia": ["ESTOCOLMO"], "Portugal": ["FARO", "LISBOA", "PORTO"], "Suíça": ["GENEBRA", "ZURIQUE"],
        "Finlândia": ["HELSINQUE"], "Ucrânia": ["KIEV"], "Eslovênia": ["LIUBLIANA"], "França": ["MARSELHA", "PARIS"],
        "Itália": ["MILÃO", "ROMA"], "Rússia": ["MOSCOU"], "Chipre": ["NICOSIA"], "Noruega": ["OSLO"],
        "República Tcheca": ["PRAGA"], "Bósnia e Herzegovina": ["SARAJEVO"], "Bulgária": ["SÓFIA"],
        "Estônia": ["TALIN"], "Albânia": ["TIRANA"], "Polônia": ["VARSÓVIA"], "Áustria": ["VIENA"], "Croácia": ["ZAGREB"],
        "Geórgia": ["TBILISI"], "Armênia": ["IEREVAN"], "Azerbaijão": ["BAKU"],
    },
    "Oriente Médio": {
        "Emirados Árabes Unidos": ["ABU DHABI"], "Jordânia": ["AMÃ"], "Iraque": ["BAGDÁ"], "Bahrein": ["BAREIN"],
        "Líbano": ["BEIRUTE"], "Síria": ["DAMASCO"], "Catar": ["DOHA"], "Kuwait": ["KUAITE"], "Omã": ["MASCATE"],
        "Palestina": ["RAMALLAH"], "Arábia Saudita": ["RIADE"], "Irã": ["TEERÃ"], "Israel": ["TEL AVIV"],
    },
    "Ásia": {
        "Cazaquistão": ["ASTANA"], "Tailândia": ["BANGKOK"], "China": ["CANTÃO", "HONG KONG", "PEQUIM", "XANGAI"],
        "Sri Lanka": ["COLOMBO"], "Bangladesh": ["DACCA"], "Timor-Leste": ["DÍLI"],
        "Japão": ["HAMAMATSU", "NAGÓIA", "TÓQUIO"], "Vietnã": ["HANÓI"], "Paquistão": ["ISLAMABADE"],
        "Indonésia": ["JACARTA"], "Nepal": ["KATMANDU"], "Malásia": ["KUALA LUMPUR"], "Filipinas": ["MANILA"],
        "Índia": ["MUMBAI", "NOVA DELHI"], "Coreia do Norte": ["PYONGYANG"], "Coreia do Sul": ["SEUL"],
        "Singapura": ["SINGAPURA"], "Taiwan": ["TAIPÉ"], "Mianmar": ["YANGON"],
    },
    "Oceania": {
        "Austrália": ["CAMBERRA", "SYDNEY"], "Nova Zelândia": ["WELLINGTON"],
    },
}
PAIS_POR_CIDADE = {cidade: (pais, continente) for continente, paises in _PAISES.items()
                   for pais, cidades in paises.items() for cidade in cidades}


def localizar_csvs(origem: Path):
    if origem.is_file():
        return [origem]
    brasil = sorted(origem.glob("*_BRASIL.csv"))
    if brasil:
        return brasil
    return sorted(p for p in origem.glob("*.csv"))


def agregar(csvs, turno: str = "1"):
    """Soma eleitores (QT_ELEITOR_ELEICAO_FEDERAL) e conta seções principais por município."""
    mun = defaultdict(lambda: {"eleitores": 0, "secoes": 0, "nome": "", "dicas": defaultdict(int)})
    for caminho in csvs:
        with open(caminho, encoding="latin-1", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if row.get("DS_SITU_SECAO", "ATIVO").strip().upper() != "ATIVO":
                    continue
                # Depois do 1º turno o TSE inclui as seções do 2º turno no mesmo arquivo
                if row.get("NR_TURNO", turno).strip() != turno:
                    continue
                chave = (row["SG_UF"].strip().upper(), row["CD_MUNICIPIO"].strip().zfill(5))
                m = mun[chave]
                m["nome"] = row["NM_MUNICIPIO"].strip()
                if chave[0] == "ZZ":
                    m["dicas"][row.get("NM_BAIRRO", "").strip()] += 1
                m["eleitores"] += int(row["QT_ELEITOR_ELEICAO_FEDERAL"] or 0)
                # Seções agregadas são apuradas junto com a principal: não contam como seção própria
                if row.get("CD_TIPO_SECAO_AGREGADA", "1").strip() == "1":
                    m["secoes"] += 1
    return mun


def _sem_acento(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().upper().replace("-", " ").strip()


def gerar_exterior(mun) -> dict:
    """{cod: {cidade, pais, continente, eleitores, secoes}} das cidades do exterior (UF ZZ)."""
    saida, sem_pais, conflitos = {}, [], []
    paises_norm = {_sem_acento(p): p for p, _ in PAIS_POR_CIDADE.values()}
    for (uf, cod), m in sorted(mun.items()):
        if uf != "ZZ":
            continue
        pais, continente = PAIS_POR_CIDADE.get(m["nome"], (None, None))
        if pais is None:
            sem_pais.append(m["nome"])
            continue
        # Confere com o "bairro" do TSE quando ele traz um nome de país
        for dica in m["dicas"]:
            d = _sem_acento(dica)
            if d in paises_norm and paises_norm[d] != pais:
                conflitos.append(f"{m['nome']}: tabela={pais}, TSE={dica}")
        saida[cod] = {"cidade": m["nome"], "pais": pais, "continente": continente,
                      "eleitores": m["eleitores"], "secoes": m["secoes"]}
    if sem_pais:
        sys.exit(f"Cidades do exterior sem país na tabela PAIS_POR_CIDADE: {sem_pais}")
    for c in conflitos:
        print(f"[aviso] país divergente do TSE: {c}")
    print(f"Exterior: {len(saida)} cidades em {len({v['pais'] for v in saida.values()})} países")
    return saida


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
    ap.add_argument("--turno", default="1", help="Turno do eleitorado (o arquivo pode trazer os dois)")
    args = ap.parse_args()

    csvs = localizar_csvs(args.origem)
    if not csvs:
        sys.exit(f"Nenhum CSV encontrado em {args.origem}")
    mun = agregar(csvs, args.turno)
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

    exterior = gerar_exterior(mun)

    for nome, conteudo in (
        ("ufs_metadados.json", ufs_meta),
        ("cidades_100k.json", cidades),
        ("municipios_meta.json", mun_meta),
        ("exterior_cidades.json", exterior),
    ):
        with open(DATA_DIR / nome, "w", encoding="utf-8") as f:
            json.dump(conteudo, f, ensure_ascii=False, indent=1)

    total = sum(d["eleitores"] for d in ufs_meta.values())
    n_cid = sum(len(v) for v in cidades.values())
    print(f"Eleitorado total: {total:,} | seções: {sum(d['secoes'] for d in ufs_meta.values()):,}")
    print(f"Municípios estratificados: {n_cid} (limiar {args.limiar:,} eleitores + capitais)")


if __name__ == "__main__":
    main()

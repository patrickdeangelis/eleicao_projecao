"""
Prepara o replay de uma apuração real a partir dos Boletins de Urna (Dados Abertos do TSE).

Cada boletim traz os votos da seção e o horário em que o TSE o recebeu (DT_BU_RECEBIDO, horário
de Brasília). Este script soma os votos de Presidente por município e por minuto de recebimento,
o que permite reproduzir a noite da apuração na ordem real em que as urnas chegaram.

Os arquivos (um .zip por UF, mais ZZ = exterior) vêm de cdn.tse.jus.br, o portal de Dados
Abertos (não é o servidor de resultados com limite de 100 req/s). Os do 2º turno são pequenos
(~150 MB no total); os do 1º turno trazem todos os cargos e somam alguns GB.

Saída: <pasta de dados do SPETR>/replay/<ano>_<turno>t.json.gz  (ex.: ~/.local/share/spetr/replay/2022_2t.json.gz)

    python scripts/preparar_replay.py --ano 2022 --turno 2
    python scripts/preparar_replay.py --ano 2022 --turno 1 --manter-zips
    python scripts/preparar_replay.py --ano 2026 --turno 1
"""
import argparse
import csv
import datetime
import gzip
import io
import json
import os
import re
import sys
import time
import zipfile

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from spetr.caminhos import pasta_replays  # noqa: E402

CKAN = "https://dadosabertos.tse.jus.br/api/3/action/package_show?id=resultados-{ano}-boletim-de-urna"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
       "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]


def urls_boletins(ano: str, turno: int):
    pacote = httpx.get(CKAN.format(ano=ano), timeout=60).json()["result"]
    por_uf = {}
    for r in pacote["resources"]:
        m = re.search(rf"bweb_{turno}t_([A-Z]{{2}})_(\d{{12}})\.zip$", r["url"])
        if m:
            uf, versao = m.group(1), m.group(2)
            # Se houver mais de uma geração do arquivo, fica a mais recente (ddmmaaaahhmm)
            chave = versao[4:8] + versao[2:4] + versao[0:2] + versao[8:]
            if uf not in por_uf or chave > por_uf[uf][0]:
                por_uf[uf] = (chave, r["url"])
    return {uf: url for uf, (_, url) in por_uf.items()}


def baixar(url: str, destino: str) -> None:
    if os.path.exists(destino):
        return
    parcial = destino + ".parcial"
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        feito, ultimo = 0, 0.0
        with open(parcial, "wb") as f:
            for bloco in r.iter_bytes(1 << 20):
                f.write(bloco)
                feito += len(bloco)
                if time.monotonic() - ultimo > 2:
                    ultimo = time.monotonic()
                    print(f"\r    baixando {feito / 1e6:,.0f} de {total / 1e6:,.0f} MB", end="", flush=True)
    os.replace(parcial, destino)
    print()


def processar_uf(caminho_zip: str, secoes: dict, candidatos: dict, info: dict) -> int:
    """Lê o CSV do zip (sem extrair) e acumula, por seção, os votos de Presidente."""
    linhas = 0
    with zipfile.ZipFile(caminho_zip) as z:
        for nome in z.namelist():
            if not nome.lower().endswith(".csv"):
                continue
            with z.open(nome) as bruto:
                leitor = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin1", newline=""), delimiter=";")
                for row in leitor:
                    if row["CD_CARGO_PERGUNTA"] != "1":
                        continue
                    linhas += 1
                    chave = (row["SG_UF"], row["CD_MUNICIPIO"].zfill(5), row["NR_ZONA"], row["NR_SECAO"])
                    s = secoes.get(chave)
                    if s is None:
                        try:
                            recebido = datetime.datetime.fromisoformat(row["DT_BU_RECEBIDO"])
                        except ValueError:
                            recebido = datetime.datetime.strptime(row["DT_BU_RECEBIDO"], "%d/%m/%Y %H:%M:%S")
                        s = secoes[chave] = {
                            "recebido": recebido, "aptos": int(row["QT_APTOS"]),
                            "comp": int(row["QT_COMPARECIMENTO"]), "abst": int(row["QT_ABSTENCOES"]),
                            "br": 0, "nu": 0, "votos": {},
                        }
                        info.setdefault("eleicao", row["CD_ELEICAO"])
                        info.setdefault("municipios", {})[chave[:2]] = row["NM_MUNICIPIO"]
                    tipo = row["DS_TIPO_VOTAVEL"]
                    qt = int(row["QT_VOTOS"])
                    if tipo == "Branco":
                        s["br"] += qt
                    elif tipo == "Nominal":
                        n = row["NR_VOTAVEL"]
                        s["votos"][n] = s["votos"].get(n, 0) + qt
                        candidatos.setdefault(n, {"n": n, "nm": row["NM_VOTAVEL"], "partido": row["SG_PARTIDO"]})
                    else:  # Nulo (inclui votos anulados)
                        s["nu"] += qt
    return linhas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ano", default="2022")
    ap.add_argument("--turno", type=int, choices=(1, 2), default=2)
    ap.add_argument("--manter-zips", action="store_true", help="Não apaga os .zip baixados")
    ap.add_argument("--ufs", help="Só estas UFs (teste), ex.: AC,RR")
    args = ap.parse_args()

    pasta = pasta_replays()
    pasta_zips = os.path.join(pasta, "boletins", f"{args.ano}_{args.turno}t")
    os.makedirs(pasta_zips, exist_ok=True)
    urls = urls_boletins(args.ano, args.turno)
    ufs = args.ufs.upper().split(",") if args.ufs else UFS
    faltando = [uf for uf in ufs if uf not in urls]
    if faltando:
        print(f"Aviso: sem boletim publicado para {', '.join(faltando)}")

    secoes, candidatos, info = {}, {}, {}
    for uf in ufs:
        if uf not in urls:
            continue
        destino = os.path.join(pasta_zips, os.path.basename(urls[uf]))
        print(f"{uf}: {os.path.basename(urls[uf])}")
        baixar(urls[uf], destino)
        n = processar_uf(destino, secoes, candidatos, info)
        print(f"    {n:,} linhas de Presidente · {len(secoes):,} seções no total")
        if not args.manter_zips:
            os.remove(destino)

    if not secoes:
        print("Nenhuma seção lida.")
        return 1

    # Municípios (totais) e eventos (município × minuto de recebimento)
    t0 = min(s["recebido"] for s in secoes.values()).replace(second=0)
    nums = sorted(candidatos, key=lambda n: -sum(s["votos"].get(n, 0) for s in secoes.values()))
    idx_mun, municipios, eventos = {}, [], {}
    for (uf, cod, _z, _s), s in secoes.items():
        chave_mun = (uf, cod)
        if chave_mun not in idx_mun:
            idx_mun[chave_mun] = len(municipios)
            municipios.append([uf, cod, info["municipios"].get(chave_mun, ""), 0, 0])
        mi = idx_mun[chave_mun]
        municipios[mi][3] += 1
        municipios[mi][4] += s["aptos"]
        minuto = int((s["recebido"] - t0).total_seconds() // 60)
        ev = eventos.setdefault((minuto, mi), [0] * (6 + len(nums)))
        ev[0] += 1
        ev[1] += s["aptos"]
        ev[2] += s["comp"]
        ev[3] += s["abst"]
        ev[4] += s["br"]
        ev[5] += s["nu"]
        for k, n in enumerate(nums):
            ev[6 + k] += s["votos"].get(n, 0)

    saida = {
        "versao": 1, "ano": args.ano, "turno": args.turno, "cargo": 1, "eleicao": info.get("eleicao", ""),
        "t0": t0.strftime("%Y-%m-%d %H:%M"),
        "gerado_em": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ufs": sorted({m[0] for m in municipios}),
        "candidatos": [candidatos[n] for n in nums],
        "campos_evento": ["minuto", "municipio", "secoes", "aptos", "comparecimento", "abstencao", "brancos", "nulos"]
                         + [f"votos_{n}" for n in nums],
        "municipios": municipios,  # [uf, cod_tse, nome, secoes, aptos]
        "eventos": sorted([m, mi, *v] for (m, mi), v in eventos.items()),
    }
    arquivo = os.path.join(pasta, f"{args.ano}_{args.turno}t{'_parcial' if args.ufs else ''}.json.gz")
    with gzip.open(arquivo, "wt", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    fim = max(e[0] for e in saida["eventos"])
    print(f"\nGravado {arquivo} ({os.path.getsize(arquivo) / 1e6:.1f} MB): {len(secoes):,} seções, "
          f"{len(municipios):,} municípios, {len(saida['eventos']):,} eventos, de {saida['t0']} até +{fim // 60}h{fim % 60:02d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

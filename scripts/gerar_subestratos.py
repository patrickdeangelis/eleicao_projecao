"""
Gera a subestratificação do interior de uma UF (padrão: MG em Interior Norte × Interior Sul).

O grupo nomeado (ex.: NORTE) é a lista de municípios das mesorregiões do IBGE informadas, sem as
cidades que já são estratos próprios (cidades_100k.json). O outro grupo (ex.: SUL) não precisa de
lista: é o Interior Remanescente menos o grupo nomeado, pela mesma subtração vetorial do SPETR.

Fontes:
- Mesorregiões e municípios: API de localidades do IBGE (servicodados.ibge.gov.br)
- Código TSE de cada município: arquivo de configuração de municípios do TSE (EA12), que traz o
  código IBGE no campo "cdi" (sem correspondência por nome)
- Validação (--validar): baixa o arquivo de resultado de cada município numa eleição já publicada
  (ex.: 1º turno de 2026), no máximo 5 requisições/s. Qualquer URL que não responda 200 aborta a
  geração, porque muitos 404 podem bloquear o IP no TSE. Também grava eleitores e seções reais.

Saída: spetr/data/subestratos.json

Uso:
    python scripts/gerar_subestratos.py --validar
    python scripts/gerar_subestratos.py --uf MG --mesorregioes 3101,3102,3103,3104,3108 --grupo NORTE --resto SUL
"""
import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from spetr.collector.parser import parse_tse_json  # noqa: E402

DATA_DIR = RAIZ / "spetr" / "data"
IBGE = "https://servicodados.ibge.gov.br/api/v1/localidades"
TSE = "https://resultados.tse.jus.br/oficial"


def municipios_ibge(mesorregioes):
    saida = {}
    with httpx.Client(timeout=30) as c:
        for meso in mesorregioes:
            info = c.get(f"{IBGE}/mesorregioes/{meso}").json()
            for m in c.get(f"{IBGE}/mesorregioes/{meso}/municipios").json():
                saida[str(m["id"])] = {"nome": m["nome"], "mesorregiao": info["nome"]}
    return saida


async def validar(uf, codigos, ano, eleicao, cargo):
    """Baixa o resultado de cada município (≤ 5 req/s). Retorna {cod: parsed} ou levanta erro."""
    u = uf.lower()
    resultados, falhas = {}, []
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "SPETR-Desktop/1.0 (validacao de URLs)"}) as c:
        for i, cod in enumerate(codigos):
            url = f"{TSE}/ele{ano}/{eleicao}/dados/{u}/{u}{cod}-c{int(cargo):04d}-e{int(eleicao):06d}-u.json"
            r = await c.get(url)
            if r.status_code != 200:
                falhas.append(f"{cod} (HTTP {r.status_code})")
                if len(falhas) >= 3:
                    break
            else:
                resultados[cod] = parse_tse_json(r.json(), uf=uf, cod_mun=cod)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(codigos)} validados")
            await asyncio.sleep(0.2)
    if falhas:
        raise SystemExit(f"Validação interrompida; URLs sem resposta 200: {', '.join(falhas)}")
    return resultados


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uf", default="MG")
    ap.add_argument("--mesorregioes", default="3101,3102,3103,3104,3108",
                    help="IDs IBGE (padrão: Noroeste, Norte de Minas, Jequitinhonha, Vale do Mucuri, Vale do Rio Doce)")
    ap.add_argument("--grupo", default="NORTE", help="Chave do grupo listado")
    ap.add_argument("--nome-grupo", default="Interior Norte")
    ap.add_argument("--resto", default="SUL", help="Chave do grupo obtido por subtração")
    ap.add_argument("--nome-resto", default="Interior Sul")
    ap.add_argument("--config-mun", default=str(RAIZ / "docs/tse_oficial/mun-e021270-cm.json"))
    ap.add_argument("--validar", action="store_true", help="Confere cada URL no TSE (eleição já publicada)")
    ap.add_argument("--ano", default="2026")
    ap.add_argument("--eleicao", default="6257", help="Eleição publicada usada na validação (6257 = 1º turno 2026, presidente)")
    ap.add_argument("--cargo", default="1")
    args = ap.parse_args()
    uf = args.uf.upper()

    with open(args.config_mun, encoding="utf-8") as f:
        abr = next(a for a in json.load(f)["abr"] if a["cd"].upper() == uf)
    tse_por_ibge = {m["cdi"]: m for m in abr["mu"]}
    cidades = set(json.loads((DATA_DIR / "cidades_100k.json").read_text(encoding="utf-8")).get(uf, []))

    ibge = municipios_ibge([m.strip() for m in args.mesorregioes.split(",") if m.strip()])
    sem_tse = [v["nome"] for k, v in ibge.items() if k not in tse_por_ibge]
    if sem_tse:
        raise SystemExit(f"Municípios do IBGE sem código TSE: {', '.join(sem_tse)}")

    municipios, ja_estratos = {}, []
    for cdi, info in sorted(ibge.items()):
        cod = tse_por_ibge[cdi]["cd"]
        if cod in cidades:
            ja_estratos.append(tse_por_ibge[cdi]["nm"])
            continue
        municipios[cod] = {"nome": tse_por_ibge[cdi]["nm"], "ibge": cdi, "mesorregiao": info["mesorregiao"]}
    print(f"{uf}/{args.grupo}: {len(municipios)} municípios a coletar "
          f"({len(ja_estratos)} já são estratos próprios: {', '.join(ja_estratos)})")

    saida_uf = {
        "grupos": {args.grupo: {"nome": args.nome_grupo, "municipios": municipios}},
        "resto": {"chave": args.resto, "nome": args.nome_resto},
        "mesorregioes_ibge": sorted({v["mesorregiao"] for v in ibge.values()}),
        "gerado_em": datetime.date.today().isoformat(),
    }

    if args.validar:
        print(f"Validando {len(municipios)} URLs em ele{args.ano}/{args.eleicao} (≤ 5 req/s)...")
        res = asyncio.run(validar(uf, list(municipios), args.ano, args.eleicao, args.cargo))
        for cod, p in res.items():
            municipios[cod]["eleitores"] = p["eleitores"]
            municipios[cod]["secoes"] = p["secoes_total"]
        saida_uf["validado"] = {"eleicao": f"ele{args.ano}/{args.eleicao}", "em": datetime.date.today().isoformat(),
                                "urls_ok": len(res)}
        # Referência do grupo na eleição validada (só informativo)
        votos = {}
        for p in res.values():
            for n, v in p["candidatos_votos"].items():
                votos[n] = votos.get(n, 0) + v
        total = sum(votos.values()) or 1
        topo = sorted(votos, key=votos.get, reverse=True)[:4]
        print("Resultado do grupo na eleição validada: " + " · ".join(f"{n}: {votos[n] / total * 100:.2f}%" for n in topo))
        saida_uf["validado"]["votos_grupo"] = votos

    caminho = DATA_DIR / "subestratos.json"
    dados = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    dados[uf] = saida_uf
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Gravado {caminho.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

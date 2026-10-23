"""
Replay de uma apuração gravada no banco do SPETR, para medir a calibração do modelo.

Reprocessa os estratos gravados (snapshots_apuracao) de uma execução, ciclo a ciclo, e compara
com o resultado final da própria execução:
- projeção principal: erro, cobertura do IC 95% e primeira chamada de vitória;
- projeções extras (erro): razão de crescimento, estimador direto e swing sobre a eleição de referência.

O swing usa o replay de referência da eleição (--ano/--turno; ex.: 2026 1º turno → 2022_1t). Não use
--dois com o 2º turno de 2026 e referência 2026_1t sobre dados do próprio 1º turno: seria vazamento.

Com --dois, reduz a apuração a um confronto entre dois candidatos (ensaio de 2º turno com os
dados reais do 1º). --desloca transfere uma fração dos votos do 1º para o 2º em todos os
estratos e instantes, para ensaiar uma disputa mais apertada com a mesma ordem de apuração.

    python scripts/replay_apuracao.py --execucao 74f16c746af0 --dois 22,13
    python scripts/replay_apuracao.py --execucao 74f16c746af0 --dois 22,13 --desloca 0.02 --min-cobertura 0.85

Sai com código 1 se a cobertura do IC 95% ficar abaixo de --min-cobertura.
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import OrderedDict

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from spetr.domain.entities import SnapshotParcial  # noqa: E402
from spetr.services.pipeline_coordinator import PipelineCoordinator  # noqa: E402

BANCO_PADRAO = os.path.expanduser("~/.local/share/spetr/spetr_eleicoes.sqlite")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=BANCO_PADRAO)
    ap.add_argument("--execucao", required=True, help="execucao_id gravado no banco")
    ap.add_argument("--dois", help="Dois números de candidato (ex.: 22,13) para ensaiar um 2º turno")
    ap.add_argument("--desloca", type=float, default=0.0, help="Fração dos votos do 1º que passa para o 2º (com --dois)")
    ap.add_argument("--ano", default="2026", help="Ano da eleição gravada (escolhe a referência do swing)")
    ap.add_argument("--turno", type=int, default=1, help="Turno da eleição gravada (escolhe a referência do swing)")
    ap.add_argument("--referencia", default="auto", help="Replay de referência do swing (auto, ex.: 2022_1t, ou 'nenhuma')")
    ap.add_argument("--passo", type=int, default=3, help="Avalia 1 a cada N ciclos gravados")
    ap.add_argument("--simulacoes", type=int, default=4000)
    ap.add_argument("--sigma-uf", type=float)
    ap.add_argument("--sigma-nacional", type=float)
    ap.add_argument("--min-cobertura", type=float, default=0.0)
    ap.add_argument("--quieto", action="store_true", help="Só o resumo")
    args = ap.parse_args()
    logging.disable(logging.WARNING)

    con = sqlite3.connect(args.db)
    linhas = con.execute(
        """SELECT timestamp, estrato_id, secoes_total, secoes_apuradas, eleitores_aptos, comparecimento,
                  abstencao, votos_validos, votos_brancos, votos_nulos, votos_candidatos_json
           FROM snapshots_apuracao WHERE execucao_id = ? ORDER BY timestamp, id""", (args.execucao,)).fetchall()
    if not linhas:
        print(f"Nenhum estrato gravado para a execução {args.execucao}")
        return 2
    por_ts = OrderedDict()
    for l in linhas:
        por_ts.setdefault(l[0], []).append(l)

    dois = args.dois.split(",") if args.dois else None

    def votos(js):
        v = json.loads(js)
        if not dois:
            return {n: int(x) for n, x in v.items()}
        a, b = int(v.get(dois[0], 0)), int(v.get(dois[1], 0))
        m = int(round(a * args.desloca))
        return {dois[0]: a - m, dois[1]: b + m}

    def snapshot(l, ts):
        vc = votos(l[10])
        return SnapshotParcial(
            estrato_id=l[1], timestamp=ts, secoes_total=l[2], secoes_apuradas=l[3], eleitores_aptos=l[4],
            comparecimento=l[5], abstencao=l[6], votos_validos=sum(vc.values()) if dois else l[7],
            votos_brancos=l[8], votos_nulos=l[9], votos_candidatos=vc)

    estado = {}
    for ts, ls in por_ts.items():
        for l in ls:
            estado[l[1]] = l
    final = {}
    # Subestratos (ex.: MG_SUB_NORTE/SUL) repetem o Interior: o total usa só a versão normal
    for l in estado.values():
        if "_SUB_" in l[1]:
            continue
        for n, v in votos(l[10]).items():
            final[n] = final.get(n, 0) + v
    tot = sum(final.values())
    final = {n: v / tot * 100 for n, v in final.items()}
    ordem = sorted(final, key=final.get, reverse=True)
    vencedor, alvo = ordem[0], ordem[0]

    pipe = PipelineCoordinator(db_path=":memory:", num_simulacoes=args.simulacoes, ano_eleicao=args.ano, turno=args.turno,
                               referencia=None if args.referencia == "nenhuma" else args.referencia)
    eng = pipe.engine
    eng.rng = np.random.default_rng(3)
    if args.sigma_uf is not None:
        eng.sigma_uf = args.sigma_uf
    if args.sigma_nacional is not None:
        eng.sigma_nacional = args.sigma_nacional

    print(f"Execução {args.execucao}{' · confronto ' + ' × '.join(dois) if dois else ''}"
          f"{f' · desloca {args.desloca:.3f}' if args.desloca else ''} · σ UF {eng.sigma_uf} · σ nacional {eng.sigma_nacional}")
    print("Resultado final: " + " · ".join(f"{n} {final[n]:.2f}%" for n in ordem[:3]))
    if not args.quieto:
        print(f"\n{'hora':5} {'seções':>7} │ {'apurado':>7} {'projeção [IC 95%]':>24} {'erro':>6} │ {'cresc.':>6} {'erro':>6} │ {'direto':>6} {'erro':>6} │ {'swing':>6} {'erro':>6} │ situação")

    estado, erros, erros_cresc, erros_direto, erros_swing, cobre, n = {}, [], [], [], [], 0, 0
    erros_outros: dict = {}  # modelo -> [(% apurado, erro)] dos demais modelos da aba Modelos
    chamada, ultimo = None, -10.0
    for i, (ts, ls) in enumerate(por_ts.items()):
        for l in ls:
            estado[l[1]] = l
        snaps = {l[1]: snapshot(l, ts) for l in estado.values()}
        if i % args.passo and i != len(por_ts) - 1:
            eng.crescimento.registrar(snaps)
            continue
        r = eng.calcular(snaps, num_simulacoes=args.simulacoes, ciclo_id=i)
        if not r.candidatos or r.total_validos_apurados == 0:
            continue
        c = {p.numero: p for p in r.candidatos}.get(alvo)
        if c is None:
            continue
        cresc = (r.analise.get("crescimento_nacional") or {}).get(alvo)
        versao = "subestratificado" if "subestratificado" in (r.analise.get("direto_versoes") or {}) else "normal"
        direto = ((r.analise.get("direto_versoes") or {}).get(versao) or {}).get(alvo)
        swing = ((r.analise.get("swing_versoes") or {}).get(versao) or {}).get(alvo)
        pct = r.perc_secoes_apuradas
        ok = c.ic_inferior_95 <= final[alvo] <= c.ic_superior_95
        if pct < 99.9:
            n += 1
            cobre += ok
            erros.append((pct, c.perc_projetado - final[alvo]))
            if cresc is not None:
                erros_cresc.append((pct, cresc - final[alvo]))
            if direto is not None:
                erros_direto.append((pct, direto - final[alvo]))
            if swing is not None:
                erros_swing.append((pct, swing - final[alvo]))
            for nome_m, por_v in (r.analise.get("modelos_resumo") or {}).items():
                val = (por_v.get(versao) or por_v.get("_") or {}).get(alvo)
                if val is not None:
                    erros_outros.setdefault(nome_m, []).append((pct, val - final[alvo]))
        if chamada is None and r.status_call.value in ("VITORIA_PROJETADA", "MATEMATICAMENTE_ELEITO"):
            chamada = (pct, r.vencedor_projetado, ts)
        if not args.quieto and (pct - ultimo >= 5 or i == len(por_ts) - 1):
            ultimo = pct
            print(f"{ts[11:16]} {pct:6.1f}% │ {c.perc_apurado:6.2f}% {c.perc_projetado:7.2f}% [{c.ic_inferior_95:6.2f}–{c.ic_superior_95:6.2f}] "
                  f"{c.perc_projetado - final[alvo]:+6.2f} {'' if ok else '✗'}│ "
                  f"{(f'{cresc:6.2f}' if cresc is not None else '     –')} {(f'{cresc - final[alvo]:+6.2f}' if cresc is not None else '      ')} │ "
                  f"{(f'{direto:6.2f}' if direto is not None else '     –')} {(f'{direto - final[alvo]:+6.2f}' if direto is not None else '      ')} │ "
                  f"{(f'{swing:6.2f}' if swing is not None else '     –')} {(f'{swing - final[alvo]:+6.2f}' if swing is not None else '      ')} │ "
                  f"{r.status_call.value}")

    def resumo(lista):
        meio = [abs(e) for p, e in lista if 5 <= p <= 90]
        return f"erro médio {np.mean(meio):.2f} p.p., máximo {np.max(meio):.2f} p.p. (entre 5% e 90%)" if meio else "sem dados"

    cobertura = cobre / n if n else 0.0
    print(f"\nCandidato avaliado: {alvo}")
    print(f"Projeção principal:     {resumo(erros)}")
    print(f"Projeção p/ crescimento: {resumo(erros_cresc)}")
    print(f"Estimador direto:       {resumo(erros_direto)}")
    print(f"Swing s/ referência:    {resumo(erros_swing)}")
    for nome_m, lista in sorted(erros_outros.items()):
        print(f"{nome_m + ':':24}{resumo(lista)}")
    print(f"Cobertura do IC 95%:    {cobre}/{n} = {cobertura:.0%}")
    if chamada:
        print(f"Primeira chamada: {chamada[1]} com {chamada[0]:.1f}% das seções ({'correta' if chamada[1] == vencedor else 'ERRADA'})")
    else:
        print("Nenhuma vitória anunciada antes do fim")
    if args.min_cobertura and cobertura < args.min_cobertura:
        print(f"FALHOU: cobertura abaixo de {args.min_cobertura:.0%}")
        return 1
    if chamada and chamada[1] != vencedor:
        print("FALHOU: chamada errada")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

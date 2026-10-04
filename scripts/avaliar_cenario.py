"""
Avalia o comportamento do modelo num cenário simulado, do começo ao fim da apuração.

Roda o simulador e o pipeline (agregador + projeção) sem servidor, em vários instantes,
e mostra lado a lado o que a apuração parcial diz e o que a projeção diz, comparando
com o resultado final verdadeiro do cenário.

    python scripts/avaliar_cenario.py --cenario virada
    python scripts/avaliar_cenario.py --cenario 2t --ajustes meu_cenario.json --passos 30

O arquivo de ajustes usa o mesmo formato da tela de configuração:
    {"regioes": {"NE": {"percentuais": {"99": 65, "88": 35}, "velocidade": 3}, ...},
     "cidades_primeiro": true}
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from spetr.services.pipeline_coordinator import PipelineCoordinator  # noqa: E402
from spetr.simulador import ANO_SIMULADO, ELEICAO_SIMULADA, PERFIS, EstadoSimulacao  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cenario", choices=tuple(PERFIS), default="virada")
    ap.add_argument("--ajustes", help="Arquivo JSON com percentuais e velocidades por região")
    ap.add_argument("--passos", type=int, default=20, help="Quantos instantes avaliar (padrão: 20)")
    ap.add_argument("--simulacoes", type=int, default=5000)
    args = ap.parse_args()
    logging.disable(logging.WARNING)

    ajustes = None
    if args.ajustes:
        with open(args.ajustes, encoding="utf-8") as f:
            ajustes = json.load(f)
    estado = EstadoSimulacao(args.cenario, ajustes=ajustes)
    verdade = estado.previa(())["final"]
    nomes = {c["n"]: c["nm"] for c in estado.candidatos}
    ordem_final = sorted(verdade, key=verdade.get, reverse=True)
    vencedor, segundo = ordem_final[0], ordem_final[1]

    pipe = PipelineCoordinator(
        db_path=":memory:", num_simulacoes=args.simulacoes, ano_eleicao=ANO_SIMULADO,
        codigo_eleicao=ELEICAO_SIMULADA, turno=PERFIS[args.cenario]["turno"], formato="r",
    )
    pipe.engine.rng = __import__("numpy").random.default_rng(7)

    print(f"Cenário: {PERFIS[args.cenario]['descricao']}{' (personalizado)' if ajustes else ''}")
    print("Resultado final verdadeiro: " + " · ".join(f"{nomes[n]} {verdade[n]:.2f}%" for n in ordem_final[:4]))
    print()
    cab = (f"{'Seções':>7} │ {'Parcial (líder)':<24} │ {'Projeção de ' + nomes[vencedor].split()[-1]:<26} │ "
           f"{'Chance de ' + nomes[vencedor].split()[-1] + ' vencer':>22} │ Situação")
    print(cab)
    print("─" * len(cab))

    eventos = {"parcial_certa": None, "projecao_certa": None, "faixa_contem": None, "chamada": None}
    for i in range(1, args.passos + 1):
        estado.progresso_global = i / args.passos
        snaps = pipe.aggregator.processar_lote_bruto(estado.lote_completo())
        r = pipe.engine.calcular(snaps, num_simulacoes=args.simulacoes, ciclo_id=i, candidatos_meta=pipe.aggregator._candidatos_meta)
        if not r.candidatos:
            continue
        c = {p.numero: p for p in r.candidatos}
        lider_parcial = max(r.candidatos, key=lambda p: p.votos_apurados)
        v = c[vencedor]
        pct = r.perc_secoes_apuradas
        faixa_ok = v.ic_inferior_95 <= verdade[vencedor] <= v.ic_superior_95
        situacao = {"INDEFINIDO": "em aberto", "VITORIA_PROJETADA": f"vitória projetada: {nomes.get(r.vencedor_projetado, '?')}",
                    "MATEMATICAMENTE_ELEITO": f"eleito: {nomes.get(r.vencedor_projetado, '?')}",
                    "SEGUNDO_TURNO_PROJETADO": "2º turno projetado"}[r.status_call.value]
        print(f"{pct:6.1f}% │ {nomes[lider_parcial.numero].split()[-1]:<9} {lider_parcial.perc_apurado:5.1f}% "
              f"({nomes[vencedor].split()[-1][:6]} {v.perc_apurado:4.1f}%) │ "
              f"{v.perc_projetado:5.2f}% [{v.ic_inferior_95:5.2f}–{v.ic_superior_95:5.2f}] {'✓' if faixa_ok else '✗'}   │ "
              f"{v.prob_vitoria * 100:21.1f}% │ {situacao}")

        if eventos["parcial_certa"] is None and lider_parcial.numero == vencedor:
            eventos["parcial_certa"] = pct
        if eventos["projecao_certa"] is None and r.candidatos[0].numero == vencedor:
            eventos["projecao_certa"] = pct
        if r.status_call.value in ("VITORIA_PROJETADA", "MATEMATICAMENTE_ELEITO") and eventos["chamada"] is None:
            eventos["chamada"] = (pct, r.vencedor_projetado)
        eventos.setdefault("faixas", []).append(faixa_ok)

    print()
    fmt = lambda x: f"{x:.1f}% das seções" if x is not None else "nunca"
    print(f"Parcial passa a mostrar o vencedor certo ({nomes[vencedor]}): {fmt(eventos['parcial_certa'])}")
    print(f"Projeção passa a apontar o vencedor certo:          {fmt(eventos['projecao_certa'])}")
    if eventos["chamada"]:
        pct, quem = eventos["chamada"]
        certo = "correta" if quem == vencedor else "ERRADA"
        print(f"Primeira chamada de vitória: {nomes.get(quem, quem)} com {pct:.1f}% das seções ({certo})")
    else:
        print("Nenhuma vitória foi anunciada antes do fim (disputa apertada demais para ter certeza).")
    faixas = eventos.get("faixas", [])
    if faixas:
        print(f"Faixa provável contém o resultado final em {sum(faixas)} de {len(faixas)} instantes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

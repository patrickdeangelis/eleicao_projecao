"""
Servidor mock da CDN do TSE, isolado (fora do app).

O mesmo simulador já roda embutido no SPETR pela opção "Simular resultados" da tela
inicial. Este script serve para testar o coletor contra um processo separado:

    python scripts/mock_tse_server.py --cenario 1t --velocidade normal
    python main.py --mock
"""
import argparse
import os
import sys

import uvicorn

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from spetr.simulador import CENARIOS, VELOCIDADES, EstadoSimulacao, criar_app_simulador  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Emulador da CDN do TSE")
    ap.add_argument("--cenario", choices=tuple(CENARIOS), default="1t",
                    help="1t = 1º turno com 10 candidatos (um sub judice); 2t = segundo turno")
    ap.add_argument("--velocidade", choices=tuple(VELOCIDADES), default="normal")
    ap.add_argument("--inicio", type=float, default=0.0, help="Percentual inicial das seções apuradas")
    ap.add_argument("--porta", type=int, default=8080)
    args = ap.parse_args()

    estado = EstadoSimulacao(args.cenario, args.velocidade, args.inicio / 100.0)
    print("=" * 70)
    print(" SIMULADOR DA CDN DO TSE")
    print(f" Arquivos em:        http://127.0.0.1:{args.porta}/oficial/ele2022/545/dados-simplificados/")
    print(f" Painel de controle: http://127.0.0.1:{args.porta}/")
    print("=" * 70)
    uvicorn.run(criar_app_simulador(estado), host="127.0.0.1", port=args.porta, log_level="warning")


if __name__ == "__main__":
    main()

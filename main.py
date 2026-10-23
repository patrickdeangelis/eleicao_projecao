"""
main.py
Ponto de entrada e bootstrap do aplicativo Desktop SPETR.
"""
import sys
import os
import argparse
import asyncio
import threading
import uvicorn
import logging
from spetr.caminhos import pasta_dados_usuario


# Executável sem console (SPETR.app no macOS, ou Windows com SPETR_SEM_CONSOLE=1): stdout/stderr
# chegam como None e o uvicorn falharia ao configurar os logs. Redireciona para um arquivo.
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(pasta_dados_usuario(), "spetr.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

from spetr.services.event_bus import EventBus
from spetr.services.sessao import SessaoSPETR
from spetr.simulador import CENARIOS, VELOCIDADES
from spetr.api.server import create_api_app
from spetr.ui.window import DesktopWindow
from spetr.collector.jws import CHAVES_TSE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("spetr.main")


def rodar_servidor_e_worker(loop, sessao, api_app, porta: int, modo_inicial=None, opcoes_iniciais=None):
    """Thread de segundo plano que gerencia o loop de eventos assíncrono."""
    asyncio.set_event_loop(loop)

    # Configuração do Uvicorn para rodar em localhost
    config = uvicorn.Config(
        api_app,
        host="127.0.0.1",
        port=porta,
        log_level="warning",
        access_log=False
    )
    server = uvicorn.Server(config)
    loop.create_task(server.serve())

    # Sem modo na linha de comando, a coleta só começa após a escolha na tela inicial
    if modo_inicial:
        loop.create_task(sessao.iniciar(modo_inicial, opcoes_iniciais or {}))

    try:
        loop.run_forever()
    except Exception as e:
        logger.error(f"Erro no loop do worker: {e}")


def caminho_banco_padrao() -> str:
    """
    Rodando pelo Python, o banco fica na pasta atual (como antes). No executável
    (PyInstaller), a pasta atual pode ser qualquer uma, então usa a pasta de dados do usuário.
    """
    if not getattr(sys, "frozen", False):
        return "spetr_eleicoes.sqlite"
    return os.path.join(pasta_dados_usuario(), "spetr_eleicoes.sqlite")


def encerrar(loop, sessao) -> None:
    try:
        asyncio.run_coroutine_threadsafe(sessao.parar(), loop).result(timeout=10)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="SPETR - Sistema de Projeção Eleitoral em Tempo Real. "
                    "Sem --modo, abre a tela inicial para escolher entre coleta real e simulação."
    )
    parser.add_argument("--porta", type=int, default=48291, help="Porta local para a API e UI (padrão: 48291)")
    parser.add_argument("--simulacoes", type=int, default=10000, help="Número de simulações de Monte Carlo (padrão: 10000)")
    parser.add_argument("--headless", action="store_true", help="Executar apenas servidor local sem abrir janela nativa")
    parser.add_argument("--modo", choices=("real", "simulado"), default=None,
                        help="Inicia direto neste modo, sem a tela inicial")
    parser.add_argument("--cenario", choices=tuple(CENARIOS), default="1t", help="Cenário do modo simulado")
    parser.add_argument("--velocidade", choices=tuple(VELOCIDADES), default="normal", help="Ritmo do modo simulado")
    parser.add_argument("--mock", action="store_true",
                        help="Coleta real apontando para um mock externo (scripts/mock_tse_server.py em :8080)")
    parser.add_argument("--tse-url", type=str, default=None, help="URL base da CDN do TSE (padrão: oficial ou mock)")
    parser.add_argument("--ano", type=str, default=None, help="Ano da eleição (padrão: 2026; 2022 com --mock)")
    parser.add_argument("--eleicao", type=str, default=None,
                        help="Código da eleição no TSE (ex: 545). Se omitido no formato 'u', é descoberto via ele-c.json")
    parser.add_argument("--cargo", type=str, default="1", help="Código do cargo (1 = Presidente)")
    parser.add_argument("--turno", type=int, choices=(1, 2), default=None,
                        help="Turno usado na descoberta da eleição (padrão: 1)")
    parser.add_argument("--formato", choices=("u", "r"), default=None,
                        help="'u' = Resultado Unificado EA20 (2024+), 'r' = Dados Simplificados (até 2022)")
    parser.add_argument("--ambiente", type=str, default="oficial",
                        help="Pasta de ambiente na CDN (ex: oficial, ou simulado/simulado2026)")
    parser.add_argument("--verificar-jws", choices=tuple(CHAVES_TSE), default=None,
                        help="Baixa os arquivos .jws e valida a assinatura do TSE com a chave do ambiente indicado")
    parser.add_argument("--db", type=str, default=None,
                        help="Arquivo SQLite de histórico (padrão: pasta atual; no executável, a pasta de dados do usuário)")
    args = parser.parse_args()
    if args.db is None:
        args.db = caminho_banco_padrao()

    # Padrões da coleta real (pré-preenchem a tela inicial); --mock aponta para o emulador externo
    padroes_reais = {
        "tse_url": args.tse_url or ("http://127.0.0.1:8080" if args.mock else "https://resultados.tse.jus.br"),
        "ano": args.ano or ("2022" if args.mock else "2026"),
        "eleicao": args.eleicao or ("545" if args.mock else ""),
        "cargo": args.cargo,
        "turno": args.turno or 1,
        "formato": args.formato or "",
        "ambiente": args.ambiente,
        "jws": args.verificar_jws or "",
    }
    modo_inicial = "real" if args.mock else args.modo
    opcoes_iniciais = (
        {"cenario": args.cenario, "velocidade": args.velocidade} if modo_inicial == "simulado" else {}
    )

    print("=" * 70)
    print(" SPETR // SISTEMA DE PROJEÇÃO ELEITORAL EM TEMPO REAL")
    print(f" Simulações Monte Carlo: {args.simulacoes:,} por ciclo")
    print(f" Servidor local UI:      http://127.0.0.1:{args.porta}")
    print(f" Banco de histórico:     {os.path.abspath(args.db)}")
    if modo_inicial == "simulado":
        print(f" Modo:                   simulação local ({args.cenario}, {args.velocidade})")
    elif modo_inicial == "real":
        print(f" Modo:                   coleta real em {padroes_reais['tse_url']} (ele{padroes_reais['ano']})")
    else:
        print(" Modo:                   escolha na tela inicial (coleta real ou simulação)")
    print("=" * 70)

    # 1. Barramento, sessão (coleta real ou simulada) e API
    bus = EventBus()
    sessao = SessaoSPETR(event_bus=bus, db_path=args.db, num_simulacoes=args.simulacoes, padroes_reais=padroes_reais)
    api_app = create_api_app(event_bus=bus, sessao=sessao)

    # 2. Dispara a thread de background (API + coleta)
    loop_worker = asyncio.new_event_loop()
    thread_worker = threading.Thread(
        target=rodar_servidor_e_worker,
        args=(loop_worker, sessao, api_app, args.porta, modo_inicial, opcoes_iniciais),
        daemon=True
    )
    thread_worker.start()

    url_ui = f"http://127.0.0.1:{args.porta}"

    # 3. Modo Headless ou Desktop GUI
    # Verifica se há display gráfico disponível (DISPLAY ou WAYLAND_DISPLAY no Linux, ou Windows/macOS)
    sem_display = sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if args.headless or sem_display:
        if sem_display and not args.headless:
            logger.info("Nenhum servidor gráfico detectado ($DISPLAY ausente). Executando em modo headless.")
        print(f"\n[SPETR PRONTO] Acesse pelo navegador em: {url_ui}\nPressione Ctrl+C para encerrar.\n")
        try:
            thread_worker.join()
        except KeyboardInterrupt:
            print("\nEncerrando SPETR...")
            encerrar(loop_worker, sessao)
            sys.exit(0)
    else:
        # Abre janela Desktop nativa com PyWebView
        janela = DesktopWindow(
            titulo="SPETR - Painel de Projeção Eleitoral em Tempo Real",
            url_local=url_ui,
            largura=1366,
            altura=768
        )
        sucesso = janela.exibir()
        if not sucesso:
            import webbrowser
            print(f"\n[SPETR PRONTO] Abrindo no navegador padrão em: {url_ui}")
            print("Pressione Ctrl+C para encerrar.\n")
            try:
                webbrowser.open(url_ui)
            except Exception:
                pass
            try:
                thread_worker.join()
            except KeyboardInterrupt:
                print("\nEncerrando SPETR...")

        encerrar(loop_worker, sessao)
        sys.exit(0)


if __name__ == "__main__":
    main()

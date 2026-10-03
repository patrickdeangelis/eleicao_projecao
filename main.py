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

from spetr.services.event_bus import EventBus
from spetr.services.pipeline_coordinator import PipelineCoordinator
from spetr.api.server import create_api_app
from spetr.ui.window import DesktopWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("spetr.main")


def rodar_servidor_e_worker(loop, coordinator, api_app, porta: int):
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

    # Agenda o servidor e o loop de coleta
    loop.create_task(server.serve())
    loop.create_task(coordinator.scheduler.iniciar_loop())

    try:
        loop.run_forever()
    except Exception as e:
        logger.error(f"Erro no loop do worker: {e}")


def main():
    parser = argparse.ArgumentParser(description="SPETR - Sistema de Projeção Eleitoral em Tempo Real")
    parser.add_argument("--porta", type=int, default=48291, help="Porta local para a API e UI (padrão: 48291)")
    parser.add_argument("--simulacoes", type=int, default=10000, help="Número de simulações de Monte Carlo (padrão: 10000)")
    parser.add_argument("--headless", action="store_true", help="Executar apenas servidor local sem abrir janela nativa")
    args = parser.parse_args()

    print("=" * 70)
    print(" SPETR // SISTEMA DE PROJEÇÃO ELEITORAL EM TEMPO REAL")
    print(f" Simulações Monte Carlo: {args.simulacoes:,} por ciclo")
    print(f" Servidor local: http://127.0.0.1:{args.porta}")
    print("=" * 70)

    # 1. Instancia o coordenador e o barramento desacoplado
    bus = EventBus()
    coordinator = PipelineCoordinator(
        event_bus=bus,
        db_path="spetr_eleicoes.sqlite",
        num_simulacoes=args.simulacoes
    )

    # 2. Cria a aplicação FastAPI
    api_app = create_api_app(
        event_bus=bus,
        repository=coordinator.repo
    )

    # 3. Dispara a thread de background (API + Coletor)
    loop_worker = asyncio.new_event_loop()
    thread_worker = threading.Thread(
        target=rodar_servidor_e_worker,
        args=(loop_worker, coordinator, api_app, args.porta),
        daemon=True
    )
    thread_worker.start()

    url_ui = f"http://127.0.0.1:{args.porta}"

    # 4. Modo Headless ou Desktop GUI
    # Verifica se há display gráfico disponível (DISPLAY ou WAYLAND_DISPLAY no Linux, ou Windows/macOS)
    sem_display = sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if args.headless or sem_display:
        if sem_display and not args.headless:
            logger.info("Nenhum servidor gráfico detectado ($DISPLAY ausente). Executando em modo headless.")
        print(f"\n[SPETR PRONTO] Acesse o dashboard pelo seu navegador em: {url_ui}\nPressione Ctrl+C para encerrar.\n")
        try:
            thread_worker.join()
        except KeyboardInterrupt:
            print("\nEncerrando SPETR...")
            coordinator.scheduler.parar()
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
            print(f"\n[SPETR PRONTO] Abrindo dashboard no navegador padrão em: {url_ui}")
            print("Pressione Ctrl+C para encerrar.\n")
            try:
                webbrowser.open(url_ui)
            except Exception:
                pass
            try:
                thread_worker.join()
            except KeyboardInterrupt:
                print("\nEncerrando SPETR...")

        coordinator.scheduler.parar()
        sys.exit(0)




if __name__ == "__main__":
    main()

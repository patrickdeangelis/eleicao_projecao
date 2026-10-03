"""
Launcher da Janela Desktop Nativa com PyWebView.
"""
import sys
import logging
from typing import Optional

logger = logging.getLogger("spetr.ui.window")


class DesktopWindow:
    """Gerenciador da janela desktop nativa."""

    def __init__(
        self,
        titulo: str = "SPETR - Painel de Projeção Eleitoral em Tempo Real",
        url_local: str = "http://127.0.0.1:48291",
        largura: int = 1400,
        altura: int = 860,
    ):
        self.titulo = titulo
        self.url = url_local
        self.largura = largura
        self.altura = altura
        self._window = None

    def exibir(self) -> None:
        """Inicia a interface nativa do sistema operacional."""
        try:
            import webview
            logger.info(f"Iniciando PyWebView em {self.url}...")
            self._window = webview.create_window(
                title=self.titulo,
                url=self.url,
                width=self.largura,
                height=self.altura,
                min_size=(1024, 650),
                background_color="#0F172A",  # Slate 900
            )
            webview.start(debug=False)
        except Exception as e:
            logger.error(
                f"Não foi possível abrir janela nativa com PyWebView ({e}). "
                f"Acesse diretamente pelo navegador no endereço: {self.url}"
            )

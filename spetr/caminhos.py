"""Pastas de dados do SPETR fora do repositório."""
import os
import sys


def pasta_dados_usuario() -> str:
    """Pasta de dados do SPETR no executável: ~/.local/share/spetr, %APPDATA%\\SPETR ou Application Support."""
    if sys.platform.startswith("win"):
        pasta = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SPETR")
    elif sys.platform == "darwin":
        pasta = os.path.expanduser("~/Library/Application Support/SPETR")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        pasta = os.path.join(base, "spetr")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def pasta_replays() -> str:
    """Onde ficam os replays preparados por scripts/preparar_replay.py."""
    pasta = os.path.join(pasta_dados_usuario(), "replay")
    os.makedirs(pasta, exist_ok=True)
    return pasta

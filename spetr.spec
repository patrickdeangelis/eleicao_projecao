# -*- mode: python ; coding: utf-8 -*-
"""
spetr.spec
Arquivo de especificação do PyInstaller para compilar o SPETR em executável único auto-contido.
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None


def _verificar_ambiente_de_build():
    """
    Recusa builds com o Python errado. O caso clássico: `pyinstaller` do PATH rodando com o
    Python do sistema (Fedora), cujo NumPy usa FlexiBLAS — o backend BLAS é escolhido em tempo
    de execução por arquivos do sistema que não vão no executável, e ele aborta ao abrir com
    "flexiblas Failed to load the BLAS fallback library".
    """
    faltando = []
    for modulo in ("numpy", "fastapi", "uvicorn", "httpx", "cryptography", "webview"):
        try:
            __import__(modulo)
        except ImportError:
            faltando.append(modulo)
    if faltando:
        raise SystemExit(
            f"\n[SPETR] Dependências ausentes neste Python ({sys.executable}): {', '.join(faltando)}.\n"
            f"Use o Python do projeto:  .venv/bin/python -m PyInstaller spetr.spec --clean --noconfirm\n"
        )
    import numpy
    try:
        blas = numpy.show_config(mode="dicts")["Build Dependencies"]["blas"]["name"]
    except Exception:
        blas = ""
    if "flexiblas" in str(blas).lower():
        raise SystemExit(
            f"\n[SPETR] O NumPy deste Python ({numpy.__file__}) usa FlexiBLAS, que não funciona dentro "
            f"do executável.\nUse o NumPy do pip (OpenBLAS embutido), pelo Python do projeto:\n"
            f"  .venv/bin/python -m PyInstaller spetr.spec --clean --noconfirm\n"
        )


_verificar_ambiente_de_build()

# Diretório base
BASE_DIR = Path.cwd()

# Coleta de assets estáticos e dados essenciais
datas = [
    (str(BASE_DIR / 'spetr' / 'ui' / 'assets'), 'spetr/ui/assets'),
    (str(BASE_DIR / 'spetr' / 'storage' / 'schema.sql'), 'spetr/storage'),
    (str(BASE_DIR / 'spetr' / 'data'), 'spetr/data'),
]

# Hidden imports necessários para Uvicorn, FastAPI e o HTTP/2 do httpx (importado sob demanda)
hiddenimports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'pydantic',
    'pydantic_core',
    'h2',
    'hpack',
    'hyperframe',
    'sqlite3',
    'webview',
]

a = Analysis(
    ['main.py'],
    pathex=[str(BASE_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    # GTK (janela do pywebview no Linux): só o tema/ícones Adwaita e o idioma pt_BR.
    # Sem isso, todos os temas de ícones instalados no sistema entram no executável (~250 MB).
    hooksconfig={
        'gi': {
            'icons': ['Adwaita'],
            'themes': ['Adwaita'],
            'languages': ['pt_BR'],
        },
    },
    runtime_hooks=[],
    # Pacotes que o SPETR não usa, mas que entram por dependência transitiva ou por o .venv
    # enxergar os site-packages do sistema (necessário para o WebKitGTK no Linux)
    excludes=[
        'tkinter', 'matplotlib', 'notebook', 'IPython', 'scipy', 'pandas',
        'pytest', '_pytest', 'pluggy', 'sentry_sdk', 'sqlalchemy', 'boto3', 'botocore',
        'mcp', 'PIL', 'lxml', 'html5lib', 'Cython',
        'google', 'pydantic_settings', 'jsonschema', 'rich', 'markdown_it',
        # O pywebview usa GTK (Linux), Cocoa (macOS) ou WebView2 (Windows); Qt seria uma
        # segunda biblioteca de janelas
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'qtpy',
    ] + (
        # Só no Linux: entram pelos site-packages do sistema. No Windows o pythonnet (janela
        # WebView2) pode precisar deles, então não arriscamos excluir lá.
        ['setuptools', 'pkg_resources'] if sys.platform.startswith('linux') else []
    ),
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Console: mantido por padrão (logs da coleta). SPETR_SEM_CONSOLE=1 gera executável sem
# terminal (útil no Windows para usuários finais).
CONSOLE = os.environ.get('SPETR_SEM_CONSOLE', '') != '1'

if sys.platform == 'darwin':
    # macOS: aplicativo SPETR.app (pasta), que abre com duplo-clique e sem Terminal.
    # Para depurar, rode SPETR.app/Contents/MacOS/spetr pelo Terminal e veja os logs.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='spetr',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=os.environ.get('SPETR_TARGET_ARCH') or None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='spetr')
    app = BUNDLE(
        coll,
        name='SPETR.app',
        icon=None,
        bundle_identifier='br.spetr.projecao',
        info_plist={
            'CFBundleDisplayName': 'SPETR',
            'CFBundleShortVersionString': '1.2.0',
            'NSHighResolutionCapable': True,
            # O app conversa com o próprio servidor local (127.0.0.1) por HTTP
            'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
        },
    )
else:
    # Windows e Linux: executável único
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='spetr',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=CONSOLE,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

# -*- mode: python ; coding: utf-8 -*-
"""
spetr.spec
Arquivo de especificação do PyInstaller para compilar o SPETR em executável único auto-contido.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Diretório base
BASE_DIR = Path.cwd()

# Coleta de assets estáticos e dados essenciais
datas = [
    (str(BASE_DIR / 'spetr' / 'ui' / 'assets'), 'spetr/ui/assets'),
    (str(BASE_DIR / 'spetr' / 'storage' / 'schema.sql'), 'spetr/storage'),
    (str(BASE_DIR / 'spetr' / 'data'), 'spetr/data'),
]

# Hidden imports necessários para Uvicorn, FastAPI e SciPy
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
    'scipy',
    'scipy.special',
    'scipy.stats',
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
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'notebook', 'IPython'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    console=True,  # Mantém console para logs e diagnóstico
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

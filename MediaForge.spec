# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спека: один exe без консоли + опциональный бандл ffmpeg.

    pyinstaller MediaForge.spec --noconfirm
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
BIN = ROOT / "bin"
ASSETS = ROOT / "assets"

datas = []
for name in ("icon.ico", "icon.png"):
    if (ASSETS / name).exists():
        datas.append((str(ASSETS / name), "assets"))

# Если рядом лежит bin/ffmpeg(.exe) — кладём внутрь сборки.
for exe in ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"):
    if (BIN / exe).exists():
        datas.append((str(BIN / exe), "bin"))

block_cipher = None

a = Analysis(
    [str(ROOT / "mediaforge" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "numpy", "scipy", "matplotlib", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.Qt3DCore", "PySide6.QtWebEngineCore", "PySide6.QtMultimedia",
        "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtPdf",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MediaForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ASSETS / "icon.ico") if (ASSETS / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MediaForge",
)

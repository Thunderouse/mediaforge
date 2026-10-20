# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спека: один exe без консоли + опциональный бандл ffmpeg.

    pyinstaller MediaForge.spec --noconfirm
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

# версию берём из кода, чтобы не расходилась с тегом
_version_match = re.search(
    r'APP_VERSION\s*=\s*"([^"]+)"',
    (ROOT / "mediaforge" / "core" / "config.py").read_text(encoding="utf-8"),
)
APP_VERSION = _version_match.group(1) if _version_match else "0.0.0"
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

# на macOS собираем .app, иначе получается голый unix-бинарник без иконки в Dock
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MediaForge.app",
        icon=str(ASSETS / "icon.icns") if (ASSETS / "icon.icns").exists() else None,
        bundle_identifier="ru.mediaforge.app",
        info_plist={
            "CFBundleName": "MediaForge",
            "CFBundleDisplayName": "MediaForge",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "14.0",
            "LSApplicationCategoryType": "public.app-category.video",
        },
    )

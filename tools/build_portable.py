"""Собирает portable-сборку Windows из официальных артефактов (Linux/macOS/Windows).

    python tools/build_portable.py --stage ./portable --out ./dist

Скачивает embeddable Python, wheels PySide6/Pillow для win_amd64, ffmpeg,
раскладывает всё в портативную папку и упаковывает в zip.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from peutil import prune_orphans  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY_VERSION = "3.11.9"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# что можно выбросить из wheel PySide6 без риска для приложения
# (не трогаем Qt6Core/Gui/Widgets/Svg/Network/Xml/OpenGL/DBus/PrintSupport —
#  их загрузка возможна транзитивно через Qt6Gui)
QT_PRUNE_DIRS = ("qml", "translations", "typesystems", "include", "glue")
QT_PRUNE_GLOBS = (
    "Qt6Qml*", "Qt6Quick*", "Qt6Pdf*", "Qt6Designer*", "Qt6Help*", "Qt6Test*",
    "Qt6Sql*", "Qt6Bluetooth*", "Qt6Nfc*", "Qt6Positioning*", "Qt6Sensors*",
    "Qt6Multimedia*", "Qt6Charts*", "Qt6DataVisualization*", "Qt6WebSockets*",
    "Qt6SerialPort*", "Qt6RemoteObjects*", "Qt6Scxml*", "Qt6StateMachine*",
    "QtQml*", "QtQuick*", "QtPdf*", "QtDesigner*", "QtHelp*", "QtTest*", "QtSql*",
    "QtBluetooth*", "QtNfc*", "QtPositioning*", "QtSensors*", "QtMultimedia*",
    "QtCharts*", "QtDataVisualization*", "QtWebSockets*", "QtSerialPort*",
    "opengl32sw.dll",
)


def fetch(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  кэш: {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  качаю {url}")
    with urllib.request.urlopen(url, timeout=300) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)
    return dest


def unpack_wheel(whl: Path, site_packages: Path) -> None:
    site_packages.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(whl) as zf:
        zf.extractall(site_packages)


def prune_qt(site_packages: Path) -> int:
    """Убирает из PySide6 то, что приложение не использует. Возвращает сэкономленные КБ."""
    freed = 0
    pyside = site_packages / "PySide6"
    for name in QT_PRUNE_DIRS:
        target = pyside / name
        if target.is_dir():
            freed += dir_size(target)
            shutil.rmtree(target, ignore_errors=True)
    for pattern in QT_PRUNE_GLOBS:
        for path in list(pyside.glob(pattern)) + list((pyside / "Qt" / "bin").glob(pattern)):
            if path.is_dir():
                freed += dir_size(path)
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                freed += path.stat().st_size // 1024
                path.unlink(missing_ok=True)
    return freed


# консольные утилиты PySide6 приложению не нужны
TOOL_EXES = (
    "assistant.exe", "designer.exe", "linguist.exe", "lupdate.exe", "lrelease.exe",
    "svgtoqml.exe", "qmlcachegen.exe", "qmlformat.exe", "qmlimportscanner.exe",
    "qmljsrootgen.exe", "qmltyperegistrar.exe", "qmlbalsam.exe", "pyside6-deploy.exe",
    "pyside6-project.exe", "shiboken6.exe", "pyside6-lupdate.exe",
)
# какие плагины Qt оставляем (остальное — модули, которых в приложении нет)
PLUGIN_KEEP = ("platforms", "imageformats", "iconengines", "styles", "generic")


# что должно остаться при любых обстоятельствах (используется приложением)
PROTECTED = (
    "qt6core.dll", "qt6gui.dll", "qt6widgets.dll", "qt6svg.dll", "qt6network.dll",
    "qtcore.pyd", "qtgui.pyd", "qtwidgets.pyd", "qtsvg.pyd",
    "shiboken6*.dll", "pyside6*.dll", "pyside6*.pyd", "qt6*.pyd",
    "plugins/platforms/*", "plugins/imageformats/*", "plugins/iconengines/*",
    "plugins/styles/*", "plugins/generic/*",
)


def prune_pyside_extras(site_packages: Path) -> None:
    pyside = site_packages / "PySide6"
    for name in TOOL_EXES:
        (pyside / name).unlink(missing_ok=True)
    for exe in pyside.glob("*.exe"):
        exe.unlink(missing_ok=True)
    # QML-биндинги и импорт-библиотеки приложению не нужны
    for pattern in ("pyside6qml.abi3.*", "*.lib"):
        for path in pyside.glob(pattern):
            path.unlink(missing_ok=True)
    plugins = pyside / "plugins"
    if plugins.is_dir():
        for item in plugins.iterdir():
            if item.is_dir() and item.name not in PLUGIN_KEEP:
                shutil.rmtree(item, ignore_errors=True)
    # плагин PDF-картинок требует Qt6Pdf, который мы не поставляем
    (plugins / "imageformats" / "qpdf.dll").unlink(missing_ok=True)


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) // 1024


def _zig(args: list[str], cwd: Path | None = None) -> bool:
    """Запускает zig (модуль ziglang или бинарник в PATH)."""
    exe = shutil.which("zig")
    cmd = [exe] if exe else [sys.executable, "-m", "ziglang"]
    try:
        res = subprocess.run(cmd + args, cwd=str(cwd) if cwd else None,
                             capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return False
    if res.returncode != 0:
        print(f"  zig: {res.stderr.strip()[:300]}")
    return res.returncode == 0


def build_launcher(target: Path) -> bool:
    """Собирает нативный MediaForge.exe (кросс-компиляция через zig cc).

    Если zig недоступен — сборка продолжится, останется только .cmd-лаунчер.
    """
    src = ROOT / "packaging" / "portable" / "launcher.c"
    ico = ROOT / "assets" / "icon.ico"
    if not src.exists():
        return False
    if not _zig(["version"]):
        print("  zig не найден — MediaForge.exe не собран (остаётся .cmd)")
        return False

    work = target.parent / "_launcher"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy2(src, work / "launcher.c")
    res = work / "icon.res"
    if ico.exists():
        shutil.copy2(ico, work / "icon.ico")
        (work / "icon.rc").write_text('1 ICON "icon.ico"\n', encoding="utf-8")
        _zig(["rc", "icon.rc", "icon.res"], cwd=work)

    args = [
        "cc", "-target", "x86_64-windows-gnu", "-municode", "-static", "-O2",
        "-Wl,--subsystem,windows", "-o", str(target / "MediaForge.exe"),
        str(work / "launcher.c"),
    ]
    if res.exists():
        args.append(str(res))
    ok = _zig(args, cwd=work)
    shutil.rmtree(work, ignore_errors=True)
    if ok:
        size = (target / "MediaForge.exe").stat().st_size / 1024
        print(f"  MediaForge.exe: {size:.0f} КБ")
    return ok


def build(stage: Path, out: Path, keep_cache: Path) -> Path:
    name = "MediaForge-portable-win64"
    target = stage / name
    if target.exists():
        shutil.rmtree(target)
    (target / "app").mkdir(parents=True)
    (target / "bin").mkdir()

    # 1. embeddable Python
    print("→ Python embedded")
    py_zip = fetch(PY_URL, keep_cache / f"python-{PY_VERSION}-embed-amd64.zip")
    with zipfile.ZipFile(py_zip) as zf:
        zf.extractall(target / "python")

    # 2. wheels
    print("→ PySide6 / Pillow")
    wheels = sorted((keep_cache / "wheels").glob("*.whl"))
    if not wheels:
        raise SystemExit("нет wheels в кэше — сначала pip download для win_amd64")
    site_packages = target / "app" / "Lib" / "site-packages"
    for whl in wheels:
        print(f"  {whl.name}")
        unpack_wheel(whl, site_packages)
    freed = prune_qt(site_packages)
    prune_pyside_extras(site_packages)
    orphans = prune_orphans(site_packages / "PySide6", protect=PROTECTED)
    print(f"  вырезано из Qt: {freed // 1024} МБ, осиротевших файлов: {orphans}")

    # 3. код приложения
    print("→ код приложения")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "mediaforge", target / "app" / "mediaforge", ignore=ignore)

    # 4. ffmpeg
    print("→ ffmpeg")
    ff_zip = fetch(FFMPEG_URL, keep_cache / "ffmpeg-release-essentials.zip")
    with zipfile.ZipFile(ff_zip) as zf:
        for member in zf.namelist():
            base = os.path.basename(member)
            if base in ("ffmpeg.exe", "ffprobe.exe"):
                with zf.open(member) as src, open(target / "bin" / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                print(f"  + {base}")

    # 5. _pth: пути для embedded Python
    (target / "python" / "python311._pth").write_text(
        "python311.zip\n"
        ".\n"
        "..\\app\n"
        "..\\app\\Lib\\site-packages\n"
        "import site\n",
        encoding="utf-8",
    )

    # 6. лаунчеры и readme
    for src in sorted((ROOT / "packaging" / "portable").glob("*")):
        if src.is_file() and src.suffix != ".c":
            shutil.copy2(src, target / src.name)
    print("→ нативный лаунчер")
    build_launcher(target)
    # Windows-файлы должны быть с CRLF
    for pattern in ("*.cmd", "*.txt"):
        for path in target.glob(pattern):
            data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            path.write_bytes(data)

    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"{name}.zip"
    print("→ архив")
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                zf.write(path, Path(name) / path.relative_to(target))
    print(f"готово: {archive} — {archive.stat().st_size / 1e6:.0f} МБ")
    return archive


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", default=str(ROOT / "build" / "portable"))
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--cache", default=str(ROOT / "build" / "cache"))
    args = ap.parse_args()
    build(Path(args.stage), Path(args.out), Path(args.cache))
    return 0


if __name__ == "__main__":
    sys.exit(main())

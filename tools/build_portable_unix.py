"""Собирает portable-архивы MediaForge для Linux (x86_64 / aarch64).

    python tools/build_portable_unix.py --target linux-aarch64
    python tools/build_portable_unix.py --target linux-x86_64

Внутри архива: python-build-standalone, PySide6/Pillow из официальных wheels,
статический ffmpeg/ffprobe, код приложения и лаунчер `MediaForge.sh`.
Ничего не устанавливается в систему: настройки пишутся в `data/` рядом.

macOS этим скриптом собрать нельзя: на arm64 macOS требует подписи (хотя бы
ad-hoc) и сборки на самой macOS. Для macOS используйте `build_unix.sh` на Mac
или GitHub Actions (workflow `release.yml`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from peutil import prune_orphans  # noqa: F401  (для Windows-веток не используется)
from version import app_version  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY_SERIES = "3.12"
PBS_API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
FFMPEG_SOURCES = {
    # BtbN (GitHub) — основной источник: доступен отовсюду и содержит x264/x265
    "amd64": [
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-linux64-gpl-shared.tar.xz",
        "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    ],
    "arm64": [
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-linuxarm64-gpl-shared.tar.xz",
        "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
    ],
}

TARGETS = {
    "linux-x86_64": {
        "triple": "x86_64-unknown-linux-gnu",
        "wheel_plats": ["manylinux_2_34_x86_64", "manylinux_2_28_x86_64",
                        "manylinux2014_x86_64", "linux_x86_64"],
        "ffmpeg_arch": "amd64",
        "name": "portable-linux-x86_64",
    },
    "linux-aarch64": {
        "triple": "aarch64-unknown-linux-gnu",
        "wheel_plats": ["manylinux_2_39_aarch64", "manylinux_2_28_aarch64",
                        "manylinux2014_aarch64", "linux_aarch64"],
        "ffmpeg_arch": "arm64",
        "name": "portable-linux-aarch64",
    },
}

# что оставляем из Qt (Linux-раскладка: PySide6/Qt/plugins)
PLUGIN_KEEP = (
    "platforms", "platformthemes", "platforminputcontexts", "imageformats",
    "iconengines", "styles", "generic", "xcbglintegrations", "egldeviceintegrations",
    "wayland-decoration-client", "wayland-graphics-integration-client",
    "wayland-shell-integration",
)
QT_PRUNE_DIRS = ("qml", "translations", "libexec", "metatypes", "typesystems", "include", "glue")
QT_PRUNE_GLOBS = (
    "libQt6Qml*", "libQt6Quick*", "libQt6Pdf*", "libQt6Designer*", "libQt6Help*",
    "libQt6Test*", "libQt6Sql*", "libQt6Charts*", "libQt6DataVisualization*",
    "libQt6Multimedia*", "libQt6WebSockets*", "libQt6SerialPort*", "libQt6Bluetooth*",
    "libQt6Nfc*", "libQt6Positioning*", "libQt6Sensors*", "libQt6Scxml*",
    "libQt6StateMachine*", "libQt6RemoteObjects*", "libQt6Labs*", "libQt6Lottie*",
    "libQt6Quick3D*", "libQt6VirtualKeyboard*", "libQt6UiTools*", "libQt6OpenGL*",
    "QtQml*", "QtQuick*", "QtPdf*", "QtDesigner*", "QtHelp*", "QtTest*", "QtSql*",
    "QtCharts*", "QtMultimedia*", "QtWebSockets*", "QtSerialPort*", "QtBluetooth*",
    "QtNfc*", "QtPositioning*", "QtSensors*", "QtScxml*", "QtStateMachine*",
    "QtRemoteObjects*", "QtLabs*", "QtLottie*", "QtQuick3D*", "QtOpenGL*",
    "QtUiTools*", "QtGraphs*", "QtSpatialAudio*", "QtHttpServer*",
    "libpyside6qml*", "libpyside6quick*",
)
PROTECTED = (
    "*.abi3.so", "shiboken6/*", "PySide6/libpyside6*",
    "libQt6Core.so*", "libQt6Gui.so*", "libQt6Widgets.so*", "libQt6Svg.so*",
    "libQt6DBus.so*", "libQt6Network.so*", "libQt6XcbQpa.so*", "libicu*.so*",
    "libpyside6*", "libshiboken6*", "libssl*", "libcrypto*",
    "plugins/platforms/*", "plugins/imageformats/*", "plugins/iconengines/*",
    "plugins/platformthemes/*", "plugins/wayland-*/*", "plugins/xcbglintegrations/*",
)


def fetch(url: str, dest: Path) -> Path:
    """Скачивает файл через curl (urllib в некоторых окружениях падает на TLS)."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  кэш: {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  качаю {url}")
    subprocess.run(["curl", "-sSL", "--retry", "3", "--fail", "-o", str(dest), url],
                   check=True)
    return dest


def pbs_asset(triple: str) -> str:
    raw = subprocess.run(["curl", "-sSL", "--fail", PBS_API],
                         check=True, capture_output=True).stdout
    data = json.loads(raw)
    prefix = f"cpython-{PY_SERIES}."
    for asset in data["assets"]:
        name = asset["name"]
        if name.startswith(prefix) and triple in name and name.endswith("-install_only.tar.gz"):
            return asset["browser_download_url"]
    raise SystemExit(f"нет сборки python-build-standalone для {triple}")


def dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file() and not f.is_symlink():
            total += f.stat().st_size
    return total // 1024


def prune_pyside(site_packages: Path) -> int:
    """Срезает неиспользуемые модули Qt. Возвращает сэкономленные КБ."""
    pyside = site_packages / "PySide6"
    qt = pyside / "Qt"
    freed = 0
    for name in QT_PRUNE_DIRS:
        for base in (qt, pyside):
            target = base / name
            if target.is_dir():
                freed += dir_size(target)
                shutil.rmtree(target, ignore_errors=True)
    for pattern in QT_PRUNE_GLOBS:
        for base in (qt / "lib", pyside):
            for path in list(base.glob(pattern)):
                if path.is_file():
                    freed += path.stat().st_size // 1024
                    path.unlink(missing_ok=True)
    for path in list(pyside.glob("*.pyi")) + list((qt / "lib").glob("*.prl")):
        if path.is_file():
            freed += path.stat().st_size // 1024
            path.unlink(missing_ok=True)
    plugins = qt / "plugins"
    if plugins.is_dir():
        for item in plugins.iterdir():
            if item.is_dir() and item.name not in PLUGIN_KEEP:
                freed += dir_size(item)
                shutil.rmtree(item, ignore_errors=True)
    return freed


def _elf_needed(path: Path) -> list[str] | None:
    """DT_NEEDED файла или None, если это не ELF."""
    from elftools.elf.elffile import ELFFile

    try:
        with open(path, "rb") as fh:
            if fh.read(4) != b"\x7fELF":
                return None
            fh.seek(0)
            elf = ELFFile(fh)
            needed: list[str] = []
            for seg in elf.iter_segments():
                if seg.header.p_type == "PT_DYNAMIC":
                    needed += [t.needed for t in seg.iter_tags()
                               if t.entry.d_tag == "DT_NEEDED"]
            return needed
    except Exception:  # noqa: BLE001
        return None


def prune_orphan_elf(root: Path, protect: tuple[str, ...] = (), passes: int = 5) -> int:
    """Удаляет модули Qt, чьи зависимости вырезаны (аналог prune_orphans для ELF)."""
    import fnmatch

    removed = 0
    for _ in range(passes):
        files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
        names = {p.name for p in root.rglob("*")}
        gone = 0
        for path in files:
            rel = str(path.relative_to(root))
            if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat)
                   for pat in protect):
                continue
            needed = _elf_needed(path)
            if not needed:
                continue
            if any(dep not in names and not _is_system_elf(dep) for dep in needed):
                path.unlink(missing_ok=True)
                gone += 1
        removed += gone
        if not gone:
            break
    return removed


# системные библиотеки, которые обязаны быть в дистрибутиве
_SYSTEM_ELF = {
        "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1",
        "ld-linux-x86-64.so.2", "ld-linux-aarch64.so.1", "libgcc_s.so.1",
        "libstdc++.so.6", "libgobject-2.0.so.0", "libglib-2.0.so.0", "libz.so.1",
        "libexpat.so.1", "libX11.so.6", "libxcb.so.1", "libfontconfig.so.1",
        "libfreetype.so.6", "libXext.so.6", "libXrender.so.1", "libXfixes.so.3",
        "libXi.so.6", "libXcursor.so.1", "libXrandr.so.2", "libXinerama.so.1",
        "libxkbcommon.so.0", "libxkbcommon-x11.so.0", "libEGL.so.1", "libGL.so.1",
        "libGLX.so.0", "libGLdispatch.so.0", "libOpenGL.so.0", "libdbus-1.so.3",
        "libresolv.so.2", "libutil.so.1", "libselinux.so.1", "libpcre2-8.so.0",
        "libpng16.so.16", "libjpeg.so.8", "libzstd.so.1", "liblzma.so.5",
        "libbz2.so.1.0", "libffi.so.8", "libICE.so.6", "libSM.so.6",
        "libX11-xcb.so.1", "libdrm.so.2", "libgbm.so.1", "libwayland-client.so.0",
        "libwayland-cursor.so.0", "libwayland-egl.so.1", "libwayland-server.so.0",
        "libxcb-icccm.so.4", "libxcb-image.so.0", "libxcb-keysyms.so.1",
        "libxcb-randr.so.0", "libxcb-render-util.so.0", "libxcb-shape.so.0",
        "libxcb-sync.so.1", "libxcb-xfixes.so.0", "libxcb-xkb.so.1",
        "libxcb-cursor.so.0", "libxcb-glx.so.0", "libxcb-shm.so.0",
        "libxcb-util.so.1", "libxcb-keysyms.so.1", "libmd.so.0", "libbsd.so.0",
        "liblz4.so.1", "libproxy.so.1", "libsystemd.so.0", "libudev.so.1",
        "libbrotlidec.so.1", "libbrotlicommon.so.1", "libcrypt.so.1",
        "libxcb-render.so.0", "libXau.so.6", "libXdmcp.so.6", "libuuid.so.1",
        "libcap.so.2", "libgcrypt.so.20", "libgpg-error.so.0", "libnsl.so.1",
        "libgssapi_krb5.so.2", "libkrb5.so.3", "libk5crypto.so.3", "libkrb5support.so.0",
        "libgthread-2.0.so.0", "libmvec.so.1", "libcom_err.so.2", "libkeyutils.so.1",
}


def _is_system_elf(dep: str) -> bool:
    if dep.startswith("$ORIGIN") or "/" in dep:
        return True
    return dep in _SYSTEM_ELF


def slim_python(stage: Path) -> int:
    """Убирает из переносимого Python тесты, pip, Tk и заголовки."""
    py = stage / "python"
    freed = 0
    patterns = (
        "lib/python3.*/test", "lib/python3.*/tests", "lib/python3.*/idlelib",
        "lib/python3.*/tkinter", "lib/python3.*/turtledemo", "lib/python3.*/ensurepip",
        "lib/python3.*/lib2to3", "lib/python3.*/pydoc_data", "lib/python3.*/config-*",
        "lib/python3.*/site-packages/pip*", "lib/python3.*/site-packages/setuptools*",
        "lib/python3.*/site-packages/pkg_resources*", "lib/python3.*/site-packages/wheel*",
        "include", "lib/pkgconfig", "share/man", "share/doc", "share/info",
        "bin/idle3*", "bin/2to3*", "bin/pydoc3*", "bin/pip3*",
    )
    for pattern in patterns:
        for path in list(py.glob(pattern)):
            if path.is_dir():
                freed += dir_size(path)
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                freed += path.stat().st_size // 1024
                path.unlink(missing_ok=True)
    return freed


def missing_elf_deps(root: Path) -> dict[str, set[str]]:
    """Библиотеки, которых нет ни в архиве, ни в системе (ELF DT_NEEDED)."""
    from elftools.elf.elffile import ELFFile

    libs = {p.name for p in root.rglob("*.so*") if p.is_file()}
    system = _SYSTEM_ELF
    missing: dict[str, set[str]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            with open(path, "rb") as fh:
                if fh.read(4) != b"\x7fELF":
                    continue
                fh.seek(0)
                elf = ELFFile(fh)
                needed: list[str] = []
                for seg in elf.iter_segments():
                    if seg.header.p_type == "PT_DYNAMIC":
                        needed += [t.needed for t in seg.iter_tags()
                                   if t.entry.d_tag == "DT_NEEDED"]
        except Exception:  # noqa: BLE001 — не-ELF или обрезанный файл
            continue
        for dep in needed:
            if dep in libs or dep in system or dep.startswith("$ORIGIN") or "/" in dep:
                continue
            missing.setdefault(dep, set()).add(str(path.relative_to(root)))
    return missing


def build(target_key: str, out: Path, cache: Path, stage_dir: Path | None = None) -> Path:
    cfg = TARGETS[target_key]
    name = f"MediaForge-{app_version()}-{cfg['name']}"
    stage = (stage_dir or out / "stage") / name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    print("→ Python (python-build-standalone)")
    pbs = fetch(pbs_asset(cfg["triple"]), cache / f"pbs-{cfg['triple']}.tar.gz")
    # share/terminfo в python-build-standalone содержит симлинк-петли, которые
    # валят распаковку — эта папка приложению не нужна, пропускаем её
    with tarfile.open(pbs) as tf:
        for member in tf:
            if "share/terminfo" in member.name:
                continue
            try:
                tf.extract(member, stage)
            except (OSError, tarfile.ExtractError):
                continue
    if (stage / "python").exists() and not (stage / "python" / "bin").exists() and (stage / "python" / "install").exists():
        pass
    py_root = stage / "python"
    if not (py_root / "bin").exists():
        for candidate in stage.iterdir():
            if candidate.is_dir() and (candidate / "bin" / "python3").exists():
                shutil.copytree(candidate, py_root, dirs_exist_ok=True)
                shutil.rmtree(candidate, ignore_errors=True)
                break

    print("→ колёса PySide6 / Pillow")
    wheels_dir = cache / f"wheels-{target_key}"
    wheels_dir.mkdir(parents=True, exist_ok=True)
    if not list(wheels_dir.glob("*.whl")):
        cmd = [sys.executable, "-m", "pip", "download", "--only-binary=:all:",
               "--no-deps", "--python-version", PY_SERIES, "-d", str(wheels_dir)]
        for plat in cfg["wheel_plats"]:
            cmd += ["--platform", plat]
        cmd += ["PySide6-Essentials", "shiboken6", "Pillow"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stdout[-1500:], res.stderr[-1500:])
            raise SystemExit("не удалось скачать колёса для " + cfg["name"])
    site_packages = next(py_root.glob("lib/python3.*/site-packages"))
    for whl in sorted(wheels_dir.glob("*.whl")):
        print(f"  {whl.name}")
        with zipfile.ZipFile(whl) as zf:
            zf.extractall(site_packages)
    freed = prune_pyside(site_packages)
    orphans = prune_orphan_elf(site_packages, protect=PROTECTED)
    slim = slim_python(stage)
    print(f"  вырезано из Qt: {freed // 1024} МБ, сирот: {orphans}, "
          f"из Python: {slim // 1024} МБ")

    print("→ код приложения")
    shutil.copytree(ROOT / "mediaforge", stage / "app" / "mediaforge",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    print("→ ffmpeg")
    ff_dest = cache / f"ffmpeg-{cfg['ffmpeg_arch']}.tar.xz"
    last_error = None
    for url in FFMPEG_SOURCES[cfg["ffmpeg_arch"]]:
        try:
            ff = fetch(url, ff_dest)
            break
        except subprocess.CalledProcessError as exc:
            last_error = exc
            print(f"  источник недоступен: {url.split('/')[2]}")
    else:
        raise SystemExit(f"не удалось скачать ffmpeg: {last_error}")
    (stage / "bin").mkdir(exist_ok=True)
    (stage / "lib").mkdir(exist_ok=True)
    with tarfile.open(ff) as tf:
        for member in tf.getmembers():
            base = os.path.basename(member.name)
            parent = os.path.basename(os.path.dirname(member.name))
            if parent == "bin" and member.isfile() and base in ("ffmpeg", "ffprobe"):
                with tf.extractfile(member) as src, open(stage / "bin" / base, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                (stage / "bin" / base).chmod(0o755)
                print(f"  + bin/{base}")
            elif parent == "lib" and base.startswith("lib"):
                target = stage / "lib" / base
                if member.issym():
                    if target.exists() or target.is_symlink():
                        target.unlink()
                    os.symlink(member.linkname, target)
                elif member.isfile():
                    with tf.extractfile(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

    icon = ROOT / "assets" / "icon.png"
    if icon.exists():
        shutil.copy2(icon, stage / "icon.png")

    print("→ лаунчеры")
    for src in sorted((ROOT / "packaging" / "portable-unix").glob("*")):
        dst = stage / src.name
        shutil.copy2(src, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                  if src.suffix == ".sh" else dst.stat().st_mode)

    missing = missing_elf_deps(stage)
    out.mkdir(parents=True, exist_ok=True)      # --out может ещё не существовать
    archive = out / f"{name}.tar.gz"
    print(f"→ архив {archive.name}")
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz", compresslevel=6) as tf:
        tf.add(stage, arcname=name)
    print(f"   {archive.stat().st_size / 1e6:.0f} МБ, распаковано {dir_size(stage) // 1024} МБ")
    if missing:
        print("   ВНИМАНИЕ, не найдены библиотеки:", ", ".join(sorted(missing)[:12]))
    else:
        print("   ELF-зависимости замкнуты внутри архива (кроме системных)")
    return archive


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True, choices=sorted(TARGETS))
    ap.add_argument("--out", default=str(ROOT / "build" / "portable-unix"))
    ap.add_argument("--cache", default=str(ROOT / "build" / "cache-unix"))
    ap.add_argument("--stage", default="", help="куда распаковывать (по умолчанию <out>/stage)")
    args = ap.parse_args()
    build(args.target, Path(args.out), Path(args.cache),
          Path(args.stage) if args.stage else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())

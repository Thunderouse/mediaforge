"""Скачивает статическую сборку ffmpeg в папку bin/ (для автономной поставки).

    python tools/fetch_ffmpeg.py [--dest bin]

Windows → gyan.dev essentials, Linux → johnvansickle static, macOS → подсказка brew.
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SOURCES = {
    "windows": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "linux": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    "linux-arm64": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
}


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    if system == "linux":
        return "linux-arm64" if machine in ("aarch64", "arm64") else "linux"
    return system


def download(url: str) -> bytes:
    print(f"→ {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:
        total = int(resp.headers.get("content-length") or 0)
        chunks, done = [], 0
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            chunks.append(block)
            done += len(block)
            if total:
                print(f"\r  {done / 1e6:6.1f} / {total / 1e6:.1f} МБ", end="", flush=True)
    print()
    return b"".join(chunks)


def extract(data: bytes, name: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {"ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"}
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                base = os.path.basename(member)
                if base in wanted:
                    with zf.open(member) as src, open(dest / base, "wb") as out:
                        shutil.copyfileobj(src, out)
                    print(f"  + {base}")
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            for member in tf.getmembers():
                base = os.path.basename(member.name)
                if member.isfile() and base in wanted:
                    src = tf.extractfile(member)
                    if src is None:
                        continue
                    with open(dest / base, "wb") as out:
                        shutil.copyfileobj(src, out)
                    print(f"  + {base}")
    for f in dest.iterdir():
        if f.suffix in ("", ".exe"):
            f.chmod(0o755)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", default=str(ROOT / "bin"))
    args = ap.parse_args()
    key = platform_key()
    if key == "macos":
        print("macOS: установите ffmpeg через Homebrew → brew install ffmpeg")
        return 1
    url = SOURCES.get(key)
    if not url:
        print(f"Нет готовой сборки для {key}")
        return 1
    dest = Path(args.dest)
    extract(download(url), url, dest)
    found = sorted(p.name for p in dest.iterdir())
    print(f"ffmpeg готов в {dest}: {', '.join(found)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

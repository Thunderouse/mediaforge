#!/usr/bin/env bash
# Сборка для Linux/macOS: ./build_unix.sh [--with-ffmpeg]
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt pyinstaller
python tools/make_icons.py

if [ "${1:-}" = "--with-ffmpeg" ]; then
  python tools/fetch_ffmpeg.py || echo "ffmpeg не скачан — возьмите из пакетного менеджера"
fi

python -m PyInstaller MediaForge.spec --noconfirm --clean
echo
echo "Готово: dist/MediaForge/MediaForge"

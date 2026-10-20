#!/usr/bin/env bash
# Запуск из исходников на Linux/macOS
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null
  ./.venv/bin/python -m pip install -r requirements.txt
fi
exec ./.venv/bin/python -m mediaforge "$@"

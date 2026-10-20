"""Версия приложения в одном месте для скриптов сборки."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "mediaforge" / "core" / "config.py"


def app_version() -> str:
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', CONFIG.read_text(encoding="utf-8"))
    return match.group(1) if match else "0.0.0"


if __name__ == "__main__":
    print(app_version())

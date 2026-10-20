"""Настройки приложения: JSON в системной папке конфигурации."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, fields
from pathlib import Path

from .formats import ConvertOptions

APP_NAME = "MediaForge"
APP_VERSION = "1.3.0"


def config_dir() -> Path:
    # портативный режим: лаунчер задаёт папку рядом с программой
    env_dir = os.environ.get("MEDIAFORGE_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def config_path() -> Path:
    return config_dir() / "settings.json"


DEFAULTS = {
    "theme": "system",          # system | light | dark
    "out_dir": "",
    "use_source_dir": True,
    "recursive": True,
    "max_workers": 2,
    "window_geometry": "",
    **{f"opt_{f.name}": f.default for f in fields(ConvertOptions)},
}


class Settings:
    def __init__(self, data: dict | None = None):
        self._data = dict(DEFAULTS)
        self._data.update(data or {})

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(config_path().read_text("utf-8"))
            if isinstance(raw, dict):
                return cls(raw)
        except (OSError, json.JSONDecodeError):
            pass
        return cls()

    def save(self) -> None:
        try:
            config_dir().mkdir(parents=True, exist_ok=True)
            config_path().write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8"
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def options(self) -> ConvertOptions:
        kw = {}
        for f in fields(ConvertOptions):
            val = self._data.get(f"opt_{f.name}", f.default)
            if val is None:
                continue
            kw[f.name] = val
        return ConvertOptions(**kw)

    def store_options(self, opts: ConvertOptions) -> None:
        for k, v in asdict(opts).items():
            self._data[f"opt_{k}"] = v

"""Настройки приложения: JSON в системной папке конфигурации."""

from __future__ import annotations

import json
import logging
import logging.handlers
import math
import os
import platform
import sys
import threading
from dataclasses import asdict, fields
from pathlib import Path

from . import formats as fm
from .formats import ConvertOptions

log = logging.getLogger(__name__)

APP_NAME = "MediaForge"
APP_VERSION = "1.3.5"


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


LOG_MAX_BYTES = 1024 * 1024      # 1 МБ на файл
LOG_BACKUPS = 3                 # плюс три архивных копии
LOG_NAME = "mediaforge.log"
_NO_FILE_HANDLER = "_mediaforge_file_handler"


def log_dir() -> Path:
    return config_dir() / "logs"


def log_path() -> Path:
    return log_dir() / LOG_NAME


def setup_logging(
    log_file: Path | None = None,
    debug: bool | None = None,
    max_bytes: int = LOG_MAX_BYTES,
    backups: int = LOG_BACKUPS,
) -> Path | None:
    """Файловый лог рядом с настройками; без прав на запись просто молчим.

    Возвращает путь к логу или None, если писать некуда: диагностика не должна
    мешать запуску.
    """
    if debug is None:
        debug = os.environ.get("MEDIAFORGE_DEBUG", "").strip().lower() in {
            "1", "true", "yes", "on"}
    level = logging.DEBUG if debug else logging.INFO

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _NO_FILE_HANDLER, False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass

    target = Path(log_file) if log_file is not None else log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    except OSError:
        return None

    setattr(handler, _NO_FILE_HANDLER, True)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
    log.info("%s %s · python %s · %s", APP_NAME, APP_VERSION,
             platform.python_version(), sys.platform)
    log.info("лог: %s (уровень %s)", target, logging.getLevelName(level))
    return target


def config_path() -> Path:
    return config_dir() / "settings.json"


THEMES = ("system", "light", "dark")

# сколько ждём после последнего изменения, прежде чем писать файл
SAVE_DELAY = 0.3

_TRUE = {"1", "true", "yes", "on", "да"}
_FALSE = {"0", "false", "no", "off", "", "нет"}

_MAX_EDGE = 100_000


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    return default


def _as_choice(value, allowed: tuple[str, ...], default: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    if isinstance(value, (int, float)) and str(value) in allowed:
        return str(value)
    return default


def _as_seconds(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number) or number < 0:
        return default
    return number


def _as_size(value) -> str:
    """Ширина/высота в px: пустая строка или число в разумных пределах."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if not text.isdigit():
        return ""
    number = int(text)
    if not 1 <= number <= _MAX_EDGE:
        return ""
    return str(number)


def _as_int(value, default: int, low: int, high: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if low <= number <= high else default


def _as_text(value, default: str = "") -> str:
    return value if isinstance(value, str) else default


_OPTION_RULES = {
    "quality": lambda v: _as_choice(v, fm.QUALITY_VALUES, "balanced"),
    "resolution": lambda v: _as_choice(v, fm.RESOLUTION_VALUES, "original"),
    "gif_fps": lambda v: _as_choice(v, fm.GIF_FPS, "15"),
    "audio_bitrate": lambda v: _as_choice(v, fm.AUDIO_BITRATES, "192k"),
    "image_scale": lambda v: _as_choice(v, fm.IMAGE_SCALE_VALUES, "none"),
    "image_percent": lambda v: _as_choice(v, fm.IMAGE_PERCENTS, "150"),
    "image_filter": lambda v: _as_choice(v, fm.IMAGE_FILTER_VALUES, "lanczos"),
    "image_width": _as_size,
    "image_height": _as_size,
    "trim_start": _as_seconds,
    "trim_end": _as_seconds,
}


def clean_option(name: str, value, default):
    """Приводит значение опции к допустимому виду; мусор → default."""
    rule = _OPTION_RULES.get(name)
    if rule is not None:
        return rule(value)
    if isinstance(default, bool):
        return _as_bool(value, default)
    if isinstance(default, float):
        return _as_seconds(value, default)
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return value


def clean_setting(name: str, value, default):
    """То же для служебных ключей (тема, потоки, папки)."""
    if name == "theme":
        return _as_choice(value, THEMES, "system")
    if name == "max_workers":
        return _as_int(value, 2, 1, 32)
    if name in ("use_source_dir", "recursive"):
        return _as_bool(value, bool(default))
    if name in ("out_dir", "window_geometry"):
        return _as_text(value, "")
    return value


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
        self._save_lock = threading.Lock()
        self._save_timer: threading.Timer | None = None
        self.sanitize(log_problems=True)

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

    def save(self, immediate: bool = False) -> None:
        """Планирует запись с задержкой `SAVE_DELAY`; `immediate=True` — сразу.

        Ввод в поле «1920» — это четыре вызова на символ; раньше каждый писал
        файл целиком. Теперь запись склеивается в одну.
        """
        if immediate:
            self.flush()
            return
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            timer = threading.Timer(SAVE_DELAY, self.flush)
            timer.daemon = True
            self._save_timer = timer
            timer.start()

    def flush(self) -> None:
        """Немедленная атомарная запись: свой tmp-файл + os.replace.

        Лок держится на всю запись, а не только на снимок данных: иначе таймер
        дебаунса и closeEvent могли писать в один и тот же tmp одновременно, и
        один поток replace'ил файл, пока второй дописывал в него.
        Имя tmp уникально для вызова — на случай двух экземпляров Settings.
        """
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            data = dict(self._data)
            try:
                config_dir().mkdir(parents=True, exist_ok=True)
                path = config_path()
                tmp = path.with_name(
                    f"{path.name}.{os.getpid()}-{os.urandom(3).hex()}.tmp")
                try:
                    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
                    os.replace(tmp, path)   # читатель видит либо старый, либо новый файл
                finally:
                    if tmp.exists():        # replace не сработал — убираем за собой
                        try:
                            tmp.unlink()
                        except OSError:
                            pass
            except OSError:
                pass

    # ------------------------------------------------------------------ #
    def sanitize(self, log_problems: bool = False) -> list[str]:
        """Чинит значения из settings.json: мусор заменяется дефолтом.

        Молча подставлять нельзя — старый файл с `quality: ultra` иначе
        доезжает до ffmpeg и падает с KeyError уже во время конвертации.
        """
        fixed: list[str] = []
        for key, default in DEFAULTS.items():
            raw = self._data.get(key, default)
            if key.startswith("opt_"):
                name = key[4:]
                field_default = next(
                    (f.default for f in fields(ConvertOptions) if f.name == name), default)
                clean = clean_option(name, raw, field_default)
            else:
                clean = clean_setting(key, raw, default)
            self._data[key] = clean          # тип тоже нормализуем молча
            if clean != raw:
                fixed.append(f"{key}={raw!r} → {clean!r}")
        if log_problems:
            for problem in fixed:
                log.warning("настройка вне допустимых значений: %s", problem)
        return fixed

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        """Терпимое чтение числа: мусор возвращает default, не исключение."""
        value = self.get(key, default)
        if isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return default

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def options(self) -> ConvertOptions:
        kw = {}
        for f in fields(ConvertOptions):
            val = self._data.get(f"opt_{f.name}", f.default)
            if val is None:
                continue
            kw[f.name] = clean_option(f.name, val, f.default)
        return ConvertOptions(**kw)

    def store_options(self, opts: ConvertOptions) -> None:
        for k, v in asdict(opts).items():
            self._data[f"opt_{k}"] = v

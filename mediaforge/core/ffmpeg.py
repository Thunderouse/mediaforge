"""Поиск и запуск ffmpeg/ffprobe, чтение метаданных, прогресс и отмена.

Модуль не зависит от Qt — его можно использовать отдельно (CLI, тесты).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Callable, Iterable, Sequence

IS_WINDOWS = os.name == "nt"
EXE = ".exe" if IS_WINDOWS else ""

# --------------------------------------------------------------------------- #
# Поиск бинарников
# --------------------------------------------------------------------------- #


class FFmpegNotFound(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message)


def _candidate_dirs() -> list[Path]:
    here = Path(__file__).resolve()
    dirs: list[Path] = []

    env_dir = os.environ.get("MEDIAFORGE_BIN")
    if env_dir:
        dirs.append(Path(env_dir))

    # PyInstaller: onefile распаковывается в sys._MEIPASS, onedir — рядом с exe
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        dirs.append(Path(bundle) / "bin")
        dirs.append(Path(bundle))
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent / "bin")
        dirs.append(Path(sys.executable).resolve().parent)

    # Запуск из исходников: <repo>/bin, <repo>/vendor/ffmpeg
    for parent in here.parents:
        dirs.append(parent / "bin")
        dirs.append(parent / "vendor" / "ffmpeg")
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            break

    # Типичные места установки на Windows/macOS/Linux
    dirs += [
        Path("C:/ffmpeg/bin"),
        Path("C:/Program Files/ffmpeg/bin"),
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path.home() / "bin",
    ]
    return dirs


def _find(tool: str, extra_names: Sequence[str] = ()) -> str | None:
    names = [f"{tool}{EXE}", *extra_names, tool]
    for d in _candidate_dirs():
        for name in names:
            p = d / name
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


@dataclass
class Tools:
    ffmpeg: str
    ffprobe: str
    encoders: set[str] = field(default_factory=set)
    _hw: str | None = None
    _hw_checked: bool = False

    @classmethod
    def locate(cls) -> "Tools":
        ffmpeg = _find("ffmpeg")
        ffprobe = _find("ffprobe")
        if not ffmpeg or not ffprobe:
            raise FFmpegNotFound(
                "Не найден ffmpeg. Установите его (winget install Gyan.FFmpeg) "
                "или положите ffmpeg.exe и ffprobe.exe в папку bin рядом с программой."
            )
        tools = cls(ffmpeg=ffmpeg, ffprobe=ffprobe)
        tools.encoders = tools._list_encoders()
        return tools

    def _list_encoders(self) -> set[str]:
        try:
            out = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=20,
                **_popen_flags(),
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return set()
        names: set[str] = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            flags = parts[0]
            # строки таблицы кодировщиков: " V....D libx264   H.264 ..."
            if len(flags) == 6 and flags[0] in "VAS" and set(flags) <= set("VASFDX."):
                names.add(parts[1])
        return names

    def has(self, encoder: str) -> bool:
        return encoder in self.encoders

    def detect_hardware(self) -> str | None:
        """Реально проверяет аппаратный кодировщик (наличие в списке ничего не значит)."""
        if self._hw_checked:
            return self._hw
        for enc in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"):
            if not self.has(enc):
                continue
            try:
                res = subprocess.run(
                    [
                        self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25:d=0.2",
                        "-frames:v", "1", "-c:v", enc, "-f", "null", "-",
                    ],
                    capture_output=True, timeout=30, **_popen_flags(),
                )
                if res.returncode == 0:
                    self._hw = enc
                    break
            except (OSError, subprocess.SubprocessError):
                continue
        self._hw_checked = True
        return self._hw

    def version(self) -> str:
        try:
            out = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-version"],
                capture_output=True,
                text=True,
                timeout=20,
                **_popen_flags(),
            ).stdout
            return out.splitlines()[0] if out else "ffmpeg"
        except (OSError, subprocess.SubprocessError):
            return "ffmpeg"


def _popen_flags() -> dict:
    if IS_WINDOWS:
        # не показывать консольные окна при вызове ffmpeg
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


# --------------------------------------------------------------------------- #
# Метаданные
# --------------------------------------------------------------------------- #

IMAGE_EXT = {
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".avif", ".bmp", ".dib",
    ".tif", ".tiff", ".gif", ".ico", ".heic", ".heif", ".tga", ".jxl", ".jp2",
    ".ppm", ".pgm", ".pbm", ".svg",
}
VIDEO_EXT = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv", ".mpg",
    ".mpeg", ".ts", ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".rmvb", ".asf", ".mxf",
}
AUDIO_EXT = {
    ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".wma",
    ".aiff", ".aif", ".alac", ".ape", ".amr", ".mka", ".caf",
}


@dataclass
class MediaInfo:
    path: Path
    kind: str  # image | video | audio | unknown
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    has_video: bool = False
    has_audio: bool = False
    size: int = 0
    bitrate: int = 0
    probe_failed: bool = False   # ffprobe не смог прочитать файл

    @property
    def size_label(self) -> str:
        return human_size(self.size)

    @property
    def duration_label(self) -> str:
        return human_duration(self.duration)

    @property
    def kind_label(self) -> str:
        return {"image": "картинка", "video": "видео", "audio": "звук"}.get(
            self.kind, "файл")

    @property
    def resolution_label(self) -> str:
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return ""


def human_size(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def human_duration(sec: float) -> str:
    if not sec or sec <= 0:
        return ""
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def guess_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return "unknown"


def _gif_is_animated(path: Path) -> bool:
    """Анимированный ли GIF — по числу кадров Pillow (её импорт не обязателен)."""
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with Image.open(path) as im:
            return int(getattr(im, "n_frames", 1)) > 1
    except Exception:  # noqa: BLE001 — битый gif просто не анимированный
        return False


def _probe_failed(info: MediaInfo) -> MediaInfo:
    """Файл не прочитался: помечаем и уточняем тип по содержимому.

    Для GIF одной догадки по расширению мало: анимированный GIF, отданный в
    Pillow-ветку, молча превратился бы в один статичный кадр. Поэтому кадры
    считаем через Pillow и такой файл считаем видео — дальше работает ffmpeg.
    """
    info.probe_failed = True
    if info.path.suffix.lower() == ".gif" and _gif_is_animated(info.path):
        info.kind = "video"
    return info


def probe(path: Path, tools: Tools) -> MediaInfo:
    """Читает метаданные через ffprobe; при ошибке возвращает догадку по расширению."""
    info = MediaInfo(path=Path(path), kind=guess_kind(Path(path)))
    try:
        info.size = Path(path).stat().st_size
    except OSError:
        pass
    try:
        raw = subprocess.run(
            [
                tools.ffprobe, "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            **_popen_flags(),
        )
        data = json.loads(raw.stdout or "{}")
        if raw.returncode != 0 or not (data.get("streams") or data.get("format")):
            return _probe_failed(info)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return _probe_failed(info)

    streams = data.get("streams", []) or []
    fmt = data.get("format", {}) or {}
    for st in streams:
        ctype = st.get("codec_type")
        if ctype == "video" and not info.has_video:
            # обложки/вложенные картинки в mp3 не считаем видео
            if (st.get("disposition") or {}).get("attached_pic"):
                continue
            info.has_video = True
            info.video_codec = st.get("codec_name", "")
            info.width = int(st.get("width") or 0)
            info.height = int(st.get("height") or 0)
            info.fps = _parse_fps(st.get("avg_frame_rate") or st.get("r_frame_rate") or "0/0")
        elif ctype == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = st.get("codec_name", "")

    try:
        info.duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        info.duration = 0.0
    try:
        info.bitrate = int(fmt.get("bit_rate") or 0)
    except (TypeError, ValueError):
        info.bitrate = 0

    guess = guess_kind(Path(path))
    if info.has_video:
        # одиночный кадр (gif/apng/анимированный webp тоже сюда попадут)
        info.kind = "image" if guess == "image" and info.duration <= 0.1 else "video"
    elif info.has_audio:
        info.kind = "audio"
    else:
        info.kind = guess if guess != "unknown" else "unknown"
    return info


def _parse_fps(value: str) -> float:
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den)
            return round(float(num) / den_f, 3) if den_f else 0.0
        return round(float(value), 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


# --------------------------------------------------------------------------- #
# Запуск задачи с прогрессом и отменой
# --------------------------------------------------------------------------- #


class Cancelled(RuntimeError):
    pass


class ConvertError(RuntimeError):
    pass


STDERR_TAIL = 200          # сколько последних строк stderr держим в памяти
_STDERR_LINE_MAX = 400     # одна строка тоже не должна быть безразмерной


def _drain_stderr(stream: IO[str] | None, tail: deque[str]) -> None:
    """Вычитывает stderr ffmpeg построчно, оставляя только последние строки.

    Без этого ffmpeg с большим объёмом диагностики (повреждённый файл,
    `-loglevel debug`) упирается в буфер канала (~64 КБ), встаёт на записи и
    перестаёт писать в stdout — а там висит наш цикл прогресса, вместе с
    проверкой отмены.
    """
    if stream is None:
        return
    try:
        for line in stream:
            tail.append(line.rstrip("\r\n")[:_STDERR_LINE_MAX])
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _start_stderr_reader(proc: subprocess.Popen, tail: deque[str]) -> threading.Thread:
    """Фоновый читатель stderr: daemon, чтобы не держать выход из процесса."""
    thread = threading.Thread(
        target=_drain_stderr,
        args=(proc.stderr, tail),
        name=f"ffmpeg-stderr-{proc.pid}",
        daemon=True,
    )
    thread.start()
    return thread


def run_ffmpeg(
    cmd: Sequence[str],
    duration: float = 0.0,
    on_progress: Callable[[float, str], None] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Запускает ffmpeg, транслирует прогресс (0..1) и поддерживает отмену.

    ffmpeg вызывается с `-progress pipe:1`, поэтому stdout содержит
    строки вида `out_time_us=1234567` и `speed=1.42x`. stderr читается
    отдельным потоком — иначе большой поток ошибок блокирует ffmpeg.
    """
    flags = _popen_flags()
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **flags,
    )
    speed = ""
    tail: deque[str] = deque(maxlen=STDERR_TAIL)
    reader = _start_stderr_reader(proc, tail)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                _kill(proc)
                raise Cancelled()
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                raw = line.split("=", 1)[1]
                try:
                    # ffmpeg исторически пишет микросекунды в out_time_ms
                    us = float(raw)
                except ValueError:
                    continue
                if duration > 0 and on_progress:
                    on_progress(min(0.999, max(0.0, us / 1_000_000.0 / duration)), speed)
            elif line.startswith("speed="):
                speed = line.split("=", 1)[1].strip()
            elif line.startswith(("progress=end", "progress=continue")) and on_progress:
                pass
        proc.wait(timeout=30)
    finally:
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass
        if proc.poll() is None:
            _kill(proc)
        # процесс закончился — читатель должен увидеть EOF и выйти
        reader.join(timeout=5.0)

    if proc.returncode not in (0, None) or (cancel and cancel.is_set()):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        err = "\n".join(tail)
        raise ConvertError(_short_error(err) or f"ffmpeg завершился с кодом {proc.returncode}")
    if on_progress:
        on_progress(1.0, speed)


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except (subprocess.SubprocessError, OSError):
        pass


def _short_error(stderr: str) -> str:
    lines = [l.strip() for l in stderr.splitlines() if l.strip()]
    if not lines:
        return ""
    interesting = [l for l in lines if "error" in l.lower() or "invalid" in l.lower()]
    return (interesting or lines)[-1][:300]


def iter_media_files(paths: Iterable[Path], recursive: bool = True) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            for f in sorted(p.glob(pattern)):
                if f.is_file() and guess_kind(f) != "unknown":
                    out.append(f)
        elif p.is_file():
            out.append(p)
    return out

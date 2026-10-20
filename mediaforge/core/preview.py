"""Кадры для предпросмотра: извлечение через ffmpeg, без Qt.

QtMultimedia в сборке нет (это +200 МБ и кодеки), поэтому «плеер» здесь — это
полоска кадров и один крупный кадр в позиции ползунка. Файлы кэшируются в
темпе по пути, mtime и параметрам запроса.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from .ffmpeg import MediaInfo, Tools, _popen_flags

CACHE_DIR = Path(tempfile.gettempdir()) / "mediaforge-preview"


def _cache_path(src: Path, tag: str, *parts) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        mtime = src.stat().st_mtime
    except OSError:
        mtime = 0
    raw = "|".join([str(src.resolve()), str(mtime), tag, *map(str, parts)])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{tag}-{digest}.png"


def _run(tools: Tools, args: list[str], out: Path) -> Path | None:
    cmd = [tools.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
           "-y", *args, str(out)]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=60, **_popen_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        return None
    return out


def frame_at(src: Path, tools: Tools, at: float, max_width: int = 720) -> Path | None:
    """Один кадр в позиции `at` секунд, уменьшенный до max_width."""
    out = _cache_path(src, "frame", round(at, 2), max_width)
    if out.exists():
        return out
    return _run(tools, [
        "-ss", f"{max(0.0, at):.3f}", "-i", str(src), "-frames:v", "1",
        "-vf", f"scale='min({max_width},iw)':-2:flags=lanczos",
    ], out)


def filmstrip(src: Path, tools: Tools, duration: float,
              count: int = 12, tile_width: int = 160) -> Path | None:
    """Полоска из `count` кадров, по одному на равных интервалах."""
    if duration <= 0:
        return None
    out = _cache_path(src, "strip", count, tile_width, round(duration, 2))
    if out.exists():
        return out
    fps = max(count / duration, 0.01)
    return _run(tools, [
        "-i", str(src),
        "-vf", f"fps={fps:.6f},scale={tile_width}:-2:flags=lanczos,"
               f"tile={count}x1:padding=0:margin=0",
        "-frames:v", "1",
    ], out)


def waveform(src: Path, tools: Tools, width: int = 900, height: int = 120) -> Path | None:
    """Картинка волновой формы для аудио (и для видео со звуком)."""
    out = _cache_path(src, "wave", width, height)
    if out.exists():
        return out
    return _run(tools, [
        "-i", str(src),
        "-filter_complex",
        f"aformat=channel_layouts=mono,showwavespic=s={width}x{height}:"
        "colors=#2E90EA:scale=sqrt",
        "-frames:v", "1",
    ], out)


def image_preview(src: Path, tools: Tools, max_px: int = 1000) -> Path | None:
    """Превью картинки: Pillow (понимает больше форматов, чем Qt), ffmpeg — резерв."""
    out = _cache_path(src, "img", max_px)
    if out.exists():
        return out
    try:
        from PIL import Image, ImageOps

        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            im.save(out, "PNG")
        return out
    except Exception:  # noqa: BLE001 — битый/неподдерживаемый файл: пробуем ffmpeg
        return _run(tools, [
            "-i", str(src), "-frames:v", "1",
            "-vf", f"scale='min({max_px},iw)':-2:flags=lanczos",
        ], out)


def cache_size() -> int:
    if not CACHE_DIR.exists():
        return 0
    return sum(f.stat().st_size for f in CACHE_DIR.glob("*") if f.is_file())


def cleanup() -> None:
    for f in CACHE_DIR.glob("*.png"):
        try:
            f.unlink()
        except OSError:
            pass


def thumbnail_path(src: Path, tools: Tools, info: MediaInfo) -> Path | None:
    """Универсальная точка входа для списка файлов и панели предпросмотра."""
    if info.kind == "image":
        return image_preview(src, tools)
    if info.kind == "audio":
        return waveform(src, tools)
    return frame_at(src, tools, min(1.0, (info.duration or 2.0) / 3))


__all__ = ["CACHE_DIR", "cache_size", "cleanup", "filmstrip", "frame_at",
           "image_preview", "thumbnail_path", "waveform"]

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


def filmstrip_frames(src: Path, tools: Tools, duration: float,
                     count: int = 12) -> list[Path]:
    """Кадры полоски: по одному `-ss` на кадр, параллельно.

    Декодировать файл целиком фильтром `fps,tile` нельзя: на длинном видео
    ffmpeg проходит его от начала до конца (минуты), а интерфейс в это время
    висит. Двенадцать отдельных seek'ов — доли секунды даже на часовом файле.
    """
    if duration <= 0:
        return []
    times = [(i + 0.5) * duration / count for i in range(count)]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda t: frame_at(src, tools, t, 320), times))
    return [p for p in paths if p is not None]


def filmstrip(src: Path, tools: Tools, duration: float,
              count: int = 12, tile_width: int = 160) -> Path | None:
    """Горизонтальная полоска из `count` кадров (собирается через Pillow)."""
    if duration <= 0:
        return None
    out = _cache_path(src, "strip", count, tile_width, round(duration, 2))
    if out.exists():
        return out
    frames = filmstrip_frames(src, tools, duration, count)
    if not frames:
        return None
    try:
        from PIL import Image

        tiles = []
        for path in frames:
            with Image.open(path) as im:
                im = im.convert("RGB")
                h = max(2, round(tile_width * im.height / im.width / 2) * 2)
                tiles.append(im.resize((tile_width, h), Image.LANCZOS))
        height = max(t.height for t in tiles)
        strip = Image.new("RGB", (tile_width * len(tiles), height), (0, 0, 0))
        for index, tile in enumerate(tiles):
            strip.paste(tile, (index * tile_width,
                               (height - tile.height) // 2))
        strip.save(out, "PNG")
        return out
    except Exception:  # noqa: BLE001 — без Pillow остаётся только кадр
        return None


def open_frame_stream(src: Path, tools: Tools, info: MediaInfo,
                      start: float, end: float, fps: int = 12,
                      max_height: int = 480) -> tuple[subprocess.Popen, int, int]:
    """Запускает ffmpeg, отдающий кадры rgb24 в stdout (для «проигрывания»).

    Возвращает (process, width, height). Кадр занимает width*height*3 байт.
    Звук не воспроизводится: полноценный плеер потребовал бы QtMultimedia.
    """
    height = max(2, min(max_height, info.height or max_height) // 2 * 2)
    width = max(2, round(height * (info.width or 16) / (info.height or 9) / 2) * 2)
    duration = max(0.05, (end or info.duration) - start)
    cmd = [
        tools.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        # -re: читаем вход в реальном времени, иначе ffmpeg за секунду
        # выплёвывает весь фрагмент и «проигрывание» мгновенно заканчивается
        "-re", "-ss", f"{max(0.0, start):.3f}", "-i", str(src), "-t", f"{duration:.3f}",
        "-vf", f"fps={fps},scale={width}:{height}:flags=fast_bilinear",
        "-an", "-sn", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, **_popen_flags(),
    )
    return proc, width, height


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


__all__ = ["CACHE_DIR", "cache_size", "cleanup", "filmstrip", "filmstrip_frames",
           "frame_at", "image_preview", "open_frame_stream", "thumbnail_path",
           "waveform"]

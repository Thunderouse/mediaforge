"""Сборка команды ffmpeg / вызов Pillow и фактическая конвертация одного файла."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import formats as fm
from .ffmpeg import (Cancelled, ConvertError, MediaInfo, Tools, guess_kind, probe,
                     run_ffmpeg)
from .timecode import format_timecode

ProgressCB = Callable[[float, str], None]

# --------------------------------------------------------------------------- #
# Качество: CRF/пресеты по кодекам
# --------------------------------------------------------------------------- #

_X264 = {"high": (17, "slow"), "balanced": (23, "medium"), "small": (28, "faster")}
_X265 = {"high": (20, "medium"), "balanced": (26, "fast"), "small": (31, "faster")}
_VP9 = {"high": 24, "balanced": 32, "small": 40}
_MPEG4_Q = {"high": 2, "balanced": 4, "small": 7}

_AUDIO_CODECS = {
    "mp3": ("libmp3lame", "mp3"),
    "m4a": ("aac", "m4a"),
    "wav": ("pcm_s16le", "wav"),
    "flac": ("flac", "flac"),
    "opus": ("libopus", "opus"),
    "ogg": ("libvorbis", "ogg"),
}

def _int_or_zero(value) -> int:
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def target_image_size(size: tuple[int, int], opts: fm.ConvertOptions) -> tuple[int, int]:
    """Итоговый размер картинки: «Разрешение» (ограничение по длинной стороне),
    затем явный масштаб (проценты или ширина×высота).

    Явный масштаб (проценты и «свой размер») применяется всегда — это прямое
    указание пользователя. Флажок `image_allow_upscale` ограничивает только
    список «Разрешение»: без него 1080p не растянет маленькое фото.
    """
    width, height = size
    if width <= 0 or height <= 0:
        return max(1, width), max(1, height)

    max_edge = _IMG_MAX_EDGE.get(opts.resolution)
    if max_edge:
        longest = max(width, height)
        if longest > max_edge:
            k = max_edge / longest
            width, height = max(1, round(width * k)), max(1, round(height * k))
        elif opts.image_allow_upscale and longest < max_edge:
            k = max_edge / longest
            width, height = max(1, round(width * k)), max(1, round(height * k))

    if opts.image_scale == "percent":
        try:
            percent = float(str(opts.image_percent).replace(",", ".").strip())
        except (TypeError, ValueError):
            raise ConvertError("Некорректный процент масштаба") from None
        if percent <= 0:
            raise ConvertError("Процент масштаба должен быть больше нуля")
        k = percent / 100.0
        width, height = max(1, round(width * k)), max(1, round(height * k))
    elif opts.image_scale == "size":
        target_w = _int_or_zero(opts.image_width)
        target_h = _int_or_zero(opts.image_height)
        if not target_w and not target_h:
            raise ConvertError("Укажите ширину и/или высоту для масштабирования")
        if opts.image_keep_ratio:
            if target_w and target_h:
                k = min(target_w / width, target_h / height)
            elif target_w:
                k = target_w / width
            else:
                k = target_h / height
            width, height = max(1, round(width * k)), max(1, round(height * k))
        else:
            width, height = max(1, target_w or width), max(1, target_h or height)
    return width, height


_IMG_QUALITY = {
    # (jpeg/webp/avif quality, png compress level)
    "high": (95, 9),
    "balanced": (85, 7),
    "small": (72, 9),
}


def _threads(gentle: bool) -> list[str]:
    if not gentle:
        return []
    n = max(1, (os.cpu_count() or 4) // 2)
    return ["-threads", str(n), "-filter_threads", str(n)]


def _meta(opts: fm.ConvertOptions) -> list[str]:
    return ["-map_metadata", "0"] if opts.keep_metadata else ["-map_metadata", "-1"]


def _scale_chain(info: MediaInfo, opts: fm.ConvertOptions) -> list[str]:
    """Фильтры масштабирования: разрешение — это ограничение по высоте.

    Одно правило для видео и GIF: `-2` даёт чётную ширину (требование H.264
    и большинства GIF-декодеров), апскейл не делаем.
    """
    if opts.resolution == "original":
        return []
    target_h = int(opts.resolution)
    if info.height and info.height <= target_h:
        return []
    return [f"scale=-2:{target_h}:flags=lanczos"]


def _scale_video(info: MediaInfo, opts: fm.ConvertOptions) -> list[str]:
    chain = _scale_chain(info, opts)
    return ["-vf", ",".join(chain)] if chain else []


def _pick_encoder(tools: Tools, preferred: str, fallbacks: tuple[str, ...]) -> str | None:
    for enc in (preferred, *fallbacks):
        if tools.has(enc):
            return enc
    return None


def _hw_encoder(tools: Tools) -> str | None:
    return tools.detect_hardware()


def trim_plan(info: MediaInfo, opts: fm.ConvertOptions) -> tuple[list[str], list[str], float]:
    """Аргументы ffmpeg для вырезания фрагмента и его длительность.

    `-ss` ставится до `-i` (быстрый seek), `-t` — после (длительность вырезки).
    Возвращает ([], [], duration) если фрагмент не задан.
    """
    start = max(0.0, float(opts.trim_start or 0.0))
    end = float(opts.trim_end or 0.0)
    total = info.duration or 0.0

    if start and total and start >= total:
        raise ConvertError(
            f"Начало фрагмента ({format_timecode(start)}) за пределами файла "
            f"({format_timecode(total)})"
        )
    if end and total and end > total:
        end = total
    if end and end <= start:
        raise ConvertError("Конец фрагмента должен быть больше его начала")
    if not start and not end:
        return [], [], total

    pre = ["-ss", f"{start:.3f}"] if start else []
    if end:
        duration = end - start
    else:
        duration = max(0.0, total - start) if total else 0.0
    post = ["-t", f"{duration:.3f}"] if duration > 0 else []
    return pre, post, duration or total


# --------------------------------------------------------------------------- #
# Видео / аудио / GIF: аргументы ffmpeg
# --------------------------------------------------------------------------- #


def build_video_cmd(
    src: Path, dst: Path, info: MediaInfo, target: fm.Target,
    opts: fm.ConvertOptions, tools: Tools,
) -> tuple[list[str], str]:
    """Возвращает (argv, примечание)."""
    note = ""
    vf = _scale_video(info, opts)
    trim_pre, trim_post, _ = trim_plan(info, opts)
    cmd = [
        tools.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-progress", "pipe:1", *trim_pre, "-i", str(src), *trim_post,
    ]
    audio_out: list[str] = []
    video_out: list[str] = []
    key = target.key
    color_pix = ["-pix_fmt", "yuv420p"]

    def h264_args() -> list[str]:
        nonlocal note
        if opts.gpu:
            enc = _hw_encoder(tools)
            if enc == "h264_nvenc":
                q = {"high": 20, "balanced": 25, "small": 31}[opts.quality]
                preset = {"high": "p5", "balanced": "p4", "small": "p3"}[opts.quality]
                return ["-c:v", enc, "-preset", preset, "-rc", "vbr", "-cq", str(q), "-b:v", "0"]
            if enc == "h264_videotoolbox":
                q = {"high": 60, "balanced": 50, "small": 40}[opts.quality]
                return ["-c:v", enc, "-q:v", str(q)]
            if enc == "h264_qsv":
                q = {"high": 21, "balanced": 26, "small": 32}[opts.quality]
                return ["-c:v", enc, "-preset", "medium", "-global_quality", str(q)]
            if enc == "h264_amf":
                q = {"high": 21, "balanced": 26, "small": 32}[opts.quality]
                return ["-c:v", enc, "-quality", "balanced", "-rc", "cqp",
                        "-qp_i", str(q), "-qp_p", str(q + 2)]
            note = "GPU-кодировщик не найден — использован CPU"
        crf, preset = _X264[opts.quality]
        enc = _pick_encoder(tools, "libx264", ("libopenh264",))
        if enc is None:
            raise ConvertError("В сборке ffmpeg нет кодировщика H.264")
        return ["-c:v", enc, "-preset", preset, "-crf", str(crf), "-profile:v", "high"]

    if key in ("mp4", "mov", "mkv264"):
        video_out = h264_args() + color_pix
        audio_out = ["-c:a", "aac", "-b:a", "160k" if opts.quality != "high" else "192k",
                     "-ac", "2"]
        if key == "mp4":
            video_out += ["-movflags", "+faststart"]
        elif key == "mov":
            video_out += ["-movflags", "+faststart", "-tag:v", "avc1"]
        else:
            video_out += ["-tag:v", "avc1"]
    elif key == "mkv":
        crf, preset = _X265[opts.quality]
        enc = _pick_encoder(tools, "libx265", ())
        if enc is None:
            video_out = h264_args() + color_pix
            note = "H.265 недоступен — использован H.264"
        else:
            video_out = ["-c:v", enc, "-preset", preset, "-crf", str(crf),
                         "-x265-params", "log-level=error", "-tag:v", "hvc1"] + color_pix
        audio_out = ["-c:a", "aac", "-b:a", "160k"]
    elif key == "webm":
        crf = _VP9[opts.quality]
        enc = _pick_encoder(tools, "libvpx-vp9", ("libvpx",))
        if enc is None:
            raise ConvertError("В сборке ffmpeg нет кодировщика VP9")
        video_out = ["-c:v", enc, "-crf", str(crf), "-b:v", "0",
                     "-row-mt", "1", "-deadline", "good", "-cpu-used",
                     "2" if opts.quality != "small" else "4"] + color_pix
        aenc = "libopus" if tools.has("libopus") else "libvorbis"
        audio_out = ["-c:a", aenc, "-b:a", "128k"]
    elif key == "avi":
        q = _MPEG4_Q[opts.quality]
        video_out = ["-c:v", "mpeg4", "-q:v", str(q), "-vtag", "XVID"] + color_pix
        audio_out = ["-c:a", "libmp3lame", "-b:a", "192k"] if tools.has("libmp3lame") else []
    else:  # gif обрабатывается отдельно
        raise ConvertError(f"Неизвестный формат видео: {key}")

    cmd += ["-map", "0:v:0", "-map", "0:a?", *vf, *video_out, *audio_out,
            *_meta(opts), *_threads(opts.gentle), str(dst)]
    return cmd, note


def build_gif_cmd(
    src: Path, dst: Path, info: MediaInfo, opts: fm.ConvertOptions, tools: Tools,
) -> list[str]:
    fps = int(opts.gif_fps or 15)
    chain = [f"fps={fps}", *_scale_chain(info, opts)]
    chain.append("split[s0][s1];[s0]palettegen=max_colors=256:stats_mode=diff[p];"
                 "[s1][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle")
    vf = ",".join(chain)
    trim_pre, trim_post, _ = trim_plan(info, opts)
    return [
        tools.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-progress", "pipe:1", *trim_pre, "-i", str(src), *trim_post,
        "-an", "-sn", "-vf", vf, "-loop", "0" if opts.gif_loop else "-1",
        *_threads(opts.gentle), str(dst),
    ]


def build_audio_cmd(
    src: Path, dst: Path, info: MediaInfo, target: fm.Target,
    opts: fm.ConvertOptions, tools: Tools,
) -> list[str]:
    if not info.has_audio:
        raise ConvertError("В этом файле нет звуковой дорожки")
    codec, _ = _AUDIO_CODECS[target.key]
    if not tools.has(codec) and codec == "libvorbis":
        codec = "libopus"
    args = ["-vn", "-sn", "-dn", "-c:a", codec]
    if codec in ("libmp3lame", "aac", "libopus", "libvorbis"):
        bitrate = opts.audio_bitrate
        if codec == "libopus":
            bitrate = {"320k": "192k", "256k": "160k"}.get(bitrate, "128k")
        args += ["-b:a", bitrate]
    if codec == "pcm_s16le":
        args += ["-ar", "48000", "-ac", "2"]
    if target.key == "m4a":
        args += ["-movflags", "+faststart"]
    trim_pre, trim_post, _ = trim_plan(info, opts)
    return [
        tools.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-progress", "pipe:1", *trim_pre, "-i", str(src), *trim_post,
        *args, *_meta(opts), *_threads(opts.gentle), str(dst),
    ]


# --------------------------------------------------------------------------- #
# Изображения: Pillow, с откатом на ffmpeg
# --------------------------------------------------------------------------- #

_IMG_MAX_EDGE = {"2160": 2160, "1440": 1440, "1080": 1080, "720": 720, "480": 480}


def _convert_image_pillow(
    src: Path, dst: Path, target: fm.Target, opts: fm.ConvertOptions,
) -> None:
    from PIL import Image, ImageOps  # мягкая зависимость

    quality, level = _IMG_QUALITY[opts.quality]
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        new_size = target_image_size(im.size, opts)
        if new_size != im.size:
            resample = {
                "lanczos": Image.LANCZOS,
                "bicubic": Image.BICUBIC,
                "nearest": Image.NEAREST,
            }.get(opts.image_filter, Image.LANCZOS)
            im = im.resize(new_size, resample)

        key = target.key
        params: dict = {}
        if key == "jpg":
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            params = {"quality": quality, "optimize": True, "progressive": True,
                      "subsampling": 1 if quality >= 90 else 2}
        elif key == "png":
            params = {"optimize": True, "compress_level": level}
        elif key == "webp":
            params = {"quality": quality, "method": 6 if quality >= 85 else 4}
            if im.mode == "P":
                im = im.convert("RGBA")
        elif key == "avif":
            params = {"quality": quality, "speed": 4}
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        elif key == "tiff":
            params = {"compression": "tiff_lzw"}
        elif key == "bmp":
            if im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGB")
        elif key in ("gif", "gif_img"):
            im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
            im = im.convert("P", palette=Image.ADAPTIVE, colors=256)
            params = {"optimize": True, "save_all": False}
        elif key == "ico":
            im = im.convert("RGBA") if im.mode != "RGBA" else im
            side = max(16, min(256, min(im.size)))
            im = im.copy()
            im.thumbnail((side, side), Image.LANCZOS)
            params = {"sizes": [(s, s) for s in (16, 32, 48, 64, 128, 256) if s <= side]}
        elif key == "pdf":
            if im.mode != "RGB":
                im = im.convert("RGB")
            params = {"resolution": 150.0}
        else:
            raise ConvertError(f"Формат {target.label} не поддерживается")
        im.save(dst, **params)


def _convert_image_ffmpeg(
    src: Path, dst: Path, target: fm.Target, opts: fm.ConvertOptions, tools: Tools,
    info: MediaInfo | None = None,
) -> None:
    quality, _ = _IMG_QUALITY[opts.quality]
    info = info or probe(src, tools)
    info_size = (info.width or 0, info.height or 0)
    target = target_image_size(info_size, opts) if all(info_size) else info_size
    flags = {"lanczos": "lanczos", "bicubic": "bicubic", "nearest": "neighbor"}.get(
        opts.image_filter, "lanczos")
    vf = []
    if target and all(info_size) and target != info_size:
        vf = ["-vf", f"scale={target[0]}:{target[1]}:flags={flags}"]
    cmd = [tools.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(src), "-frames:v", "1"]
    if target.key == "avif":
        enc = "libaom-av1" if tools.has("libaom-av1") else ("libsvtav1" if tools.has("libsvtav1") else None)
        if enc is None:
            raise ConvertError("Нет кодировщика AVIF (libaom-av1/libsvtav1)")
        crf = {"high": 24, "balanced": 30, "small": 38}[opts.quality]
        cmd += ["-c:v", enc, "-crf", str(crf), "-b:v", "0", "-still-picture", "1",
                "-pix_fmt", "yuv420p"]
    elif target.key in ("png", "png_lossless"):
        cmd += ["-c:v", "png"]
    else:
        cmd += ["-q:v", str(max(1, min(31, 31 - quality // 4)))]
    cmd += [*vf, str(dst)]
    run_ffmpeg(cmd)


# --------------------------------------------------------------------------- #
# Публичный API
# --------------------------------------------------------------------------- #


def unique_path(directory: Path, stem: str, ext: str, overwrite: bool = False) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}.{ext}"
    if overwrite:
        return candidate
    i = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({i}).{ext}"
        i += 1
    return candidate


@dataclass
class ConversionResult:
    output: Path
    note: str = ""


def convert_file(
    src: Path,
    target: fm.Target,
    opts: fm.ConvertOptions,
    tools: Tools,
    out_dir: Path,
    info: MediaInfo | None = None,
    on_progress: ProgressCB | None = None,
    cancel: threading.Event | None = None,
) -> ConversionResult:
    src = Path(src)
    if info is None:
        info = MediaInfo(path=src, kind=guess_kind(src)) if tools is None else probe(src, tools)
    if info.kind == "unknown":
        raise ConvertError("Неизвестный тип файла")
    # проверяем границы фрагмента до создания файлов
    _, _, effective_duration = trim_plan(info, opts)
    note = ""

    is_image_path = target.kind == fm.KIND_IMAGE or target.key == "gif_img" or (
        target.key == "gif" and info.kind == "image"
    )
    ext = "gif" if target.key.startswith("gif") else target.ext
    dst = unique_path(out_dir, src.stem, ext, opts.overwrite)
    if dst.resolve() == src.resolve():
        dst = unique_path(out_dir, src.stem, ext, overwrite=False)

    try:
        if is_image_path:
            if on_progress:
                on_progress(0.05, "")
            try:
                _convert_image_pillow(src, dst, target, opts)
            except ImportError:
                if tools is None:
                    raise ConvertError("Для этого формата нужен ffmpeg или Pillow")
                _convert_image_ffmpeg(src, dst, target, opts, tools, info)
            if on_progress:
                on_progress(1.0, "")
        elif target.key == "gif":
            if tools is None:
                raise ConvertError("Для видео нужен ffmpeg")
            cmd = build_gif_cmd(src, dst, info, opts, tools)
            run_ffmpeg(cmd, effective_duration, on_progress, cancel)
        elif target.kind == fm.KIND_AUDIO:
            if tools is None:
                raise ConvertError("Для извлечения звука нужен ffmpeg")
            cmd = build_audio_cmd(src, dst, info, target, opts, tools)
            run_ffmpeg(cmd, effective_duration, on_progress, cancel)
        else:
            if info.kind == "audio":
                raise ConvertError("Это аудиофайл — выберите аудиоформат")
            if tools is None:
                raise ConvertError("Для конвертации видео нужен ffmpeg")
            cmd, note = build_video_cmd(src, dst, info, target, opts, tools)
            run_ffmpeg(cmd, effective_duration, on_progress, cancel)
    except BaseException:
        _cleanup(dst)
        raise

    if not dst.exists() or dst.stat().st_size == 0:
        _cleanup(dst)
        raise ConvertError("ffmpeg не создал выходной файл")
    return ConversionResult(output=dst, note=note)


def _cleanup(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


__all__ = [
    "Cancelled",
    "ConversionResult",
    "ConvertError",
    "convert_file",
    "unique_path",
    "build_audio_cmd",
    "build_gif_cmd",
    "build_video_cmd",
]

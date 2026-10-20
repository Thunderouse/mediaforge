"""Консольный интерфейс MediaForge — на случай автоматизации или headless-сервера.

    python -m mediaforge.cli video.mp4 --to gif --fps 12 -r 480
    python -m mediaforge.cli *.png --to webp --quality small --out ./out
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import formats as fm
from .core.convert import ConvertError, convert_file
from .core.ffmpeg import (FFmpegNotFound, Tools, iter_media_files,
                          probe)
from .core.timecode import parse_timecode


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mediaforge",
        description="Конвертация видео, изображений и звука через ffmpeg",
    )
    p.add_argument("inputs", nargs="+", help="Файлы или папки")
    p.add_argument("-t", "--to", required=True,
                   help="Целевой формат: mp4, mkv, webm, mov, avi, gif, mp3, m4a, "
                        "wav, flac, opus, ogg, png, jpg, webp, avif, tiff, bmp, ico, pdf")
    p.add_argument("-o", "--out", default=".", help="Папка для результатов")
    p.add_argument("-q", "--quality", choices=[q for q, _ in fm.QUALITY_LABELS],
                   default="balanced", help="Качество (по умолчанию balanced)")
    p.add_argument("-r", "--resolution", default="original",
                   help="2160/1440/1080/720/480 или original (видео, GIF, картинки)")
    p.add_argument("--fps", default="15", help="FPS для GIF")
    p.add_argument("--no-loop", action="store_true", help="GIF без зацикливания")
    p.add_argument("--bitrate", default="192k", help="Битрейт аудио (mp3/aac/opus)")
    p.add_argument("--overwrite", action="store_true", help="Перезаписывать файлы")
    p.add_argument("--start", default="", help="Начало фрагмента: 1:30 или секунды")
    p.add_argument("--end", default="", help="Конец фрагмента (по умолчанию до конца)")
    p.add_argument("--gpu", action="store_true", help="Аппаратное кодирование")
    p.add_argument("--gentle", action="store_true", help="Меньше нагрузки на CPU")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        tools = Tools.locate()
    except FFmpegNotFound as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    key = args.to.lower().lstrip(".")
    if key == "jpeg":
        key = "jpg"
    target = fm.BY_KEY.get(key)
    if target is None:
        print(f"Ошибка: неизвестный формат '{args.to}'", file=sys.stderr)
        return 2

    try:
        trim_start = parse_timecode(args.start) or 0.0
        trim_end = parse_timecode(args.end) or 0.0
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    opts = fm.ConvertOptions(
        quality=args.quality, resolution=args.resolution, gif_fps=args.fps,
        gif_loop=not args.no_loop,
        audio_bitrate=args.bitrate, overwrite=args.overwrite,
        gpu=args.gpu, gentle=args.gentle,
        trim_start=trim_start, trim_end=trim_end,
    )
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    files = iter_media_files([Path(p) for p in args.inputs], recursive=True)
    if not files:
        print("Не найдено поддерживаемых файлов", file=sys.stderr)
        return 1

    failed = 0
    for src in files:
        try:
            info = probe(src, tools)
            compat = {t.key for t in fm.targets_for(info.kind)}
            if target.key not in compat:
                print(f"  пропуск {src.name}: формат {target.label} не подходит для "
                      f"{info.kind}", file=sys.stderr)
                failed += 1
                continue
            last = {"p": -1}

            def progress(p: float, speed: str) -> None:
                pct = int(p * 100)
                if pct != last["p"]:
                    last["p"] = pct
                    print(f"\r  {src.name}: {pct:3d}% {speed:>7s}", end="", flush=True)

            result = convert_file(src, target, opts, tools, out_dir,
                                  info=info, on_progress=progress)
            print(f"\r  {src.name} → {result.output.name} "
                  f"({result.output.stat().st_size / 1024:.0f} КБ)"
                  f"{' · ' + result.note if result.note else ''}")
        except (ConvertError, OSError, ValueError) as exc:
            failed += 1
            print(f"\r  {src.name}: ошибка — {exc}", file=sys.stderr)
    print(f"Готово: {len(files) - failed} из {len(files)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

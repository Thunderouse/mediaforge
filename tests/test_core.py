"""Тесты ядра MediaForge (GUI не требуется).

    python -m pytest            # всё
    python -m pytest -k image   # только изображения
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from mediaforge.core import formats as fm
from mediaforge.core.convert import (ConvertError, build_audio_cmd, build_gif_cmd,
                                     build_video_cmd, convert_file, trim_plan,
                                     unique_path)
from mediaforge.core import preview as pv
from mediaforge.core.timecode import format_timecode, parse_timecode
from mediaforge.core.ffmpeg import (MediaInfo, Tools, human_duration, human_size,
                                   iter_media_files, probe)

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="нет ffmpeg в системе")


@pytest.fixture(scope="session")
def tools() -> Tools:
    if not FFMPEG:
        pytest.skip("нет ffmpeg")
    return Tools.locate()


@pytest.fixture(scope="session")
def media(tmp_path_factory) -> dict[str, Path]:
    """Готовит тестовые файлы: видео со звуком, беззвучное видео, картинки, wav."""
    d = tmp_path_factory.mktemp("media")
    out: dict[str, Path] = {}
    if FFMPEG:
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
             "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
             "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "clip.mp4")],
            check=True,
        )
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-t", "1",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an",
             str(d / "silent.mp4")],
            check=True,
        )
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=220:duration=1", str(d / "tone.wav")],
            check=True,
        )
        out["clip"] = d / "clip.mp4"
        out["silent"] = d / "silent.mp4"
        out["wav"] = d / "tone.wav"
    try:
        from PIL import Image
        Image.new("RGBA", (160, 100), (30, 120, 240, 255)).save(d / "pic.png")
        Image.new("RGB", (80, 60), (200, 40, 40)).save(d / "pic.jpg")
        out["png"] = d / "pic.png"
        out["jpg"] = d / "pic.jpg"
    except ImportError:
        pass
    return out


# --------------------------------------------------------------------------- #
# Реестр форматов
# --------------------------------------------------------------------------- #
def test_every_target_has_unique_ext():
    for target in fm.ALL_TARGETS:
        assert target.ext and "." not in target.ext
        assert target.label


def test_targets_for_kinds():
    assert "webp" in {t.key for t in fm.targets_for("image")}
    video_keys = {t.key for t in fm.targets_for("video")}
    assert {"mp4", "gif", "mp3"} <= video_keys
    assert "mp4" not in {t.key for t in fm.targets_for("audio")}


def test_default_target_never_returns_missing():
    for ext, kind in ((".png", "image"), (".mp4", "video"), (".flac", "audio")):
        assert fm.default_target(ext, kind) in fm.BY_KEY


# --------------------------------------------------------------------------- #
# Утилиты
# --------------------------------------------------------------------------- #
def test_humanizers():
    assert human_size(0) == "0 Б"
    assert human_size(1536) == "1.5 КБ"
    assert human_duration(0) == ""
    assert human_duration(65) == "1:05"
    assert human_duration(3725) == "1:02:05"


def test_unique_path(tmp_path):
    first = unique_path(tmp_path, "clip", "mp4")
    assert first.name == "clip.mp4"
    first.write_bytes(b"x")
    assert unique_path(tmp_path, "clip", "mp4").name == "clip (1).mp4"
    assert unique_path(tmp_path, "clip", "mp4", overwrite=True) == first


def test_iter_media_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "sub" / "b.mp4").write_bytes(b"x")
    # encoding обязателен: на Windows локаль по умолчанию cp1252 и кириллица падает
    (tmp_path / "note.txt").write_text("не медиа", encoding="utf-8")
    found = {p.name for p in iter_media_files([tmp_path], recursive=True)}
    assert found == {"a.png", "b.mp4"}


# --------------------------------------------------------------------------- #
# Метаданные и конвертация
# --------------------------------------------------------------------------- #
@needs_ffmpeg
def test_probe_video(tools, media):
    info = probe(media["clip"], tools)
    assert info.kind == "video"
    assert info.has_video and info.has_audio
    assert (info.width, info.height) == (320, 240)
    assert 1.5 < info.duration < 3.0


@needs_ffmpeg
def test_probe_image(tools, media):
    info = probe(media["png"], tools)
    assert info.kind == "image"
    assert info.resolution_label == "160×100"


def test_image_conversion_chain(tmp_path, media):
    pytest.importorskip("PIL")
    if "png" not in media:
        pytest.skip("нет тестовых картинок")
    src = media["png"]
    for key in ("webp", "jpg", "tiff", "bmp", "ico", "pdf", "avif"):
        out = convert_file(src, fm.BY_KEY[key], fm.ConvertOptions(), None, tmp_path)  # type: ignore[arg-type]
        assert out.output.exists() and out.output.stat().st_size > 0
    # jpg из картинки с прозрачностью не должен падать
    assert (tmp_path / "pic.jpg").exists()


def test_image_resize_respects_long_edge(tmp_path, media):
    pytest.importorskip("PIL")
    from PIL import Image
    if "png" not in media:
        pytest.skip("нет тестовых картинок")
    opts = fm.ConvertOptions(resolution="480")
    big = tmp_path / "big.png"
    Image.new("RGB", (1600, 800), (0, 0, 0)).save(big)
    res = convert_file(big, fm.BY_KEY["png"], opts, None, tmp_path)  # type: ignore[arg-type]
    with Image.open(res.output) as im:
        assert max(im.size) == 480


@needs_ffmpeg
def test_video_to_mp4_and_webm(tools, media, tmp_path):
    for key in ("mp4", "webm"):
        res = convert_file(media["clip"], fm.BY_KEY[key], fm.ConvertOptions(quality="small"),
                           tools, tmp_path)
        info = probe(res.output, tools)
        assert info.has_video
        assert res.output.stat().st_size > 0


@needs_ffmpeg
def test_video_to_gif_has_frames(tools, media, tmp_path):
    opts = fm.ConvertOptions(gif_fps="10", resolution="120")
    res = convert_file(media["clip"], fm.BY_KEY["gif"], opts, tools, tmp_path)
    info = probe(res.output, tools)
    assert res.output.suffix == ".gif"
    assert info.kind in ("image", "video")
    assert res.output.stat().st_size > 1000


@needs_ffmpeg
def test_audio_extraction(tools, media, tmp_path):
    for key in ("mp3", "wav", "flac", "m4a"):
        res = convert_file(media["clip"], fm.BY_KEY[key], fm.ConvertOptions(), tools, tmp_path)
        info = probe(res.output, tools)
        assert info.has_audio and not info.has_video


@needs_ffmpeg
def test_audio_extraction_without_track_fails(tools, media, tmp_path):
    with pytest.raises(ConvertError):
        convert_file(media["silent"], fm.BY_KEY["mp3"], fm.ConvertOptions(), tools, tmp_path)


@needs_ffmpeg
def test_cancel_stops_conversion(tools, media, tmp_path):
    import threading
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Exception):
        convert_file(media["clip"], fm.BY_KEY["mkv"], fm.ConvertOptions(), tools, tmp_path,
                     cancel=cancel)


# --------------------------------------------------------------------------- #
# Сборка команд
# --------------------------------------------------------------------------- #
def test_gif_command_uses_two_pass_palette(tools, media):
    if "clip" not in media:
        pytest.skip("нет тестового видео")
    info = MediaInfo(path=media["clip"], kind="video", duration=2.0,
                     width=1920, height=1080, has_video=True, has_audio=True)
    cmd = build_gif_cmd(media["clip"], Path("out.gif"), info,
                        fm.ConvertOptions(gif_fps="12", resolution="480"), tools)
    joined = " ".join(cmd)
    assert "palettegen" in joined and "paletteuse" in joined
    assert "fps=12" in joined
    # масштаб GIF берётся из общего «Разрешения» — по высоте, с чётной шириной
    assert "scale=-2:480" in joined
    assert "scale=480:-1" not in joined


def test_gif_does_not_upscale(tools, media):
    if "clip" not in media:
        pytest.skip("нет тестового видео")
    info = MediaInfo(path=media["clip"], kind="video", duration=2.0,
                     width=320, height=240, has_video=True)
    cmd = build_gif_cmd(media["clip"], Path("out.gif"), info,
                        fm.ConvertOptions(gif_fps="10", resolution="1080"), tools)
    assert "scale=" not in " ".join(cmd)


def test_audio_command_maps_only_audio(tools, media):
    info = probe(media["wav"], tools) if "wav" in media else None
    if info is None:
        pytest.skip("нет тестового аудио")
    cmd = build_audio_cmd(media["wav"], Path("out.mp3"), info, fm.BY_KEY["mp3"],
                          fm.ConvertOptions(audio_bitrate="256k"), tools)
    joined = " ".join(cmd)
    assert "-vn" in joined and "libmp3lame" in joined and "256k" in joined


def test_gentle_mode_limits_threads(tools, media):
    if "clip" not in media:
        pytest.skip("нет тестового видео")
    info = probe(media["clip"], tools)
    cmd = build_audio_cmd(media["clip"], Path("o.mp3"), info, fm.BY_KEY["mp3"],
                          fm.ConvertOptions(gentle=True), tools)
    assert "-threads" in cmd


# --------------------------------------------------------------------------- #
# Таймкоды и вырезание фрагмента
# --------------------------------------------------------------------------- #
def test_parse_timecode_formats():
    assert parse_timecode("0") == 0.0
    assert parse_timecode("") is None
    assert parse_timecode("   ") is None
    assert parse_timecode(None) is None
    assert parse_timecode("90") == 90.0
    assert parse_timecode("1:30") == 90.0
    assert parse_timecode("00:01:30") == 90.0
    assert parse_timecode("1:30.5") == 90.5
    assert parse_timecode("1:30,25") == 90.25
    assert parse_timecode("0:00:01.250") == 1.25


def test_parse_timecode_rejects_garbage():
    for bad in ("abc", "1:75", "1:2:3:4", "-5"):
        with pytest.raises(ValueError):
            parse_timecode(bad)


def test_format_timecode():
    assert format_timecode(0) == "0:00"
    assert format_timecode(90.5) == "1:30.5"
    assert format_timecode(3675) == "1:01:15"
    assert format_timecode(-1) == ""


@needs_ffmpeg
def test_trim_plan_fragment(tools, media):
    info = probe(media["clip"], tools)
    opts = fm.ConvertOptions(trim_start=0.5, trim_end=1.5)
    pre, post, duration = trim_plan(info, opts)
    assert pre == ["-ss", "0.500"]
    assert post == ["-t", "1.000"]
    assert duration == pytest.approx(1.0)


def test_trim_plan_without_fragment(media):
    info = MediaInfo(path=Path("x.mp4"), kind="video", duration=10.0)
    assert trim_plan(info, fm.ConvertOptions()) == ([], [], 10.0)


def test_trim_plan_validation():
    info = MediaInfo(path=Path("x.mp4"), kind="video", duration=10.0)
    with pytest.raises(ConvertError):
        trim_plan(info, fm.ConvertOptions(trim_start=5, trim_end=5))
    with pytest.raises(ConvertError):
        trim_plan(info, fm.ConvertOptions(trim_start=20))
    # конец за пределами файла аккуратно подрезается
    _, post, duration = trim_plan(info, fm.ConvertOptions(trim_start=8, trim_end=99))
    assert post == ["-t", "2.000"]
    assert duration == pytest.approx(2.0)


@needs_ffmpeg
def test_video_trim_actually_cuts(tools, media, tmp_path):
    opts = fm.ConvertOptions(trim_start=0.5, trim_end=1.5)
    res = convert_file(media["clip"], fm.BY_KEY["mp4"], opts, tools, tmp_path)
    info = probe(res.output, tools)
    assert info.duration == pytest.approx(1.0, abs=0.25)


@needs_ffmpeg
def test_gif_and_audio_trim(tools, media, tmp_path):
    opts = fm.ConvertOptions(trim_start=0.2, trim_end=1.2, gif_fps="10")
    gif = convert_file(media["clip"], fm.BY_KEY["gif"], opts, tools, tmp_path)
    assert probe(gif.output, tools).duration == pytest.approx(1.0, abs=0.3)
    mp3 = convert_file(media["clip"], fm.BY_KEY["mp3"], opts, tools, tmp_path)
    assert probe(mp3.output, tools).duration == pytest.approx(1.0, abs=0.3)


def test_trim_args_in_commands(tools, media):
    if "clip" not in media:
        pytest.skip("нет тестового видео")
    info = probe(media["clip"], tools)
    opts = fm.ConvertOptions(trim_start=1.0, trim_end=2.0)
    for cmd in (
        build_gif_cmd(media["clip"], Path("o.gif"), info, opts, tools),
        build_audio_cmd(media["clip"], Path("o.mp3"), info, fm.BY_KEY["mp3"], opts, tools),
        build_video_cmd(media["clip"], Path("o.mp4"), info, fm.BY_KEY["mp4"], opts, tools)[0],
    ):
        joined = " ".join(cmd)
        # -ss должен стоять до -i, -t — после
        assert joined.index("-ss 1.000") < joined.index("-i ")
        assert "-t 1.000" in joined


# --------------------------------------------------------------------------- #
# Предпросмотр (кадры, полоска, волна)
# --------------------------------------------------------------------------- #
@needs_ffmpeg
def test_preview_frame_and_strip(tools, media, tmp_path):
    from PIL import Image

    pytest.importorskip("PIL")
    assert "clip" in media, "нужно тестовое видео"
    pv.cleanup()
    frame = pv.frame_at(media["clip"], tools, 0.5, 320)
    assert frame and frame.exists()
    assert Image.open(frame).width <= 320

    strip = pv.filmstrip(media["clip"], tools, 2.0, count=6, tile_width=80)
    assert strip and strip.exists()
    assert Image.open(strip).width > 100

    # повторный запрос берётся из кэша, ffmpeg заново не запускается
    assert pv.frame_at(media["clip"], tools, 0.5, 320) == frame


def test_preview_cache_cleanup(media):
    pv.cleanup()
    assert pv.cache_size() == 0


@needs_ffmpeg
def test_preview_waveform(tools, media):
    from PIL import Image

    pytest.importorskip("PIL")
    assert "wav" in media
    wave = pv.waveform(media["wav"], tools, 300, 80)
    assert wave and wave.exists()
    assert Image.open(wave).size[0] <= 300


def test_image_preview_via_pillow(tools, media):
    from PIL import Image

    pytest.importorskip("PIL")
    preview = pv.image_preview(media["png"], tools, 100)
    assert preview and preview.exists()
    assert Image.open(preview).width <= 100


@needs_ffmpeg
def test_frame_stream_returns_even_rgb_frames(tools, media):
    """Поток кадров для «проигрывания»: ровные размеры и целый кадр в rgb24."""
    assert "clip" in media
    info = probe(media["clip"], tools)
    proc, width, height = pv.open_frame_stream(media["clip"], tools, info,
                                              0.0, 1.0, fps=8, max_height=120)
    try:
        assert width % 2 == 0 and height % 2 == 0
        frame = proc.stdout.read(width * height * 3)
        assert frame is not None and len(frame) == width * height * 3
    finally:
        proc.kill()
        proc.wait(timeout=5)

"""Тесты ядра MediaForge (GUI не требуется).

    python -m pytest            # всё
    python -m pytest -k image   # только изображения
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import pytest

from mediaforge.core import convert as conv
from mediaforge.core import engine as engine_mod
from mediaforge.core import formats as fm
from mediaforge.core import preview as pv
from mediaforge.core import updates
from mediaforge.core.config import Settings
from mediaforge.core.convert import (
    Cancelled,
    ConversionResult,
    ConvertError,
    build_audio_cmd,
    build_gif_cmd,
    build_video_cmd,
    convert_file,
    target_image_size,
    trim_plan,
    unique_path,
)
from mediaforge.core.engine import STATUS_CANCELLED, STATUS_DONE, Engine, Job
from mediaforge.core.ffmpeg import (
    STDERR_TAIL,
    MediaInfo,
    Tools,
    _drain_stderr,
    human_duration,
    human_size,
    iter_media_files,
    probe,
    run_ffmpeg,
)
from mediaforge.core.timecode import format_timecode, parse_timecode

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


def test_preview_cache_cleanup(tmp_path, monkeypatch):
    """Полная уборка — только по явному запросу (возраст 0, без защиты).

    Раньше тест вычищал настоящий кэш в темпе и требовал пустоты; теперь
    кэш чистится по возрасту/размеру, поэтому работаем в своей папке.
    """
    monkeypatch.setattr(pv, "CACHE_DIR", tmp_path)
    stamp = time.time() - 3600
    for name in ("a.png", "b.png"):
        path = tmp_path / name
        path.write_bytes(b"x" * 10)
        os.utime(path, (stamp, stamp))      # час назад, иначе mtime может совпасть с now
    assert pv.cache_size() == 20

    pv.cleanup(max_age_days=0, protect_seconds=0)
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


# --------------------------------------------------------------------------- #
# Масштаб изображений и апскейл
# --------------------------------------------------------------------------- #
def test_target_size_percent_always_applies():
    """Явный процент — прямое указание, флажок апскейла на него не влияет."""
    size = (1280, 800)
    assert target_image_size(size, fm.ConvertOptions()) == size
    assert target_image_size(size, fm.ConvertOptions(
        image_scale="percent", image_percent="50")) == (640, 400)
    assert target_image_size(size, fm.ConvertOptions(
        image_scale="percent", image_percent="200")) == (2560, 1600)
    assert target_image_size(size, fm.ConvertOptions(
        image_scale="percent", image_percent="200",
        image_allow_upscale=True)) == (2560, 1600)


def test_target_size_explicit_dimensions():
    size = (1280, 800)
    fit = fm.ConvertOptions(image_scale="size", image_width="400", image_height="400")
    assert target_image_size(size, fit) == (400, 250)
    stretch = fm.ConvertOptions(image_scale="size", image_width="300",
                                image_height="150", image_keep_ratio=False)
    assert target_image_size(size, stretch) == (300, 150)
    only_width = fm.ConvertOptions(image_scale="size", image_width="320")
    assert target_image_size(size, only_width) == (320, 200)
    # явный размер больше исходного применяется без флажка апскейла
    assert target_image_size(size, fm.ConvertOptions(
        image_scale="size", image_width="2000", image_height="2000")) == (2000, 1250)


def test_target_size_resolution_and_upscale():
    # для картинок «Разрешение» ограничивает длинную сторону (у видео — высоту)
    assert target_image_size((1920, 1080), fm.ConvertOptions(resolution="720")) == (720, 405)
    # картинку меньше целевого разрешения апскейлим только по флажку
    assert target_image_size((320, 200), fm.ConvertOptions(resolution="1080")) == (320, 200)
    assert target_image_size((320, 200), fm.ConvertOptions(
        resolution="1080", image_allow_upscale=True)) == (1080, 675)


def test_target_size_validation():
    with pytest.raises(ConvertError):
        target_image_size((100, 100), fm.ConvertOptions(image_scale="size"))
    with pytest.raises(ConvertError):
        target_image_size((100, 100), fm.ConvertOptions(
            image_scale="percent", image_percent="0"))


def test_image_upscale_writes_bigger_file(tmp_path, media):
    from PIL import Image

    pytest.importorskip("PIL")
    opts = fm.ConvertOptions(image_scale="percent", image_percent="200",
                             image_allow_upscale=True, image_filter="lanczos")
    res = convert_file(media["png"], fm.BY_KEY["png"], opts, None, tmp_path)
    with Image.open(res.output) as im:
        assert im.size == (320, 200)


def test_image_explicit_size_with_nearest(tmp_path, media):
    from PIL import Image

    pytest.importorskip("PIL")
    opts = fm.ConvertOptions(image_scale="size", image_width="64", image_height="64",
                             image_keep_ratio=False, image_filter="nearest")
    res = convert_file(media["png"], fm.BY_KEY["png"], opts, None, tmp_path)
    with Image.open(res.output) as im:
        assert im.size == (64, 64)


# --------------------------------------------------------------------------- #
# Проверка обновлений
# --------------------------------------------------------------------------- #
def test_version_compare():
    assert updates.parse_version("v1.2.0") == (1, 2, 0)
    assert updates.parse_version("1.2.0-beta1") == (1, 2, 0)
    assert updates.is_newer("1.3.0", "1.2.0")
    assert updates.is_newer("1.10.0", "1.9.9")
    assert not updates.is_newer("1.2.0", "1.2.0")
    assert not updates.is_newer("1.1.9", "1.2.0")


def _fake_release(tag: str, body: str = "заметки") -> dict:
    return {"tag_name": tag, "html_url": f"https://example/{tag}", "body": body,
            "published_at": "2026-10-20T00:00:00Z"}


def test_check_latest_reports_newer_release():
    release = updates.check_latest("1.2.0", fetcher=lambda repo: _fake_release("v1.3.0"))
    assert release is not None
    assert release.version == "1.3.0"
    assert release.url.endswith("v1.3.0")
    assert release.notes == "заметки"


def test_check_latest_none_when_current():
    assert updates.check_latest("1.3.0", fetcher=lambda repo: _fake_release("v1.3.0")) is None


def test_check_latest_errors():
    def broken(repo):
        raise updates.UpdateError("нет сети")

    with pytest.raises(updates.UpdateError):
        updates.check_latest("1.0.0", fetcher=broken)
    with pytest.raises(updates.UpdateError):
        updates.check_latest("1.0.0", fetcher=lambda repo: {"html_url": "x"})


# --------------------------------------------------------------------------- #
# Отмена в очереди (регрессия: движок навсегда оставался в running)
# --------------------------------------------------------------------------- #
def _wait_for(predicate, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _fake_jobs(count: int, tmp_path: Path) -> list[Job]:
    return [
        Job(src=tmp_path / f"clip{i}.mp4",
            info=MediaInfo(path=tmp_path / f"clip{i}.mp4", kind="video", duration=1.0),
            target=fm.BY_KEY["mp4"])
        for i in range(count)
    ]


def test_cancel_before_start_releases_engine(monkeypatch, tmp_path):
    """5 задач, 2 потока, «Остановить» сразу: две в работе, три ещё в очереди."""
    events: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def fake_convert(*args, **kwargs):
        cancel = kwargs.get("cancel")
        started.set()
        release.wait(3.0)
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        return ConversionResult(output=tmp_path / "out.mp4")

    monkeypatch.setattr(engine_mod, "convert_file", fake_convert)
    jobs = _fake_jobs(5, tmp_path)
    engine = Engine(tools=object(), options=fm.ConvertOptions(),
                    on_event=lambda event, job: events.append(event), max_workers=2)

    engine.start(jobs, tmp_path)
    assert started.wait(3.0), "воркеры не успели взять ни одной задачи"
    assert engine.running is True

    engine.stop()          # два ffmpeg уже работают, три задачи ещё в очереди
    release.set()

    assert _wait_for(lambda: events.count("finished") > 0), \
        "движок не прислал finished — остался в running"
    assert [job.status for job in jobs] == [STATUS_CANCELLED] * 5
    assert events.count("finished") == 1
    assert events.count("cancelled") == 5
    assert engine.running is False
    assert engine._remaining == 0


def test_cancel_midway_keeps_engine_consistent(monkeypatch, tmp_path):
    """Отмена в середине: часть задач успевает завершиться, часть отменяется."""
    events: list[str] = []
    stats = {"started": 0}
    lock = threading.Lock()
    second_started = threading.Event()

    def fake_convert(*args, **kwargs):
        cancel = kwargs.get("cancel")
        with lock:
            stats["started"] += 1
            number = stats["started"]
        if number == 1:
            time.sleep(0.02)
            return ConversionResult(output=tmp_path / "first.mp4")
        second_started.set()
        while not (cancel is not None and cancel.is_set()):
            time.sleep(0.01)
        raise Cancelled()

    monkeypatch.setattr(engine_mod, "convert_file", fake_convert)
    jobs = _fake_jobs(5, tmp_path)
    engine = Engine(tools=object(), options=fm.ConvertOptions(),
                    on_event=lambda event, job: events.append(event), max_workers=2)

    engine.start(jobs, tmp_path)
    assert second_started.wait(3.0), "вторая задача не стартовала"
    engine.stop()

    assert _wait_for(lambda: events.count("finished") == 1), \
        "finished не пришёл или пришёл не один раз"
    statuses = [job.status for job in jobs]
    assert statuses.count(STATUS_DONE) == 1
    assert statuses.count(STATUS_CANCELLED) == 4
    assert engine.running is False
    assert engine._remaining == 0


# --------------------------------------------------------------------------- #
# stderr ffmpeg (регрессия: без вычитывания канал переполнялся и всё вставало)
# --------------------------------------------------------------------------- #
_NOISY_CHILD = r"""
import sys
for i in range(2000):
    sys.stderr.write('noise line %05d %s\n' % (i, 'z' * 400))
sys.stderr.write('Invalid data found when processing input\n')
sys.stderr.flush()
sys.stdout.write('out_time_us=2000000\n')
sys.stdout.write('speed=1.0x\n')
sys.stdout.write('progress=end\n')
sys.stdout.flush()
sys.exit(int(sys.argv[1]))
"""


def _noisy_cmd(code: int) -> list[str]:
    return [sys.executable, "-c", _NOISY_CHILD, str(code)]


def test_stderr_reader_keeps_only_tail():
    """1 МБ строк → в памяти только хвост, поток завершается сам."""
    import io

    payload = "".join(f"line {i:06d} {'y' * 90}\n" for i in range(10_000))
    assert len(payload) > 1_000_000
    tail: deque[str] = deque(maxlen=STDERR_TAIL)
    stream = io.StringIO(payload)

    worker = threading.Thread(target=_drain_stderr, args=(stream, tail), daemon=True)
    worker.start()
    worker.join(10.0)

    assert not worker.is_alive(), "читатель stderr не завершился"
    assert len(tail) == STDERR_TAIL
    assert tail[-1].startswith("line 009999")
    assert tail[0].startswith("line 009800")


def test_run_ffmpeg_survives_flooded_stderr():
    """Ребёнок пишет ~800 КБ в stderr до stdout: старый код вешался навсегда."""
    progress: list[float] = []
    result: dict[str, object] = {}

    def work() -> None:
        try:
            run_ffmpeg(_noisy_cmd(0), duration=2.0,
                       on_progress=lambda p, speed: progress.append(p))
            result["ok"] = True
        except Exception as exc:  # noqa: BLE001 — нужен сам факт исключения
            result["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(20.0)

    assert not worker.is_alive(), "run_ffmpeg завис на переполненном stderr"
    assert time.monotonic() - started < 20.0
    assert result.get("ok") is True, result.get("error")
    assert progress[-1] == 1.0
    assert any(p > 0 for p in progress)


def test_run_ffmpeg_error_uses_stderr_tail():
    """При ненулевом коде сообщение берётся из накопленного хвоста."""
    with pytest.raises(ConvertError) as excinfo:
        run_ffmpeg(_noisy_cmd(1), duration=2.0)
    message = str(excinfo.value)
    assert "Invalid data found when processing input" in message
    assert len(message) <= 300


@needs_ffmpeg
def test_run_ffmpeg_with_debug_loglevel(media, tools, tmp_path):
    """Шумный -loglevel debug на коротком файле: успех по коду возврата и в срок."""
    out = tmp_path / "debug_out.mp4"
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "debug", "-y",
        "-i", str(media["clip"]), "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-an", "-progress", "pipe:1", str(out),
    ]
    seen: list[float] = []
    started = time.monotonic()
    run_ffmpeg(cmd, duration=2.0, on_progress=lambda p, s: seen.append(p))
    assert time.monotonic() - started < 60.0
    assert out.exists() and out.stat().st_size > 0
    assert seen[-1] == 1.0


@needs_ffmpeg
def test_run_ffmpeg_broken_input_raises(tools, tmp_path):
    """Повреждённый файл: ConvertError с осмысленным текстом, без зависания."""
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\xff" * 4096)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "debug", "-y",
           "-i", str(broken), "-progress", "pipe:1", str(tmp_path / "o.mp4")]
    started = time.monotonic()
    with pytest.raises(ConvertError):
        run_ffmpeg(cmd, duration=1.0)
    assert time.monotonic() - started < 60.0


@needs_ffmpeg
def test_run_ffmpeg_cancel_during_noisy_stderr(tools, tmp_path):
    """Отмена при шумном stderr: процесс убит, Cancelled за доли секунды."""
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "debug", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
        "-t", "60", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-progress", "pipe:1", str(tmp_path / "long.mp4"),
    ]
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_ffmpeg(cmd, duration=60.0, cancel=cancel)
    assert time.monotonic() - started < 10.0


# --------------------------------------------------------------------------- #
# Атомарный выбор имени (регрессия: два потока писали в один файл)
# --------------------------------------------------------------------------- #
def test_unique_path_is_atomic_under_threads(tmp_path):
    """Barrier + 2 потока: имена разные, оба файла забронированы пустыми."""
    barrier = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    results: list[Path] = []

    def worker() -> None:
        barrier.wait()
        path = unique_path(tmp_path, "a", "ext")
        with lock:
            results.append(path)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()

    assert len(results) == 2
    assert results[0] != results[1], "оба потока получили одно имя"
    for path in results:
        assert path.exists(), f"имя не забронировано: {path}"
        assert path.stat().st_size == 0


def test_unique_path_sequential_suffixes(tmp_path):
    names = [unique_path(tmp_path, "a", "ext").name for _ in range(3)]
    assert names == ["a.ext", "a (1).ext", "a (2).ext"]


def test_unique_path_overwrite_returns_name_as_is(tmp_path):
    existing = tmp_path / "a.ext"
    existing.write_text("данные", encoding="utf-8")
    assert unique_path(tmp_path, "a", "ext", overwrite=True) == existing
    # перезапись ничего не бронирует и не трогает чужой файл
    assert existing.read_text(encoding="utf-8") == "данные"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.ext"]


def test_unique_path_without_reservation_keeps_old_behaviour(tmp_path):
    """reserve=False — только выбор имени, файлов не создаёт."""
    first = unique_path(tmp_path, "a", "ext", reserve=False)
    assert first == tmp_path / "a.ext"
    assert list(tmp_path.iterdir()) == []


@needs_ffmpeg
def test_ffmpeg_overwrites_reserved_placeholder(media, tools, tmp_path):
    """Заглушка не мешает записи: ffmpeg с -y пишет поверх пустого файла."""
    src = media["clip"]
    dst = unique_path(tmp_path, "reserved", "mp4")
    assert dst.stat().st_size == 0
    cmd, _note = build_video_cmd(src, dst, probe(src, tools), fm.BY_KEY["mp4"],
                                 fm.ConvertOptions(), tools)
    run_ffmpeg(cmd)
    assert dst.stat().st_size > 0


@needs_ffmpeg
def test_failed_conversion_leaves_no_placeholder(media, tools, tmp_path):
    """Ошибка конвертации не оставляет пустых заглушек в папке назначения."""
    out = tmp_path / "out"
    out.mkdir()
    # в silent.mp4 нет звуковой дорожки — извлечение mp3 падает
    with pytest.raises(ConvertError):
        convert_file(media["silent"], fm.BY_KEY["mp3"], fm.ConvertOptions(), tools, out)
    assert list(out.iterdir()) == [], [p.name for p in out.iterdir()]


# --------------------------------------------------------------------------- #
# overwrite=True: ошибка не должна тронуть существующий файл
# --------------------------------------------------------------------------- #
@needs_ffmpeg
def test_overwrite_failure_keeps_existing_file(media, tools, tmp_path):
    """Ошибка до запуска ffmpeg: файл назначения остаётся нетронутым."""
    out = tmp_path / "out"
    out.mkdir()
    src = tmp_path / "a.mp4"
    shutil.copyfile(media["silent"], src)
    existing = out / "a.mp3"
    existing.write_bytes(b"original data")

    with pytest.raises(ConvertError):
        convert_file(src, fm.BY_KEY["mp3"], fm.ConvertOptions(overwrite=True), tools, out)

    assert existing.exists(), "существующий файл удалён"
    assert existing.read_bytes() == b"original data"
    assert [p.name for p in out.iterdir()] == ["a.mp3"], "остались временные файлы"


@needs_ffmpeg
def test_overwrite_success_replaces_existing_file(media, tools, tmp_path):
    """Успешная конвертация с overwrite=True заменяет файл и не оставляет мусора."""
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "clip.mkv"
    existing.write_bytes(b"old junk")

    result = convert_file(media["clip"], fm.BY_KEY["mkv"],
                          fm.ConvertOptions(overwrite=True), tools, out)

    assert result.output == existing
    assert existing.stat().st_size > 1000, "файл не заменён"
    assert probe(existing, tools).kind == "video"
    assert [p.name for p in out.iterdir()] == ["clip.mkv"]


@needs_ffmpeg
def test_overwrite_cancel_keeps_existing_file(media, tools, tmp_path):
    """Отмена на уже запущенном ffmpeg тоже не портит существующий файл."""
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "clip.gif"
    existing.write_bytes(b"old gif")
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(Cancelled):
        convert_file(media["clip"], fm.BY_KEY["gif"], fm.ConvertOptions(overwrite=True),
                     tools, out, cancel=cancel)

    assert existing.read_bytes() == b"old gif"
    assert [p.name for p in out.iterdir()] == ["clip.gif"]


# --------------------------------------------------------------------------- #
# Отмена для изображений (Pillow-ветка раньше не читала cancel)
# --------------------------------------------------------------------------- #
def _big_png(path: Path, side: int = 2200) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    im = Image.new("RGB", (side, side))
    px = im.load()
    for y in range(side):
        for x in range(0, side, 7):
            px[x, y] = ((x * 3) % 256, (y * 5) % 256, ((x + y) * 2) % 256)
    im.save(path)
    return True


def test_image_conversion_cancelled_before_start(tmp_path):
    """cancel взведён до вызова: Cancelled, в папке пусто."""
    src = tmp_path / "big.png"
    if not _big_png(src):
        pytest.skip("нет Pillow")
    out = tmp_path / "out"
    out.mkdir()
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(Cancelled):
        convert_file(src, fm.BY_KEY["webp"], fm.ConvertOptions(),
                     tools=None, out_dir=out, cancel=cancel)

    assert list(out.iterdir()) == [], [p.name for p in out.iterdir()]
    assert not (out / "big.webp").exists()


def test_image_conversion_without_cancel(tmp_path):
    """Без отмены картинка конвертируется как раньше."""
    src = tmp_path / "pic.png"
    if not _big_png(src, side=300):
        pytest.skip("нет Pillow")
    out = tmp_path / "out"
    out.mkdir()

    result = convert_file(src, fm.BY_KEY["webp"], fm.ConvertOptions(),
                          tools=None, out_dir=out)

    assert result.output.name == "pic.webp"
    assert result.output.stat().st_size > 0
    from PIL import Image
    with Image.open(result.output) as im:
        assert im.format == "WEBP"
        assert im.size == (300, 300)


def test_image_cancel_midway_leaves_no_file(tmp_path, monkeypatch):
    """Отмена между этапами Pillow: файл не создаётся, заглушки убраны."""
    src = tmp_path / "pic.png"
    if not _big_png(src, side=400):
        pytest.skip("нет Pillow")
    out = tmp_path / "out"
    out.mkdir()
    cancel = threading.Event()

    import mediaforge.core.convert as conv
    real_size = conv.target_image_size

    def size_and_cancel(size, opts):
        # отмена приходит уже после открытия файла — как в реальной работе
        cancel.set()
        return real_size(size, opts)

    monkeypatch.setattr(conv, "target_image_size", size_and_cancel)

    with pytest.raises(Cancelled):
        convert_file(src, fm.BY_KEY["jpg"], fm.ConvertOptions(),
                     tools=None, out_dir=out, cancel=cancel)

    assert list(out.iterdir()) == []


@needs_ffmpeg
def test_image_ffmpeg_fallback_respects_cancel(media, tools, tmp_path, monkeypatch):
    """Ветка отката на ffmpeg тоже уважает отмену."""
    out = tmp_path / "out"
    out.mkdir()
    cancel = threading.Event()
    cancel.set()

    import mediaforge.core.convert as conv

    def no_pillow(*_args, **_kwargs):
        raise ImportError("нет Pillow")

    monkeypatch.setattr(conv, "_convert_image_pillow", no_pillow)

    with pytest.raises(Cancelled):
        convert_file(media["png"], fm.BY_KEY["webp"], fm.ConvertOptions(),
                     tools=tools, out_dir=out, cancel=cancel)

    assert list(out.iterdir()) == []


# --------------------------------------------------------------------------- #
# Снятая с очереди задача не должна конвертироваться
# --------------------------------------------------------------------------- #
def test_removed_pending_job_is_skipped(monkeypatch, tmp_path):
    """3 задачи, 1 поток: вторая снята до старта — convert_file вызван 2 раза."""
    events: list[str] = []
    calls: list[str] = []
    lock = threading.Lock()
    first_started = threading.Event()
    release = threading.Event()

    def fake_convert(src, target, opts, tools, out_dir, info=None,
                     on_progress=None, cancel=None):
        with lock:
            calls.append(src.name)
            number = len(calls)
        if number == 1:
            first_started.set()
            release.wait(5.0)
        assert cancel is None or not cancel.is_set() or number > 1
        return ConversionResult(output=Path(out_dir) / f"{src.stem}.{target.ext}")

    monkeypatch.setattr(engine_mod, "convert_file", fake_convert)
    jobs = _fake_jobs(3, tmp_path)
    engine = Engine(tools=object(), options=fm.ConvertOptions(),
                    on_event=lambda event, job: events.append(event), max_workers=1)

    engine.start(jobs, tmp_path)
    assert first_started.wait(5.0), "первая задача не стартовала"
    jobs[1].cancel.set()          # пользователь удалил строку из очереди
    release.set()

    assert _wait_for(lambda: events.count("finished") == 1), "finished не пришёл"
    assert calls == ["clip0.mp4", "clip2.mp4"], calls
    assert jobs[0].status == STATUS_DONE
    assert jobs[1].status == STATUS_CANCELLED
    assert jobs[2].status == STATUS_DONE
    assert jobs[1].output is None
    assert events.count("finished") == 1
    assert engine._remaining == 0 and engine._done_count == 3
    assert engine.running is False


def test_job_cancel_flag_is_reset_on_restart(monkeypatch, tmp_path):
    """Повторный запуск сбрасывает флаг отмены, иначе задача «залипнет» снятой."""
    calls: list[str] = []

    def fake_convert(src, target, opts, tools, out_dir, info=None,
                     on_progress=None, cancel=None):
        calls.append(src.name)
        return ConversionResult(output=Path(out_dir) / f"{src.stem}.{target.ext}")

    monkeypatch.setattr(engine_mod, "convert_file", fake_convert)
    jobs = _fake_jobs(1, tmp_path)
    jobs[0].cancel.set()

    engine = Engine(tools=object(), options=fm.ConvertOptions(),
                    on_event=lambda event, job: None, max_workers=1)
    engine.start(jobs, tmp_path)
    assert _wait_for(lambda: not engine.running, 5.0)

    assert calls == ["clip0.mp4"], "флаг отмены пережил перезапуск"
    assert jobs[0].status == STATUS_DONE


# --------------------------------------------------------------------------- #
# overwrite=True: свой .part у каждого потока, атомарная публикация
# --------------------------------------------------------------------------- #
def test_part_targets_unique_for_same_stem(tmp_path):
    """Два потока с одинаковым stem не должны получить общий .part."""
    dst = tmp_path / "clip.mp4"
    barrier = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    parts: list[Path] = []

    def worker() -> None:
        barrier.wait()
        path = conv._part_target(dst)
        with lock:
            parts.append(path)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()

    assert len(parts) == 2
    assert parts[0] != parts[1], "оба потока получили один .part"
    assert all(p.name.startswith("clip.part") and p.suffix == ".mp4" for p in parts), parts
    assert all(p.exists() and p.stat().st_size == 0 for p in parts)


@needs_ffmpeg
def test_parallel_overwrite_keeps_both_outputs(media, tools, tmp_path):
    """Barrier-тест: два потока с разными stem перезаписывают каждый своё."""
    out = tmp_path / "out"
    out.mkdir()
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    shutil.copyfile(media["clip"], a)
    shutil.copyfile(media["silent"], b)
    (out / "a.gif").write_bytes(b"old a")
    (out / "b.gif").write_bytes(b"old b")

    barrier = threading.Barrier(2, timeout=10)
    results: dict[str, ConversionResult] = {}
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(src: Path) -> None:
        try:
            barrier.wait()
            res = convert_file(src, fm.BY_KEY["gif"], fm.ConvertOptions(overwrite=True),
                               tools, out)
            with lock:
                results[src.stem] = res
        except BaseException as exc:  # noqa: BLE001 — покажем в assert
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(src,)) for src in (a, b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
        assert not thread.is_alive()

    assert not errors, errors
    assert set(results) == {"a", "b"}
    assert results["a"].output == out / "a.gif"
    assert results["b"].output == out / "b.gif"
    assert (out / "a.gif").exists() and (out / "b.gif").exists()
    assert (out / "a.gif").read_bytes() != (out / "b.gif").read_bytes()
    assert sorted(p.name for p in out.iterdir()) == ["a.gif", "b.gif"]


@needs_ffmpeg
def test_overwrite_uses_part_and_publishes(media, tools, tmp_path, monkeypatch):
    """Успех: запись идёт в .part, публикация — os.replace, .part не остаётся."""
    out = tmp_path / "out"
    out.mkdir()
    existing = out / "clip.mp4"
    existing.write_bytes(b"old")

    seen: list[tuple[str, str]] = []
    import mediaforge.core.convert as conv

    real_publish = conv._publish
    real_part = conv._part_target

    def spy_part(dst: Path) -> Path:
        part = real_part(dst)
        seen.append(("part", part.name))
        return part

    def spy_publish(part: Path, dst: Path) -> None:
        seen.append(("replace", part.name))
        assert part.name.startswith("clip.part")
        assert part.stat().st_size > 0
        real_publish(part, dst)

    monkeypatch.setattr(conv, "_part_target", spy_part)
    monkeypatch.setattr(conv, "_publish", spy_publish)

    result = convert_file(media["clip"], fm.BY_KEY["mp4"],
                          fm.ConvertOptions(overwrite=True), tools, out)

    assert result.output == existing
    assert [kind for kind, _ in seen] == ["part", "replace"], seen
    assert existing.stat().st_size > 1000
    assert sorted(p.name for p in out.iterdir()) == ["clip.mp4"]


@needs_ffmpeg
def test_overwrite_error_removes_part_and_keeps_file(media, tools, tmp_path):
    """Ошибка: .part удалён, старый файл цел."""
    out = tmp_path / "out"
    out.mkdir()
    src = tmp_path / "a.mp4"
    shutil.copyfile(media["silent"], src)
    existing = out / "a.mp3"
    existing.write_bytes(b"real data")

    with pytest.raises(ConvertError):
        convert_file(src, fm.BY_KEY["mp3"], fm.ConvertOptions(overwrite=True), tools, out)

    assert existing.read_bytes() == b"real data"
    assert sorted(p.name for p in out.iterdir()) == ["a.mp3"], [p.name for p in out.iterdir()]


# --------------------------------------------------------------------------- #
# Валидация настроек (мусор в settings.json не должен доезжать до конвертации)
# --------------------------------------------------------------------------- #
def test_invalid_quality_falls_back_to_default():
    settings = Settings({"opt_quality": "ultra"})
    assert settings.options().quality == "balanced"
    assert "ultra" not in fm.QUALITY_VALUES


def test_invalid_image_percent_and_resolution_are_clean():
    settings = Settings({
        "opt_image_scale": "percent",
        "opt_image_percent": "37",
        "opt_resolution": 9999,
        "opt_gif_fps": 7,
        "opt_audio_bitrate": "999k",
        "opt_image_filter": "magic",
    })
    opts = settings.options()
    assert opts.image_scale == "percent"
    assert opts.image_percent in fm.IMAGE_PERCENTS
    assert opts.resolution in fm.RESOLUTION_VALUES
    assert opts.gif_fps in fm.GIF_FPS
    assert opts.audio_bitrate in fm.AUDIO_BITRATES
    assert opts.image_filter in fm.IMAGE_FILTER_VALUES
    # и конвертация с такими опциями не падает на расчёте размера
    assert target_image_size((1280, 800), opts) == (1920, 1200)


def test_max_workers_junk_does_not_raise():
    settings = Settings({"max_workers": "abc"})
    assert settings.get_int("max_workers", 2) == 2
    assert settings.get("max_workers") == 2
    assert int(settings.get("max_workers", 2)) == 2      # как делает UI
    settings.set("max_workers", 7)
    assert settings.get_int("max_workers", 2) == 7       # нормальное число читается
    settings.set("max_workers", None)
    assert settings.get_int("max_workers", 2) == 2       # и None тоже не роняет


def test_valid_config_reads_unchanged(tmp_path, monkeypatch):
    valid = {
        "theme": "dark", "out_dir": str(tmp_path), "use_source_dir": False,
        "recursive": True, "max_workers": 3, "window_geometry": "abc",
        "opt_quality": "high", "opt_resolution": "1080", "opt_gif_fps": "20",
        "opt_gif_loop": False, "opt_audio_bitrate": "320k",
        "opt_keep_metadata": False, "opt_gpu": True, "opt_gentle": False,
        "opt_overwrite": True, "opt_trim_start": 1.5, "opt_trim_end": 9.0,
        "opt_image_scale": "size", "opt_image_percent": "200",
        "opt_image_width": "640", "opt_image_height": "480",
        "opt_image_keep_ratio": False, "opt_image_allow_upscale": True,
        "opt_image_filter": "nearest",
    }
    settings = Settings(valid)
    assert settings.sanitize() == [], "валидный конфиг не должен правиться"
    assert settings._data == valid
    opts = settings.options()
    assert (opts.quality, opts.resolution, opts.image_percent) == ("high", "1080", "200")
    assert (opts.image_width, opts.image_height, opts.image_filter) == ("640", "480", "nearest")
    assert opts.trim_start == 1.5 and opts.trim_end == 9.0


def test_load_repairs_broken_settings_file(tmp_path, monkeypatch):
    """Испорченный settings.json: load() не падает и отдаёт допустимые опции."""
    monkeypatch.setenv("MEDIAFORGE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({
        "opt_quality": "ultra",
        "opt_resolution": 9999,
        "opt_image_scale": "percent",
        "opt_image_percent": "37",
        "opt_trim_start": "пять",
        "opt_image_width": "abc",
        "max_workers": "abc",
        "theme": "neon",
        "unknown_key": {"x": 1},
    }, ensure_ascii=False), encoding="utf-8")

    settings = Settings.load()
    opts = settings.options()
    assert opts.quality == "balanced"
    assert opts.resolution == "original"
    assert opts.image_percent in fm.IMAGE_PERCENTS
    assert opts.trim_start == 0.0
    assert opts.image_width == ""
    assert settings.get_int("max_workers", 2) == 2
    assert settings.get("theme") == "system"
    # посторонний ключ не потерян и не мешает
    assert settings.get("unknown_key") == {"x": 1}

    settings.save()                       # файл остаётся читаемым
    again = Settings.load()
    assert again.options() == opts


def test_options_stay_valid_after_direct_set():
    settings = Settings()
    settings.set("opt_quality", "ultra")
    settings.set("opt_image_percent", "37")
    settings.set("opt_trim_end", "конец")
    opts = settings.options()
    assert opts.quality in fm.QUALITY_VALUES
    assert opts.image_percent in fm.IMAGE_PERCENTS
    assert opts.trim_end == 0.0


# --------------------------------------------------------------------------- #
# Кэш предпросмотра: возраст и размер
# --------------------------------------------------------------------------- #
def _touch(path: Path, size: int, age_seconds: float) -> Path:
    path.write_bytes(b"z" * size)
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def test_preview_cleanup_removes_old_keeps_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(pv, "CACHE_DIR", tmp_path)
    old = _touch(tmp_path / "old.png", 100, age_seconds=10 * 86400)
    fresh = _touch(tmp_path / "fresh.png", 100, age_seconds=60)

    freed = pv.cleanup(max_age_days=7)

    assert not old.exists(), "старый файл не удалён"
    assert fresh.exists(), "свежий файл удалён"
    assert freed == 100


def test_preview_cleanup_trims_by_size_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(pv, "CACHE_DIR", tmp_path)
    files = [_touch(tmp_path / f"f{i}.png", 1000, age_seconds=(10 - i) * 7200)
             for i in range(5)]

    freed = pv.cleanup(max_age_days=30, max_bytes=3000, protect_seconds=0)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["f2.png", "f3.png", "f4.png"]
    assert not files[0].exists() and not files[1].exists()
    assert freed == 2000


def test_preview_cleanup_keeps_current_session_files(tmp_path, monkeypatch):
    monkeypatch.setattr(pv, "CACHE_DIR", tmp_path)
    for i in range(5):
        _touch(tmp_path / f"new{i}.png", 1000, age_seconds=i * 10)

    freed = pv.cleanup(max_age_days=30, max_bytes=1000)   # лимит меньше объёма

    assert len(list(tmp_path.iterdir())) == 5, "тронули файлы текущей сессии"
    assert freed == 0


def test_preview_cleanup_missing_or_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pv, "CACHE_DIR", tmp_path / "нет-такой-папки")
    assert pv.cleanup() == 0

    monkeypatch.setattr(pv, "CACHE_DIR", tmp_path)
    assert pv.cleanup() == 0

    (tmp_path / "subdir").mkdir()
    (tmp_path / "broken.png").write_bytes(b"x")
    (tmp_path / "broken.png").chmod(0o000)      # нет прав на чтение файла
    assert pv.cleanup(max_age_days=0) >= 0      # не падаем
    (tmp_path / "broken.png").chmod(0o644)


def test_cache_size_ignores_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(pv, "CACHE_DIR", tmp_path)
    _touch(tmp_path / "a.png", 500, age_seconds=10)
    (tmp_path / "sub").mkdir()
    assert pv.cache_size() == 500


# --------------------------------------------------------------------------- #
# Неудачная проба: флаг, тип и анимированный GIF
# --------------------------------------------------------------------------- #
def _animated_gif(path: Path, frames: int = 3, size: int = 40) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    images = [Image.new("RGB", (size, size), (40 * i % 255, 90, 160)) for i in range(frames)]
    images[0].save(path, save_all=True, append_images=images[1:], duration=120, loop=0)
    return True


@needs_ffmpeg
def test_probe_failed_flag_for_broken_file(tools, tmp_path):
    """Битый файл: probe_failed=True, тип — по расширению."""
    broken = tmp_path / "broken.webm"
    broken.write_bytes(b"\x00" * 512)

    info = probe(broken, tools)

    assert info.probe_failed is True
    assert info.kind == "video"          # догадка по расширению
    assert info.duration == 0.0

    good = probe(Path(FFMPEG).with_name("ffmpeg"), tools)  # заведомо не медиа, но файл есть
    assert good.probe_failed is True


@needs_ffmpeg
def test_probe_ok_has_no_flag(media, tools):
    info = probe(media["clip"], tools)
    assert info.probe_failed is False
    assert info.kind == "video"
    assert info.duration > 0


@needs_ffmpeg
def test_animated_gif_without_ffprobe_goes_to_video_branch(tools, tmp_path):
    """ffprobe недоступен, но GIF анимированный — значит не Pillow-ветка."""
    gif = tmp_path / "anim.gif"
    if not _animated_gif(gif):
        pytest.skip("нет Pillow")

    blind = Tools(ffmpeg=tools.ffmpeg, ffprobe=str(tmp_path / "нет-ffprobe"))
    info = probe(gif, blind)

    assert info.probe_failed is True
    assert info.kind == "video", "анимированный GIF попал в ветку картинки"

    out = tmp_path / "out"
    out.mkdir()
    result = convert_file(gif, fm.BY_KEY["gif"], fm.ConvertOptions(), tools, out)

    from PIL import Image
    with Image.open(result.output) as im:
        assert getattr(im, "n_frames", 1) > 1, "анимация потеряна"


def test_static_gif_without_ffprobe_stays_image(tools, tmp_path):
    """Статичный GIF при неудачной пробе остаётся картинкой."""
    gif = tmp_path / "static.gif"
    if not _animated_gif(gif, frames=1):
        pytest.skip("нет Pillow")

    blind = Tools(ffmpeg=tools.ffmpeg, ffprobe=str(tmp_path / "нет-ffprobe"))
    info = probe(gif, blind)

    assert info.probe_failed is True
    assert info.kind == "image"


# --------------------------------------------------------------------------- #
# Отмена без строк прогресса
# --------------------------------------------------------------------------- #
_SILENT_CHILD = r"""
import os, sys, time
pid_file, delay = sys.argv[1], float(sys.argv[2])
with open(pid_file, "w") as fh:
    fh.write(str(os.getpid()))
time.sleep(delay)
sys.stdout.write("out_time_us=2000000\n")
sys.stdout.write("progress=end\n")
sys.stdout.flush()
"""


@needs_ffmpeg
def test_cancel_while_child_is_silent(tmp_path):
    """Молчащий процесс: отмена за доли секунды, а не после первой строки."""
    pid_file = tmp_path / "pid.txt"
    cmd = [sys.executable, "-c", _SILENT_CHILD, str(pid_file), "5"]
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()

    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_ffmpeg(cmd, duration=2.0, cancel=cancel)
    spent = time.monotonic() - started

    assert spent < 2.0, f"отмена ждала прогресса {spent:.2f} с"
    pid = int(pid_file.read_text() or 0)
    assert pid
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)          # процесс убит, сирот нет


def test_silent_child_success_is_not_broken(tmp_path):
    """Молчание + успешное завершение: поведение прежнее, прогресс доходит до 1."""
    seen: list[float] = []
    cmd = [sys.executable, "-c", _SILENT_CHILD, str(tmp_path / "pid.txt"), "0.3"]

    run_ffmpeg(cmd, duration=2.0, on_progress=lambda p, s: seen.append(p))

    assert seen[-1] == 1.0
    assert any(p > 0 for p in seen)


@needs_ffmpeg
def test_cancel_with_noisy_stderr_is_still_fast(media, tools, tmp_path):
    """Шумный stderr + отмена: не медленнее, чем раньше."""
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "debug", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
        "-t", "60", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-progress", "pipe:1", str(tmp_path / "long.mp4"),
    ]
    cancel = threading.Event()
    threading.Timer(0.4, cancel.set).start()

    started = time.monotonic()
    with pytest.raises(Cancelled):
        run_ffmpeg(cmd, duration=60.0, cancel=cancel)

    assert time.monotonic() - started < 3.0

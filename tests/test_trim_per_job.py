"""Фрагмент принадлежит файлу: обрезка одного не трогает остальные."""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="нет PySide6")

try:                       # на headless-машинах часто нет libEGL/libGL
    from PySide6.QtWidgets import QApplication

    from mediaforge.core import formats as fm
    from mediaforge.core.config import Settings
    from mediaforge.core.convert import ConversionResult
    from mediaforge.core.engine import STATUS_DONE, Job
    from mediaforge.core.ffmpeg import MediaInfo
    from mediaforge.ui import theme
    from mediaforge.ui.main_window import MainWindow
except ImportError as exc:
    if os.environ.get("CI"):
        raise RuntimeError(
            f"UI-тесты не запускаются в CI: Qt недоступен ({exc}). "
            "Проверьте установку PySide6-Essentials и системных библиотек."
        ) from exc
    pytest.skip(f"Qt недоступен: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _job(tmp_path: Path, name: str, duration: float = 30.0) -> Job:
    src = tmp_path / name
    src.write_bytes(b"x")
    return Job(src=src, info=MediaInfo(path=src, kind="video", duration=duration),
               target=fm.BY_KEY["mp4"])


def _window(qapp, tmp_path, monkeypatch, count: int = 2) -> MainWindow:
    monkeypatch.setenv("MEDIAFORGE_CONFIG_DIR", str(tmp_path / "cfg"))
    theme.apply("dark")
    win = MainWindow(Settings(), object(), "")
    win.resize(1000, 700)
    for index in range(count):
        win._add_job(_job(tmp_path, f"clip{index}.mp4"))
    win._after_list_change()
    qapp.processEvents()
    return win


def _set_fields(win, start: str, end: str) -> None:
    win.preview.edit_start.setText(start)
    win.preview.edit_end.setText(end)
    win.preview._on_fields_edited()


def test_trim_applies_only_to_selected_job(qapp, tmp_path, monkeypatch):
    win = _window(qapp, tmp_path, monkeypatch)
    first, second = win.jobs
    win.preview.select_job(first.id)
    qapp.processEvents()

    _set_fields(win, "0:01", "0:02")

    assert (first.trim_start, first.trim_end) == (1.0, 2.0)
    assert (second.trim_start, second.trim_end) == (0.0, 0.0), "второй файл не тронут"
    assert win.rows[second.id]._trim == (0.0, 0.0)
    assert "✂" in win.rows[first.id].meta.text()
    assert "✂" not in win.rows[second.id].meta.text()
    # глобальные настройки больше не пишутся
    assert win.settings.get("opt_trim_start") in (0.0, None)
    assert win.settings.get("opt_trim_end") in (0.0, None)


def test_second_job_gets_its_own_trim(qapp, tmp_path, monkeypatch):
    win = _window(qapp, tmp_path, monkeypatch)
    first, second = win.jobs

    win.preview.select_job(first.id)
    qapp.processEvents()
    _set_fields(win, "0:01", "0:02")

    win.preview.select_job(second.id)
    qapp.processEvents()
    _set_fields(win, "0:03", "0:04")

    assert (first.trim_start, first.trim_end) == (1.0, 2.0)
    assert (second.trim_start, second.trim_end) == (3.0, 4.0)
    assert win.rows[first.id]._trim == (1.0, 2.0)
    assert win.rows[second.id]._trim == (3.0, 4.0)


def test_switching_files_shows_their_values(qapp, tmp_path, monkeypatch):
    win = _window(qapp, tmp_path, monkeypatch)
    first, second = win.jobs
    first.trim_start, first.trim_end = 1.0, 2.0
    second.trim_start, second.trim_end = 3.0, 4.0

    win.preview.select_job(first.id)
    qapp.processEvents()
    assert win.preview.edit_start.text() == "0:01"
    assert win.preview.edit_end.text() == "0:02"

    win.preview.select_job(second.id)
    qapp.processEvents()
    assert win.preview.edit_start.text() == "0:03"
    assert win.preview.edit_end.text() == "0:04"


def test_reset_touches_only_selected(qapp, tmp_path, monkeypatch):
    win = _window(qapp, tmp_path, monkeypatch)
    first, second = win.jobs
    first.trim_start, first.trim_end = 1.0, 2.0
    second.trim_start, second.trim_end = 3.0, 4.0
    win.rows[first.id].set_trim(1.0, 2.0)
    win.rows[second.id].set_trim(3.0, 4.0)

    win.preview.select_job(first.id)
    qapp.processEvents()
    win.preview._reset_trim()

    assert (first.trim_start, first.trim_end) == (0.0, 0.0)
    assert (second.trim_start, second.trim_end) == (3.0, 4.0)
    assert "✂" not in win.rows[first.id].meta.text()
    assert "✂" in win.rows[second.id].meta.text()


def test_invalid_time_is_not_applied_and_turns_red(qapp, tmp_path, monkeypatch):
    win = _window(qapp, tmp_path, monkeypatch)
    job = win.jobs[0]
    win.preview.select_job(job.id)
    qapp.processEvents()

    _set_fields(win, "0:10", "0:05")       # конец раньше начала

    assert (job.trim_start, job.trim_end) == (0.0, 0.0)
    assert theme.current()["danger"] in win.preview.edit_end.styleSheet()
    assert win.preview.trim_note.text()

    _set_fields(win, "0:01", "0:05")       # исправили — ошибка снимается
    assert (job.trim_start, job.trim_end) == (1.0, 5.0)
    assert win.preview.edit_end.styleSheet() == ""
    assert win.preview.trim_note.text() == ""


def test_conversion_uses_each_job_trim(qapp, tmp_path, monkeypatch):
    import mediaforge.core.engine as engine_mod

    win = _window(qapp, tmp_path, monkeypatch)
    first, second = win.jobs
    first.trim_start, first.trim_end = 1.0, 2.0
    second.trim_start, second.trim_end = 3.0, 4.0
    seen: dict[str, tuple[float, float]] = {}

    def fake_convert(src, target, opts, tools, out_dir, **kwargs):
        seen[src.name] = (opts.trim_start, opts.trim_end)
        return ConversionResult(output=Path(out_dir) / src.name)

    monkeypatch.setattr(engine_mod, "convert_file", fake_convert)
    win.start_conversion()

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and len(seen) < 2:
        qapp.processEvents()
        time.sleep(0.02)

    assert seen == {"clip0.mp4": (1.0, 2.0), "clip1.mp4": (3.0, 4.0)}, seen
    assert all(job.status == STATUS_DONE for job in win.jobs)


def test_unparsable_time_is_highlighted_instead_of_raising(qapp, tmp_path, monkeypatch):
    """«1:75» валидатор пускает как Intermediate — слот не должен падать."""
    win = _window(qapp, tmp_path, monkeypatch)
    job = win.jobs[0]
    win.preview.select_job(job.id)
    qapp.processEvents()

    _set_fields(win, "1:75", "")          # раньше здесь летел ValueError из слота

    assert (job.trim_start, job.trim_end) == (0.0, 0.0)
    assert theme.current()["danger"] in win.preview.edit_start.styleSheet()
    assert theme.current()["danger"] in win.preview.edit_end.styleSheet()
    assert win.preview.trim_note.text(), "подпись должна объяснять ошибку"


def test_start_beyond_duration_is_rejected(qapp, tmp_path, monkeypatch):
    """Начало за концом файла (30 с) не сохраняется."""
    win = _window(qapp, tmp_path, monkeypatch)
    job = win.jobs[0]
    win.preview.select_job(job.id)
    qapp.processEvents()

    _set_fields(win, "40", "")

    assert (job.trim_start, job.trim_end) == (0.0, 0.0)
    assert theme.current()["danger"] in win.preview.edit_start.styleSheet()
    assert "пределами" in win.preview.trim_note.text()
    assert "✂" not in win.rows[job.id].meta.text()


def test_end_beyond_duration_is_clamped_to_file_end(qapp, tmp_path, monkeypatch):
    """Конец за файлом обрезается до длительности, полоска и подпись согласованы."""
    win = _window(qapp, tmp_path, monkeypatch)
    job = win.jobs[0]
    win.preview.select_job(job.id)
    qapp.processEvents()

    _set_fields(win, "", "99")

    assert job.trim_end == pytest.approx(30.0)
    assert job.trim_end <= job.info.duration
    assert win.preview.strip._end == pytest.approx(30.0)
    assert win.preview._trim == (0.0, pytest.approx(30.0))
    caption = win.preview.caption.text()
    assert "0:30" in caption and "весь файл" not in caption, caption
    assert win.preview.edit_end.text() == "0:30", "поле показывает принятое значение"
    assert win.preview.trim_note.text() == ""

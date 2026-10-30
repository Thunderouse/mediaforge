"""Ручки фрагмента на полоске кадров и следующий за ними предпросмотр."""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="нет PySide6")

try:                       # на headless-машинах часто нет libEGL/libGL
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    from mediaforge.core import formats as fm
    from mediaforge.core.engine import Job
    from mediaforge.core.ffmpeg import MediaInfo
    from mediaforge.ui.preview import Filmstrip, PreviewPanel
except ImportError as exc:  # noqa: BLE001
    if os.environ.get("CI"):
        raise RuntimeError(
            f"UI-тесты не запускаются в CI: Qt недоступен ({exc}). "
            "Проверьте установку PySide6-Essentials и системных библиотек."
        ) from exc
    pytest.skip(f"Qt недоступен: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # noqa: BLE001
        if os.environ.get("CI"):
            raise RuntimeError(f"UI-тесты не запускаются в CI: {exc}") from exc
        pytest.skip(f"Qt не поднимается: {exc}")
    yield app


class _Mouse:
    """Минимальный заменитель QMouseEvent: обработчикам нужен только position()."""

    def __init__(self, x: float) -> None:
        self._x = x

    def position(self) -> QPointF:
        return QPointF(self._x, 32.0)


class _Player:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _strip(qapp) -> tuple[Filmstrip, list[tuple[float, float]], list[float]]:
    strip = Filmstrip()
    strip.resize(300, 64)
    strip.set_duration(30.0)
    strip.set_trim(0.0, 0.0)          # end == 0 -> «до конца», ручки по краям
    trims: list[tuple[float, float]] = []
    seeks: list[float] = []
    strip.trimEdited.connect(lambda a, b: trims.append((a, b)))
    strip.seeked.connect(seeks.append)
    strip.show()
    qapp.processEvents()
    return strip, trims, seeks


def _panel(qapp, duration: float = 30.0, tools=None) -> PreviewPanel:
    panel = PreviewPanel(tools)
    src = Path(__file__)
    job = Job(src=src, info=MediaInfo(path=src, kind="video", duration=duration),
              target=fm.BY_KEY["mp4"])
    panel.set_jobs([job])
    panel.strip.resize(300, 64)
    panel.show()
    qapp.processEvents()
    return panel


# --------------------------------------------------------------------------- #
# Полоска кадров
# --------------------------------------------------------------------------- #
def test_drag_start_handle_moves_position(qapp):
    strip, trims, seeks = _strip(qapp)

    strip.mousePressEvent(_Mouse(2))
    assert strip._drag == "start"
    strip.mouseMoveEvent(_Mouse(150))

    assert strip._start == pytest.approx(15.0, abs=0.5)
    assert strip._pos == pytest.approx(strip._start)
    assert seeks and seeks[-1] == pytest.approx(strip._start)
    assert trims == [], "trimEdited не должен лететьть во время движения"


def test_release_after_start_drag_emits_trim_once(qapp):
    strip, trims, _seeks = _strip(qapp)

    strip.mousePressEvent(_Mouse(2))
    strip.mouseMoveEvent(_Mouse(150))
    strip.mouseMoveEvent(_Mouse(160))
    strip.mouseReleaseEvent(_Mouse(160))

    assert len(trims) == 1, trims
    start, end = trims[0]
    assert start == pytest.approx(strip._start, abs=0.01)
    assert start == pytest.approx(16.0, abs=0.6)
    assert end == 0, "конец не двигали — значит «до конца файла»"


def test_end_handle_does_not_move_position(qapp):
    strip, trims, seeks = _strip(qapp)
    strip.set_position(4.0)
    seeks.clear()

    strip.mousePressEvent(_Mouse(298))
    assert strip._drag == "end"
    strip.mouseMoveEvent(_Mouse(200))
    strip.mouseReleaseEvent(_Mouse(200))

    assert strip._pos == pytest.approx(4.0), "вторая ручка не двигает просмотр"
    assert seeks == [], "seeked не должен эмититься второй ручкой"
    assert len(trims) == 1
    assert trims[0][0] == 0.0
    assert trims[0][1] == pytest.approx(20.0, abs=0.6)


def test_click_outside_handles_still_seeks(qapp):
    strip, trims, seeks = _strip(qapp)

    strip.mousePressEvent(_Mouse(150))
    strip.mouseReleaseEvent(_Mouse(150))

    assert strip._drag is None
    assert strip._pos == pytest.approx(15.0, abs=0.5)
    assert seeks and seeks[-1] == pytest.approx(15.0, abs=0.5)
    assert trims == []


def test_zero_duration_is_safe(qapp):
    strip = Filmstrip()
    strip.resize(300, 64)
    strip.set_duration(0.0)
    seeks: list[float] = []
    strip.seeked.connect(seeks.append)

    strip.mousePressEvent(_Mouse(10))
    strip.mouseMoveEvent(_Mouse(150))
    strip.mouseReleaseEvent(_Mouse(150))

    assert seeks == []
    assert strip._start == 0.0


# --------------------------------------------------------------------------- #
# Панель предпросмотра
# --------------------------------------------------------------------------- #
def test_on_seek_updates_slider_strip_timer_and_caption(qapp):
    panel = _panel(qapp)

    panel._on_seek(12.0)

    assert panel.slider.value() == 400
    assert panel.strip._pos == pytest.approx(12.0)
    assert panel._timer.isActive() is True
    assert "0:12" in panel.caption.text()


def test_seek_debounces_frame_requests(qapp, monkeypatch):
    # tools не None — иначе _load_frame выходит раньше, чем доходит до пула
    panel = _panel(qapp, tools=object())
    submitted: list[tuple] = []
    monkeypatch.setattr(panel._pool, "submit",
                        lambda fn, *args, **kwargs: submitted.append(args))

    for step in range(10):
        panel._on_seek(step * 0.5)

    assert submitted == [], "кадр запросили до истечения дебаунса"

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not submitted:
        qapp.processEvents()
        time.sleep(0.02)
    assert len(submitted) == 1, submitted


def test_drag_during_playback_stops_it(qapp):
    panel = _panel(qapp)
    panel._player = _Player()
    panel._play_timer.start()
    panel.btn_play.setChecked(True)

    panel._on_seek(5.0)

    assert panel._player is None
    assert panel._play_timer.isActive() is False
    assert panel.btn_play.isChecked() is False
    assert panel.strip._pos == pytest.approx(5.0)
    assert panel.slider.value() == pytest.approx(167, abs=1)


def test_seek_without_job_and_without_tools(qapp):
    panel = PreviewPanel(None)          # ни файла, ни ffmpeg
    panel.show()
    qapp.processEvents()

    panel._on_seek(3.0)                 # не должно падать и эмитить

    assert panel.slider.value() == 0
    assert panel._timer.isActive() is False


# --------------------------------------------------------------------------- #
# Подпись фрагмента во время перетаскивания
# --------------------------------------------------------------------------- #
def _timeline_panel(qapp, monkeypatch, duration: float = 30.0) -> PreviewPanel:
    """Панель с полоской кадров: без tools она таймлайна не получает вовсе."""
    panel = PreviewPanel(object())
    monkeypatch.setattr(panel._pool, "submit", lambda *a, **k: None)  # без ffmpeg
    src = Path(__file__)
    job = Job(src=src, info=MediaInfo(path=src, kind="video", duration=duration),
              target=fm.BY_KEY["mp4"])
    panel.set_jobs([job])
    panel.strip.resize(300, 64)
    panel.show()
    qapp.processEvents()
    return panel


def test_caption_follows_start_handle_while_dragging(qapp, monkeypatch):
    panel = _timeline_panel(qapp, monkeypatch)
    emitted: list[tuple] = []
    panel.trimChanged.connect(lambda *args: emitted.append(args))

    panel.strip.mousePressEvent(_Mouse(2))
    panel.strip.mouseMoveEvent(_Mouse(panel.strip.width() * 0.5))
    qapp.processEvents()

    start = panel.strip._start
    text = panel.caption.text()
    assert start == pytest.approx(15.0, abs=0.6)
    assert f"{start:.1f} с" in text, text
    assert "весь файл" not in text, text
    assert "–конец" in text, text
    assert emitted == [], "trimChanged — только на отпускании"
    assert panel._trim == (0.0, 0.0), "настройки до отпускания не трогаем"


def test_caption_updates_throughout_drag_and_once_on_release(qapp, monkeypatch):
    panel = _timeline_panel(qapp, monkeypatch)
    emitted: list[tuple[str, float, float]] = []
    panel.trimChanged.connect(lambda job_id, a, b: emitted.append((job_id, a, b)))

    panel.strip.mousePressEvent(_Mouse(2))
    seen: list[str] = []
    for fraction in (0.2, 0.35, 0.5, 0.65):
        panel.strip.mouseMoveEvent(_Mouse(panel.strip.width() * fraction))
        qapp.processEvents()
        seen.append(panel.caption.text())
    panel.strip.mouseReleaseEvent(_Mouse(panel.strip.width() * 0.65))

    starts = [text.split("фрагмент ")[1].split("–")[0] for text in seen if "фрагмент " in text]
    assert len(set(starts)) > 1, starts            # подпись едет вместе с ручкой
    assert len(emitted) == 1, emitted
    job_id, start, end = emitted[0]
    assert job_id == panel._job.id
    assert start == pytest.approx(panel.strip._start, abs=0.01) and end == 0
    assert start == pytest.approx(19.5, abs=1.5), start
    assert panel._trim[0] == pytest.approx(start) and panel._trim[1] == 0


def test_caption_after_plain_seek_keeps_old_trim(qapp, monkeypatch):
    """Клик по полоске не выдаёт текущий фрагмент за обрезанный."""
    panel = _timeline_panel(qapp, monkeypatch)
    panel.apply_trim(5.0, 20.0)

    panel.strip.mousePressEvent(_Mouse(panel.strip.width() - 2))
    panel.strip.mouseReleaseEvent(_Mouse(panel.strip.width() - 2))
    qapp.processEvents()

    text = panel.caption.text()
    assert "фрагмент 0:05–0:20" in text, text
    assert panel._trim == (5.0, 20.0)

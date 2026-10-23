"""Таймкод фрагмента: валидатор, заголовок и смена темы.

Тесты требуют Qt; если платформа не поднимается — пропускаются.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="нет PySide6")

try:                       # на headless-машинах часто нет libEGL/libGL
    from PySide6.QtGui import QValidator
    from PySide6.QtWidgets import QApplication

    from mediaforge.core.config import Settings
    from mediaforge.core.engine import Job
    from mediaforge.core.ffmpeg import MediaInfo
    from mediaforge.ui import theme
    from mediaforge.ui.options_sidebar import OptionsSidebar, TimecodeValidator
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


# --------------------------------------------------------------------------- #
# Валидатор
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text, expected", [
    ("1:2:3:4", QValidator.Invalid),        # четыре группы — parse_timecode не умеет
    ("1:2:3:4:5", QValidator.Invalid),
    ("12345", QValidator.Invalid),          # группа длиннее трёх цифр
    ("abc", QValidator.Invalid),
    ("1:30.5", QValidator.Acceptable),
    ("1:30,5", QValidator.Acceptable),
    ("90", QValidator.Acceptable),
    ("00:01:30.5", QValidator.Acceptable),
    ("1:", QValidator.Intermediate),        # недописанное — можно продолжать
    ("", QValidator.Intermediate),
    ("1:75", QValidator.Intermediate),      # минуты ≥ 60 подсветятся как ошибка
])
def test_timecode_validator_states(qapp, text, expected):
    validator = TimecodeValidator()
    state, _text, _pos = validator.validate(text, len(text))
    assert state == expected


def test_everything_acceptable_parses(qapp):
    """Инвариант: Acceptable ⇒ parse_timecode не падает."""
    from mediaforge.core.timecode import parse_timecode

    validator = TimecodeValidator()
    samples = ["90", "1:30", "1:30.5", "00:01:30.5", "1:30,25", "0:05", "999:59"]
    for text in samples:
        state, _t, _p = validator.validate(text, len(text))
        assert state == QValidator.Acceptable, text
        assert parse_timecode(text) is not None


# --------------------------------------------------------------------------- #
# Заголовок
# --------------------------------------------------------------------------- #
def test_trim_title_shows_saved_values_at_start(qapp):
    theme.apply("dark")
    settings = Settings({"opt_trim_start": 5.0, "opt_trim_end": 10.0})
    side = OptionsSidebar(settings)

    assert side.trim_title.text().startswith("Фрагмент · 0:05 по 0:10"), side.trim_title.text()


def test_trim_title_empty_for_whole_file(qapp):
    theme.apply("dark")
    side = OptionsSidebar(Settings({"opt_trim_start": 0.0, "opt_trim_end": 0.0}))
    assert side.trim_title.text() == "Фрагмент · весь файл"


def test_trim_title_repaints_on_theme_change(qapp):
    theme.apply("dark")
    side = OptionsSidebar(Settings({"opt_trim_start": 5.0, "opt_trim_end": 10.0}))
    dark_muted = theme.current()["muted"]
    assert dark_muted in side.trim_title.styleSheet()

    theme.apply("light")
    light_muted = theme.current()["muted"]
    assert light_muted != dark_muted
    assert light_muted in side.trim_title.styleSheet(), side.trim_title.styleSheet()

    theme.apply("dark")
    assert dark_muted in side.trim_title.styleSheet()


def test_invalid_trim_turns_red_and_survives_theme(qapp):
    theme.apply("dark")
    side = OptionsSidebar(Settings())
    side.edit_trim_start.setText("0:10")
    side.edit_trim_end.setText("0:05")      # конец раньше начала

    assert side.trim_title.text() == "Фрагмент · проверьте время"
    assert theme.current()["danger"] in side.trim_title.styleSheet()

    theme.apply("light")
    assert theme.current()["danger"] in side.trim_title.styleSheet()


# --------------------------------------------------------------------------- #
# Блок «Качество»: показывается только там, где влияет
# --------------------------------------------------------------------------- #
def _sidebar(qapp, settings: Settings | None = None) -> OptionsSidebar:
    theme.apply("dark")
    side = OptionsSidebar(settings or Settings())
    side.resize(320, 900)
    side.show()
    qapp.processEvents()
    return side


def test_quality_hidden_for_gif_only(qapp):
    side = _sidebar(qapp)
    side.set_quality_context([("gif", "video")])
    qapp.processEvents()

    assert side.quality_box.isVisible() is False
    assert side.cmb_resolution.isVisible() is True      # соседний блок на месте


def test_quality_hidden_for_audio_only(qapp):
    side = _sidebar(qapp)
    side.set_quality_context([("mp3", "audio")])
    qapp.processEvents()

    assert side.quality_box.isVisible() is False


def test_quality_visible_for_mp4_with_numbers(qapp):
    side = _sidebar(qapp)
    side.set_quality_context([("mp4", "video")])
    qapp.processEvents()

    assert side.quality_box.isVisible() is True
    assert "CRF" in side.quality_hint.text()


def test_quality_hint_mentions_mix(qapp):
    side = _sidebar(qapp)
    side.set_quality_context([("mp4", "video"), ("gif", "video")])
    qapp.processEvents()

    hint = side.quality_hint.text()
    assert side.quality_box.isVisible() is True
    assert "CRF 17" in hint and "GIF" in hint and "не влияет" in hint


def test_quality_tooltips_filled(qapp):
    side = _sidebar(qapp)
    side.set_quality_context([("mp4", "video"), ("jpg", "image")])
    qapp.processEvents()

    tips = [btn.toolTip() for btn in side.seg_quality._group.buttons()]
    assert len(tips) == 3
    assert all(tip.strip() for tip in tips), tips
    assert "CRF 17" in tips[0] and "JPEG/WebP/AVIF 95" in tips[0]


def test_quality_segment_restores_saved_value(qapp):
    side = _sidebar(qapp, Settings({"opt_quality": "small"}))
    assert side.seg_quality.value() == "small"
    assert side.seg_quality._group.buttons()[2].text() == "Размер"


def test_quality_hint_follows_gpu_flag(qapp):
    side = _sidebar(qapp)
    side.set_quality_context([("mp4", "video")])
    qapp.processEvents()
    assert "CRF 17" in side.quality_hint.text()

    side.set_quality_context([("mp4", "video")], gpu=True)
    qapp.processEvents()
    hint = side.quality_hint.text()
    assert "NVENC" in hint and "CRF 17" not in hint
    assert "CRF 17" not in side.seg_quality._group.buttons()[0].toolTip()


def test_window_passes_gpu_to_sidebar(qapp, monkeypatch, tmp_path):
    """Переключение GPU в сайдбаре сразу меняет подсказку качества."""
    from pathlib import Path

    import mediaforge.ui.main_window as mw

    monkeypatch.setenv("MEDIAFORGE_CONFIG_DIR", str(tmp_path))
    theme.apply("dark")
    win = mw.MainWindow(Settings({"opt_gpu": True}), None, "ffmpeg не найден")
    src = Path("x.mp4")
    win.jobs.append(Job(src=src, info=MediaInfo(path=src, kind="video", duration=5.0),
                        target=mw.fm.BY_KEY["mp4"]))
    win._update_option_visibility()
    qapp.processEvents()
    assert "NVENC" in win.sidebar.quality_hint.text()

    win.sidebar.chk_gpu.setChecked(False)
    qapp.processEvents()
    assert "CRF 17" in win.sidebar.quality_hint.text()
    assert win.settings.get("opt_gpu") is False

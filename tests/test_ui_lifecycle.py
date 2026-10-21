"""Уборка кэша предпросмотра вызывается из приложения.

Тест требует Qt; если платформа не поднимается (нет libGL и т.п.),
он пропускается, а не падает.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="нет PySide6")

try:                       # на headless-машинах часто нет libEGL/libGL
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QApplication
    from mediaforge.core import preview
    from mediaforge.core.config import Settings
except ImportError as exc:  # noqa: BLE001
    pytest.skip(f"Qt недоступен: {exc}", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    try:
        app = QApplication.instance() or QApplication([])
    except Exception as exc:  # noqa: BLE001 — нет дисплея/библиотек
        pytest.skip(f"Qt не поднимается: {exc}")
    yield app


def test_cleanup_runs_on_window_close(qapp, monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(preview, "cleanup", lambda *a, **k: calls.append("close"))
    monkeypatch.setenv("MEDIAFORGE_CONFIG_DIR", str(tmp_path))

    from mediaforge.ui.main_window import MainWindow

    win = MainWindow(Settings(), None, "ffmpeg не найден")
    win.closeEvent(QCloseEvent())

    assert calls == ["close"], "уборка кэша не вызвана при закрытии окна"


def test_cleanup_runs_on_startup(monkeypatch, tmp_path):
    """Старт приложения проверяем в отдельном процессе: QApplication один на процесс."""
    repo = Path(__file__).resolve().parents[1]
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        "from PySide6.QtWidgets import QApplication\n"
        "QApplication.exec = lambda self: 0\n"
        "from mediaforge.core import preview\n"
        "calls = []\n"
        "preview.cleanup = lambda *a, **k: calls.append('start')\n"
        "from mediaforge import app\n"
        "app.main([])\n"
        "print('CALLS:', calls)\n"
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MEDIAFORGE_CONFIG_DIR"] = str(tmp_path)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, timeout=180, env=env)
    if proc.returncode != 0:
        pytest.skip(f"приложение не стартует в этом окружении: {proc.stderr[-300:]}")
    assert "CALLS: ['start']" in proc.stdout, proc.stdout + proc.stderr

"""Точка входа приложения."""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from .core.config import APP_NAME, APP_VERSION, Settings
from .core.ffmpeg import FFmpegNotFound, Tools
from .ui import theme
from .ui.main_window import MainWindow, app_icon


def _pick_font() -> QFont:
    available = set(QFontDatabase.families())
    for family in ("Segoe UI Variable Text", "Segoe UI", "Inter",
                   "SF Pro Text", "Noto Sans", "DejaVu Sans"):
        if family in available:
            return QFont(family, 10)
    return QFont()


def _install_excepthook(app: QApplication) -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        # под pythonw.exe stderr отсутствует
        try:
            if sys.stderr is not None:
                sys.stderr.write(text)
        except Exception:  # noqa: BLE001
            pass
        try:
            Path(tempfile.gettempdir(), "mediaforge-error.log").write_text(text, "utf-8")
        except Exception:  # noqa: BLE001
            pass
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle(f"{APP_NAME} — ошибка")
        box.setText("Произошла непредвиденная ошибка.")
        box.setDetailedText(text[-3000:])
        box.exec()

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    if os.name == "nt":
        try:  # корректная иконка/группировка в панели задач Windows
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "MediaForge.Converter.1"
            )
        except Exception:  # noqa: BLE001
            pass

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(_pick_font())
    icon = app_icon()
    if icon is not None and not icon.isNull():
        app.setWindowIcon(icon)

    settings = Settings.load()
    theme.apply(settings.get("theme", "system"))

    tools: Tools | None
    error = ""
    try:
        tools = Tools.locate()
    except FFmpegNotFound as exc:
        tools = None
        error = str(exc)

    _install_excepthook(app)
    window = MainWindow(settings, tools, error)
    if icon is not None and not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

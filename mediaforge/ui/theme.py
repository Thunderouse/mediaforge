"""Темы оформления: палитры + стили QSS. Без внешних ресурсов — всё рисуется кодом."""

from __future__ import annotations

from string import Template

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QGuiApplication

DARK = {
    "name": "dark",
    "bg": "#141518",
    "surface": "#1A1C20",
    "card": "#212328",
    "card_hover": "#26292F",
    "input": "#1E2025",
    "border": "#2C2F35",
    "border_strong": "#3A3E46",
    "text": "#EDEEF1",
    "muted": "#9096A0",
    "dim": "#6A7079",
    "accent": "#2E90EA",
    "accent_hover": "#3F9DF3",
    "accent_pressed": "#257CCB",
    "accent_soft": "#1C3350",
    "on_accent": "#FFFFFF",
    "success": "#3FB950",
    "danger": "#F2555A",
    "warn": "#D9A343",
    "selection": "#26608F",
    "shadow": "#0B0C0E",
    "badge": "#2A2D34",
}

LIGHT = {
    "name": "light",
    "bg": "#F1F2F4",
    "surface": "#FAFAFB",
    "card": "#FFFFFF",
    "card_hover": "#F6F7F9",
    "input": "#FFFFFF",
    "border": "#E2E4E9",
    "border_strong": "#CDD1D8",
    "text": "#15171B",
    "muted": "#666C77",
    "dim": "#8A909A",
    "accent": "#0B6BCB",
    "accent_hover": "#0F7BE4",
    "accent_pressed": "#0959A8",
    "accent_soft": "#E3EEFA",
    "on_accent": "#FFFFFF",
    "success": "#1F883D",
    "danger": "#D33B41",
    "warn": "#B57A16",
    "selection": "#CFE4FA",
    "shadow": "#B9BEC7",
    "badge": "#EDEFF3",
}

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", Inter, "SF Pro Text", ' \
             '"Noto Sans", "DejaVu Sans", sans-serif'

_palette = DARK


class _Bus(QObject):
    changed = Signal()


bus = _Bus()


def current() -> dict:
    return _palette


def color(token: str) -> QColor:
    return QColor(_palette[token])


def system_is_dark() -> bool:
    try:
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorScheme"):
            return hints.colorScheme().name.lower() == "dark"
    except Exception:  # noqa: BLE001
        pass
    return False


def resolve(name: str) -> dict:
    if name == "light":
        return LIGHT
    if name == "dark":
        return DARK
    return DARK if system_is_dark() else LIGHT


def apply(name: str) -> dict:
    """Переключает тему и возвращает активную палитру."""
    global _palette
    _palette = resolve(name)
    bus.changed.emit()
    return _palette


QSS = Template(
    """
* { outline: 0; }
QWidget {
    background: transparent;
    color: $text;
    font-family: $font;
    font-size: 13px;
}
QMainWindow, #root { background: $bg; }

#header { background: $surface; border-bottom: 1px solid $border; }
#sidebar { background: $surface; border-left: 1px solid $border; }
#footer { background: $surface; border-top: 1px solid $border; }
#sidebarBottom { background: $surface; border-top: 1px solid $border; }
#listHeader { background: transparent; }

#appTitle { font-size: 15px; font-weight: 600; }
#appSub { color: $muted; font-size: 11px; }
#sectionTitle { color: $muted; font-size: 11px; font-weight: 600; }
#hint { color: $dim; font-size: 11px; }
#status { color: $muted; font-size: 12px; }
#statusStrong { color: $text; font-size: 12px; font-weight: 600; }
#summary { color: $muted; font-size: 12px; }
#emptyTitle { font-size: 14px; font-weight: 600; }
#emptySub { color: $muted; font-size: 12px; }

#banner { background: $accent_soft; border: 1px solid $border_strong; border-radius: 10px; }
#bannerText { color: $text; font-size: 12px; }

#featureCard { background: $card; border: 1px solid $border; border-radius: 12px; }
#featureTitle { font-size: 12px; font-weight: 600; }

QPushButton#primary {
    background: $accent; color: $on_accent; border: none; border-radius: 9px;
    padding: 11px 16px; font-size: 13px; font-weight: 600;
}
QPushButton#primary:hover { background: $accent_hover; }
QPushButton#primary:pressed { background: $accent_pressed; }
QPushButton#primary:disabled { background: $input; color: $dim; }

QPushButton#secondary {
    background: $input; color: $text; border: 1px solid $border;
    border-radius: 9px; padding: 10px 16px; font-size: 13px;
}
QPushButton#secondary:hover { background: $card_hover; border-color: $border_strong; }
QPushButton#secondary:disabled { color: $dim; border-color: $border; }

QPushButton#ghost {
    background: transparent; color: $muted; border: none;
    border-radius: 7px; padding: 6px 9px; font-size: 12px;
}
QPushButton#ghost:hover { background: $card; color: $text; }
QPushButton#ghost:disabled { color: $dim; }

QPushButton#iconBtn {
    background: transparent; border: none; border-radius: 8px; padding: 6px;
}
QPushButton#iconBtn:hover { background: $card; }
QPushButton#iconBtn:pressed { background: $card_hover; }

QPushButton#segBtn {
    background: transparent; border: none; border-radius: 7px;
    padding: 6px 10px; color: $muted; font-size: 12px;
}
QPushButton#segBtn:hover { color: $text; }
QPushButton#segBtn:checked { background: $card; color: $text; font-weight: 600; }

#segWrap { background: $input; border: 1px solid $border; border-radius: 9px; }

QComboBox {
    background: $input; color: $text; border: 1px solid $border;
    border-radius: 8px; padding: 6px 26px 6px 10px; min-height: 18px; font-size: 12px;
}
QComboBox:hover { border-color: $border_strong; }
QComboBox:focus { border-color: $accent; }
QComboBox:disabled { color: $dim; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: $card; color: $text; border: 1px solid $border_strong;
    border-radius: 8px; padding: 4px; outline: none;
    selection-background-color: $selection; selection-color: $text;
}
QComboBox QAbstractItemView::item { padding: 6px 8px; border-radius: 6px; min-height: 22px; }

QLineEdit {
    background: $input; color: $text; border: 1px solid $border;
    border-radius: 8px; padding: 7px 9px; font-size: 12px;
}
QLineEdit:focus { border-color: $accent; }
QLineEdit:disabled { color: $dim; }

QTabWidget#mainTabs::pane { border: none; background: $bg; }
QTabWidget#mainTabs > QTabBar { background: $surface; }
QTabBar::tab {
    background: transparent; color: $muted; padding: 7px 16px; margin: 6px 2px 6px 0;
    border-radius: 8px; font-size: 12px;
}
QTabBar::tab:selected { background: $card; color: $text; font-weight: 600; }
QTabBar::tab:hover { color: $text; }

QListWidget#previewList {
    background: $card; border: 1px solid $border; border-radius: 10px; padding: 4px;
    outline: none;
}
QListWidget#previewList::item { padding: 7px 8px; border-radius: 7px; color: $muted; }
QListWidget#previewList::item:selected { background: $selection; color: $text; }
QListWidget#previewList::item:hover { color: $text; }

QSlider::groove:horizontal { height: 4px; background: $border; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: $accent;
}
QSlider::handle:horizontal:hover { background: $accent_hover; }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: $border_strong; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QToolTip {
    background: $card; color: $text; border: 1px solid $border_strong;
    border-radius: 6px; padding: 5px 7px; font-size: 11px;
}

QMenu {
    background: $card; color: $text; border: 1px solid $border_strong;
    border-radius: 8px; padding: 4px;
}
QMenu::item { padding: 6px 18px 6px 10px; border-radius: 6px; }
QMenu::item:selected { background: $selection; }

QMessageBox { background: $surface; }
QMessageBox QLabel { color: $text; }
QDialog { background: $surface; }

#divider { background: $border; }
#chip {
    background: $badge; color: $muted; border-radius: 7px;
    padding: 3px 7px; font-size: 10px; font-weight: 600;
}
"""
)


def qss(palette: dict | None = None) -> str:
    p = palette or _palette
    return QSS.substitute(font=FONT_STACK, **p)

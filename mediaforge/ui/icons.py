"""Иконки: инлайн-SVG, перекрашиваются под текущую тему."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4'
           'M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11Z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3 8.5A2.5 2.5 0 0 1 5.5 6H9l2 2h7.5A2.5 2.5 0 0 1 21 10.5v7A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5Z"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "image": '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/>'
             '<circle cx="8.5" cy="9.5" r="1.6"/><path d="M4 17l4.5-4.5 3.5 3.5 3-3L20 17"/>',
    "video": '<rect x="2.5" y="6" width="13" height="12" rx="2.5"/>'
             '<path d="M15.5 10.5l5-3v9l-5-3z"/>',
    "audio": '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/>'
             '<circle cx="16.5" cy="16" r="2.5"/>',
    "arrow": '<path d="M4 12h15M13 6l6 6-6 6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "alert": '<path d="M12 8v5M12 16.5v.5"/><circle cx="12" cy="12" r="9"/>',
    "trash": '<path d="M4 7h16M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7'
             'M6.5 7l.8 12A1.5 1.5 0 0 0 8.8 20.5h6.4a1.5 1.5 0 0 0 1.5-1.5L17.5 7"/>',
    "gif": '<rect x="2.5" y="5" width="19" height="14" rx="3"/>'
           '<path d="M10 10.5a2 2 0 1 0 0 3h.7v-1.4M13.5 13.5v-4M16.5 9.5h2.5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8v.4"/>',
    "spark": '<path d="M12 3l1.8 4.9L19 9.7l-5.2 1.8L12 16.4l-1.8-4.9L5 9.7l5.2-1.8z"/>',
    "chevron": '<path d="M7 10l5 5 5-5"/>',
}

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="{color}" stroke-width="{w}" stroke-linecap="round" '
        'stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=512)
def _render(name: str, color_hex: str, size: int, width: float) -> QPixmap:
    body = _PATHS.get(name, _PATHS["info"])
    svg = _SVG.format(color=color_hex, w=width, body=body)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    ratio = 2.0
    pm = QPixmap(QSize(int(size * ratio), int(size * ratio)))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size * ratio, size * ratio))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def pixmap(name: str, color_hex: str, size: int = 18, width: float = 1.7) -> QPixmap:
    return _render(name, color_hex, size, width)


def icon(name: str, color_hex: str, size: int = 18, width: float = 1.7) -> QIcon:
    return QIcon(_render(name, color_hex, size, width))


def qcolor(hex_str: str) -> QColor:
    return QColor(hex_str)


KIND_ICON = {"image": "image", "video": "video", "audio": "audio", "gif": "gif"}

"""Кастомные виджеты: зона перетаскивания, строка задачи, чекбоксы, сегменты."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (QPointF, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..core import formats as fm
from ..core.engine import (STATUS_CANCELLED, STATUS_DONE, STATUS_ERROR,
                           STATUS_RUNNING, Job)
from ..core.ffmpeg import human_size
from ..core.timecode import format_timecode
from . import icons, theme


# --------------------------------------------------------------------------- #
class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent=None, mode: Qt.TextElideMode = Qt.ElideMiddle):
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self.setText(text)
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self._apply()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, self._mode, max(40, self.width())))
        self.setToolTip(self._full)


class CheckBox(QAbstractButton):
    """Флажок рисуется вручную — одинаково аккуратно в обеих темах."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 34, 26)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(1, (self.height() - 17) / 2, 17, 17)
        checked = self.isChecked()
        path = QPainterPath()
        path.addRoundedRect(box, 5, 5)
        if checked:
            painter.fillPath(path, QColor(p["accent"]))
            painter.setPen(QPen(QColor(p["on_accent"]), 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            points = [QPointF(box.left() + 4.4, box.top() + 8.8),
                      QPointF(box.left() + 7.4, box.top() + 11.8),
                      QPointF(box.left() + 12.8, box.top() + 5.2)]
            painter.drawPolyline(points)
        else:
            painter.setBrush(QColor(p["input"]))
            border = p["accent"] if self.underMouse() else p["border_strong"]
            painter.setPen(QPen(QColor(border), 1.3))
            painter.drawPath(path)

        font = QFont(self.font())
        painter.setFont(font)
        painter.setPen(QColor(p["text"] if checked or self.underMouse() else p["muted"]))
        rect = QRectF(26, 0, self.width() - 28, self.height())
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        painter.end()


# --------------------------------------------------------------------------- #
class Segmented(QWidget):
    """Компактный переключатель из 2–4 вариантов."""

    changed = Signal(str)

    def __init__(self, items: tuple[tuple[str, str], ...], parent=None):
        super().__init__(parent)
        self.setObjectName("segWrap")
        self.setFixedHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._keys: list[str] = []
        for key, label in items:
            btn = QPushButton(label, self)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self._group.addButton(btn)
            lay.addWidget(btn)
            self._keys.append(key)
            btn.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        if self._keys:
            self._group.buttons()[0].setChecked(True)

    def value(self) -> str:
        for key, btn in zip(self._keys, self._group.buttons()):
            if btn.isChecked():
                return key
        return self._keys[0] if self._keys else ""

    def setValue(self, key: str) -> None:  # noqa: N802
        for k, btn in zip(self._keys, self._group.buttons()):
            if k == key:
                btn.setChecked(True)
                return


# --------------------------------------------------------------------------- #
class IconButton(QPushButton):
    def __init__(self, name: str, tooltip: str = "", size: int = 18, parent=None):
        super().__init__(parent)
        self._name = name
        self._size = size
        self.setObjectName("iconBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(32, 32)
        self.setToolTip(tooltip)
        self.setIconSize(QSize(size, size))
        self.refresh()

    def refresh(self) -> None:
        self.setIcon(icons.icon(self._name, theme.current()["muted"], self._size))

    def set_icon(self, name: str) -> None:
        self._name = name
        self.refresh()


class Combo(QComboBox):
    """QComboBox с собственной стрелкой (QSS-стрелки в Qt выглядят инородно)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() - 14
        cy = self.height() / 2
        pen = QPen(QColor(p["muted"]), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2.5), QPointF(cx + 4, cy - 2)])
        painter.end()


# --------------------------------------------------------------------------- #
class DropZone(QWidget):
    """Пунктирная зона: перетащите файлы или кликните."""

    clicked = Signal()
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self._compact = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignCenter)

        self.icon_label = QLabel(self)
        self.icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.icon_label.setAlignment(Qt.AlignCenter)

        self.title = QLabel("Перетащите файлы или папки", self)
        self.title.setObjectName("emptyTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.sub = QLabel("видео · картинки · музыка — или нажмите, чтобы выбрать", self)
        self.sub.setObjectName("emptySub")
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setAttribute(Qt.WA_TransparentForMouseEvents)

        lay.addWidget(self.icon_label)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        theme.bus.changed.connect(self.refresh_theme)
        self.set_compact(False)

    def refresh_theme(self) -> None:
        self._refresh()

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self.sub.setVisible(not compact)
        self.title.setText("Добавить файлы" if compact else "Перетащите файлы или папки")
        self.setFixedHeight(78 if compact else 196)
        self._refresh()

    def _refresh(self) -> None:
        p = theme.current()
        size = 26 if self._compact else 40
        col = p["accent"] if self._hover else p["dim"]
        self.icon_label.setPixmap(icons.pixmap("plus", col, size, 1.9))
        self.update()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._hover = True
            self._refresh()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._refresh()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._refresh()
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self._refresh()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._refresh()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.fillPath(path, QColor(p["card_hover"] if self._hover else p["surface"]))
        pen = QPen(QColor(p["accent"] if self._hover else p["border_strong"]), 1.4, Qt.DashLine)
        pen.setDashPattern([4, 3])
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()


# --------------------------------------------------------------------------- #
class JobRow(QFrame):
    """Строка файла: иконка, имя, метаданные, выбор формата, прогресс."""

    targetChanged = Signal(str, str)   # job_id, target_key
    removeRequested = Signal(str)
    activated = Signal(str)            # двойной клик — открыть предпросмотр

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.job = job
        self.setFixedHeight(78)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hover = False
        self._trim: tuple[float, float] = (0.0, 0.0)
        self.setAttribute(Qt.WA_Hover, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 10, 16)
        lay.setSpacing(11)

        self.badge = QLabel(self)
        self.badge.setFixedSize(38, 38)
        self.badge.setAlignment(Qt.AlignCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        self.name = ElidedLabel(job.name, self)
        self.name.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.meta = ElidedLabel("", self, Qt.ElideRight)
        self.meta.setObjectName("hint")
        text_col.addWidget(self.name)
        text_col.addWidget(self.meta)

        self.combo = Combo(self)
        self.combo.setFixedWidth(172)
        self.combo.setCursor(Qt.PointingHandCursor)
        self._keys: list[str] = []
        for target in fm.targets_for(job.info.kind):
            self._keys.append(target.key)
            self.combo.addItem(target.label)
            idx = self.combo.count() - 1
            hint = target.hint
            self.combo.setItemData(idx, f"{target.label}\n{hint}" if hint else target.label,
                                   Qt.ToolTipRole)
        self.combo.setCurrentIndex(max(0, self._keys.index(job.target.key))
                                   if job.target.key in self._keys else 0)
        self.combo.currentIndexChanged.connect(self._on_combo)

        self.remove = IconButton("close", "Убрать из списка", 16, self)
        self.remove.setFixedSize(26, 26)
        self.remove.clicked.connect(lambda: self.removeRequested.emit(self.job.id))

        lay.addWidget(self.badge)
        lay.addLayout(text_col, 1)
        lay.addWidget(self.combo)
        lay.addWidget(self.remove)

        theme.bus.changed.connect(self.refresh_theme)
        self.refresh_theme()
        self.update_state()

    # ------------------------------------------------------------------ #
    def _on_combo(self, index: int) -> None:
        if 0 <= index < len(self._keys):
            key = self._keys[index]
            self.targetChanged.emit(self.job.id, key)

    def set_combo_key(self, key: str) -> None:
        if key in self._keys:
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(self._keys.index(key))
            self.combo.blockSignals(False)

    def set_trim(self, start: float, end: float) -> None:
        self._trim = (start or 0.0, end or 0.0)
        self.update_state()

    def set_info(self, info) -> None:
        """Обновляет тип файла после ffprobe: пересобирает список форматов."""
        self.job.info = info
        keys = [t.key for t in fm.targets_for(info.kind)]
        if keys != self._keys:
            self.combo.blockSignals(True)
            self.combo.clear()
            self._keys = []
            for target in fm.targets_for(info.kind):
                self._keys.append(target.key)
                self.combo.addItem(target.label)
                idx = self.combo.count() - 1
                if target.hint:
                    self.combo.setItemData(idx, f"{target.label}\n{target.hint}", Qt.ToolTipRole)
            keep = self.job.target.key if self.job.target.key in self._keys else \
                fm.default_target(info.path.suffix, info.kind)
            if keep not in self._keys and self._keys:
                keep = self._keys[0]
            self.combo.setCurrentIndex(self._keys.index(keep))
            self.combo.blockSignals(False)
            self.job.target = fm.BY_KEY[keep]
        self.refresh_theme()
        self.update_state()

    def refresh_theme(self) -> None:
        p = theme.current()
        kind = "gif" if self.job.target.key.startswith("gif") else self.job.info.kind
        name = {"image": "image", "video": "video", "audio": "audio", "gif": "gif"}.get(kind, "info")
        self.badge.setPixmap(icons.pixmap(name, p["muted"], 19))
        self.badge.setStyleSheet(
            f"background: {p['badge']}; border-radius: 10px;"
        )
        self.remove.refresh()
        self.update()

    def update_state(self) -> None:
        job = self.job
        p = theme.current()
        info = job.info
        parts: list[str] = []
        if info.kind == "image":
            parts.append((info.path.suffix.lstrip(".") or "img").upper())
            if info.resolution_label:
                parts.append(info.resolution_label)
        elif info.kind == "audio":
            parts.append((info.audio_codec or "audio").upper())
            if info.duration_label:
                parts.append(info.duration_label)
        else:
            parts.append((info.path.suffix.lstrip(".") or "video").upper())
            if info.resolution_label:
                parts.append(info.resolution_label)
            if info.duration_label:
                parts.append(info.duration_label)
        parts.append(info.size_label)

        if job.status == STATUS_DONE and job.output:
            try:
                out_size = job.output.stat().st_size
                delta = ""
                tone = p["text"]
                if info.size:
                    ratio = out_size / info.size
                    delta = f" · {ratio:.0%}"
                    tone = p["success"] if ratio < 0.98 else (
                        p["warn"] if ratio > 1.1 else p["muted"])
                parts.append(f"→ {job.output.suffix.lstrip('.').upper()} {human_size(out_size)}{delta}")
            except OSError:
                parts.append("готово")
                tone = p["success"]
            self.meta.setStyleSheet(f"color: {tone}; font-size: 11px;")
        elif job.status == STATUS_ERROR:
            self.meta.setText(f"Ошибка: {job.message}")
            self.meta.setStyleSheet(f"color: {p['danger']}; font-size: 11px;")
            self.meta.setToolTip(f"{job.message}\n{job.src}")
            return
        elif job.status == STATUS_CANCELLED:
            parts.append("отменено")
            self.meta.setStyleSheet(f"color: {p['dim']}; font-size: 11px;")
        elif job.status == STATUS_RUNNING:
            pct = int(job.progress * 100)
            speed = f" · {job.speed}" if job.speed else ""
            parts = [f"{pct}%{speed}"] + parts
            self.meta.setStyleSheet(f"color: {p['accent']}; font-size: 11px;")
        else:
            tone = p["warn"] if info.probe_failed else p["dim"]
            self.meta.setStyleSheet(f"color: {tone}; font-size: 11px;")
        if info.probe_failed:
            # ffprobe не осилил файл: честно говорим об этом, а не показываем нули
            # (подсказку ставит ElidedLabel — полный текст подписи)
            parts.append("⚠ метаданные не прочитаны")
        start, end = self._trim
        if (start or end) and self.job.info.kind in ("video", "audio"):
            tail = format_timecode(end) if end else "конец"
            parts.insert(0, f"✂ {format_timecode(start)}–{tail}")
        self.meta.setText("   ·   ".join(x for x in parts if x))
        self.combo.setEnabled(job.status != STATUS_RUNNING)
        self.update()

    # ------------------------------------------------------------------ #
    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.activated.emit(self.job.id)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme.current()
        job = self.job
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)

        bg = QColor(p["card_hover"] if self._hover else p["card"])
        painter.fillPath(path, bg)

        border = p["border"]
        if job.status == STATUS_RUNNING:
            border = p["accent"]
        elif job.status == STATUS_ERROR:
            border = p["danger"]
        painter.setPen(QPen(QColor(border), 1.0))
        painter.drawPath(path)

        # индикатор прогресса — тонкая линия по нижней кромке
        if job.status in (STATUS_RUNNING, STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED):
            track = QRectF(rect.left() + 12, rect.bottom() - 7, rect.width() - 24, 2.5)
            track_path = QPainterPath()
            track_path.addRoundedRect(track, 1.2, 1.2)
            painter.fillPath(track_path, QColor(p["border"]))
            frac = 1.0 if job.status == STATUS_DONE else max(0.02, min(1.0, job.progress))
            color = {STATUS_DONE: p["success"], STATUS_ERROR: p["danger"],
                     STATUS_CANCELLED: p["dim"]}.get(job.status, p["accent"])
            bar = QRectF(track)
            bar.setWidth(max(3.0, track.width() * frac))
            bar_path = QPainterPath()
            bar_path.addRoundedRect(bar, 1.2, 1.2)
            painter.fillPath(bar_path, QColor(color))
        painter.end()


# --------------------------------------------------------------------------- #
class ProgressLine(QWidget):
    """Тонкая полоса прогресса для подвала окна."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self.setFixedHeight(3)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setValue(self, value: float) -> None:  # noqa: N802
        self._value = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme.current()
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(p["border"]))
        w = int(self.width() * self._value)
        if w > 0:
            painter.fillRect(0, 0, w, self.height(), QColor(p["accent"]))
        painter.end()

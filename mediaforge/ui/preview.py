"""Вкладка «Предпросмотр»: кадр/картинка/волна + ползунки обрезки по полоске кадров."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QSizePolicy, QSlider, QVBoxLayout,
                               QWidget)

from ..core import preview as pv
from ..core.engine import Job
from ..core.ffmpeg import Tools
from ..core.timecode import format_timecode
from . import theme


class Filmstrip(QWidget):
    """Полоска кадров с двумя ручками: начало и конец фрагмента."""

    trimEdited = Signal(float, float)
    seeked = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setMaximumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._strip: QPixmap | None = None
        self._duration = 0.0
        self._start = 0.0
        self._end = 0.0
        self._pos = 0.0
        self._drag: str | None = None

    # ------------------------------------------------------------------ #
    def set_strip(self, path: Path | None) -> None:
        self._strip = QPixmap(str(path)) if path and Path(path).exists() else None
        self.update()

    def set_duration(self, seconds: float) -> None:
        self._duration = max(0.0, seconds)
        self.update()

    def set_trim(self, start: float, end: float) -> None:
        # глобальный фрагмент может быть длиннее конкретного файла — показываем
        # то, что помещается, чтобы ручки не уезжали за пределы полоски
        duration = self._duration or 1e9
        self._start = min(max(0.0, start), duration)
        self._end = min(end, duration) if end > 0 else duration
        self._end = max(self._end, self._start)
        self.update()

    def set_position(self, seconds: float) -> None:
        self._pos = max(0.0, seconds)
        self.update()

    # ------------------------------------------------------------------ #
    def _x(self, seconds: float) -> float:
        if self._duration <= 0:
            return 0.0
        return min(1.0, max(0.0, seconds / self._duration)) * self.width()

    def _t(self, x: float) -> float:
        if self.width() <= 0 or self._duration <= 0:
            return 0.0
        return min(self._duration, max(0.0, x / self.width() * self._duration))

    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._duration <= 0:
            return
        x = event.position().x()
        if abs(x - self._x(self._start)) <= 12:
            self._drag = "start"
        elif abs(x - self._x(self._end)) <= 12:
            self._drag = "end"
        else:
            self._drag = "seek"
            self._move_position(x)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None or self._duration <= 0:
            return
        x = event.position().x()
        if self._drag == "seek":
            self._move_position(x)
            return
        t = self._t(x)
        if self._drag == "start":
            self._start = min(t, self._end - 0.1)
            self._start = max(0.0, self._start)
        else:
            self._end = max(t, self._start + 0.1)
            self._end = min(self._duration, self._end)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag in ("start", "end"):
            self.trimEdited.emit(self._start, self._end if self._end < self._duration else 0.0)
        self._drag = None

    def _move_position(self, x: float) -> None:
        self._pos = self._t(x)
        self.update()
        self.seeked.emit(self._pos)

    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:  # noqa: N802
        p = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 8, 8)
        painter.setClipPath(clip)
        painter.fillPath(clip, QColor(p["input"]))

        if self._strip is not None and not self._strip.isNull():
            # растягиваем по ширине виджета: иначе кадры обрезаются и время
            # перестаёт соответствовать позиции на полоске
            scaled = self._strip.scaled(self.size(), Qt.IgnoreAspectRatio,
                                        Qt.SmoothTransformation)
            painter.drawPixmap(0, 0, scaled)

        if self._duration > 0:
            sx, ex = self._x(self._start), self._x(self._end)
            shade = QColor(0, 0, 0, 170)
            painter.fillRect(QRectF(0, 0, sx, rect.height()), shade)
            painter.fillRect(QRectF(ex, 0, rect.width() - ex, rect.height()), shade)

            # рамка выделения: акцент + светлая внутренняя линия
            painter.setPen(QPen(QColor(p["accent"]), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(sx + 1, 1, max(1.0, ex - sx - 2), rect.height() - 2))

            # ручки: широкие, с тёмной обводкой — видны на любом кадре
            for x in (sx, ex):
                handle = QRectF(x - 6, 0, 12, rect.height())
                path = QPainterPath()
                path.addRoundedRect(handle, 4, 4)
                painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
                painter.fillPath(path, QColor(p["accent"]))
                painter.drawPath(path)
                painter.fillRect(QRectF(x - 0.75, rect.height() / 2 - 9, 1.5, 18),
                                 QColor(255, 255, 255, 230))

            # текущая позиция
            px = self._x(self._pos)
            painter.fillRect(QRectF(px - 0.5, 0, 1.5, rect.height()),
                             QColor(255, 255, 255, 200))

            # подписи
            font = QFont(self.font())
            font.setPointSizeF(max(7.0, font.pointSizeF() - 2))
            painter.setFont(font)
            painter.setPen(QColor(p["on_accent"]))
            metrics = QFontMetrics(font)
            for value, x, align in ((self._start, sx + 8, Qt.AlignLeft),
                                    (self._end, ex - 8, Qt.AlignRight)):
                text = format_timecode(value)
                w = metrics.horizontalAdvance(text) + 8
                box = QRectF(x - (w if align == Qt.AlignRight else 0), rect.height() - 18, w, 14)
                painter.fillRect(box, QColor(0, 0, 0, 150))
                painter.drawText(box, align | Qt.AlignVCenter, f" {text} ")
        painter.end()


class _ScaledImage(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._pixmap: QPixmap | None = None

    def set_image(self, path: Path | None) -> None:
        self._pixmap = QPixmap(str(path)) if path and Path(path).exists() else None
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self.setPixmap(QPixmap())
            return
        area = self.size() - QSize(4, 4)
        if area.width() < 8 or area.height() < 8:
            return
        self.setPixmap(self._pixmap.scaled(area, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class PreviewPanel(QWidget):
    """Слева список файлов, справа кадр и ползунки фрагмента."""

    trimChanged = Signal(float, float)
    jobSelected = Signal(str)

    def __init__(self, tools: Tools | None, parent=None):
        super().__init__(parent)
        self.tools = tools
        self.jobs: list[Job] = []
        self._job: Job | None = None
        self._trim = (0.0, 0.0)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        body = QWidget()
        lay.addWidget(body, 1)

        root = QHBoxLayout(body)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(14)

        self.list = QListWidget()
        self.list.setFixedWidth(248)
        self.list.setObjectName("previewList")
        self.list.currentItemChanged.connect(self._on_list_changed)
        self.list.itemDoubleClicked.connect(
            lambda item: self.jobSelected.emit(item.data(Qt.UserRole)))
        root.addWidget(self.list)

        right = QVBoxLayout()
        right.setSpacing(8)
        root.addLayout(right, 1)

        self.title = QLabel("Файл не выбран")
        self.title.setObjectName("appTitle")
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        right.addWidget(self.title)

        self.image = _ScaledImage()
        right.addWidget(self.image, 1)

        self.strip = Filmstrip()
        self.strip.trimEdited.connect(self._on_strip_trim)
        self.strip.seeked.connect(self._on_seek)
        right.addWidget(self.strip)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self._on_slider)
        self.slider.valueChanged.connect(self._on_slider)
        right.addWidget(self.slider)

        self.caption = QLabel("")
        self.caption.setObjectName("hint")
        right.addWidget(self.caption)

        self.btn_reset = QPushButton("Сбросить фрагмент")
        self.btn_reset.setObjectName("ghost")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.clicked.connect(self._reset_trim)
        right.addWidget(self.btn_reset, 0, Qt.AlignLeft)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._load_frame)

    # ------------------------------------------------------------------ #
    def set_jobs(self, jobs: list[Job]) -> None:
        current = self._job.id if self._job else None
        self.jobs = list(jobs)
        self.list.blockSignals(True)
        self.list.clear()
        for job in self.jobs:
            text = job.name
            if job.info.duration:
                text += f"   {format_timecode(job.info.duration)}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, job.id)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if current:
            self.select_job(current)
        elif self.jobs:
            self.list.setCurrentRow(0)
        else:
            self._job = None
            self.title.setText("Файл не выбран")
            self.image.set_image(None)
            self.strip.set_strip(None)
            self.caption.setText("")

    def select_job(self, job_id: str) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.UserRole) == job_id:
                self.list.setCurrentRow(row)
                return

    def apply_trim(self, start: float, end: float) -> None:
        """Внешнее обновление (из сайдбара) без эмита сигнала."""
        self._trim = (start, end)
        if self._job and self._job.info.duration:
            self.strip.set_duration(self._job.info.duration)
            self.strip.set_trim(start, end)
        self._update_caption()

    # ------------------------------------------------------------------ #
    def _on_list_changed(self, current, previous) -> None:
        if current is None:
            return
        job_id = current.data(Qt.UserRole)
        self._job = next((j for j in self.jobs if j.id == job_id), None)
        self._show_job()

    def _show_job(self) -> None:
        job = self._job
        if job is None:
            return
        info = job.info
        self.title.setText(f"{job.name}  ·  {info.kind_label}"
                           f"{'  ·  ' + info.resolution_label if info.resolution_label else ''}"
                           f"{'  ·  ' + info.duration_label if info.duration_label else ''}")
        self.slider.blockSignals(True)
        self.slider.setValue(0)
        self.slider.blockSignals(False)

        has_timeline = info.kind in ("video", "audio") and info.duration > 0
        self.strip.setVisible(has_timeline)
        self.slider.setVisible(has_timeline)
        self.btn_reset.setVisible(has_timeline)

        if self.tools is None:
            self.image.set_image(None)
            self.caption.setText("Предпросмотр недоступен без ffmpeg")
            return

        if info.kind == "image":
            self.image.set_image(pv.image_preview(job.src, self.tools))
            self.strip.set_strip(None)
            self.caption.setText(f"{info.resolution_label} · {info.size_label}")
            return

        if has_timeline:
            self.strip.set_duration(info.duration)
            self.strip.set_trim(*self._trim)
            if info.kind == "video":
                self.strip.set_strip(pv.filmstrip(job.src, self.tools, info.duration))
            else:
                self.strip.set_strip(pv.waveform(job.src, self.tools, 1400, 120))
            self.strip.set_position(0)
        self._load_frame()
        self._update_caption()

    def _load_frame(self) -> None:
        job = self._job
        if job is None or self.tools is None:
            return
        if job.info.kind == "image":
            return
        position = self.slider.value() / 1000 * max(0.0, job.info.duration)
        if job.info.kind == "video":
            self.image.set_image(pv.frame_at(job.src, self.tools, position))
        else:
            self.image.set_image(pv.waveform(job.src, self.tools, 1200, 260))
        self._update_caption()

    def _on_slider(self, value: int) -> None:
        if self._job is None:
            return
        position = value / 1000 * max(0.0, self._job.info.duration)
        self.strip.set_position(position)
        self._update_caption()
        self._timer.start()

    def _on_seek(self, seconds: float) -> None:
        if self._job is None:
            return
        duration = max(0.001, self._job.info.duration)
        self.slider.blockSignals(True)
        self.slider.setValue(int(seconds / duration * 1000))
        self.slider.blockSignals(False)
        self._update_caption()

    def _on_strip_trim(self, start: float, end: float) -> None:
        self._trim = (start, end)
        self._update_caption()
        self.trimChanged.emit(start, end)

    def _reset_trim(self) -> None:
        self._trim = (0.0, 0.0)
        self.strip.set_trim(0.0, self._job.info.duration if self._job else 0.0)
        self._update_caption()
        self.trimChanged.emit(0.0, 0.0)

    def _update_caption(self) -> None:
        job = self._job
        if job is None:
            return
        start, end = self._trim
        if job.info.kind not in ("video", "audio"):
            return
        length = (end - start) if end else max(0.0, job.info.duration - start)
        parts = []
        if job.info.duration:
            pos = self.slider.value() / 1000 * job.info.duration
            parts.append(f"кадр {format_timecode(pos)}")
        if start or end:
            parts.append(f"фрагмент {format_timecode(start)}–"
                         f"{format_timecode(end) if end else 'конец'} ({length:.1f} с)")
        else:
            parts.append("фрагмент — весь файл")
        parts.append("потяните ручки на полоске кадров")
        self.caption.setText("   ·   ".join(parts))

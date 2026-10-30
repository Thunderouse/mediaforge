"""Вкладка «Предпросмотр»: кадр/картинка/волна + ползунки обрезки по полоске кадров."""

from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSizePolicy,
                               QSlider, QVBoxLayout, QWidget)

from ..core import preview as pv
from ..core.engine import Job
from ..core.ffmpeg import Tools
from ..core.timecode import format_timecode, parse_timecode
from . import theme
from .widgets import IconButton, TimecodeValidator


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
        # фрагмент принадлежит конкретному файлу, но полоска бывает короче:
        # показываем то, что помещается, чтобы ручки не уезжали за её пределы
        duration = self._duration or 1e9
        self._start = min(max(0.0, start), duration)
        self._end = min(end, duration) if end > 0 else duration
        self._end = max(self._end, self._start)
        self.update()

    def set_position(self, seconds: float) -> None:
        self._pos = max(0.0, seconds)
        self.update()

    def trim(self) -> tuple[float, float]:
        """Текущие ручки в той же форме, что и trimEdited: 0 = «до конца»."""
        end = self._end if self._end < self._duration else 0.0
        return self._start, end

    def is_dragging_trim(self) -> bool:
        return self._drag in ("start", "end")

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
            # просмотр едет за ручкой: маркер, ползунок и кадр обновляются сразу,
            # а не только после отпускания
            self._pos = self._start
            self.update()
            self.seeked.emit(self._pos)
            return
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

            # подписи: при узком выделении выносим их наружу, иначе наезжают
            font = QFont(self.font())
            font.setPointSizeF(max(7.0, font.pointSizeF() - 2))
            painter.setFont(font)
            painter.setPen(QColor(p["on_accent"]))
            metrics = QFontMetrics(font)
            narrow = (ex - sx) < 110
            labels = []
            if narrow:
                labels.append((format_timecode(self._start), sx - 4, Qt.AlignRight))
                labels.append((format_timecode(self._end), ex + 4, Qt.AlignLeft))
            else:
                labels.append((format_timecode(self._start), sx + 6, Qt.AlignLeft))
                labels.append((format_timecode(self._end), ex - 6, Qt.AlignRight))
            for text, x, align in labels:
                w = metrics.horizontalAdvance(text) + 8
                left = x - w if align == Qt.AlignRight else x
                left = min(max(0.0, left), rect.width() - w)
                box = QRectF(left, rect.height() - 17, w, 14)
                painter.fillRect(box, QColor(0, 0, 0, 165))
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

    def set_qimage(self, image: QImage) -> None:
        self._pixmap = QPixmap.fromImage(image)
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



class _FramePlayer:
    """Читает rgb24-кадры из ffmpeg в фоновом потоке.

    Это «проигрывание» вырезанного фрагмента без QtMultimedia: 12 кадров/с,
    без звука. Очередь маленькая — если интерфейс не успевает, старые кадры
    выбрасываются, и видео не отстаёт от реального времени.
    """

    def __init__(self, job: Job, tools: Tools, start: float, end: float, fps: int = 12):
        self.fps = fps
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=4)
        self._proc, self.width, self.height = pv.open_frame_stream(
            job.src, tools, job.info, start, end, fps=fps)
        self._alive = True
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        frame_size = self.width * self.height * 3
        stdout = self._proc.stdout
        try:
            while self._alive and stdout is not None:
                chunk = stdout.read(frame_size)
                if not chunk or len(chunk) < frame_size:
                    break
                while self._alive:
                    try:
                        self._queue.put_nowait(chunk)
                        break
                    except queue.Full:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
        except (OSError, ValueError):
            pass
        finally:
            self._alive = False

    def read(self) -> bytes | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def finished(self) -> bool:
        return not self._alive and self._queue.empty()

    def close(self) -> None:
        self._alive = False
        try:
            self._proc.kill()
        except OSError:
            pass
        try:
            self._thread.join(timeout=1.0)
        except RuntimeError:
            pass


class PreviewPanel(QWidget):
    """Слева список файлов, справа кадр и ползунки фрагмента."""

    trimChanged = Signal(str, float, float)   # job_id, начало, конец
    jobSelected = Signal(str)
    renderReady = Signal(str, dict)

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

        # фрагмент редактируется здесь и принадлежит выбранному файлу
        trim_row = QHBoxLayout()
        trim_row.setSpacing(10)
        self.edit_start = QLineEdit()
        self.edit_end = QLineEdit()
        self.trim_boxes: list[QWidget] = []
        for text, edit, placeholder in (("С начала", self.edit_start, "0:00"),
                                        ("По", self.edit_end, "конец файла")):
            box = QWidget()
            col = QVBoxLayout(box)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(3)
            caption = QLabel(text)
            caption.setObjectName("hint")
            col.addWidget(caption)
            edit.setPlaceholderText(placeholder)
            edit.setValidator(TimecodeValidator(edit))
            edit.setClearButtonEnabled(True)
            edit.setMaximumWidth(120)
            edit.editingFinished.connect(self._on_fields_edited)
            col.addWidget(edit)
            trim_row.addWidget(box)
            self.trim_boxes.append(box)
        self.trim_note = QLabel("")
        self.trim_note.setObjectName("hint")
        trim_row.addWidget(self.trim_note, 1, Qt.AlignBottom)
        right.addLayout(trim_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.btn_play = IconButton("play", "Проиграть фрагмент", 18)
        self.btn_play.setCheckable(True)
        self.btn_play.setFixedSize(34, 30)
        self.btn_play.clicked.connect(self._toggle_play)
        controls.addWidget(self.btn_play)

        self.btn_reset = QPushButton("Сбросить фрагмент")
        self.btn_reset.setObjectName("ghost")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.clicked.connect(self._reset_trim)
        controls.addWidget(self.btn_reset)
        controls.addStretch(1)
        right.addLayout(controls)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._load_frame)

        # предпросмотр готовится в фоне: иначе ffmpeg подвешивал бы окно
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="preview")
        self._token = 0
        self._frame_token = 0
        self.renderReady.connect(self._on_render_ready)

        self._player: _FramePlayer | None = None
        self._play_pos = 0.0
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(int(1000 / 12))
        self._play_timer.timeout.connect(self._on_play_tick)


    # ------------------------------------------------------------------ #
    # Проигрывание фрагмента (без звука, кадры из ffmpeg)
    # ------------------------------------------------------------------ #
    def _toggle_play(self, checked: bool) -> None:
        if checked:
            self._start_playback()
        else:
            self._stop_playback()

    def _start_playback(self) -> None:
        job = self._job
        ready = (job is not None and self.tools is not None
                 and job.info.kind == "video" and job.info.duration > 0)
        if not ready:
            self.btn_play.setChecked(False)
            if job is not None and job.info.kind != "video":
                self.caption.setText("Проигрывание доступно для видео")
            return
        start, end = self._trim
        start = max(0.0, start)
        end = end if end > 0 else job.info.duration
        if end <= start + 0.05:
            self.btn_play.setChecked(False)
            return
        self._player = _FramePlayer(job, self.tools, start, end)
        self._play_pos = start
        self.btn_play.set_icon("pause")
        self.btn_play.setToolTip("Пауза")
        self._play_timer.start()

    def _stop_playback(self) -> None:
        self._play_timer.stop()
        if self._player is not None:
            self._player.close()
            self._player = None
        if hasattr(self, "btn_play"):
            self.btn_play.setChecked(False)
            self.btn_play.set_icon("play")
            self.btn_play.setToolTip("Проиграть фрагмент")

    def _on_play_tick(self) -> None:
        player = self._player
        job = self._job
        if player is None or job is None:
            self._stop_playback()
            return
        buffer = player.read()
        if buffer is None:
            if player.finished():
                # фрагмент закончился — начинаем заново, чтобы можно было
                # оценить петлю и границы
                self._restart_playback()
            return
        image = QImage(buffer, player.width, player.height,
                       player.width * 3, QImage.Format_RGB888).copy()
        self.image.set_qimage(image)
        self._play_pos = min(job.info.duration, self._play_pos + 1.0 / player.fps)
        self.strip.set_position(self._play_pos)
        duration = max(0.001, job.info.duration)
        self.slider.blockSignals(True)
        self.slider.setValue(int(self._play_pos / duration * 1000))
        self.slider.blockSignals(False)
        self._update_caption(playing=True)

    def _restart_playback(self) -> None:
        job = self._job
        if job is None:
            self._stop_playback()
            return
        start, end = self._trim
        start = max(0.0, start)
        end = end if end > 0 else job.info.duration
        if self._player is not None:
            self._player.close()
        self._player = _FramePlayer(job, self.tools, start, end)
        self._play_pos = start

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_playback()
        super().closeEvent(event)

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
                if self.list.currentRow() == row:
                    self._show_job()      # уже выбран: поля всё равно обновляем
                else:
                    self.list.setCurrentRow(row)
                return

    def current_job_id(self) -> str:
        return self._job.id if self._job else ""

    def apply_trim(self, start: float, end: float) -> None:
        """Внешнее обновление выбранного файла без эмита сигнала."""
        self._trim = (start or 0.0, end or 0.0)
        if self._job and self._job.info.duration:
            self.strip.set_duration(self._job.info.duration)
            self.strip.set_trim(start, end)
        self._sync_fields()
        self._update_caption()

    def _sync_fields(self) -> None:
        """Поля показывают фрагмент выбранного файла."""
        enabled = bool(self._job and self._job.info.duration > 0
                       and self._job.info.kind in ("video", "audio"))
        start, end = self._trim
        for edit, value in ((self.edit_start, start), (self.edit_end, end)):
            edit.blockSignals(True)
            edit.setText(format_timecode(value) if value else "")
            edit.setEnabled(enabled)
            edit.blockSignals(False)
        self._paint_fields(valid=True)
        for box in self.trim_boxes:
            box.setVisible(enabled)

    def _paint_fields(self, valid: bool, reason: str = "") -> None:
        for edit in (self.edit_start, self.edit_end):
            edit.setStyleSheet("" if valid else
                               f"border-color: {theme.current()['danger']};")
        if valid:
            self.trim_note.setText("")
        else:
            self.trim_note.setText(reason or "время не разобрано или конец раньше начала")

    def _on_fields_edited(self) -> None:
        """Enter или уход из поля: применяем фрагмент только к выбранному файлу.

        Валидатор намеренно пропускает недописанное («1:75»), чтобы можно было
        допечатать, — поэтому разбор здесь терпимый: любая ошибка только
        подсвечивает поля и не трогает job.
        """
        job = self._job
        if job is None or not self.current_job_id():
            return
        try:
            start = parse_timecode(self.edit_start.text()) or 0.0
            end = parse_timecode(self.edit_end.text()) or 0.0
        except ValueError:
            self._paint_fields(valid=False, reason="время не разобрано: нужен 1:30 или 90")
            return

        duration = job.info.duration or 0.0
        if duration > 0:
            if start >= duration:
                self._paint_fields(
                    valid=False,
                    reason=f"начало за пределами файла ({format_timecode(duration)})")
                return
            if end > duration:
                end = duration          # конец за файлом — значит «до конца файла»
        if end and end <= start:
            self._paint_fields(valid=False, reason="конец должен быть больше начала")
            return

        if (start, end) == self._trim:
            # значение не изменилось, но текст стоит нормализовать: «60» -> «1:00»
            self._paint_fields(valid=True)
            self._sync_fields()
            return
        self._trim = (start, end)
        self.strip.set_trim(start, end)
        self._update_caption()
        self._paint_fields(valid=True)
        self._sync_fields()             # поля показывают то, что реально принято
        self.trimChanged.emit(job.id, start, end)

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

        self._stop_playback()
        if self.tools is None:
            self.image.set_image(None)
            self.caption.setText("Предпросмотр недоступен без ffmpeg")
            return

        if has_timeline:
            self._trim = (job.trim_start, job.trim_end)
            self.strip.set_duration(info.duration)
            self.strip.set_trim(*self._trim)
            self.strip.set_position(0)
        self._sync_fields()

        # кадры/полоска/волна готовятся в фоне — окно не должно подвисать
        self._token += 1
        token = str(self._token)
        self.image.set_image(None)
        self.strip.set_strip(None)
        self.caption.setText("готовлю предпросмотр…")
        self._pool.submit(self._render_media, job, token)

    def _render_media(self, job: Job, token: str) -> None:
        data: dict = {}
        try:
            info = job.info
            if info.kind == "video":
                data["strip"] = pv.filmstrip(job.src, self.tools, info.duration or 0)
            elif info.kind == "audio":
                data["strip"] = pv.waveform(job.src, self.tools, 1400, 120)
            data["frame"] = pv.thumbnail_path(job.src, self.tools, info)
        except Exception:  # noqa: BLE001 — битый файл не должен ронять окно
            data["error"] = True
        self.renderReady.emit(token, data)

    def _on_render_ready(self, token: str, data: dict) -> None:
        if token.startswith("f"):
            if token != f"f{self._frame_token}":
                return
        elif token != str(self._token):
            return
        if data.get("strip"):
            self.strip.set_strip(data["strip"])
        if data.get("frame"):
            self.image.set_image(data["frame"])
        self._update_caption()

    def _load_frame(self) -> None:
        job = self._job
        if job is None or self.tools is None:
            return
        if job.info.kind != "video":
            return
        position = self.slider.value() / 1000 * max(0.0, job.info.duration)
        self._frame_token += 1
        token = f"f{self._frame_token}"
        self._pool.submit(self._render_frame, job, position, token)

    def _render_frame(self, job: Job, position: float, token: str) -> None:
        path = pv.frame_at(job.src, self.tools, position)
        if path is not None:
            self.renderReady.emit(token, {"frame": path})

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
        if self._player is not None:
            # перетаскивание ручки прерывает проигрывание, фрагмент не сбрасываем
            self._stop_playback()
            self.btn_play.setChecked(False)
        duration = max(0.001, self._job.info.duration)
        # blockSignals: иначе slider.valueChanged вернётся в _on_slider и пойдёт цикл
        self.slider.blockSignals(True)
        self.slider.setValue(int(seconds / duration * 1000))
        self.slider.blockSignals(False)
        self.strip.set_position(seconds)
        # пока ручку тянут, _trim ещё старый — подпись берёт живые значения
        # с полоски, иначе до отпускания она врёт про «весь файл»
        live = self.strip.trim() if self.strip.is_dragging_trim() else None
        self._update_caption(trim=live)
        self._timer.start()               # кадр перезапрашивается с дебаунсом

    def _on_strip_trim(self, start: float, end: float) -> None:
        job = self._job
        if job is None:
            return
        self._trim = (start, end)
        self._update_caption()
        self._sync_fields()
        self.trimChanged.emit(job.id, start, end)

    def _reset_trim(self) -> None:
        job = self._job
        if job is None:
            return
        self._trim = (0.0, 0.0)
        self.strip.set_trim(0.0, job.info.duration)
        self._update_caption()
        self._sync_fields()
        self.trimChanged.emit(job.id, 0.0, 0.0)

    def _update_caption(self, playing: bool = False,
                        trim: tuple[float, float] | None = None) -> None:
        job = self._job
        if job is None:
            return
        start, end = trim if trim is not None else self._trim
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
        parts.append("▶ проигрывание" if playing else "потяните ручки на полоске кадров")
        self.caption.setText("   ·   ".join(parts))

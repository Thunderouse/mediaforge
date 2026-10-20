"""Главное окно MediaForge."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import (QPointF, QRectF, QSize, Qt, QTimer, Signal, QObject)
from PySide6.QtGui import (QColor, QIcon, QLinearGradient,
                           QPainter, QPainterPath, QPixmap, QShortcut,
                           QKeySequence)
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from ..core import formats as fm
from ..core.config import APP_NAME, APP_VERSION, Settings
from ..core.engine import (STATUS_CANCELLED, STATUS_DONE, STATUS_ERROR,
                           STATUS_PENDING, STATUS_RUNNING, Engine, Job)
from ..core.ffmpeg import (AUDIO_EXT, IMAGE_EXT, VIDEO_EXT,
                           MediaInfo, Tools, guess_kind, human_size,
                           iter_media_files, probe)
from . import icons, theme
from .widgets import (CheckBox, Combo, DropZone, IconButton, JobRow,
                      ProgressLine, Segmented)


class Bridge(QObject):
    """Передаёт события из рабочих потоков в GUI-поток."""

    event = Signal(str, object)
    probed = Signal(str, object)


def app_icon(size: int = 256) -> QIcon:
    """Иконка приложения рисуется кодом — внешних ресурсов не нужно."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    path = QPainterPath()
    path.addRoundedRect(rect, size * 0.23, size * 0.23)
    grad = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.bottomRight()))
    grad.setColorAt(0.0, QColor("#49A6F6"))
    grad.setColorAt(1.0, QColor("#1560A8"))
    painter.fillPath(path, grad)
    glyph = icons.pixmap("spark", "#FFFFFF", int(size * 0.56), 1.55)
    gsize = size * 0.56
    painter.drawPixmap(
        QRectF((size - gsize) / 2, (size - gsize) / 2, gsize, gsize).toRect(), glyph
    )
    painter.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, tools: Tools | None, ffmpeg_error: str = ""):
        super().__init__()
        self.settings = settings
        self.tools = tools
        self.jobs: list[Job] = []
        self.rows: dict[str, JobRow] = {}
        self.engine: Engine | None = None
        self.bridge = Bridge(self)
        self.bridge.event.connect(self._on_engine_event, Qt.QueuedConnection)
        self.bridge.probed.connect(self._on_probed, Qt.QueuedConnection)
        self._seen: set[Path] = set()
        self._ffmpeg_error = ffmpeg_error

        self.setWindowTitle(f"{APP_NAME} — медиаконвертер")
        self.setMinimumSize(QSize(940, 620))
        self.resize(QSize(1100, 800))
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_theme(self.settings.get("theme", "system"), persist=False)
        self._build_shortcuts()
        self._after_list_change()
        self._restore_geometry()

    # ================================================================== #
    # Построение интерфейса
    # ================================================================== #
    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), 1)
        outer.addWidget(self._build_footer())
        self.progress_line = ProgressLine(root)
        outer.addWidget(self.progress_line)

    # ------------------------------------------------------------------ #
    def _logo_pixmap(self, size: int = 30) -> QPixmap:
        pm = QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, size, size)
        path = QPainterPath()
        path.addRoundedRect(rect, size * 0.3, size * 0.3)
        grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
        p = theme.current()
        grad.setColorAt(0, QColor(p["accent"]))
        grad.setColorAt(1, QColor(p["accent_pressed"]))
        painter.fillPath(path, grad)
        icon_pm = icons.pixmap("spark", "#FFFFFF", int(size * 0.62), 1.6)
        painter.drawPixmap(
            QRectF(size * 0.19, size * 0.19, size * 0.62, size * 0.62).toRect(), icon_pm
        )
        painter.end()
        return pm

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(62)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 0, 14, 0)
        lay.setSpacing(11)

        self.logo = QLabel(header)
        self.logo.setFixedSize(30, 30)
        self.logo.setPixmap(self._logo_pixmap())
        lay.addWidget(self.logo)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        t1 = QLabel(APP_NAME, header)
        t1.setObjectName("appTitle")
        t2 = QLabel("Медиаконвертер · видео, картинки, звук", header)
        t2.setObjectName("appSub")
        titles.addWidget(t1)
        titles.addWidget(t2)
        lay.addLayout(titles)
        lay.addStretch(1)

        self.theme_switch = QFrame(header)
        self.theme_switch.setObjectName("segWrap")
        self.theme_switch.setFixedHeight(34)
        ts = QHBoxLayout(self.theme_switch)
        ts.setContentsMargins(3, 3, 3, 3)
        ts.setSpacing(2)
        self.btn_light = self._theme_btn("sun", "Светлая тема")
        self.btn_dark = self._theme_btn("moon", "Тёмная тема")
        self.btn_light.clicked.connect(lambda: self._apply_theme("light"))
        self.btn_dark.clicked.connect(lambda: self._apply_theme("dark"))
        ts.addWidget(self.btn_light)
        ts.addWidget(self.btn_dark)
        lay.addWidget(self.theme_switch)

        info = IconButton("info", "О программе и сочетания клавиш", 17, header)
        info.clicked.connect(self._show_about)
        lay.addWidget(info)
        return header

    def _theme_btn(self, name: str, tip: str) -> IconButton:
        btn = IconButton(name, tip, 17)
        btn.setCheckable(True)
        btn.setFixedSize(28, 28)
        return btn

    # ------------------------------------------------------------------ #
    def _build_body(self) -> QWidget:
        body = QWidget()
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_content(), 1)
        lay.addWidget(self._build_sidebar())
        return body

    def _build_content(self) -> QWidget:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(18, 16, 18, 8)
        lay.setSpacing(11)

        # предупреждение об отсутствии ffmpeg
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 9, 12, 9)
        bl.setSpacing(9)
        bl.addWidget(self._banner_icon())
        self.banner_text = QLabel(self._ffmpeg_error or "")
        self.banner_text.setObjectName("bannerText")
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text, 1)
        self.banner.setVisible(bool(self._ffmpeg_error))
        lay.addWidget(self.banner)

        self.dropzone = DropZone()
        self.dropzone.clicked.connect(self._pick_files)
        self.dropzone.filesDropped.connect(self.add_paths)
        lay.addWidget(self.dropzone)

        self.hints = self._build_hints()
        lay.addWidget(self.hints)

        self.empty_spacer = QWidget()
        self.empty_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.empty_spacer, 1)

        # заголовок списка
        head = QWidget()
        head.setObjectName("listHeader")
        self.list_head = head
        hl = QHBoxLayout(head)
        hl.setContentsMargins(2, 0, 2, 0)
        hl.setSpacing(8)
        self.list_title = QLabel("Файлы")
        self.list_title.setObjectName("sectionTitle")
        hl.addWidget(self.list_title)
        self.count_chip = QLabel("0")
        self.count_chip.setObjectName("chip")
        hl.addWidget(self.count_chip)
        hl.addStretch(1)
        self.bulk_label = QLabel("Всем файлам:")
        self.bulk_label.setObjectName("hint")
        hl.addWidget(self.bulk_label)
        self.bulk_combo = Combo(head)
        self.bulk_combo.setFixedWidth(168)
        self.bulk_combo.setToolTip("Применить формат ко всем совместимым файлам")
        self._fill_bulk_combo()
        self.bulk_combo.activated.connect(self._apply_bulk)
        hl.addWidget(self.bulk_combo)
        self.btn_clear = QPushButton("Очистить")
        self.btn_clear.setObjectName("ghost")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self._clear_all)
        hl.addWidget(self.btn_clear)
        lay.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        self.list_lay = QVBoxLayout(holder)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(holder)
        self.scroll.setVisible(False)
        lay.addWidget(self.scroll, 1)
        return content

    def _build_hints(self) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("hintsWrap")
        wrap.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for icon_name, title, sub in (
            ("video", "Видео → видео", "MP4 · MKV · WebM · MOV · AVI"),
            ("gif", "Видео → GIF", "fps, ширина, зацикливание"),
            ("audio", "Звук из видео", "MP3 · M4A · WAV · FLAC · Opus"),
        ):
            card = QFrame()
            card.setObjectName("featureCard")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(3)
            top = QHBoxLayout()
            top.setSpacing(7)
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, theme.current()["accent"], 16))
            t = QLabel(title)
            t.setObjectName("featureTitle")
            top.addWidget(ic)
            top.addWidget(t)
            top.addStretch(1)
            cl.addLayout(top)
            s = QLabel(sub)
            s.setObjectName("hint")
            s.setWordWrap(True)
            cl.addWidget(s)
            layout.addWidget(card, 1)
        return wrap

    def _banner_icon(self) -> QLabel:
        lab = QLabel()
        lab.setPixmap(icons.pixmap("alert", theme.current()["warn"], 18))
        self._banner_icon_label = lab
        return lab

    # ------------------------------------------------------------------ #
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(320)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 14, 16, 10)
        lay.setSpacing(8)

        opts = self.settings.options()

        lay.addWidget(self._section("Качество"))
        self.seg_quality = Segmented(fm.QUALITY_LABELS)
        self.seg_quality.setValue(opts.quality)
        self.seg_quality.changed.connect(lambda v: self._set_opt("quality", v))
        lay.addWidget(self.seg_quality)

        lay.addSpacing(2)
        lay.addWidget(self._field_label("Разрешение"))
        self.cmb_resolution = Combo()
        self._fill(self.cmb_resolution, fm.RESOLUTIONS, opts.resolution)
        self.cmb_resolution.currentIndexChanged.connect(
            lambda: self._set_opt("resolution", self.cmb_resolution.currentData()))
        lay.addWidget(self.cmb_resolution)

        # --- блок GIF ---
        self.gif_box = QWidget()
        gl = QVBoxLayout(self.gif_box)
        gl.setContentsMargins(0, 4, 0, 0)
        gl.setSpacing(6)
        gl.addWidget(self._divider())
        gl.addWidget(self._section("Анимация GIF"))
        row = QHBoxLayout()
        row.setSpacing(8)
        col_fps = QVBoxLayout()
        col_fps.setSpacing(4)
        col_fps.addWidget(self._field_label("Кадров в секунду"))
        self.cmb_gif_fps = Combo()
        self._fill(self.cmb_gif_fps, tuple((x, x + " fps") for x in fm.GIF_FPS), opts.gif_fps)
        self.cmb_gif_fps.currentIndexChanged.connect(
            lambda: self._set_opt("gif_fps", self.cmb_gif_fps.currentData()))
        col_fps.addWidget(self.cmb_gif_fps)
        col_w = QVBoxLayout()
        col_w.setSpacing(4)
        col_w.addWidget(self._field_label("Ширина"))
        self.cmb_gif_width = Combo()
        self._fill(self.cmb_gif_width, fm.GIF_WIDTHS, opts.gif_width)
        self.cmb_gif_width.currentIndexChanged.connect(
            lambda: self._set_opt("gif_width", self.cmb_gif_width.currentData()))
        col_w.addWidget(self.cmb_gif_width)
        row.addLayout(col_fps, 1)
        row.addLayout(col_w, 1)
        gl.addLayout(row)
        self.chk_loop = CheckBox("Зациклить анимацию")
        self.chk_loop.setChecked(opts.gif_loop)
        self.chk_loop.toggled.connect(lambda v: self._set_opt("gif_loop", v))
        gl.addWidget(self.chk_loop)
        lay.addWidget(self.gif_box)

        # --- блок аудио ---
        self.audio_box = QWidget()
        al = QVBoxLayout(self.audio_box)
        al.setContentsMargins(0, 4, 0, 0)
        al.setSpacing(8)
        al.addWidget(self._divider())
        al.addWidget(self._section("Звук"))
        al.addWidget(self._field_label("Битрейт"))
        self.cmb_bitrate = Combo()
        self._fill(self.cmb_bitrate, tuple((b, b) for b in fm.AUDIO_BITRATES), opts.audio_bitrate)
        self.cmb_bitrate.currentIndexChanged.connect(
            lambda: self._set_opt("audio_bitrate", self.cmb_bitrate.currentData()))
        al.addWidget(self.cmb_bitrate)
        lay.addWidget(self.audio_box)

        lay.addWidget(self._divider())
        lay.addWidget(self._section("Дополнительно"))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)

        self.chk_metadata = CheckBox("Метаданные")
        self.chk_metadata.setChecked(opts.keep_metadata)
        self.chk_metadata.setToolTip("Сохранять метаданные исходника (EXIF, теги)")
        self.chk_metadata.toggled.connect(lambda v: self._set_opt("keep_metadata", v))
        grid.addWidget(self.chk_metadata, 0, 0)

        self.chk_gpu = CheckBox("GPU-ускорение")
        self.chk_gpu.setChecked(opts.gpu)
        self.chk_gpu.setToolTip("Быстрее, если есть подходящая видеокарта. Иначе — CPU.")
        self.chk_gpu.toggled.connect(lambda v: self._set_opt("gpu", v))
        grid.addWidget(self.chk_gpu, 0, 1)

        self.chk_gentle = CheckBox("Щадящий режим")
        self.chk_gentle.setChecked(opts.gentle)
        self.chk_gentle.setToolTip("Меньше потоков CPU и по одному файлу за раз")
        self.chk_gentle.toggled.connect(lambda v: self._set_opt("gentle", v))
        grid.addWidget(self.chk_gentle, 1, 0)

        self.chk_overwrite = CheckBox("Перезапись")
        self.chk_overwrite.setChecked(opts.overwrite)
        self.chk_overwrite.setToolTip("Перезаписывать существующие файлы без суффикса «(1)»")
        self.chk_overwrite.toggled.connect(lambda v: self._set_opt("overwrite", v))
        grid.addWidget(self.chk_overwrite, 1, 1)
        lay.addLayout(grid)

        lay.addWidget(self._divider())
        lay.addWidget(self._section("Куда сохранять"))
        self.chk_source_dir = CheckBox("Рядом с исходным файлом")
        self.chk_source_dir.setChecked(bool(self.settings.get("use_source_dir", True)))
        self.chk_source_dir.toggled.connect(self._on_source_dir_toggled)
        lay.addWidget(self.chk_source_dir)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.edit_out = QLineEdit(str(self.settings.get("out_dir") or ""))
        self.edit_out.setPlaceholderText("Папка для результатов")
        self.edit_out.setReadOnly(True)
        self.btn_browse = IconButton("folder", "Выбрать папку", 17)
        self.btn_browse.clicked.connect(self._pick_out_dir)
        row.addWidget(self.edit_out, 1)
        row.addWidget(self.btn_browse)
        lay.addLayout(row)
        self._on_source_dir_toggled(self.chk_source_dir.isChecked())

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # нижний блок закреплён — кнопка всегда на виду
        bottom = QWidget()
        bottom.setObjectName("sidebarBottom")
        bottom.setAttribute(Qt.WA_StyledBackground, True)
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(16, 8, 16, 12)
        bl.setSpacing(8)
        self.summary = QLabel("")
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)
        bl.addWidget(self.summary)

        self.btn_convert = QPushButton("Конвертировать")
        self.btn_convert.setObjectName("primary")
        self.btn_convert.setCursor(Qt.PointingHandCursor)
        self.btn_convert.setFixedHeight(42)
        self.btn_convert.clicked.connect(self.start_conversion)
        bl.addWidget(self.btn_convert)

        self.btn_cancel = QPushButton("Остановить")
        self.btn_cancel.setObjectName("secondary")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setFixedHeight(38)
        self.btn_cancel.clicked.connect(self.cancel_conversion)
        self.btn_cancel.setVisible(False)
        bl.addWidget(self.btn_cancel)

        hint = QLabel("Обработка локальная — файлы никуда не загружаются")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        bl.addWidget(hint)
        outer.addWidget(bottom)
        return side

    def _field_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("hint")
        return lab

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("sectionTitle")
        return lab

    def _divider(self) -> QWidget:
        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        return line

    def _fill(self, combo: QComboBox, items, current: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        for key, label in items:
            combo.addItem(label, key)
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _fill_bulk_combo(self) -> None:
        combo = self.bulk_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Выберите формат…", None)
        for group, targets in (
            ("Изображения", fm.IMAGE_TARGETS),
            ("Видео", fm.VIDEO_TARGETS),
            ("Аудио", fm.AUDIO_TARGETS),
        ):
            combo.insertSeparator(combo.count())
            combo.addItem(f"— {group} —", f"__group__{group}")
            idx = combo.count() - 1
            combo.model().item(idx).setEnabled(False)
            for t in targets:
                combo.addItem(t.label, t.key)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(44)
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(18, 0, 14, 0)
        lay.setSpacing(10)
        self.status_icon = QLabel()
        lay.addWidget(self.status_icon)
        self.status = QLabel("Готов к работе")
        self.status.setObjectName("status")
        lay.addWidget(self.status)
        lay.addStretch(1)
        self.btn_open = QPushButton("Открыть папку")
        self.btn_open.setObjectName("ghost")
        self.btn_open.setCursor(Qt.PointingHandCursor)
        self.btn_open.clicked.connect(self._open_output)
        self.btn_open.setEnabled(False)
        lay.addWidget(self.btn_open)
        return footer

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence.Open, self, self._pick_files)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.start_conversion)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.start_conversion)
        QShortcut(QKeySequence("Esc"), self, self.cancel_conversion)
        QShortcut(QKeySequence("Ctrl+L"), self, lambda: self._apply_theme("light"))
        QShortcut(QKeySequence("Ctrl+D"), self, lambda: self._apply_theme("dark"))

    # ================================================================== #
    # Тема
    # ================================================================== #
    def _apply_theme(self, name: str, persist: bool = True) -> None:
        palette = theme.apply(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.qss(palette))
        self.logo.setPixmap(self._logo_pixmap())
        dark = palette["name"] == "dark"
        self.btn_dark.setChecked(dark)
        self.btn_light.setChecked(not dark)

        def style(btn: IconButton, active: bool) -> None:
            if active:
                btn.setStyleSheet(
                    f"background: {palette['accent_soft']}; border-radius: 7px;"
                )
                btn.setIcon(icons.icon(btn._name, palette["accent"], 17))
            else:
                btn.setStyleSheet("")
                btn.setIcon(icons.icon(btn._name, palette["muted"], 17))

        style(self.btn_dark, dark)
        style(self.btn_light, not dark)
        if hasattr(self, "_banner_icon_label"):
            self._banner_icon_label.setPixmap(icons.pixmap("alert", palette["warn"], 18))
        if persist:
            self.settings.set("theme", name)
            self.settings.save()
        for row in self.rows.values():
            row.refresh_theme()
        self.dropzone._refresh()

    # ================================================================== #
    # Работа со списком
    # ================================================================== #
    def add_paths(self, paths) -> None:
        if not self.tools:
            self._flash("ffmpeg не найден — конвертация недоступна")
            return
        recursive = bool(self.settings.get("recursive", True))
        files = iter_media_files(paths, recursive=recursive)
        added = 0
        for f in files:
            try:
                key = f.resolve()
            except OSError:
                continue
            if key in self._seen or not f.is_file():
                continue
            self._seen.add(key)
            kind = guess_kind(f)
            target_key = fm.default_target(f.suffix, "image" if kind == "image" else
                                           ("audio" if kind == "audio" else "video"))
            info = MediaInfo(path=f, kind=kind if kind != "unknown" else "video")
            try:
                info.size = f.stat().st_size
            except OSError:
                pass
            job = Job(src=f, info=info, target=fm.BY_KEY[target_key])
            row = JobRow(job, self)
            row.targetChanged.connect(self._on_row_target)
            row.removeRequested.connect(self._remove_row)
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)
            self.jobs.append(job)
            self.rows[job.id] = row
            added += 1
            threading.Thread(target=self._probe_worker, args=(job.id, f),
                             daemon=True).start()
        if added:
            self._after_list_change()
            self._flash(f"Добавлено файлов: {added}")

    def _probe_worker(self, job_id: str, path: Path) -> None:
        if not self.tools:
            return
        try:
            info = probe(path, self.tools)
        except Exception:  # noqa: BLE001
            return
        self.bridge.probed.emit(job_id, info)

    def _on_probed(self, job_id: str, info: MediaInfo) -> None:
        row = self.rows.get(job_id)
        if row is None:
            return
        row.set_info(info)
        self._after_list_change()
        self._update_summary()

    def _on_row_target(self, job_id: str, key: str) -> None:
        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is None:
            return
        job.target = fm.BY_KEY[key]
        row = self.rows[job_id]
        row.job.target = job.target
        row.set_combo_key(key)
        row.update_state()
        self._after_list_change()

    def _remove_row(self, job_id: str) -> None:
        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is not None and job.status == STATUS_RUNNING:
            self._flash("Файл конвертируется — сначала остановите")
            return
        row = self.rows.pop(job_id, None)
        if row is not None:
            self.list_lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        if job is not None:
            self.jobs.remove(job)
            try:
                self._seen.discard(job.src.resolve())
            except OSError:
                pass
        self._after_list_change()

    def _clear_all(self) -> None:
        if self._is_busy():
            self._flash("Сначала остановите конвертацию")
            return
        for job_id in list(self.rows):
            self._remove_row(job_id)
        self._flash("Список очищен")

    def _apply_bulk(self, index: int) -> None:
        key = self.bulk_combo.itemData(index)
        if not key or str(key).startswith("__group__"):
            return
        applied = 0
        for job in self.jobs:
            if key in {t.key for t in fm.targets_for(job.info.kind)}:
                job.target = fm.BY_KEY[key]
                row = self.rows.get(job.id)
                if row is not None:
                    row.set_combo_key(key)
                    row.job.target = job.target
                    row.update_state()
                applied += 1
        self.bulk_combo.blockSignals(True)
        self.bulk_combo.setCurrentIndex(0)
        self.bulk_combo.blockSignals(False)
        self._after_list_change()
        self._flash(f"Формат применён к {applied} файл(ам)")

    def _after_list_change(self) -> None:
        n = len(self.jobs)
        self.count_chip.setText(str(n))
        has = n > 0
        self.scroll.setVisible(has)
        self.list_head.setVisible(has)
        self.hints.setVisible(not has)
        self.empty_spacer.setVisible(not has)
        self.dropzone.set_compact(has)
        self.bulk_combo.setEnabled(has)
        self.bulk_label.setEnabled(has)
        self.btn_clear.setEnabled(has)
        self._update_option_visibility()
        self._update_summary()

    def _update_option_visibility(self) -> None:
        has_gif = any(j.target.key.startswith("gif") for j in self.jobs)
        has_audio = any(j.target.kind == fm.KIND_AUDIO for j in self.jobs)
        self.gif_box.setVisible(has_gif)
        self.audio_box.setVisible(has_audio)

    def _update_summary(self) -> None:
        n = len(self.jobs)
        if not n:
            self.summary.setText("Перетащите файлы, чтобы начать")
            self._update_convert_button()
            return
        kinds = {j.info.kind for j in self.jobs}
        labels = {"image": "изображения", "video": "видео", "audio": "аудио", "unknown": "файлы"}
        parts = [labels.get(k, "файлы") for k in ("image", "video", "audio") if k in kinds]
        total = sum(j.info.size or 0 for j in self.jobs)
        kinds_text = " + ".join(parts)
        size_text = human_size(total)
        count = f"{n} {self._plural(n, 'файл', 'файла', 'файлов')}"
        self.summary.setText(f"{count} · {kinds_text} · {size_text}" if n <= 3
                             else f"{count} · {size_text}")
        self._update_convert_button()

    @staticmethod
    def _plural(n: int, one: str, few: str, many: str) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return one
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return few
        return many

    def _update_convert_button(self) -> None:
        busy = self._is_busy()
        ready = bool(self.jobs) and self.tools is not None and not busy
        self.btn_convert.setEnabled(ready)
        self.btn_cancel.setVisible(busy)

    def _is_busy(self) -> bool:
        return self.engine is not None and self.engine.running

    # ================================================================== #
    # Параметры
    # ================================================================== #
    def _set_opt(self, name: str, value) -> None:
        self.settings.set(f"opt_{name}", value)
        self.settings.save()

    def _on_source_dir_toggled(self, checked: bool) -> None:
        self.settings.set("use_source_dir", bool(checked))
        self.settings.save()
        self.edit_out.setEnabled(not checked)
        self.btn_browse.setEnabled(not checked)
        if not checked and not self.edit_out.text():
            self._pick_out_dir()

    def _pick_out_dir(self) -> None:
        start = self.edit_out.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Папка для результатов", start)
        if path:
            self.edit_out.setText(path)
            self.settings.set("out_dir", path)
            self.settings.save()

    # ================================================================== #
    # Добавление файлов
    # ================================================================== #
    def _pick_files(self) -> None:
        exts = sorted({e.lstrip(".") for e in (IMAGE_EXT | VIDEO_EXT | AUDIO_EXT)})
        pattern = " ".join(f"*.{e}" for e in exts)
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выберите файлы", str(Path.home()),
            f"Медиафайлы ({pattern});;Все файлы (*.*)",
        )
        if files:
            self.add_paths([Path(f) for f in files])

    # ================================================================== #
    # Конвертация
    # ================================================================== #
    def start_conversion(self) -> None:
        if not self.tools:
            self._flash("ffmpeg не найден — конвертация недоступна")
            return
        if self._is_busy() or not self.jobs:
            return
        opts = self.settings.options()
        use_source = self.chk_source_dir.isChecked()
        out_dir = Path(self.edit_out.text()) if self.edit_out.text() else Path.home()
        if not use_source:
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, APP_NAME, f"Не удалось создать папку:\n{exc}")
                return
        for job in self.jobs:
            job.out_dir = job.src.parent if use_source else out_dir
            job.status = STATUS_PENDING
            job.progress = 0.0
            self.rows[job.id].update_state()
            self.rows[job.id].remove.setEnabled(False)

        workers = 1 if opts.gentle else max(1, int(self.settings.get("max_workers", 2)))
        self.engine = Engine(self.tools, opts, self._emit_event, max_workers=workers)
        self.engine.start(list(self.jobs), out_dir)
        self.btn_convert.setVisible(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self.progress_line.setValue(0.0)
        self._set_status(f"Конвертация: 0 из {len(self.jobs)}", "run")
        self._update_convert_button()

    def _emit_event(self, event: str, job: Job) -> None:
        self.bridge.event.emit(event, job)

    def cancel_conversion(self) -> None:
        if self.engine is not None and self.engine.running:
            self.engine.stop()
            self.btn_cancel.setEnabled(False)
            self._set_status("Останавливаю…", "wait")

    def _on_engine_event(self, event: str, job: Job) -> None:
        row = self.rows.get(job.id)
        if row is not None:
            row.update_state()
        done = sum(1 for j in self.jobs if j.status in
                   (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED))
        total = len(self.jobs)
        overall = (sum(j.progress if j.status == STATUS_RUNNING else
                       1.0 if j.status in (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED) else 0.0
                       for j in self.jobs) / total) if total else 0.0
        self.progress_line.setValue(overall)

        if event in ("start", "progress"):
            self._set_status(f"Конвертация: {done} из {total}", "run")
        elif event == "finished":
            errors = [j for j in self.jobs if j.status == STATUS_ERROR]
            cancelled = [j for j in self.jobs if j.status == STATUS_CANCELLED]
            ok = [j for j in self.jobs if j.status == STATUS_DONE]
            if cancelled:
                self._set_status(f"Остановлено: {len(ok)} из {total}", "idle")
            elif errors:
                self._set_status(
                    f"Готово: {len(ok)} · с ошибками: {len(errors)}", "error")
            else:
                self._set_status(f"Готово: {len(ok)} {self._plural(len(ok), 'файл', 'файла', 'файлов')}", "ok")
            self.btn_convert.setVisible(True)
            for row in self.rows.values():
                row.remove.setEnabled(True)
            self._update_convert_button()
            self.btn_open.setEnabled(True)
            self.progress_line.setValue(1.0 if not errors else overall)
            QTimer.singleShot(1200, lambda: self.btn_open.setEnabled(bool(ok)))
            self._update_summary()

    # ================================================================== #
    # Вспомогательное
    # ================================================================== #
    def _set_status(self, text: str, kind: str = "idle") -> None:
        p = theme.current()
        colors = {"run": p["accent"], "ok": p["success"], "error": p["danger"],
                  "wait": p["warn"], "idle": p["muted"]}
        icons_map = {"run": "arrow", "ok": "check", "error": "alert",
                     "wait": "info", "idle": "info"}
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colors.get(kind, p['muted'])}; font-size: 12px;")
        self.status_icon.setPixmap(
            icons.pixmap(icons_map.get(kind, "info"), colors.get(kind, p["muted"]), 15))

    def _flash(self, text: str) -> None:
        if not self._is_busy():
            self._set_status(text, "idle")

    def _open_output(self) -> None:
        target: Path | None = None
        for job in self.jobs:
            if job.status == STATUS_DONE and job.output:
                target = job.output.parent
                break
        if target is None:
            target = Path(self.edit_out.text() or Path.home())
        if not target.exists():
            self._flash("Папка не найдена")
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _show_about(self) -> None:
        ff = self.tools.version() if self.tools else "не найден"
        path = self.tools.ffmpeg if self.tools else "—"
        text = (
            f"<b>{APP_NAME} {APP_VERSION}</b><br>"
            "Универсальный конвертер видео, изображений и звука.<br><br>"
            f"<b>ffmpeg:</b> {ff}<br><span style='font-size:11px'>{path}</span><br><br>"
            "<b>Горячие клавиши</b><br>"
            "Ctrl+O — добавить файлы<br>"
            "Ctrl+Enter — конвертировать<br>"
            "Esc — остановить<br>"
            "Ctrl+L / Ctrl+D — светлая / тёмная тема<br><br>"
            "<span style='font-size:11px'>Работает локально, использует ffmpeg и Qt. "
            "Не требует установки, данных никуда не отправляет.</span>"
        )
        box = QMessageBox(self)
        box.setWindowTitle("О программе")
        box.setTextFormat(Qt.RichText)
        box.setText(text)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    # ---- drag&drop на всё окно ---- #
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    def _restore_geometry(self) -> None:
        raw = self.settings.get("window_geometry") or ""
        if not raw:
            return
        try:
            x, y, w, h = (int(v) for v in str(raw).split(","))
        except (ValueError, TypeError):
            return
        self.setGeometry(x, y, max(940, w), max(620, h))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.engine is not None and self.engine.running:
            self.engine.stop()
        g = self.geometry()
        self.settings.set("window_geometry", f"{g.x()},{g.y()},{g.width()},{g.height()}")
        self.settings.save()
        super().closeEvent(event)

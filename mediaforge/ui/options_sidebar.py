"""Правая колонка с параметрами конвертации.

`OptionsSidebar` ничего не знает ни об очереди файлов, ни о движке: он читает
начальные значения из `Settings`, отдаёт изменения сигналами и принимает
несколько «внешних» фактов (видимость блоков, размер первого изображения).
Фрагмент сюда не относится: он свой у каждого файла и живёт в предпросмотре.
"""

from __future__ import annotations

from pathlib import Path

import re

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import formats as fm
from ..core.config import Settings
from .widgets import CheckBox, Combo, IconButton, Segmented


# то, что ещё можно допечатать до корректного времени: «1:», «1:3», «1:30.»
_TC_PREFIX = re.compile(r"^\s*\d{0,3}(?::\d{0,2}){0,2}(?:[.,]\d{0,3})?\s*$")


class OptionsSidebar(QFrame):
    """Блок параметров: качество, разрешение, изображения, фрагмент, GIF, звук."""

    optionChanged = Signal(str, object)   # имя опции без «opt_» → значение
    useSourceDirChanged = Signal(bool)
    outDirChanged = Signal(str)
    convertRequested = Signal()
    cancelRequested = Signal()

    # поля фрагмента создаются в цикле, объявляем явно
    edit_trim_start: QLineEdit
    edit_trim_end: QLineEdit

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._image_source: tuple[int, int] | None = None
        self.setObjectName("sidebar")
        self.setFixedWidth(320)

        outer = QVBoxLayout(self)
        self._outer = outer
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

        opts = settings.options()

        self.quality_box = QWidget()
        ql = QVBoxLayout(self.quality_box)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(6)
        ql.addWidget(self._section("Качество и размер"))
        self.seg_quality = Segmented(fm.QUALITY_LABELS)
        self.seg_quality.setValue(opts.quality)
        self.seg_quality.changed.connect(lambda v: self.optionChanged.emit("quality", v))
        ql.addWidget(self.seg_quality)
        self.quality_hint = QLabel("")
        self.quality_hint.setObjectName("hint")
        self.quality_hint.setWordWrap(True)
        ql.addWidget(self.quality_hint)
        lay.addWidget(self.quality_box)

        lay.addSpacing(2)
        lay.addWidget(self._field_label("Разрешение"))
        self.cmb_resolution = Combo()
        self._fill(self.cmb_resolution, fm.RESOLUTIONS, opts.resolution)
        self.cmb_resolution.currentIndexChanged.connect(
            lambda: self.optionChanged.emit("resolution", self.cmb_resolution.currentData()))
        lay.addWidget(self.cmb_resolution)

        # --- изображения ---
        self.image_box = QWidget()
        il = QVBoxLayout(self.image_box)
        il.setContentsMargins(0, 4, 0, 0)
        il.setSpacing(6)
        il.addWidget(self._divider())
        il.addWidget(self._section("Изображения"))
        il.addWidget(self._field_label("Размер"))

        self.cmb_image_scale = Combo()
        self.cmb_image_scale.addItem("Не менять", None)
        for percent in fm.IMAGE_PERCENTS:
            self.cmb_image_scale.addItem(f"{percent} %", percent)
        self.cmb_image_scale.addItem("Свой размер, px", "custom")
        current = (opts.image_percent if opts.image_scale == "percent"
                   else "custom" if opts.image_scale == "size" else None)
        index = self.cmb_image_scale.findData(current)
        self.cmb_image_scale.setCurrentIndex(index if index >= 0 else 0)
        self.cmb_image_scale.currentIndexChanged.connect(self._on_image_scale)
        il.addWidget(self.cmb_image_scale)

        self.image_size_row = QWidget()
        rl = QHBoxLayout(self.image_size_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.edit_img_w = QLineEdit(str(opts.image_width or ""))
        self.edit_img_w.setPlaceholderText("ширина")
        self.edit_img_h = QLineEdit(str(opts.image_height or ""))
        self.edit_img_h.setPlaceholderText("высота")
        validator = QRegularExpressionValidator(QRegularExpression(r"^[0-9]{0,5}$"))
        for edit, which in ((self.edit_img_w, "w"), (self.edit_img_h, "h")):
            edit.setValidator(validator)
            edit.textChanged.connect(
                lambda _text, side=which: self._on_image_size_edited(side))
        times = QLabel("×")
        times.setFixedWidth(12)
        times.setAlignment(Qt.AlignCenter)
        rl.addWidget(self.edit_img_w, 1)
        rl.addWidget(times)
        rl.addWidget(self.edit_img_h, 1)
        il.addWidget(self.image_size_row)

        self.chk_ratio = CheckBox("Сохранять пропорции")
        self.chk_ratio.setChecked(opts.image_keep_ratio)
        self.chk_ratio.setToolTip(
            "Пустое поле — сторона считается по пропорциям. Снимите флажок, "
            "чтобы задать точные размеры (картинка может исказиться).")
        self.chk_ratio.toggled.connect(self._on_ratio_toggled)
        il.addWidget(self.chk_ratio)

        il.addWidget(self._field_label("Метод"))
        self.cmb_image_filter = Combo()
        self._fill(self.cmb_image_filter, fm.IMAGE_FILTERS, opts.image_filter)
        self.cmb_image_filter.currentIndexChanged.connect(
            lambda: self.optionChanged.emit("image_filter",
                                            self.cmb_image_filter.currentData()))
        il.addWidget(self.cmb_image_filter)

        self.chk_upscale = CheckBox("Разрешение может увеличивать")
        self.chk_upscale.setChecked(opts.image_allow_upscale)
        self.chk_upscale.setToolTip(
            "Влияет только на список «Разрешение»: без флажка маленькая картинка "
            "не растягивается до 1080p. Проценты и «Свой размер» применяются "
            "всегда — это прямое указание.")
        self.chk_upscale.toggled.connect(
            lambda v: self.optionChanged.emit("image_allow_upscale", v))
        il.addWidget(self.chk_upscale)

        lay.addWidget(self.image_box)

        # --- фрагмент ---
        # поля переехали в предпросмотр: фрагмент у каждого файла свой
        self.trim_box = QWidget()
        tl = QVBoxLayout(self.trim_box)
        tl.setContentsMargins(0, 4, 0, 0)
        tl.setSpacing(6)
        tl.addWidget(self._divider())
        tl.addWidget(self._section("Фрагмент"))
        trim_hint = QLabel("задаётся в предпросмотре — для каждого файла свой")
        trim_hint.setObjectName("hint")
        trim_hint.setWordWrap(True)
        tl.addWidget(trim_hint)
        lay.addWidget(self.trim_box)

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
            lambda: self.optionChanged.emit("gif_fps", self.cmb_gif_fps.currentData()))
        col_fps.addWidget(self.cmb_gif_fps)
        row.addLayout(col_fps, 1)
        gl.addLayout(row)
        gif_scale_hint = QLabel("Масштаб — из «Разрешения» выше")
        gif_scale_hint.setObjectName("hint")
        gl.addWidget(gif_scale_hint)
        self.chk_loop = CheckBox("Зациклить анимацию")
        self.chk_loop.setChecked(opts.gif_loop)
        self.chk_loop.toggled.connect(lambda v: self.optionChanged.emit("gif_loop", v))
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
        self._fill(self.cmb_bitrate, tuple((b, b) for b in fm.AUDIO_BITRATES),
                   opts.audio_bitrate)
        self.cmb_bitrate.currentIndexChanged.connect(
            lambda: self.optionChanged.emit("audio_bitrate", self.cmb_bitrate.currentData()))
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
        self.chk_metadata.toggled.connect(
            lambda v: self.optionChanged.emit("keep_metadata", v))
        grid.addWidget(self.chk_metadata, 0, 0)

        self.chk_gpu = CheckBox("GPU-ускорение")
        self.chk_gpu.setChecked(opts.gpu)
        self.chk_gpu.setToolTip("Быстрее, если есть подходящая видеокарта. Иначе — CPU.")
        self.chk_gpu.toggled.connect(lambda v: self.optionChanged.emit("gpu", v))
        grid.addWidget(self.chk_gpu, 0, 1)

        self.chk_gentle = CheckBox("Щадящий режим")
        self.chk_gentle.setChecked(opts.gentle)
        self.chk_gentle.setToolTip("Меньше потоков CPU и по одному файлу за раз")
        self.chk_gentle.toggled.connect(lambda v: self.optionChanged.emit("gentle", v))
        grid.addWidget(self.chk_gentle, 1, 0)

        self.chk_overwrite = CheckBox("Перезапись")
        self.chk_overwrite.setChecked(opts.overwrite)
        self.chk_overwrite.setToolTip("Перезаписывать существующие файлы без суффикса «(1)»")
        self.chk_overwrite.toggled.connect(
            lambda v: self.optionChanged.emit("overwrite", v))
        grid.addWidget(self.chk_overwrite, 1, 1)
        lay.addLayout(grid)

        lay.addWidget(self._divider())
        lay.addWidget(self._section("Куда сохранять"))
        self.chk_source_dir = CheckBox("Рядом с исходным файлом")
        self.chk_source_dir.setChecked(bool(settings.get("use_source_dir", True)))
        self.chk_source_dir.toggled.connect(self._on_source_dir_toggled)
        lay.addWidget(self.chk_source_dir)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.edit_out = QLineEdit(str(settings.get("out_dir") or ""))
        self.edit_out.setPlaceholderText("Папка для результатов")
        self.edit_out.setReadOnly(True)
        self.btn_browse = IconButton("folder", "Выбрать папку", 17)
        self.btn_browse.clicked.connect(self.pick_out_dir)
        row.addWidget(self.edit_out, 1)
        row.addWidget(self.btn_browse)
        lay.addLayout(row)
        self._sync_out_dir_state()
        self._update_image_widgets()

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
        self.btn_convert.clicked.connect(self.convertRequested.emit)
        bl.addWidget(self.btn_convert)

        self.btn_cancel = QPushButton("Остановить")
        self.btn_cancel.setObjectName("secondary")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setFixedHeight(38)
        self.btn_cancel.clicked.connect(self.cancelRequested.emit)
        self.btn_cancel.setVisible(False)
        bl.addWidget(self.btn_cancel)

        hint = QLabel("Обработка локальная — файлы никуда не загружаются")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        bl.addWidget(hint)
        outer.addWidget(bottom)

    # ------------------------------------------------------------------ #
    # Мелкие строители
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    # Внешний API (то, что нужно окну)
    # ------------------------------------------------------------------ #
    def set_quality_context(self, targets: list[tuple[str, str]],
                            gpu: bool = False) -> None:
        """Показывает качество только там, где оно что-то меняет.

        `targets` — пары (ключ формата, тип файла) по всей очереди, `gpu` —
        текущая настройка: при ней у H.264 действуют значения видеокарты.
        """
        keys = [key for key, _kind in targets]
        if not keys or all(fm.quality_effect(key) == "none" for key in keys):
            self.quality_box.setVisible(False)
            return
        self.quality_box.setVisible(True)
        self.quality_hint.setText(fm.quality_hint(keys, gpu=gpu))
        self.seg_quality.set_tooltips(fm.quality_tooltips(keys, gpu=gpu))

    def update_option_visibility(
        self, has_media: bool, has_image: bool, has_gif: bool, has_audio: bool,
    ) -> None:
        self.trim_box.setVisible(has_media)
        self.image_box.setVisible(has_image)
        self.gif_box.setVisible(has_gif)
        self.audio_box.setVisible(has_audio)

    def set_image_source_size(self, width: int | None, height: int | None) -> None:
        """Размер первого изображения в очереди: для пропорций и подстановки."""
        self._image_source = (width, height) if width and height else None

    @property
    def use_source_dir(self) -> bool:
        return self.chk_source_dir.isChecked()

    def out_dir_text(self) -> str:
        return self.edit_out.text()

    def pick_out_dir(self) -> None:
        start = self.edit_out.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Папка для результатов", start)
        if path:
            self.edit_out.setText(path)
            self.outDirChanged.emit(path)

    # ------------------------------------------------------------------ #
    # Внутренняя логика
    # ------------------------------------------------------------------ #
    def _sync_out_dir_state(self) -> None:
        checked = self.chk_source_dir.isChecked()
        self.edit_out.setEnabled(not checked)
        self.btn_browse.setEnabled(not checked)

    def _on_source_dir_toggled(self, checked: bool) -> None:
        self._sync_out_dir_state()
        if not checked and not self.edit_out.text():
            self.pick_out_dir()
        self.useSourceDirChanged.emit(bool(checked))

    def _image_aspect(self) -> float | None:
        """Пропорции первого изображения в очереди — по ним подгоняем поля."""
        if self._image_source and all(self._image_source):
            width, height = self._image_source
            return width / height
        return None

    def _set_img_field(self, edit: QLineEdit, value: str) -> None:
        if edit.text() == value:
            return
        edit.blockSignals(True)
        edit.setText(value)
        edit.blockSignals(False)

    def _on_image_scale(self) -> None:
        data = self.cmb_image_scale.currentData()
        if data == "custom" and not (self.edit_img_w.text().strip()
                                     or self.edit_img_h.text().strip()):
            # стартуем от текущего размера первого изображения, а не с пустых полей
            if self._image_source:
                width, height = self._image_source
                self._set_img_field(self.edit_img_w, str(width))
                self._set_img_field(self.edit_img_h, str(height))
                self._on_image_size_edited("w")
        if data is None:
            self.optionChanged.emit("image_scale", "none")
        elif data == "custom":
            self.optionChanged.emit("image_scale", "size")
        else:
            self.optionChanged.emit("image_scale", "percent")
            self.optionChanged.emit("image_percent", data)
        self._update_image_widgets()

    def _on_ratio_toggled(self, checked: bool) -> None:
        self.optionChanged.emit("image_keep_ratio", checked)
        if not checked:
            return
        if self.edit_img_w.text().strip():
            self._on_image_size_edited("w")
        elif self.edit_img_h.text().strip():
            self._on_image_size_edited("h")

    def _on_image_size_edited(self, which: str = "w") -> None:
        """Ручной размер в пикселях: при «Сохранять пропорции» вторая сторона
        пересчитывается сразу, чтобы в интерфейсе был реальный размер."""
        if self.chk_ratio.isChecked():
            aspect = self._image_aspect()
            if aspect:
                if which == "w":
                    text = self.edit_img_w.text().strip()
                    if text.isdigit() and int(text) > 0:
                        self._set_img_field(
                            self.edit_img_h, str(max(1, round(int(text) / aspect))))
                else:
                    text = self.edit_img_h.text().strip()
                    if text.isdigit() and int(text) > 0:
                        self._set_img_field(
                            self.edit_img_w, str(max(1, round(int(text) * aspect))))
        self.optionChanged.emit("image_width", self.edit_img_w.text().strip())
        self.optionChanged.emit("image_height", self.edit_img_h.text().strip())

    def _update_image_widgets(self) -> None:
        mode = self.cmb_image_scale.currentData()
        self.image_size_row.setVisible(mode == "custom")
        self.chk_ratio.setVisible(mode == "custom")

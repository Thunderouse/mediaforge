"""Реестр целевых форматов и настройки конвертации."""

from __future__ import annotations

from dataclasses import dataclass, replace

KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_AUDIO = "audio"


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    kind: str
    ext: str
    group: str
    hint: str = ""

    def __str__(self) -> str:  # для QComboBox
        return self.label


IMAGE_TARGETS = (
    Target("png", "PNG · без потерь", KIND_IMAGE, "png", "Изображения", "Прозрачность, точная копия"),
    Target("jpg", "JPEG · фото", KIND_IMAGE, "jpg", "Изображения", "Малый размер, без прозрачности"),
    Target("webp", "WebP", KIND_IMAGE, "webp", "Изображения", "До 30% меньше JPEG"),
    Target("avif", "AVIF", KIND_IMAGE, "avif", "Изображения", "Максимальное сжатие"),
    Target("tiff", "TIFF", KIND_IMAGE, "tiff", "Изображения", "Для печати и архива"),
    Target("bmp", "BMP", KIND_IMAGE, "bmp", "Изображения", "Без сжатия, большой файл"),
    Target("gif_img", "GIF · картинка", KIND_IMAGE, "gif", "Изображения", "До 256 цветов"),
    Target("ico", "ICO · иконка", KIND_IMAGE, "ico", "Изображения", "Значок Windows"),
    Target("pdf", "PDF", KIND_IMAGE, "pdf", "Изображения", "Документ с картинкой"),
)

VIDEO_TARGETS = (
    Target("mp4", "MP4 · H.264", KIND_VIDEO, "mp4", "Видео", "Универсально, играет везде"),
    Target("mkv", "MKV · H.265", KIND_VIDEO, "mkv", "Видео", "Меньше размер, HEVC"),
    Target("mkv264", "MKV · H.264", KIND_VIDEO, "mkv", "Видео", "Совместимый контейнер"),
    Target("webm", "WebM · VP9", KIND_VIDEO, "webm", "Видео", "Открытый кодек для веба"),
    Target("mov", "MOV · H.264", KIND_VIDEO, "mov", "Видео", "Для Apple и монтажа"),
    Target("avi", "AVI · MPEG-4", KIND_VIDEO, "avi", "Видео", "Старая техника"),
    Target("gif", "GIF · анимация", "gif", "gif", "Видео → GIF", "Зацикленная анимация"),
)

AUDIO_TARGETS = (
    Target("mp3", "MP3", KIND_AUDIO, "mp3", "Аудио", "Совместимо со всем"),
    Target("m4a", "M4A · AAC", KIND_AUDIO, "m4a", "Аудио", "Лучше MP3 при том же размере"),
    Target("wav", "WAV · без потерь", KIND_AUDIO, "wav", "Аудио", "Для монтажа"),
    Target("flac", "FLAC · без потерь", KIND_AUDIO, "flac", "Аудио", "Сжатие без потерь"),
    Target("opus", "Opus", KIND_AUDIO, "opus", "Аудио", "Минимальный размер"),
    Target("ogg", "OGG · Vorbis", KIND_AUDIO, "ogg", "Аудио", "Открытый формат"),
)

ALL_TARGETS = IMAGE_TARGETS + VIDEO_TARGETS + AUDIO_TARGETS
BY_KEY = {t.key: t for t in ALL_TARGETS}


def targets_for(kind: str) -> tuple[Target, ...]:
    """Форматы, доступные для файла данного типа."""
    if kind == KIND_IMAGE:
        return IMAGE_TARGETS + (Target("gif", "GIF · анимация", "gif", "gif", "Изображения"),)
    if kind == KIND_VIDEO:
        return VIDEO_TARGETS + AUDIO_TARGETS
    if kind == KIND_AUDIO:
        return AUDIO_TARGETS
    return ()


def default_target(src_ext: str, kind: str) -> str:
    src_ext = src_ext.lower().lstrip(".")
    if kind == KIND_IMAGE:
        return "png" if src_ext in {"png", "webp"} else "webp"
    if kind == KIND_VIDEO:
        return "mp4"
    return "mp3"


# --------------------------------------------------------------------------- #
# Параметры конвертации
# --------------------------------------------------------------------------- #

QUALITY_LABELS = (
    ("high", "Качество"),
    ("balanced", "Баланс"),
    ("small", "Размер"),
)

RESOLUTIONS = (
    ("original", "Оригинал"),
    ("2160", "2160p · 4K"),
    ("1440", "1440p"),
    ("1080", "1080p"),
    ("720", "720p"),
    ("480", "480p"),
)

GIF_FPS = ("10", "12", "15", "20", "25", "30")
AUDIO_BITRATES = ("96k", "128k", "160k", "192k", "256k", "320k")

# масштаб изображений
IMAGE_PERCENTS = ("25", "50", "75", "125", "150", "200", "300", "400")
IMAGE_FILTERS = (
    ("lanczos", "Lanczos · лучшее"),
    ("bicubic", "Бикубический"),
    ("nearest", "Ближайший · пиксель-арт"),
)

# --------------------------------------------------------------------------- #
# Качество: на что оно влияет и чем измеряется (единственное место с числами)
# --------------------------------------------------------------------------- #

QUALITY_LEVELS = ("high", "balanced", "small")
_LEVEL_LABEL = dict(QUALITY_LABELS)

# full — качество реально меняет результат, weak — едва заметно, none — не влияет
QUALITY_EFFECT = {
    "mp4": "full", "mov": "full", "mkv": "full", "mkv264": "full",
    "webm": "full", "avi": "full",
    "jpg": "full", "webp": "full", "avif": "full",
    "png": "weak",
    "tiff": "none", "bmp": "none", "ico": "none", "pdf": "none",
    "gif_img": "none", "gif": "none",
    "mp3": "none", "m4a": "none", "wav": "none", "flac": "none",
    "opus": "none", "ogg": "none",
}

# кодек по цели и его значения для high / balanced / small (CPU-ветка convert.py)
_QUALITY_FAMILY = {
    "mp4": "H.264", "mov": "H.264", "mkv264": "H.264",
    "mkv": "H.265", "webm": "VP9", "avi": "MPEG-4",
    "jpg": "JPEG/WebP/AVIF", "webp": "JPEG/WebP/AVIF", "avif": "JPEG/WebP/AVIF",
}

_QUALITY_LEVELS = {
    "H.264": ("CRF 17", "CRF 23", "CRF 28"),
    "H.265": ("CRF 20", "CRF 26", "CRF 31"),
    "VP9": ("CRF 24", "CRF 32", "CRF 40"),
    "MPEG-4": ("q 2", "q 4", "q 7"),
    "JPEG/WebP/AVIF": ("95", "85", "72"),
}

_IMAGE_FAMILY = "JPEG/WebP/AVIF"

# GPU-ветка есть только у H.264 (h264_args в convert.py): у H.265/VP9 её нет
_GPU_TARGETS = frozenset({"mp4", "mov", "mkv264"})
_GPU_LEVELS = (
    ("NVENC", ("CQ 20", "CQ 25", "CQ 31")),
    ("QSV/AMF", ("21", "26", "32")),
    ("VideoToolbox", ("60", "50", "40")),
)

_SPEED_NOTE = {
    "high": "Лучшая картинка, самый большой файл, кодирование медленнее.",
    "balanced": "Обычный выбор для большинства задач.",
    "small": "Файл меньше, детали мягче, кодирование быстрее.",
}

_PNG_TIPS = {
    "high": "PNG без потерь, уровень 9 — столько же у «Размер»; картинка не меняется.",
    "balanced": "PNG без потерь, уровень 7 — сжатие быстрее, файл чуть больше.",
    "small": "PNG без потерь, уровень 9 — столько же у «Качество»; файл минимальный.",
}

_AUDIO_TARGET_KEYS = frozenset(t.key for t in AUDIO_TARGETS)


def quality_effect(target_key: str, kind: str = "") -> str:
    """Насколько качество влияет на формат: full | weak | none."""
    return QUALITY_EFFECT.get(target_key, "none")


def _family_short(family: str) -> str:
    values = _QUALITY_LEVELS[family]
    if family == _IMAGE_FAMILY:
        return " / ".join(values)
    prefix = values[0].split()[0]                 # CRF | q
    return f"{prefix} " + " / ".join(v.split()[-1] for v in values)


def _families(target_keys) -> list[str]:
    ordered: list[str] = []
    for key in target_keys:
        family = _QUALITY_FAMILY.get(key)
        if family and family not in ordered:
            ordered.append(family)
    return ordered


def _uses_gpu(keys) -> bool:
    return any(key in _GPU_TARGETS for key in keys)


def _gpu_row(index: int) -> str:
    return " · ".join(f"{name} {values[index]}" for name, values in _GPU_LEVELS)


def _none_note(keys) -> str:
    bits = []
    if any(key in ("gif", "gif_img") for key in keys):
        bits.append("на GIF качество не влияет: палитра фиксирована (256 цветов), "
                    "размер задают FPS, разрешение и фрагмент")
    if any(key in _AUDIO_TARGET_KEYS for key in keys):
        bits.append("на извлечение звука качество не влияет: размер задаёт битрейт")
    if not bits:
        bits.append("на эти форматы качество не влияет")
    text = "; ".join(bits)
    return text[:1].upper() + text[1:] + "."


def quality_hint(target_keys, gpu: bool = False) -> str:
    """Человеческое объяснение выбранного качества для текущих целей очереди.

    Направление разное: у видео меньше CRF/q — лучше, у картинок больше
    quality — лучше. При включённом GPU у H.264 показываем значения
    кодировщиков видеокарты, а не CRF.
    """
    keys = [key for key in dict.fromkeys(target_keys) if key]
    if not keys:
        return ""
    effects = [quality_effect(key) for key in keys]
    families = _families(keys)
    video = [family for family in families if family != _IMAGE_FAMILY]
    images = [family for family in families if family == _IMAGE_FAMILY]
    gpu_video = gpu and _uses_gpu(keys) and bool(video)

    parts: list[str] = []
    if video:
        if gpu_video:
            rows = " · ".join(f"{name} {values[0]} / {values[1]} / {values[2]}"
                              for name, values in _GPU_LEVELS)
            parts.append(f"Видео через GPU: {rows}. Меньше значение — лучше картинка, "
                         "но больше файл; без подходящей видеокарты остаётся CPU "
                         "с обычными значениями.")
        else:
            numbers = " · ".join(f"{family} — {_family_short(family)}" for family in video)
            parts.append(f"Видео: {numbers}. Меньше значение — лучше картинка, "
                         "но больше файл и медленнее кодирование.")
    if images:
        parts.append(f"Картинки: {_family_short(_IMAGE_FAMILY)}. Больше значение — "
                     "лучше картинка, но больше файл.")
    if "weak" in effects:
        parts.append("PNG без потерь: уровень 9 у «Качество» и «Размер», 7 у «Баланса» — "
                     "картинка не меняется, различается только скорость сжатия.")
    if "none" in effects:
        parts.append(_none_note(keys))
    return " ".join(parts)


def quality_tooltips(target_keys, gpu: bool = False) -> tuple[str, str, str]:
    """Тултипы кнопок качества: те же названия, что на кнопках, и числа целей."""
    keys = [key for key in dict.fromkeys(target_keys) if key]
    families = _families(keys)
    effects = [quality_effect(key) for key in keys]
    video = [family for family in families if family != _IMAGE_FAMILY]
    images = [family for family in families if family == _IMAGE_FAMILY]
    gpu_video = gpu and _uses_gpu(keys) and bool(video)

    tips: list[str] = []
    for index, level in enumerate(QUALITY_LEVELS):
        prefix = f"{_LEVEL_LABEL[level]}: "
        numbers: list[str] = []
        if video:
            numbers.append(f"GPU {_gpu_row(index)}" if gpu_video else
                           " · ".join(f"{family} {_QUALITY_LEVELS[family][index]}"
                                      for family in video))
        if images:
            numbers.append(f"JPEG/WebP/AVIF {_QUALITY_LEVELS[_IMAGE_FAMILY][index]}")
        if numbers:
            tips.append(prefix + " · ".join(numbers) + ". " + _SPEED_NOTE[level])
        elif "weak" in effects:
            tips.append(prefix + _PNG_TIPS[level])
        else:
            tips.append(prefix + "на эти форматы качество не влияет")
    return (tips[0], tips[1], tips[2])


# то, что реально принимают команды и UI (для валидации настроек)
QUALITY_VALUES = tuple(key for key, _ in QUALITY_LABELS)
RESOLUTION_VALUES = tuple(key for key, _ in RESOLUTIONS)
IMAGE_SCALE_VALUES = ("none", "percent", "size")
IMAGE_FILTER_VALUES = tuple(key for key, _ in IMAGE_FILTERS)


@dataclass
class ConvertOptions:
    quality: str = "balanced"
    resolution: str = "original"
    gif_fps: str = "15"
    gif_loop: bool = True
    audio_bitrate: str = "192k"
    keep_metadata: bool = True
    gpu: bool = False
    gentle: bool = False  # щадящий режим: меньше потоков
    overwrite: bool = False
    trim_start: float = 0.0   # секунды от начала; 0 — с начала
    trim_end: float = 0.0     # секунды; 0 — до конца файла
    image_scale: str = "none"      # none | percent | size
    image_percent: str = "150"
    image_width: str = ""
    image_height: str = ""
    image_keep_ratio: bool = True
    image_allow_upscale: bool = False
    image_filter: str = "lanczos"  # lanczos | bicubic | nearest

    def copy(self, **changes) -> "ConvertOptions":
        return replace(self, **changes)

    @property
    def has_trim(self) -> bool:
        return self.trim_start > 0 or self.trim_end > 0

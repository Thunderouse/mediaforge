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

# кодек по цели и его значения для high / balanced / small
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

_AUDIO_TARGET_KEYS = frozenset(t.key for t in AUDIO_TARGETS)


def quality_effect(target_key: str, kind: str = "") -> str:
    """Насколько качество влияет на формат: full | weak | none."""
    return QUALITY_EFFECT.get(target_key, "none")


def _family_short(family: str) -> str:
    values = _QUALITY_LEVELS[family]
    if family == "JPEG/WebP/AVIF":
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


def quality_hint(target_keys) -> str:
    """Человеческое объяснение выбранного качества для текущих целей очереди."""
    keys = [key for key in dict.fromkeys(target_keys) if key]
    if not keys:
        return ""
    effects = [quality_effect(key) for key in keys]
    families = _families(keys)

    parts: list[str] = []
    if families:
        numbers = " · ".join(f"{family} — {_family_short(family)}" for family in families)
        parts.append(f"Качество: {numbers}.")
        parts.append("Меньше значение — лучше картинка и больше файл; "
                     "«Качество» кодирует медленнее, «Размер» — быстрее.")
    if "weak" in effects:
        parts.append("PNG сжимается без потерь: меняется только уровень сжатия "
                     "(9 / 7 / 9), картинка та же.")
    if "none" in effects:
        parts.append(_none_note(keys))
    return " ".join(parts)


def quality_tooltips(target_keys) -> tuple[str, str, str]:
    """Тултипы кнопок «Качество / Баланс / Размер» с числами для текущих целей."""
    keys = [key for key in dict.fromkeys(target_keys) if key]
    families = _families(keys)
    effects = [quality_effect(key) for key in keys]

    tips: list[str] = []
    for index, level in enumerate(QUALITY_LEVELS):
        if families:
            numbers = " · ".join(f"{family} {_QUALITY_LEVELS[family][index]}"
                                 for family in families)
        elif "weak" in effects:
            numbers = "PNG — уровень сжатия 9 / 7 / 9"
        else:
            numbers = "на эти форматы качество не влияет"
        tips.append({
            "high": f"Максимум: {numbers}. Лучшая картинка, самый большой файл, "
                    "кодирование медленнее.",
            "balanced": f"Баланс: {numbers}. Обычный выбор для большинства задач.",
            "small": f"Меньше размер: {numbers}. Файл меньше, детали мягче, "
                     "кодирование быстрее.",
        }[level])
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

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
    ("high", "Максимум"),
    ("balanced", "Баланс"),
    ("small", "Меньше размер"),
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

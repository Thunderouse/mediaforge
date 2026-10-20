"""Слой интерфейса MediaForge (PySide6/Qt Widgets)."""

from .theme import apply as apply_theme
from .theme import current as current_palette

__all__ = ["apply_theme", "current_palette"]

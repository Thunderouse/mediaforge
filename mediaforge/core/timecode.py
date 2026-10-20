"""Разбор и форматирование таймкодов вида 90, 1:30, 00:01:30.5, 1:30,25."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"^\s*(\d{1,3}(?::\d{1,2}){0,2})(?:[.,](\d{1,3}))?\s*$")


def parse_timecode(text: str) -> float | None:
    """'90' -> 90.0, '1:30' -> 90.0, '00:01:30.5' -> 90.5, '' -> None, мусор -> ValueError."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    match = _PATTERN.match(text)
    if not match:
        raise ValueError(f"не удалось разобрать время «{text}»")
    parts = [int(p) for p in match.group(1).split(":")]
    if len(parts) >= 2 and (parts[-1] >= 60 or parts[-2] >= 60 and len(parts) == 3):
        raise ValueError(f"некорректное время «{text}»: минуты и секунды должны быть < 60")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    fraction = match.group(2)
    if fraction:
        seconds += int(fraction.ljust(3, "0")) / 1000.0
    return round(seconds, 3)


def format_timecode(seconds: float) -> str:
    """90.5 -> '1:30.5', 3675 -> '1:01:15'."""
    if seconds is None or seconds < 0:
        return ""
    total_ms = int(round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    base = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    return f"{base}.{millis // 100}" if millis else base

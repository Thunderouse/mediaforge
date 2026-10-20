"""Генерирует assets/icon.ico и assets/icon.png без Qt (нужен только Pillow).

    python tools/make_icons.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
S = 1024  # рисуем крупно и уменьшаем — сглаживание без библиотек


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return mask


def gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return img


def star_points(cx: float, cy: float, outer: float, inner: float, points: int = 4) -> list[tuple[float, float]]:
    result = []
    step = math.pi / points
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * step
        result.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
    return result


def render(size: int) -> Image.Image:
    pad = round(size * 0.04)
    inner = size - 2 * pad
    body = gradient(inner, (73, 166, 246), (21, 96, 168)).convert("RGBA")
    mask = rounded_mask(inner, round(size * 0.23))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(body, (pad, pad), mask)

    g = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    c = size
    outer = size * 0.30
    inner = size * 0.085
    d.polygon(star_points(c, c, outer, inner), fill=(255, 255, 255, 255))
    # маленькая искра сверху-справа
    d.polygon(star_points(c + size * 0.26, c - size * 0.26, size * 0.10, size * 0.03),
              fill=(255, 255, 255, 235))
    g = g.resize((size, size), Image.LANCZOS)
    canvas.alpha_composite(g)
    return canvas


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    big = render(S)
    big.resize((512, 512), Image.LANCZOS).save(ASSETS / "icon.png")
    big.save(
        ASSETS / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"готово: {ASSETS / 'icon.ico'} и {ASSETS / 'icon.png'}")


if __name__ == "__main__":
    main()

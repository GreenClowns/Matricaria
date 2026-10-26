"""Превращает картинку (например, ответ stable-diffusion.cpp) в пиксельный портрет.

Шаги: уменьшить до сетки → убрать фон → ограничить палитру → обвести контур →
увеличить без сглаживания. Нужен Pillow: `pip install matricaria[art]`.
"""

from __future__ import annotations

from collections import deque

from PIL import Image

from matricaria.art.style import PixelStyle

# Насколько цвет может отличаться от цвета угла, чтобы считаться фоном.
BACKGROUND_TOLERANCE = 40

_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def pixelize(image: Image.Image, style: PixelStyle, upscale: bool = True) -> Image.Image:
    small = _downscale(image.convert("RGBA"), style.grid)
    mask = _foreground_mask(small)
    small = _quantize(small, mask, style.colors)
    small = _add_outline(small, mask, style)
    if upscale and style.display_scale > 1:
        size = (small.width * style.display_scale, small.height * style.display_scale)
        small = small.resize(size, Image.Resampling.NEAREST)
    return small


def _downscale(image: Image.Image, grid: int) -> Image.Image:
    ratio = grid / max(image.size)
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    # BOX усредняет цвет блока: меньше случайных «грязных» пикселей, чем у NEAREST.
    return image.resize(size, Image.Resampling.BOX)


def _foreground_mask(image: Image.Image) -> list[list[bool]]:
    """True — персонаж, False — фон. Фон заливается от краёв картинки."""
    w, h = image.size
    px = image.load()
    has_alpha = any(px[x, y][3] < 255 for x in range(w) for y in (0, h - 1))
    fg = [[True] * w for _ in range(h)]

    if has_alpha:
        for y in range(h):
            for x in range(w):
                fg[y][x] = px[x, y][3] >= 128
        return fg

    corner = px[0, 0][:3]

    def is_bg(x: int, y: int) -> bool:
        return sum(abs(a - b) for a, b in zip(px[x, y][:3], corner)) <= BACKGROUND_TOLERANCE

    queue = deque((x, y) for x in range(w) for y in (0, h - 1))
    queue.extend((x, y) for y in range(h) for x in (0, w - 1))
    while queue:
        x, y = queue.popleft()
        if not fg[y][x] or not is_bg(x, y):
            continue
        fg[y][x] = False
        for dx, dy in _NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and fg[ny][nx]:
                queue.append((nx, ny))
    return fg


def _quantize(image: Image.Image, mask: list[list[bool]], colors: int) -> Image.Image:
    rgb = image.convert("RGB")
    paletted = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    out = paletted.convert("RGBA")
    px = out.load()
    for y, row in enumerate(mask):
        for x, solid in enumerate(row):
            if not solid:
                px[x, y] = (0, 0, 0, 0)
    return out


def _add_outline(image: Image.Image, mask: list[list[bool]], style: PixelStyle) -> Image.Image:
    """Обвести силуэт снаружи линией в 1 пиксель."""
    w, h = image.size
    out = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    out.paste(image, (1, 1))
    src = image.load()
    dst = out.load()
    base = _hex_to_rgb(style.outline)

    for y in range(-1, h + 1):
        for x in range(-1, w + 1):
            if 0 <= x < w and 0 <= y < h and mask[y][x]:
                continue
            touching = [src[x + dx, y + dy] for dx, dy in _NEIGHBOURS
                        if 0 <= x + dx < w and 0 <= y + dy < h and mask[y + dy][x + dx]]
            if not touching:
                continue
            if style.selout:
                # Контур оттенком соседнего цвета, но не светлее основного контура.
                r, g, b = (sum(c[i] for c in touching) // len(touching) for i in range(3))
                color = tuple(max(base[i], int(v * 0.35)) for i, v in enumerate((r, g, b)))
            else:
                color = base
            dst[x + 1, y + 1] = (*color, 255)
    return out


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

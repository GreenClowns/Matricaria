"""Обработка картинок эталона графики (решение D48).

Нейросеть рисует «под пиксели», но квадратики у неё неровные, фон часто
нарисован прямо на картинке. Скрипт приводит картинку к настоящей пиксельной
сетке и ограниченной палитре, убирает фон, режет лист кадров на отдельные
кадры и перекрашивает спрайты.

Запуск (нужны Pillow и numpy):
    uv run --with pillow --with numpy python tools/art/process_art.py --help
"""

from __future__ import annotations

import argparse
import colorsys
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

MAGENTA = (255, 0, 255)
OUTLINE = (40, 26, 22)


def estimate_block(img: Image.Image) -> int:
    """Оценивает размер «пикселя» нейросети в точках исходной картинки."""
    a = np.asarray(img.convert("RGB")).astype(int)
    edges = np.abs(np.diff(a, axis=1)).sum(2) > 40
    runs: list[int] = []
    for row in edges[::5]:
        idx = np.flatnonzero(row)
        if len(idx) > 2:
            runs.extend(np.diff(idx).tolist())
    runs_arr = np.array([r for r in runs if 2 < r < 40])
    if runs_arr.size == 0:
        return 1
    return int(np.bincount(runs_arr).argmax())


def pixelize(img: Image.Image, width: int, height: int, colors: int) -> Image.Image:
    """Уменьшает картинку до пиксельной сетки и ограничивает палитру."""
    small = img.convert("RGB").resize((width, height), Image.BOX)
    q = small.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                       dither=Image.Dither.NONE)
    return q.convert("RGB")


def background_mask(rgb: np.ndarray, bg: tuple[int, int, int] | None, tol: int) -> np.ndarray:
    """Маска фона: заливка от краёв картинки по цвету фона."""
    h, w, _ = rgb.shape
    ref = np.array(bg if bg is not None else rgb[0, 0], dtype=int)
    mask = np.zeros((h, w), bool)
    seen = np.zeros((h, w), bool)
    queue = deque([(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
                  + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)])
    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or seen[y, x]:
            continue
        seen[y, x] = True
        if np.abs(rgb[y, x] - ref).sum() > tol:
            continue
        mask[y, x] = True
        queue.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
    return mask


def clean_fringe(rgba: np.ndarray, ref: np.ndarray, tol: int, passes: int = 1) -> np.ndarray:
    """Убирает светлую кайму: краевые пиксели, похожие на фон."""
    out = rgba.copy()
    for _ in range(passes):
        solid = out[:, :, 3] > 0
        near = np.zeros_like(solid)
        near[1:, :] |= ~solid[:-1, :]
        near[:-1, :] |= ~solid[1:, :]
        near[:, 1:] |= ~solid[:, :-1]
        near[:, :-1] |= ~solid[:, 1:]
        similar = np.abs(out[:, :, :3].astype(int) - ref).sum(2) < tol
        out[solid & near & similar, 3] = 0
    return out


def process_portrait(src: Path, dst: Path, width: int, colors: int,
                     bg: tuple[int, int, int] | None, tol: int) -> Image.Image:
    """Портрет или фигура: сетка, палитра, прозрачный фон."""
    img = Image.open(src)
    height = round(img.height * width / img.width)
    if img.mode == "RGBA" and np.asarray(img.split()[3]).min() < 128:
        # У картинки есть настоящая прозрачность — берём её.
        alpha = np.asarray(img.split()[3].resize((width, height), Image.BOX)) > 140
        rgb = np.asarray(pixelize(img, width, height, colors)).astype(int)
    else:
        rgb = np.asarray(pixelize(img, width, height, colors)).astype(int)
        alpha = ~background_mask(rgb, bg, tol)
    rgba = np.dstack([rgb, np.where(alpha, 255, 0)]).astype(np.uint8)
    ref = np.array(bg if bg is not None else rgb[0, 0], dtype=int)
    rgba = clean_fringe(rgba, ref, tol + 30)
    out = Image.fromarray(rgba, "RGBA")
    out.save(dst)
    return out


def magenta_like(a: np.ndarray) -> np.ndarray:
    """Маска «розовых» точек: фон, его смесь с контуром и тени на фоне.

    У таких точек красный и синий близки и заметно больше зелёного.
    Фиолетовая мантия или лавандовые волосы под порог не попадают.
    """
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (np.minimum(r, b) - g > 60) & (np.abs(r - b) < 60)


def checker_or_flat_bg(a: np.ndarray, bg: tuple[int, int, int] | None, tol: int) -> np.ndarray:
    """Маска фона листа: нарисованная серо-белая шахматка или сплошной цвет."""
    if bg == MAGENTA:
        return magenta_like(a)
    if bg is not None:
        return np.abs(a - np.array(bg)).sum(2) < tol
    mx, mn = a.max(2), a.min(2)
    return ((mx - mn) < 20) & (mx > 178) & (mx < 232)


def slice_sheet(src: Path, out_dir: Path, block: int, colors: int,
                bg: tuple[int, int, int] | None, tol: int, min_area: int = 4000,
                gap: int = 15) -> dict:
    """Режет лист кадров на отдельные кадры и собирает атлас.

    gap — на каком расстоянии (в точках исходника) части считаются одним
    кадром. Если кадры стоят тесно и слипаются, его уменьшают.
    """
    img = Image.open(src).convert("RGB")
    a = np.asarray(img).astype(int)
    fg = ~checker_or_flat_bg(a, bg, tol)
    m = Image.fromarray((fg * 255).astype(np.uint8))
    fg = np.asarray(m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))) > 0
    grouped = np.asarray(Image.fromarray((fg * 255).astype(np.uint8))
                         .filter(ImageFilter.MaxFilter(gap | 1))) > 0
    h, w = grouped.shape
    label = np.zeros((h, w), int)
    boxes = []
    count = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if not grouped[y, x] or label[y, x]:
                continue
            count += 1
            queue = deque([(x, y)])
            label[y, x] = count
            x0 = x1 = x
            y0 = y1 = y
            area = 0
            while queue:
                cx, cy = queue.popleft()
                area += 1
                x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and grouped[ny, nx] and not label[ny, nx]:
                        label[ny, nx] = count
                        queue.append((nx, ny))
            if area > min_area:
                boxes.append((x0, y0, x1, y1))
    row_h = max(1, h // 8)
    boxes.sort(key=lambda b: (round((b[1] + b[3]) / 2 / row_h), b[0]))
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(w, x1 + 3), min(h, y1 + 3)
        fw, fh = (x1 - x0) // block, (y1 - y0) // block
        if fw < 1 or fh < 1:
            continue
        crop = img.crop((x0, y0, x0 + fw * block, y0 + fh * block))
        if bg is not None:
            # Фон заменяем цветом контура, чтобы при уменьшении края
            # смешивались с тёмным контуром, а не с цветом фона.
            c = np.asarray(crop).copy()
            c[~fg[y0:y0 + fh * block, x0:x0 + fw * block]] = OUTLINE
            crop = Image.fromarray(c)
        mcrop = Image.fromarray((fg[y0:y0 + fh * block, x0:x0 + fw * block] * 255).astype(np.uint8))
        rgb = np.asarray(pixelize(crop, fw, fh, colors))
        alpha = np.asarray(mcrop.resize((fw, fh), Image.BOX)) > 110
        rgba = np.dstack([rgb, np.where(alpha, 255, 0)]).astype(np.uint8)
        light_grey = ((rgba[:, :, :3].max(2).astype(int) - rgba[:, :, :3].min(2)) < 28) & (rgba[:, :, :3].max(2) > 165)
        rgba = rgba.copy()
        for _ in range(2):
            solid = rgba[:, :, 3] > 0
            near = np.zeros_like(solid)
            near[1:, :] |= ~solid[:-1, :]
            near[:-1, :] |= ~solid[1:, :]
            near[:, 1:] |= ~solid[:, :-1]
            near[:, :-1] |= ~solid[:, 1:]
            rgba[solid & near & light_grey, 3] = 0
        frame = Image.fromarray(rgba, "RGBA")
        frame.save(out_dir / f"frame_{i:02d}.png")
        frames.append(frame)
    # Атлас: все кадры в одну строку с промежутком 2 пикселя.
    atlas_w = sum(f.width + 2 for f in frames)
    atlas_h = max((f.height for f in frames), default=1)
    atlas = Image.new("RGBA", (max(1, atlas_w), atlas_h), (0, 0, 0, 0))
    meta = []
    x = 0
    for f in frames:
        atlas.alpha_composite(f, (x, 0))
        meta.append([x, 0, f.width, f.height])
        x += f.width + 2
    atlas.save(out_dir / "atlas.png")
    info = {"W": atlas.width, "H": atlas.height, "frames": meta}
    (out_dir / "atlas.json").write_text(json.dumps(info), encoding="utf-8")
    return info


def recolor(src: Path, dst: Path, rules: list[dict]) -> None:
    """Перекраска палитрой: правила по оттенку (hue), насыщенности и яркости.

    Правило: {"hue": [от, до], "min_sat": 0.15, "light": [от, до],
              "to_hue": 275, "sat_mul": 0.9, "light_mul": 0.85}
    """
    img = Image.open(src).convert("RGBA")
    a = np.asarray(img).astype(float) / 255
    out = a.copy()
    h, w, _ = a.shape
    for y in range(h):
        for x in range(w):
            r, g, b, al = a[y, x]
            if al == 0:
                continue
            hue, light, sat = colorsys.rgb_to_hls(r, g, b)
            deg = hue * 360
            for rule in rules:
                h0, h1 = rule["hue"]
                in_hue = h0 <= deg <= h1 if h0 <= h1 else (deg >= h0 or deg <= h1)
                l0, l1 = rule.get("light", [0, 1])
                if in_hue and sat >= rule.get("min_sat", 0) and l0 <= light <= l1:
                    nl = min(1.0, light * rule.get("light_mul", 1))
                    ns = min(1.0, sat * rule.get("sat_mul", 1))
                    out[y, x, :3] = colorsys.hls_to_rgb(rule["to_hue"] / 360, nl, ns)
                    break
    Image.fromarray((out * 255).astype(np.uint8), "RGBA").save(dst)


def parse_color(text: str | None) -> tuple[int, int, int] | None:
    if not text:
        return None
    if text.lower() == "magenta":
        return MAGENTA
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Process AI art into clean pixel art (D48).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_est = sub.add_parser("estimate", help="estimate the pixel block size of an image")
    p_est.add_argument("src", type=Path)

    p_por = sub.add_parser("portrait", help="portrait or single figure: grid, palette, transparent background")
    p_por.add_argument("src", type=Path)
    p_por.add_argument("dst", type=Path)
    p_por.add_argument("--width", type=int, default=160, help="target width in pixels")
    p_por.add_argument("--colors", type=int, default=40)
    p_por.add_argument("--bg", help="background color: #rrggbb or 'magenta' (default: corner color)")
    p_por.add_argument("--tol", type=int, default=75)

    p_sh = sub.add_parser("sheet", help="slice a sprite sheet into frames and an atlas")
    p_sh.add_argument("src", type=Path)
    p_sh.add_argument("out_dir", type=Path)
    p_sh.add_argument("--block", type=int, default=6, help="source points per sprite pixel")
    p_sh.add_argument("--colors", type=int, default=28)
    p_sh.add_argument("--bg", help="flat background color (default: grey/white checkerboard)")
    p_sh.add_argument("--tol", type=int, default=90)
    p_sh.add_argument("--gap", type=int, default=15,
                      help="merge distance in source points; lower it if frames stick together")

    p_rc = sub.add_parser("recolor", help="palette swap by hue rules from a JSON file")
    p_rc.add_argument("src", type=Path)
    p_rc.add_argument("dst", type=Path)
    p_rc.add_argument("rules", type=Path, help="JSON list of rules")

    args = parser.parse_args(argv)
    if args.cmd == "estimate":
        print(f"Pixel block: about {estimate_block(Image.open(args.src))} points")
    elif args.cmd == "portrait":
        out = process_portrait(args.src, args.dst, args.width, args.colors, parse_color(args.bg), args.tol)
        print(f"Saved {args.dst} ({out.width}x{out.height})")
    elif args.cmd == "sheet":
        info = slice_sheet(args.src, args.out_dir, args.block, args.colors, parse_color(args.bg), args.tol,
                           gap=args.gap)
        print(f"Saved {len(info['frames'])} frames and atlas to {args.out_dir}")
    elif args.cmd == "recolor":
        recolor(args.src, args.dst, json.loads(args.rules.read_text(encoding="utf-8")))
        print(f"Saved {args.dst}")


if __name__ == "__main__":
    main()

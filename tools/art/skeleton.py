"""Скелетные спрайты: код строит скелет, на нём тело и одежду, потом пиксели.

Проба к решению о графике (после D48): тело обычных жителей рисует код по
ползункам (рост, мускулы, полнота, грудь, плечи), а стиль подгоняется под
эталон — лист Бориса, вариант 3: чиби, тёмный контур, свет слева сверху,
тёплая палитра, рост фигуры около 52 пикселей.

Как устроено:
1. Поза — положения суставов (таз, колени, стопы, плечи, локти, кисти).
2. Каждая часть тела — «объём» вокруг кости; толщину задают ползунки.
3. Части рисуются в увеличенной сетке и уменьшаются до пикселей.
4. Светотень по правилам: светлый край слева сверху, тень справа и снизу,
   тёмный внутренний контур у частей спереди, тёмный внешний контур.

Запуск (нужны Pillow и numpy):
    uv run --with pillow --with numpy python tools/art/skeleton.py demo папка
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# Во сколько раз голова крупнее обычной (пропорции чиби).
HEAD = 1.15
# Размер кадра в пикселях и линия земли.
FRAME_W, FRAME_H = 48, 64
GROUND = 61
# Во сколько раз увеличена сетка, в которой рисуются фигуры.
SS = 6

OUTLINE = (41, 16, 22)


def hexrgb(text: str) -> tuple[int, int, int]:
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def ramp(*colors: str) -> list[tuple[int, int, int]]:
    """Тона одного материала: контур, тень, основной, свет."""
    return [hexrgb(c) for c in colors]


# Палитра снята с листа Бориса (вариант 3).
PALETTE = {
    "skin": ramp("#7a402a", "#c27a5c", "#e8a888", "#f4c4a4"),
    "shirt": ramp("#7d5240", "#c9a58e", "#ecd2b8", "#f8e6d0"),
    "apron": ramp("#4a271b", "#753822", "#915732", "#a8683c"),
    "pants": ramp("#251e18", "#2a1719", "#3d1e19", "#4a332a"),
    "boots": ramp("#291016", "#542017", "#663828", "#874023"),
    "hair": ramp("#3d1116", "#632819", "#8f4828", "#a75d32"),
    "wood": ramp("#3d1e19", "#663828", "#8d5332", "#a8683c"),
    "foam": ramp("#9b7665", "#d8c0a8", "#f1e6d6", "#ffffff"),
}


@dataclass
class Body:
    """Ползунки тела. Все, кроме роста, от 0 до 1."""

    height: float = 1.0      # 0.8 — коротышка, 1.2 — высокий
    muscle: float = 0.3
    fat: float = 0.3
    bust: float = 0.0
    shoulders: float = 0.5


@dataclass
class Pose:
    """Смещения суставов от стойки (в пикселях) для одного кадра."""

    bob: float = 0.0                       # тело вверх-вниз
    lean: float = 0.0                      # наклон корпуса вперёд
    leg_back: tuple[float, float] = (0, 0)   # (вперёд, подъём) дальней ноги
    leg_front: tuple[float, float] = (0, 0)
    arm_back: tuple[float, float] = (0, 0)   # (вперёд, вверх) кисти
    arm_front: tuple[float, float] = (0, 0)


POSES: dict[str, list[Pose]] = {
    "idle": [Pose()],
    "walk": [
        Pose(bob=0, leg_back=(-3, 0), leg_front=(3, 0), arm_back=(2, 0), arm_front=(-2, 0)),
        Pose(bob=-1, leg_back=(1, 2), leg_front=(0, 0), arm_back=(0, 0), arm_front=(0, 0)),
        Pose(bob=0, leg_back=(3, 0), leg_front=(-3, 0), arm_back=(-2, 0), arm_front=(2, 0)),
        Pose(bob=-1, leg_back=(0, 0), leg_front=(1, 2), arm_back=(0, 0), arm_front=(0, 0)),
    ],
}


@dataclass
class Part:
    """Одна часть фигуры: материал, маска, нужен ли внутренний контур."""

    name: str
    material: str
    contour: bool = False
    shade_band: bool = False
    shapes: list = field(default_factory=list)


def capsule(draw: ImageDraw.ImageDraw, a, b, r0: float, r1: float | None = None) -> None:
    """Объём вокруг кости от a до b (радиус может сужаться к концу)."""
    r1 = r0 if r1 is None else r1
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1e-6
    nx, ny = -dy / length, dx / length
    poly = [(x0 + nx * r0, y0 + ny * r0), (x1 + nx * r1, y1 + ny * r1),
            (x1 - nx * r1, y1 - ny * r1), (x0 - nx * r0, y0 - ny * r0)]
    draw.polygon([(x * SS, y * SS) for x, y in poly], fill=255)
    for (x, y), r in ((a, r0), (b, r1)):
        draw.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=255)


def ellipse(draw: ImageDraw.ImageDraw, cx: float, cy: float, rx: float, ry: float) -> None:
    draw.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], fill=255)


def polygon(draw: ImageDraw.ImageDraw, pts) -> None:
    draw.polygon([(x * SS, y * SS) for x, y in pts], fill=255)


def bumpy_blob(draw: ImageDraw.ImageDraw, cx: float, cy: float, rx: float, ry: float,
               bumps: int, depth: float, phase: float = 0.0) -> None:
    """Кудрявый контур: эллипс с волнистым краем (волосы, борода)."""
    pts = []
    for i in range(96):
        t = i / 96 * 2 * math.pi
        k = 1 + depth * max(0.0, math.sin(t * bumps + phase))
        pts.append((cx + math.cos(t) * rx * k, cy + math.sin(t) * ry * k))
    polygon(draw, pts)


class Rig:
    """Суставы фигуры для данного тела и позы (координаты в пикселях кадра)."""

    def __init__(self, body: Body, pose: Pose):
        h = body.height
        self.body = body
        cx = FRAME_W / 2 - 2
        leg = 12.5 * h
        torso = 11.5 * h
        hip_y = GROUND - leg + pose.bob
        self.hip = (cx, hip_y)
        self.neck = (cx + pose.lean, hip_y - torso)
        sw = 5.5 + 2.5 * body.shoulders + 3.0 * body.muscle + 2.0 * body.fat
        self.shoulder_back = (self.neck[0] - sw, self.neck[1] + 2.5)
        self.shoulder_front = (self.neck[0] + sw - 1, self.neck[1] + 2.5)
        hw = 4.0 + 2.0 * body.fat + 0.8 * body.muscle
        self.hip_back = (cx - hw + 1, hip_y)
        self.hip_front = (cx + hw - 1, hip_y)
        self.feet = {}
        for side, hp, (fwd, lift) in (("back", self.hip_back, pose.leg_back),
                                      ("front", self.hip_front, pose.leg_front)):
            foot = (hp[0] + fwd, GROUND - 1.5 - lift)
            knee = ((hp[0] + foot[0]) / 2 + lift * 0.6 + 0.3, (hp[1] + foot[1]) / 2 - lift * 0.3)
            self.feet[side] = (hp, knee, foot)
        arm = 9.5 * (0.85 + 0.15 * h)
        self.arms = {}
        for side, sh, (fwd, up) in (("back", self.shoulder_back, pose.arm_back),
                                    ("front", self.shoulder_front, pose.arm_front)):
            out = -1 if side == "back" else 1
            hand = (sh[0] + out * (1.5 + body.fat) + fwd, sh[1] + arm - up)
            elbow = ((sh[0] + hand[0]) / 2 + out * (0.8 + 0.6 * body.fat), (sh[1] + hand[1]) / 2)
            self.arms[side] = (sh, elbow, hand)
        self.head = (self.neck[0] + 1 + pose.lean * 0.5, self.neck[1] - 10.0)


def build_parts(rig: Rig) -> list[tuple[Part, Image.Image]]:
    """Части фигуры Бориса от дальних к ближним, каждая со своей маской."""
    b = rig.body
    size = (FRAME_W * SS, FRAME_H * SS)
    parts: list[tuple[Part, Image.Image]] = []

    def new(name, material, contour=False, band=False):
        img = Image.new("L", size, 0)
        parts.append((Part(name, material, contour, band), img))
        return ImageDraw.Draw(img)

    arm_r = 1.5 + 1.7 * b.muscle + 1.0 * b.fat
    leg_r = 2.0 + 1.2 * b.muscle + 1.6 * b.fat

    # Дальняя рука: закатанный рукав и голое предплечье.
    sh, el, hd = rig.arms["back"]
    d = new("arm_back_skin", "skin")
    capsule(d, el, hd, arm_r * 0.95, arm_r * 0.85)
    ellipse(d, hd[0], hd[1] + 0.5, arm_r * 0.95, arm_r * 0.9)
    d = new("sleeve_back", "shirt")
    capsule(d, sh, el, arm_r * 1.15 + 0.3, arm_r * 1.05 + 0.3)

    # Ноги: штаны и сапоги.
    for side in ("back", "front"):
        hp, kn, ft = rig.feet[side]
        d = new(f"leg_{side}", "pants", contour=side == "front")
        capsule(d, hp, kn, leg_r, leg_r * 0.9)
        capsule(d, kn, (ft[0], ft[1] - 2), leg_r * 0.9, leg_r * 0.85)
        d = new(f"boot_{side}", "boots", contour=True)
        capsule(d, (ft[0], ft[1] - 3), (ft[0], ft[1] - 0.5), leg_r * 0.95)
        ellipse(d, ft[0] + 1.2, ft[1] - 0.2, leg_r + 1.1, 1.6)

    # Корпус: рубаха. Полнота даёт живот, мускулы — широкую грудь.
    nx, ny = rig.neck
    hx, hy = rig.hip
    sb, sf = rig.shoulder_back, rig.shoulder_front
    belly = 2.5 * b.fat
    waist = 4.0 + 4.0 * b.fat + 1.5 * b.muscle
    d = new("torso", "shirt", band=True)
    polygon(d, [
        (sb[0] + 0.5, sb[1] - 1.5), (nx, ny), (sf[0] - 0.5, sf[1] - 1.5),
        (sf[0] + 0.5, sf[1] + 2.5), (hx + waist + belly, (ny + hy) / 2 + 2),
        (hx + waist - 0.5, hy + 1.5), (hx - waist + 0.5, hy + 1.5),
        (hx - waist - belly * 0.5, (ny + hy) / 2 + 2), (sb[0] - 0.5, sb[1] + 2.5),
    ])
    ellipse(d, sb[0] + 0.5, sb[1] + 0.5, 2.6 + b.muscle, 2.6 + b.muscle)
    ellipse(d, sf[0] - 0.5, sf[1] + 0.5, 2.6 + b.muscle, 2.6 + b.muscle)
    if b.bust > 0:
        ellipse(d, nx + 2.5, ny + 6, 3 + 2.5 * b.bust, 2 + 2 * b.bust)

    # Фартук: нагрудник и юбка до колен, повторяет живот.
    d = new("apron", "apron", contour=True, band=True)
    apron_bottom = hy + 4.0
    polygon(d, [
        (nx - 3.5, ny + 3), (nx + 3.5, ny + 3),
        (hx + waist + belly + 0.3, (ny + hy) / 2 + 2.5),
        (hx + waist + belly * 0.6 + 0.5, apron_bottom),
        (hx - waist - 0.2, apron_bottom),
        (hx - waist - belly * 0.4 - 0.3, (ny + hy) / 2 + 2.5),
    ])
    # Завязка фартука на поясе.
    d = new("apron_tie", "boots")
    tie_y = (ny + hy) / 2 + 3.2
    polygon(d, [(hx - waist - belly * 0.4 - 0.5, tie_y), (hx + waist + belly + 0.5, tie_y),
                (hx + waist + belly + 0.5, tie_y + 1.1), (hx - waist - belly * 0.4 - 0.5, tie_y + 1.1)])

    # Голова: волосы сзади, лицо, борода, чёлка сверху.
    # Голова у чиби крупная: размеры умножаются на HEAD.
    cx, cy = rig.head
    k = HEAD
    d = new("hair_back", "hair", band=True)
    bumpy_blob(d, cx - 1.5 * k, cy - 1.0 * k, 9.0 * k, 8.8 * k, 9, 0.14)
    d = new("face", "skin")
    ellipse(d, cx + 1.2 * k, cy + 1 * k, 6.4 * k, 7.0 * k)
    d = new("beard", "hair", band=True)
    bumpy_blob(d, cx + 1.5 * k, cy + 6.8 * k, 6.6 * k, 4.6 * k, 7, 0.14, 0.6)
    d = new("fringe", "hair")
    bumpy_blob(d, cx + 0.5 * k, cy - 5.6 * k, 7.2 * k, 3.0 * k, 6, 0.3, 0.3)

    # Ближняя рука держит кружку перед собой.
    sh, el, hd = rig.arms["front"]
    hd = (hd[0] + 3.5, hd[1] - 2.0)
    el = (el[0] + 1.0, el[1] + 0.5)
    d = new("mug", "wood", contour=True)
    polygon(d, [(hd[0] + 0.5, hd[1] - 4.5), (hd[0] + 6.5, hd[1] - 4.5),
                (hd[0] + 6.3, hd[1] + 3.0), (hd[0] + 0.7, hd[1] + 3.0)])
    d = new("foam", "foam")
    bumpy_blob(d, hd[0] + 3.5, hd[1] - 4.8, 3.6, 1.4, 4, 0.25)
    d = new("sleeve_front", "shirt", contour=True)
    capsule(d, sh, el, arm_r * 1.15 + 0.3, arm_r * 1.05 + 0.3)
    d = new("arm_front_skin", "skin", contour=True)
    capsule(d, el, hd, arm_r * 0.95, arm_r * 0.85)
    ellipse(d, hd[0] + 0.5, hd[1], arm_r * 0.95 + 0.3, arm_r * 0.9 + 0.3)
    return parts


def shrink(mask: Image.Image) -> np.ndarray:
    """Маска из увеличенной сетки в пиксели: пиксель занят, если покрыт наполовину."""
    small = mask.resize((FRAME_W, FRAME_H), Image.BOX)
    return np.asarray(small) >= 128


def shifted(m: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """Значение маски в соседнем пикселе (dx, dy); за краем — пусто."""
    out = np.zeros_like(m)
    h, w = m.shape
    ys = slice(max(0, -dy), min(h, h - dy))
    xs = slice(max(0, -dx), min(w, w - dx))
    yd = slice(max(0, dy), min(h, h + dy))
    xd = slice(max(0, dx), min(w, w + dx))
    out[ys, xs] = m[yd, xd]
    return out


def render_frame(body: Body, pose: Pose) -> Image.Image:
    """Один кадр: части → пиксели → светотень → контуры."""
    rig = Rig(body, pose)
    rgb = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)
    owner = np.full((FRAME_H, FRAME_W), -1, int)
    parts = build_parts(rig)
    masks = [shrink(img) for _, img in parts]
    for i, ((part, _), m) in enumerate(zip(parts, masks)):
        tones = PALETTE[part.material]
        # Светотень по своей полной маске, чтобы перекрытия не давали ложных краёв.
        dark = ~shifted(m, 1, 0) | ~shifted(m, 0, 1)
        light = (~shifted(m, -1, 0) | ~shifted(m, 0, -1)) & ~dark
        tone = np.full(m.shape, 2)
        if part.shade_band:
            xs = np.where(m.any(0))[0]
            if xs.size:
                x0, x1 = xs[0], xs[-1]
                band = np.arange(FRAME_W) > x0 + (x1 - x0) * 0.7
                tone[:, band] = 1
        tone[dark] = 1
        tone[light] = 3
        if part.material == "hair":
            # Кудри: редкие тёмные и светлые завитки внутри волос.
            yy, xx = np.mgrid[0:FRAME_H, 0:FRAME_W]
            tone[((xx * 3 + yy * 5) % 11 == 0) & ~dark] = 1
            tone[((xx + yy * 4) % 13 == 0) & ~dark & ~light] = 3
        colors = np.array(tones)[tone]
        rgb[m] = colors[m]
        if part.contour:
            # Внутренний контур там, где часть лежит поверх уже нарисованного.
            under = owner >= 0
            edge = m & (~shifted(m, 1, 0) | ~shifted(m, -1, 0) | ~shifted(m, 0, 1) | ~shifted(m, 0, -1))
            edge &= (shifted(under & ~m, 1, 0) | shifted(under & ~m, -1, 0)
                     | shifted(under & ~m, 0, 1) | shifted(under & ~m, 0, -1))
            rgb[edge] = tones[0]
        owner[m] = i
    fig = owner >= 0
    draw_face(rgb, fig, rig)
    # Внешний контур: пустые пиксели рядом с фигурой.
    near = (shifted(fig, 1, 0) | shifted(fig, -1, 0) | shifted(fig, 0, 1) | shifted(fig, 0, -1)) & ~fig
    rgb[near] = OUTLINE
    alpha = np.where(fig | near, 255, 0).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def draw_face(rgb: np.ndarray, fig: np.ndarray, rig: Rig) -> None:
    """Глаза, брови, нос и румянец — прямо по пикселям, как у эталона."""
    cx, cy = (int(round(v)) for v in rig.head)
    eye = hexrgb("#291016")
    brow = PALETTE["hair"][1]
    white = hexrgb("#f8e6d0")
    blush = hexrgb("#d86a5a")
    for ex in (cx, cx + 5):
        rgb[cy:cy + 2, ex] = eye
        rgb[cy, ex - 1] = white
        rgb[cy - 2, ex - 1:ex + 2] = brow
    rgb[cy + 2:cy + 4, cx + 3] = PALETTE["skin"][1]
    rgb[cy + 3, cx + 7] = blush
    rgb[cy + 3, cx - 2] = blush
    rgb[cy + 6, cx + 2:cx + 5] = PALETTE["hair"][0]


BODIES = {
    "slim": Body(height=1.05, muscle=0.0, fat=0.0, shoulders=0.2),
    "average": Body(height=1.0, muscle=0.3, fat=0.3),
    "muscular": Body(height=1.05, muscle=1.0, fat=0.2, shoulders=0.9),
    "plump": Body(height=0.95, muscle=0.2, fat=1.0),
    "short": Body(height=0.8, muscle=0.3, fat=0.4),
    "tall": Body(height=1.25, muscle=0.4, fat=0.2),
}


def render_sheet(body: Body, out: Path) -> dict:
    """Лист кадров одного тела: стойка и ходьба в одну строку."""
    frames = [render_frame(body, p) for name in ("idle", "walk") for p in POSES[name]]
    sheet = Image.new("RGBA", (FRAME_W * len(frames), FRAME_H), (0, 0, 0, 0))
    for i, f in enumerate(frames):
        sheet.alpha_composite(f, (i * FRAME_W, 0))
    sheet.save(out)
    return {"frame": [FRAME_W, FRAME_H], "count": len(frames), "idle": [0], "walk": [1, 2, 3, 4]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Skeleton-based pixel sprites (prototype).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_demo = sub.add_parser("demo", help="render sample bodies as sprite sheets")
    p_demo.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "demo":
        args.out_dir.mkdir(parents=True, exist_ok=True)
        info = {}
        for name, body in BODIES.items():
            info[name] = render_sheet(body, args.out_dir / f"{name}.png")
        (args.out_dir / "sheets.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
        print(f"Saved {len(info)} sprite sheets to {args.out_dir}")


if __name__ == "__main__":
    main()

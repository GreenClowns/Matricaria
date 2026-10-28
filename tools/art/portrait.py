"""Портреты крупным планом, нарисованные кодом (решение D51).

Портрет по грудь 128×128 пикселей, голова повёрнута на три четверти
вправо, свет слева сверху. Всё строится из «рецепта» внешности (Look):
форма челюсти, глаза, брови, причёска, борода, уши, одежда, эмоция.

Как устроено:
1. Каждая часть (волосы сзади, шея, тело, одежда, лицо, уши, борода,
   чёлка, шляпа) — фигура в увеличенной сетке, потом пиксели.
2. Объём: маска части размывается, получается «высота»; по её наклону
   считается освещённость, и пиксель берёт один из тонов материала
   (тень, основной, свет, блик) — как cel-shading в аниме.
3. Контур цветной: край части красится самым тёмным тоном её материала.
4. Глаза, брови, нос, рот, веснушки и шрамы рисуются прямо по пикселям,
   чтобы они были чёткими.

Запуск (нужны Pillow и numpy):
    uv run --with pillow --with numpy python tools/art/portrait.py demo папка
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SIZE = 128
SS = 4
LIGHT = np.array([-0.55, -0.75, 0.9])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def hexrgb(text: str) -> tuple[int, int, int]:
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(int(round(x * (1 - t) + y * t)) for x, y in zip(a, b))


def make_ramp(base: str, shadow_hue: str = "#3a2050") -> list[tuple[int, int, int]]:
    """Пять тонов материала из одного цвета: контур, тень, основной, свет, блик.

    Тени уходят в холодный фиолетовый, свет — в тёплый, как в аниме.
    """
    c = hexrgb(base)
    cold = hexrgb(shadow_hue)
    warm = (255, 244, 220)
    return [mix(mix(c, cold, 0.55), (0, 0, 0), 0.35), mix(c, cold, 0.32), c,
            mix(c, warm, 0.28), mix(c, warm, 0.6)]


@dataclass
class Look:
    """Рецепт внешности для портрета."""

    name: str = "Hero"
    skin: str = "#f2c4a4"
    hair: str = "#8a4a2a"
    hair_under: str | None = None     # второй цвет волос снизу (как у Киры)
    eyes: str = "#4a7ae0"
    hair_style: str = "short"         # short, messy, bob, long, tails, bald
    jaw: str = "soft"                 # soft, sharp, square, round
    eye_shape: str = "round"          # round, sharp, sleepy
    brows: float = 1.0                # толщина бровей
    ears: str = "human"               # human, elf
    beard: str = "none"               # none, full, mustache
    freckles: bool = False
    scar: bool = False
    age: float = 0.0                  # 0 — молодой, 1 — морщины
    female: bool = False
    outfit: str = "shirt"             # shirt, cloak, armor, robe, apron, tunic
    cloth: str = "#e8e2d0"
    cloth2: str = "#7a5236"
    trim: str = "#e8c050"
    hat: str | None = None            # witch, straw
    hat_color: str = "#3e2a52"
    bg: str = "#4a5a6a"
    emotion: str = "neutral"          # neutral, happy, angry, surprised, sad


@dataclass
class Layer:
    name: str
    ramp: list
    mask: np.ndarray
    blur: float = 6.0
    outline: bool = True
    flat: bool = False
    max_tone: int = 4


class Canvas:
    """Увеличенная сетка для фигур одной части."""

    def __init__(self):
        self.img = Image.new("L", (SIZE * SS, SIZE * SS), 0)
        self.d = ImageDraw.Draw(self.img)

    def ellipse(self, cx, cy, rx, ry, fill=255):
        self.d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], fill=fill)

    def poly(self, pts, fill=255):
        self.d.polygon([(x * SS, y * SS) for x, y in pts], fill=fill)

    def rect(self, x0, y0, x1, y1, fill=255):
        self.d.rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=fill)

    def lock(self, root, tip, width, bend=0.0, fill=255):
        """Прядь: изогнутый клин от корня к острому кончику."""
        (x0, y0), (x1, y1) = root, tip
        pts_l, pts_r = [], []
        for i in range(13):
            t = i / 12
            x = x0 + (x1 - x0) * t + bend * math.sin(t * math.pi)
            y = y0 + (y1 - y0) * t
            w = width * (1 - t) ** 0.8 / 2
            dx, dy = x1 - x0, y1 - y0
            ln = math.hypot(dx, dy) or 1
            nx, ny = -dy / ln, dx / ln
            pts_l.append((x + nx * w, y + ny * w))
            pts_r.append((x - nx * w, y - ny * w))
        self.poly(pts_l + pts_r[::-1], fill)

    def mask(self) -> np.ndarray:
        small = self.img.resize((SIZE, SIZE), Image.BOX)
        return np.asarray(small) >= 128

    def soft(self) -> Image.Image:
        return self.img


def shade_layer(layer: Layer) -> np.ndarray:
    """Номер тона (1–4) для каждого пикселя части по освещённости объёма."""
    m = layer.mask
    if layer.flat:
        return np.full(m.shape, 2)
    img = Image.fromarray((m * 255).astype(np.uint8)).resize((SIZE * 2, SIZE * 2), Image.NEAREST)
    hgt = np.asarray(img.filter(ImageFilter.GaussianBlur(layer.blur * 2))).astype(float) / 255
    hgt = np.asarray(Image.fromarray((hgt * 255).astype(np.uint8)).resize((SIZE, SIZE), Image.BOX)).astype(float) / 255
    gy, gx = np.gradient(hgt)
    nz = np.full(hgt.shape, 0.07)
    n = np.dstack([-gx, -gy, nz])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    lum = n @ LIGHT
    tone = np.where(lum > 0.86, 4, np.where(lum > 0.55, 3, np.where(lum > 0.12, 2, 1)))
    return tone


def edge_of(m: np.ndarray, other: np.ndarray | None = None) -> np.ndarray:
    """Пиксели маски, у которых сосед снаружи (или в другой маске)."""
    pad = np.pad(m, 1)
    out = np.zeros_like(m)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nb = pad[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]]
        out |= m & ~nb
    return out


class Portrait:
    """Сборка портрета: слои, светотень, контур, лицо по пикселям."""

    def __init__(self, look: Look):
        self.look = look
        self.rgb = np.zeros((SIZE, SIZE, 3), np.uint8)
        self.owner = np.full((SIZE, SIZE), "", object)
        self.skin = make_ramp(look.skin, "#a04a60")
        self.hair = make_ramp(look.hair)
        self.hair2 = make_ramp(look.hair_under) if look.hair_under else self.hair
        self.cloth = make_ramp(look.cloth)
        self.cloth2 = make_ramp(look.cloth2)
        self.trim = make_ramp(look.trim)
        # Опорные точки головы: ось лица смещена вправо (поворот на 3/4).
        self.hx, self.hy = 62, 52
        self.mid = 70
        jaw = {"soft": (0, 0), "sharp": (-3, 3), "square": (4, -1), "round": (3, -2)}[look.jaw]
        self.jaw_w, self.chin = jaw
        self.chin_y = 90 + self.chin + (2 if not look.female else 0)

    # --- слои -----------------------------------------------------------
    def put(self, layer: Layer):
        m = layer.mask
        tone = np.minimum(shade_layer(layer), layer.max_tone)
        col = np.array(layer.ramp)[tone]
        self.rgb[m] = col[m]
        if layer.outline:
            e = edge_of(m)
            self.rgb[e] = layer.ramp[0]
        self.owner[m] = layer.name

    def face_shape(self, c: Canvas):
        jw, ch = self.jaw_w, self.chin
        cy = self.chin_y
        pts = [(37, 46), (36, 60), (39 - jw * 0.3, 72), (47 - jw, 82 + ch * 0.5),
               (58, cy - 3), (self.mid, cy), (self.mid + 8 + jw * 0.5, cy - 5),
               (84 + jw * 0.4, 76), (88, 62), (88, 44), (62, 26)]
        c.poly(pts)
        c.ellipse(62, 46, 26, 22)

    def build(self) -> Image.Image:
        lk = self.look
        self.background()
        self.hair_back()
        self.body()
        # шея
        c = Canvas()
        nw = 0 if self.look.female else 3
        c.poly([(55 - nw, 76), (75 + nw, 76), (77 + nw, 104), (53 - nw, 104)])
        neck = c.mask()
        self.put(Layer("neck", self.skin, neck, blur=5))
        under = neck & (np.arange(SIZE)[:, None] < self.chin_y + 7)
        self.rgb[under & ~edge_of(neck)] = self.skin[1]
        self.clothes()
        # уши (ближнее ухо слева)
        c = Canvas()
        if lk.ears == "elf":
            c.poly([(40, 54), (20, 40), (24, 46), (34, 62), (40, 66)])
        else:
            c.ellipse(37.5, 60, 4.5, 7)
        self.put(Layer("ear", self.skin, c.mask(), blur=3))
        # лицо
        c = Canvas()
        self.face_shape(c)
        face = c.mask()
        self.face_mask = face
        self.put(Layer("face", self.skin, face, blur=12))
        if lk.beard == "full":
            c = Canvas()
            cy = self.chin_y
            c.poly([(39, 66), (43, 78), (51, 88), (self.mid, cy + 8), (self.mid + 10, cy + 2),
                    (85, 78), (87, 68), (83, 74), (77, 79), (self.mid, 78), (60, 79), (52, 78), (45, 72)])
            for i in range(7):
                c.lock((47 + i * 6, 84), (45 + i * 6.5, cy + 6 + (i % 2) * 3), 6, bend=1.5)
            beard = c.mask()
            self.put(Layer("beard", self.hair, beard, blur=5, max_tone=3))
            lines = Canvas()
            for i in range(9):
                lines.lock((46 + i * 5, 80 + (i % 3)), (45 + i * 5.2, cy + 2 + (i % 2) * 4), 1.6, bend=1)
            self.rgb[lines.mask() & beard & ~edge_of(beard)] = self.hair[1]
        self.hair_front()
        self.hat()
        self.features()
        return self.frame()

    def background(self):
        base = hexrgb(self.look.bg)
        c0, c1, c2 = mix(base, (255, 255, 255), 0.18), base, mix(base, (0, 0, 0), 0.35)
        bay = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16
        yy, xx = np.mgrid[0:SIZE, 0:SIZE]
        r = np.sqrt((xx - 52) ** 2 + (yy - 44) ** 2) / 90 + bay[yy % 4, xx % 4] * 0.18
        self.rgb[:] = np.where((r < 0.5)[..., None], c0, np.where((r < 0.82)[..., None], c1, c2))

    def hair_back(self):
        lk = self.look
        if lk.hair_style == "bald":
            return
        c = Canvas()
        if lk.hair_style in ("bob",):
            c.ellipse(61, 54, 30, 30)
            c.rect(30, 54, 92, 86)
        elif lk.hair_style == "long":
            c.ellipse(60, 52, 33, 36)
            c.poly([(27, 52), (93, 52), (100, 128), (20, 128)])
        elif lk.hair_style == "tails":
            c.ellipse(61, 47, 29, 27)
            for sx, d in ((32, -1), (91, 1)):
                c.ellipse(sx + d * 2, 48, 8, 7)
                c.lock((sx + d * 3, 50), (sx + d * 10, 122), 18, bend=d * 5)
        else:
            c.ellipse(61, 46, 29, 27)
        self.put(Layer("hair_back", self.hair2 if lk.hair_under else self.hair, c.mask(), blur=7))

    def body(self):
        lk = self.look
        c = Canvas()
        sw = 0 if lk.female else 6
        c.poly([(4 - sw, 128), (14 - sw, 106), (40, 96), (88, 96), (114 + sw, 106), (126 + sw, 128)])
        self.body_mask = c.mask()
        self.put(Layer("body", self.cloth, self.body_mask, blur=10))
        self.folds(self.body_mask, self.cloth, [((22, 112), (34, 128)), ((100, 110), (92, 128)), ((30, 106), (44, 120))])

    def folds(self, mask, ramp, strokes):
        """Складки ткани: тёмная линия и светлый край рядом с ней."""
        dark, light = Canvas(), Canvas()
        for a, b in strokes:
            dark.lock(a, b, 2.2, bend=2)
            light.lock((a[0] - 1.5, a[1]), (b[0] - 1.5, b[1]), 1.4, bend=2)
        inner = mask & ~edge_of(mask)
        self.rgb[light.mask() & inner] = ramp[3]
        self.rgb[dark.mask() & inner] = ramp[1]

    def clothes(self):
        lk = self.look
        o = lk.outfit
        if o == "cloak":
            c = Canvas()
            c.poly([(0, 128), (8, 104), (40, 92), (54, 102), (64, 128)])
            c.poly([(128, 128), (120, 104), (88, 92), (76, 102), (68, 128)])
            cloak = c.mask()
            self.put(Layer("cloak", self.cloth, cloak, blur=8))
            self.folds(cloak, self.cloth, [((16, 108), (12, 128)), ((30, 102), (34, 128)), ((112, 108), (116, 128)),
                                           ((96, 102), (92, 128)), ((48, 104), (54, 128))])
            c = Canvas()
            c.ellipse(64, 102, 6, 5)
            self.put(Layer("clasp", self.trim, c.mask(), blur=2))
        elif o == "armor":
            steel = make_ramp(lk.cloth, "#203050")
            c = Canvas()
            c.poly([(30, 128), (36, 104), (50, 98), (78, 98), (92, 104), (98, 128)])
            self.put(Layer("plate", steel, c.mask(), blur=10))
            for cx in (20, 108):
                c = Canvas()
                c.ellipse(cx, 108, 20, 13)
                self.put(Layer("pauldron", steel, c.mask(), blur=5))
            for x, y in ((40, 108), (88, 108), (64, 116)):
                self.rgb[y, x] = steel[4]
        elif o == "robe":
            c = Canvas()
            c.poly([(46, 96), (64, 124), (82, 96), (96, 100), (70, 128), (58, 128), (32, 100)])
            self.put(Layer("collar", self.trim, c.mask(), blur=3))
        elif o == "apron":
            c = Canvas()
            c.poly([(46, 108), (82, 108), (84, 128), (44, 128)])
            self.put(Layer("apron", self.cloth2, c.mask(), blur=6))
            for x0 in (48, 78):
                c = Canvas()
                c.poly([(x0, 108), (x0 + 3, 108), (x0 + 1 + (x0 - 64) * 0.4, 96), (x0 - 2 + (x0 - 64) * 0.4, 96)])
                self.put(Layer("strap", self.cloth2, c.mask(), blur=2))
        elif o == "tunic":
            c = Canvas()
            c.poly([(56, 96), (64, 114), (72, 96)])
            self.put(Layer("neckline", self.skin, c.mask(), blur=3))
            for y in range(100, 114, 4):
                self.rgb[y, 62:67] = self.cloth2[1]
        if o in ("shirt", "apron", "tunic"):
            c = Canvas()
            c.poly([(50, 94), (64, 104), (58, 108), (46, 98)])
            c.poly([(78, 94), (64, 104), (70, 108), (82, 98)])
            self.put(Layer("collar", self.cloth, c.mask(), blur=2))

    def hair_front(self):
        lk = self.look
        st = lk.hair_style
        if st == "bald":
            # Блик на лысине.
            for y in range(30, 34):
                self.rgb[y, 50 - (y - 30):58 - (y - 30)] = self.skin[4]
            return
        c = Canvas()
        # шапка волос
        c.ellipse(62, 43, 28, 21)
        c.rect(0, 40, SIZE, SIZE, fill=0)
        fringe = [((42, 32), (39, 52), 11, -2), ((50, 30), (47, 55), 11, -3), ((58, 29), (57, 50), 10, -1),
                  ((66, 29), (67, 54), 11, 2), ((74, 31), (78, 51), 10, 3), ((82, 34), (87, 55), 9, 2)]
        if st in ("short", "messy"):
            locks = [(r, (t[0], t[1] - 4), w, b) for r, t, w, b in fringe]
            side = [((36, 44), (36, 62), 8, -1), ((88, 44), (89, 58), 6, 1)]
        elif st == "bob":
            locks = fringe
            side = [((36, 44), (32, 88), 12, -3), ((88, 44), (91, 84), 9, 3)]
        elif st == "long":
            locks = fringe
            side = [((36, 44), (30, 112), 12, -4), ((88, 44), (94, 108), 10, 4)]
        else:  # tails
            locks = fringe
            side = [((36, 44), (34, 72), 9, -2), ((88, 44), (90, 70), 8, 2)]
        for root, tip, w, bend in locks + side:
            c.lock(root, tip, w, bend)
        if st == "messy":
            for x, y in ((40, 26), (52, 21), (66, 21), (80, 26)):
                c.ellipse(x + 2, y + 4, 6, 5)
        hair = c.mask()
        self.put(Layer("hair", self.hair, hair, blur=6))
        # тонкие линии между прядями
        lines = Canvas()
        for root, tip, w, bend in locks:
            lines.lock(root, tip, w * 0.18, bend)
        lm = lines.mask() & hair & ~edge_of(hair)
        self.rgb[lm] = self.hair[1]
        # «нимб» — блестящая полоса на макушке
        yy, xx = np.mgrid[0:SIZE, 0:SIZE]
        ring = (np.abs(np.sqrt(((xx - 62) / 26) ** 2 + ((yy - 50) / 22) ** 2) - 0.78) < 0.045) & (yy < 36) & hair
        ring &= ((xx // 3) % 3 != 0)
        self.rgb[ring & ~lm] = self.hair[4]
        # тень от чёлки на лбу
        shadow = np.zeros_like(hair)
        shadow[2:, :] = hair[:-2, :]
        shadow &= self.face_mask & ~hair
        self.rgb[shadow] = self.skin[1]
        self.hair_mask = hair

    def hat(self):
        lk = self.look
        if lk.hat == "witch":
            hr = make_ramp(lk.hat_color)
            c = Canvas()
            c.ellipse(62, 30, 46, 9)
            self.put(Layer("brim", hr, c.mask(), blur=4))
            c = Canvas()
            c.poly([(40, 28), (84, 28), (76, 8), (98, -4), (66, 2)])
            self.put(Layer("cone", hr, c.mask(), blur=6))
            c = Canvas()
            c.poly([(42, 24), (82, 24), (83, 28), (41, 28)])
            self.put(Layer("band", make_ramp("#50d0a0"), c.mask(), blur=2))
        elif lk.hat == "straw":
            sr = make_ramp("#e0b860")
            c = Canvas()
            c.ellipse(62, 30, 44, 10)
            c.ellipse(62, 22, 22, 12)
            self.put(Layer("straw", sr, c.mask(), blur=5))
            yy, xx = np.mgrid[0:SIZE, 0:SIZE]
            weave = c.mask() & ((xx + yy) % 5 == 0)
            self.rgb[weave] = sr[1]

    # --- лицо по пикселям --------------------------------------------------
    def features(self):
        lk = self.look
        emo = lk.emotion
        lash = self.hair[0] if lk.hair_style != "bald" else hexrgb("#2a1a20")
        # Глаза: ближний крупнее, дальний уже.
        self.eye(54, 64, 14, 12, near=True)
        self.eye(80, 64, 10, 11, near=False)
        # Брови.
        tilt = {"angry": 5, "sad": -4, "surprised": -1}.get(emo, 0)
        lift = {"surprised": -3}.get(emo, 0)
        bw = max(1, int(round(2 * lk.brows)))
        for cx, w, side in ((54, 14, -1), (80, 10, 1)):
            for i in range(w):
                t = i / (w - 1)
                x = cx - w // 2 + i
                inner = t if side < 0 else 1 - t
                y = int(round(54 + lift - 2 * math.sin(t * math.pi) + tilt * (inner - 0.5)))
                for k in range(bw):
                    self.px(x, y + k, self.hair[1])
        # Нос: тень с правой стороны и кончик.
        self.px(self.mid, 68, self.skin[1])
        self.px(self.mid, 69, self.skin[1])
        self.px(self.mid + 1, 72, self.skin[1])
        self.px(self.mid, 73, self.skin[0])
        self.px(self.mid - 1, 72, self.skin[3])
        # Рот.
        my = 80 + (self.chin // 2)
        mx = self.mid - 3
        if emo == "happy":
            for i in range(-4, 6):
                self.px(mx + i, my + (1 if abs(i - 1) < 4 else 0), self.skin[0])
            for i in range(-2, 4):
                self.px(mx + i, my + 2, hexrgb("#a83a4a"))
            self.px(mx + 1, my + 3, hexrgb("#a83a4a"))
        elif emo == "surprised":
            for dy in range(0, 4):
                for dx in range(-1, 3):
                    edge = dy in (0, 3) or dx in (-1, 2)
                    self.px(mx + dx, my + dy - 1, self.skin[0] if edge else hexrgb("#7a2a3a"))
        elif emo in ("angry", "sad"):
            for i in range(-3, 5):
                self.px(mx + i, my + (1 if abs(i - 0.5) > 2 else 0), self.skin[0])
        else:
            for i in range(-2, 4):
                self.px(mx + i, my, self.skin[0])
            self.px(mx + 4, my - 1, self.skin[1])
        if lk.beard == "mustache":
            for i in range(-6, 8):
                self.px(mx + i, my - 2 - (1 if abs(i - 1) < 4 else 0), self.hair[1])
                self.px(mx + i, my - 1 - (1 if abs(i - 1) < 3 else 0), self.hair[2])
        # Румянец и веснушки.
        for bx in (46, 82):
            for i in range(4):
                if emo in ("happy", "neutral", "surprised"):
                    self.px(bx + i, 73 + (i % 2), mix(self.skin[2], (230, 110, 120), 0.45), only_face=True)
        if lk.freckles:
            for x, y in ((47, 70), (50, 71), (53, 70), (79, 70), (82, 71), (49, 73), (84, 73)):
                self.px(x, y, self.skin[1], only_face=True)
        if lk.scar:
            for i in range(7):
                self.px(84 - i // 2, 66 + i, mix(self.skin[1], (180, 90, 90), 0.5), only_face=True)
        if lk.age > 0:
            for i in range(3):
                self.px(44 + i, 67 + i, self.skin[1], only_face=True)
                self.px(self.mid - 7 - i // 2, 76 + i, self.skin[1], only_face=True)
        if emo == "sad":
            for i in range(4):
                self.px(48, 72 + i, hexrgb("#bfe4ff"))

    def eye(self, cx, cy, w, h, near: bool):
        lk = self.look
        emo = lk.emotion
        lash = self.hair[0] if lk.hair_style not in ("bald",) else hexrgb("#2a1a20")
        lash = mix(lash, (20, 10, 20), 0.5)
        iris = make_ramp(lk.eyes, "#101030")
        if emo == "happy":
            # закрытые от улыбки глаза — дуга
            for i in range(w):
                t = i / (w - 1)
                y = int(round(cy + 1 - 3 * math.sin(t * math.pi)))
                self.px(cx - w // 2 + i, y, lash)
                self.px(cx - w // 2 + i, y + 1, lash if 0.2 < t < 0.8 else self.skin[1])
            return
        open_k = {"surprised": 1.15, "angry": 0.8, "sad": 0.85}.get(emo, 1.0)
        if lk.eye_shape == "sleepy":
            open_k *= 0.7
        top = cy - h * 0.5 * open_k
        bot = cy + h * 0.45
        look_dx = 1.5
        for y in range(int(top) - 3, int(bot) + 3):
            for x in range(cx - w // 2 - 2, cx + w // 2 + 3):
                u = (x + 0.5 - cx) / (w / 2)
                if abs(u) > 1:
                    continue
                up = cy - (cy - top) * (1 - u * u) ** 0.35
                if lk.eye_shape == "sharp":
                    up += 2 * u * (1 if near else -1) * 0.5 + 1.5 * (u ** 2)
                # Злость опускает веко к переносице, грусть — к виску.
                inner = (u + 1) / 2 if near else (1 - u) / 2
                if emo == "angry":
                    up += 3.5 * inner
                elif emo == "sad":
                    up += 2.5 * (1 - inner)
                lo = cy + (bot - cy) * (1 - u * u) ** 0.7
                yc = y + 0.5
                if up <= yc <= lo:
                    # белок
                    col = hexrgb("#fff8f2") if yc > up + 1.5 else hexrgb("#d8c8d4")
                    # радужка
                    ix, iy = cx + look_dx, cy + 0.5
                    irx, iry = w * (0.36 if near else 0.4), h * 0.52 * (0.85 if emo == "surprised" else 1)
                    d = ((x + 0.5 - ix) / irx) ** 2 + ((yc - iy) / iry) ** 2
                    if d <= 1:
                        f = (yc - (iy - iry)) / (2 * iry)
                        col = iris[0] if d > 0.78 else iris[1] if f < 0.4 else iris[2] if f < 0.75 else iris[3]
                        if ((x + 0.5 - ix) / (irx * 0.4)) ** 2 + ((yc - iy) / (iry * 0.45)) ** 2 <= 1:
                            col = mix(iris[0], (0, 0, 0), 0.5)
                    self.px(x, y, col)
                elif up - 2.2 <= yc < up:
                    self.px(x, y, lash)
                elif lo < yc <= lo + 1 and -0.6 < u < 0.9:
                    self.px(x, y, mix(lash, self.skin[1], 0.5))
        # хвостик ресниц у внешнего угла
        ox = cx - w // 2 - 1 if near else cx + w // 2 + 1
        d = -1 if near else 1
        self.px(ox, int(top) + 1, lash)
        self.px(ox + d, int(top), lash)
        if lk.female:
            self.px(ox + d * 2, int(top) - 1, lash)
        # блики
        ix, iy = int(round(cx + look_dx - w * 0.15)), int(round(cy - h * 0.18))
        hl = (255, 255, 255)
        self.px(ix, iy, hl)
        self.px(ix + 1, iy, hl)
        self.px(ix, iy + 1, hl)
        if near:
            self.px(ix + 1, iy + 1, hl)
        self.px(int(cx + look_dx + w * 0.22), int(cy + h * 0.28), hl)

    def px(self, x, y, col, only_face=False):
        x, y = int(x), int(y)
        if 0 <= x < SIZE and 0 <= y < SIZE:
            if only_face and not self.face_mask[y, x]:
                return
            if only_face and hasattr(self, "hair_mask") and self.hair_mask[y, x]:
                return
            self.rgb[y, x] = col

    def frame(self) -> Image.Image:
        img = Image.fromarray(self.rgb, "RGB")
        return img


def render(look: Look) -> Image.Image:
    return Portrait(look).build()


CAST = {
    "kira": Look(name="Kira", skin="#f6d0b4", hair="#e8386a", hair_under="#8a5ad8", eyes="#6a6af0",
                 hair_style="bob", jaw="sharp", female=True, outfit="cloak", cloth="#a83a32",
                 trim="#e8c050", bg="#6a3a4a"),
    "lina": Look(name="Lina", skin="#f0c8a8", hair="#3a3a4c", eyes="#e09a30", hair_style="short",
                 jaw="sharp", eye_shape="sharp", brows=1.4, scar=True, female=True, outfit="armor",
                 cloth="#9aa2b0", bg="#4a5260"),
    "mora": Look(name="Mora", skin="#f4dccc", hair="#b49ae0", eyes="#40b070", hair_style="long",
                 jaw="soft", eye_shape="sleepy", female=True, outfit="robe", cloth="#3e2a52",
                 trim="#50d0a0", hat="witch", hat_color="#2e2040", bg="#3a2a4a", emotion="happy"),
    "yan": Look(name="Yan", skin="#f2c8a4", hair="#d8b860", eyes="#4a8ab0", hair_style="short",
                jaw="round", ears="elf", freckles=True, outfit="tunic", cloth="#6a8a4a",
                cloth2="#4a3a2a", bg="#4a6a4a"),
    "boris": Look(name="Boris", skin="#e8b090", hair="#7a4226", eyes="#4a3a2a", hair_style="messy",
                  jaw="square", brows=1.6, beard="full", age=0.6, outfit="apron", cloth="#ece4d2",
                  cloth2="#7a5236", bg="#6a5040", emotion="happy"),
    "gron": Look(name="Gron", skin="#c8946c", hair="#2a2a30", eyes="#7a3020", hair_style="bald",
                 jaw="square", brows=1.8, beard="full", age=0.8, outfit="apron", cloth="#5a4a3a",
                 cloth2="#3e2e22", bg="#5a4a40", emotion="angry"),
    "anya": Look(name="Anya", skin="#f8dcc8", hair="#9a9aa8", eyes="#e85060", hair_style="tails",
                 jaw="soft", female=True, outfit="apron", cloth="#f0eee8", cloth2="#7a5236",
                 bg="#5a4a52"),
}

EMOTIONS = ["neutral", "happy", "angry", "surprised", "sad"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Code-drawn close-up portraits.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_demo = sub.add_parser("demo", help="render the sample cast and emotions")
    p_demo.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "demo":
        out = args.out_dir
        out.mkdir(parents=True, exist_ok=True)
        for key, look in CAST.items():
            render(look).save(out / f"{key}.png")
        for emo in EMOTIONS:
            render(replace(CAST["kira"], emotion=emo)).save(out / f"kira_{emo}.png")
        (out / "cast.json").write_text(json.dumps(list(CAST), indent=1), encoding="utf-8")
        print(f"Saved {len(CAST)} portraits and {len(EMOTIONS)} emotions to {out}")


if __name__ == "__main__":
    main()

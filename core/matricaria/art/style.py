"""Стиль портретов «аниме пиксель-арт» (JRPG faceset, hi-bit).

Признаки стиля:
- тёмный контур вокруг силуэта, внутри — контур оттенком соседнего цвета (sel-out);
- плоская заливка, 2–3 тона на цвет, без дизеринга;
- ограниченная палитра, светлые пиксели бликов на волосах и в глазах;
- аниме-пропорции: большие глаза, маленький нос и рот.
"""

from __future__ import annotations

from dataclasses import dataclass

from matricaria.world.body import AgeStage, Body


@dataclass(frozen=True)
class PixelStyle:
    """Параметры пиксельной обработки портрета."""

    name: str
    grid: int          # размер портрета в «пикселях» по большей стороне
    colors: int        # сколько цветов в палитре, не считая контура
    outline: str       # цвет внешнего контура
    selout: bool       # внутренний контур оттенком соседнего цвета
    display_scale: int # во сколько раз увеличивать для экрана (без сглаживания)


# hi-bit: тонкие линии, больше деталей (как первый пример).
HIBIT = PixelStyle("hibit", grid=128, colors=24, outline="#1a1018", selout=True, display_scale=4)
# faceset: крупные пиксели, как портреты в диалогах JRPG.
FACESET = PixelStyle("faceset", grid=64, colors=16, outline="#000000", selout=False, display_scale=6)

STYLES = {style.name: style for style in (HIBIT, FACESET)}

EMOTIONS = ("neutral", "happy", "angry", "sad", "surprised", "embarrassed", "suspicious", "scared")

_EMOTION_TAGS = {
    "neutral": "calm expression",
    "happy": "smiling",
    "angry": "angry, furrowed brows",
    "sad": "sad, teary eyes",
    "surprised": "surprised, open mouth",
    "embarrassed": "blushing, embarrassed",
    "suspicious": "suspicious, narrowed eyes",
    "scared": "scared, wide eyes",
}

_BASE_PROMPT = [
    "pixel art", "anime style", "portrait", "bust shot", "head and shoulders",
    "black outline", "flat colors", "cel shading", "limited palette",
    "white background", "facing viewer",
]

# Портреты всегда без откровенного содержания; это не настраивается.
_NEGATIVE = [
    "nsfw", "nude", "naked", "cleavage", "suggestive", "lowres", "blurry",
    "smooth gradient", "dithering", "3d", "photo", "watermark", "text",
]


def portrait_prompt(appearance: dict, body: Body, emotion: str = "neutral") -> dict:
    """Собрать запрос для stable-diffusion.cpp.

    appearance — описание внешности из карточки, например
    {"hair": {"style": "long", "color": "silver"}, "eyes": "blue", "outfit": "black hoodie"}.
    """
    if emotion not in EMOTIONS:
        raise ValueError(f"неизвестная эмоция: {emotion}")
    parts = list(_BASE_PROMPT) + body.portrait_tags()
    hair = appearance.get("hair") or {}
    if hair:
        parts.append(" ".join(filter(None, [hair.get("color"), hair.get("style"), "hair"])))
    if appearance.get("eyes"):
        parts.append(f"{appearance['eyes']} eyes")
    if appearance.get("outfit"):
        parts.append(appearance["outfit"])
    parts.append(_EMOTION_TAGS[emotion])

    negative = list(_NEGATIVE)
    if body.stage is not AgeStage.ADULT:
        parts.append("fully clothed")
        negative += ["mature", "sexualized"]
    return {"prompt": ", ".join(parts), "negative_prompt": ", ".join(negative)}

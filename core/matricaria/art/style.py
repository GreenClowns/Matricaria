"""Стиль портретов «аниме пиксель-арт» (JRPG faceset, hi-bit).

Признаки стиля:
- тёмный контур вокруг силуэта, внутри — контур оттенком соседнего цвета (sel-out);
- плоская заливка, 2–3 тона на цвет, без дизеринга;
- ограниченная палитра, светлые пиксели бликов на волосах и в глазах;
- аниме-пропорции: большие глаза, маленький нос и рот.
"""

from __future__ import annotations

from dataclasses import dataclass

from matricaria.content import ContentSettings, ModelInfo, decide
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

_NEGATIVE = ["lowres", "blurry", "smooth gradient", "dithering", "3d", "photo", "watermark", "text"]
# Добавляется, когда откровенное содержание недоступно (см. matricaria.content).
_NEGATIVE_SAFE = ["nsfw", "nude", "naked", "suggestive"]
# Добавляется всегда, когда откровенное содержание включено: персонаж должен выглядеть взрослым.
_NEGATIVE_EXPLICIT = ["child", "loli", "shota", "teen", "young-looking", "petite childlike body"]


def portrait_prompt(appearance: dict, body: Body, emotion: str = "neutral",
                    settings: ContentSettings | None = None, model: ModelInfo | None = None,
                    nude: bool = False) -> dict:
    """Собрать запрос для stable-diffusion.cpp.

    nude — просьба нарисовать без одежды. Выполняется, только если
    matricaria.content.decide разрешает откровенное содержание; иначе игнорируется.

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

    explicit = decide(settings, model, [body]).explicit
    negative = list(_NEGATIVE)
    if explicit:
        parts += ["nsfw", "nude"] if nude else []
        parts += ["adult face", "mature adult body", "adult proportions"]
        negative += _NEGATIVE_EXPLICIT
    else:
        parts.append("fully clothed")
        negative += _NEGATIVE_SAFE
        if body.stage is not AgeStage.ADULT:
            negative += ["mature", "sexualized", "cleavage"]
    return {"prompt": ", ".join(parts), "negative_prompt": ", ".join(negative), "explicit": explicit}

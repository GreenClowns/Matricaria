"""Тело персонажа: возраст, рост, вес, части тела и то, как они видны на экране.

Тело меняется только через `apply_change`: так все изменения проходят
одни и те же проверки, а валидатор может отклонить недопустимые.
Это песочница: верхних пределов у роста, веса и частей тела нет.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum

ADULT_AGE = 18

# Возраст за одно действие растёт не больше чем на год; долгое время идёт через симуляцию.
# Это не предел тела, а защита возрастных правил: ребёнка нельзя мгновенно «сделать взрослым».
MAX_AGE_STEP = 1

# Части тела. Размер — уровень: 0 — обычный, 1, 2, 3… — больше, без предела; −1…−3 — меньше.
PARTS = {
    "chest": "breasts",
    "hips": "hips",
    "butt": "butt",
    "belly": "belly",
    "thighs": "thighs",
    "muscles": "muscles",
    "arms": "arms",
    "legs": "legs",
    "hands": "hands",
    "feet": "feet",
    "hair": "hair",
}
MIN_PART_LEVEL = -3
# У персонажей младше 18 лет может меняться только длина волос.
MINOR_PARTS = frozenset({"hair"})

# Рост взрослого, при котором спрайт рисуется без масштаба.
REFERENCE_HEIGHT_CM = 170.0
SPRITE_SCALE_RANGE = (0.25, 6.0)


@dataclass(frozen=True)
class BodyRules:
    """Насколько тело может измениться за одно действие. Настраивается для мира.

    None — без ограничения. По умолчанию ограничения включены: они защищают от того,
    что ИИ одной репликой «выдумает» персонажу километровый рост.
    """

    max_step_factor: float | None = 2.0
    max_part_step: float | None = 2.0


DEFAULT_RULES = BodyRules()
UNLIMITED = BodyRules(max_step_factor=None, max_part_step=None)


def rules_for(source: str, ai_limits: bool = True) -> BodyRules:
    """Ограничения для изменения из этого источника.

    Игрок и сценарий меняют тело без ограничений. Изменения, которые предложил ИИ,
    идут шагами, пока в настройках мира не выключено ai_limits.
    """
    return DEFAULT_RULES if source == "ai" and ai_limits else UNLIMITED


class BodyChangeError(ValueError):
    """Изменение тела не прошло проверку."""


class AgeStage(str, Enum):
    CHILD = "child"
    TEEN = "teen"
    ADULT = "adult"

    @classmethod
    def from_age(cls, age_years: int) -> AgeStage:
        if age_years < 13:
            return cls.CHILD
        if age_years < ADULT_AGE:
            return cls.TEEN
        return cls.ADULT


class Build(str, Enum):
    """Телосложение по индексу массы тела. Определяет вариант спрайта и портрета."""

    THIN = "thin"
    SLIM = "slim"
    AVERAGE = "average"
    PLUMP = "plump"
    HEAVY = "heavy"


class SizeClass(str, Enum):
    """Размер относительно обычного человека. Godot по нему решает, как показать персонажа."""

    MICRO = "micro"        # меньше 10 см: помещается на ладони
    TINY = "tiny"          # 10–60 см: фея, уменьшенный человек
    SMALL = "small"        # 60–140 см
    NORMAL = "normal"      # 140–220 см
    TALL = "tall"          # 220–400 см: великан, ещё проходит в дверь с трудом
    GIANT = "giant"        # 4–12 м: выше домов
    COLOSSAL = "colossal"  # 12–100 м
    TITAN = "titan"        # 100 м – 10 км: выше небоскрёбов
    WORLD = "world"        # больше 10 км: выше гор и облаков


_SIZE_LIMITS = [(10, SizeClass.MICRO), (60, SizeClass.TINY), (140, SizeClass.SMALL), (220, SizeClass.NORMAL),
                (400, SizeClass.TALL), (1200, SizeClass.GIANT),
                (10_000, SizeClass.COLOSSAL), (1_000_000, SizeClass.TITAN)]

# Как показывать персонажа в сцене диалога.
_FRAMING = {
    SizeClass.MICRO: "closeup_on_hand",  # крупный план: персонаж на ладони или на столе
    SizeClass.TINY: "small_on_ground",
    SizeClass.SMALL: "full_body",
    SizeClass.NORMAL: "full_body",
    SizeClass.TALL: "full_body",
    SizeClass.GIANT: "cropped_upper",    # виден до пояса, смотрит сверху
    SizeClass.COLOSSAL: "legs_only",     # в кадре только ноги, лицо — отдельной вставкой
    SizeClass.TITAN: "skyline",          # силуэт над городом, лицо — отдельной вставкой
    SizeClass.WORLD: "from_space",       # вид издалека: над горами и облаками
}

# В этих границах роста ИМТ считается как обычно. За ними вес пересчитывается
# по объёму (куб роста), чтобы у гигантов и фей сложение определялось честно.
NORMAL_BMI_HEIGHT_CM = (140.0, 220.0)

# Верхняя граница ИМТ для каждого телосложения (взрослые).
_BUILD_BMI = [(17.0, Build.THIN), (20.0, Build.SLIM), (25.0, Build.AVERAGE), (31.0, Build.PLUMP)]

# Ширина спрайта относительно обычной для каждого телосложения.
_BUILD_WIDTH = {
    Build.THIN: 0.88,
    Build.SLIM: 0.94,
    Build.AVERAGE: 1.0,
    Build.PLUMP: 1.12,
    Build.HEAVY: 1.25,
}

# Слова для уровней частей тела. Теги заметны генератору: большая грудь видна и в одежде.
_SMALLER = {-1: "small", -2: "very small", -3: "tiny"}
_BIGGER = ["large", "very large", "huge", "gigantic"]
_HAIR = {-3: "very short hair", -2: "short hair", -1: "short hair",
         1: "long hair", 2: "very long hair", 3: "floor-length hair"}
_MUSCLES = {-3: "frail", -2: "skinny arms", -1: "soft body",
            1: "toned", 2: "muscular", 3: "very muscular", 4: "huge muscles, bodybuilder"}


def _part_tags(part: str, level: float) -> list[str]:
    level = math.floor(level) if level > 0 else math.ceil(level)
    if level == 0:
        return []
    noun = PARTS[part]
    if part == "hair":
        return [_HAIR.get(level, "absurdly long hair, hair longer than body")]
    if part == "muscles":
        return [_MUSCLES.get(level, "absurdly huge muscles")]
    if level < 0:
        return [f"{_SMALLER[level]} {noun}"]
    if level <= len(_BIGGER):
        tags = [f"{_BIGGER[level - 1]} {noun}"]
    elif level <= 7:
        tags = [f"gigantic {noun}", f"absurdly large {noun}"]
    elif level <= 11:
        tags = [f"gigantic {noun}", f"{noun} larger than body"]
    else:
        tags = [f"gigantic {noun}", f"{noun} larger than buildings"]
    if part in ("chest", "hips", "butt", "thighs") and level >= 2:
        tags.append("curvy")
    return tags


@dataclass(frozen=True)
class Body:
    age_years: int
    height_cm: float
    weight_kg: float
    parts: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.age_years < 0:
            raise BodyChangeError("возраст не может быть отрицательным")
        _check_positive("рост", self.height_cm)
        _check_positive("вес", self.weight_kg)
        for part, level in self.parts.items():
            if part not in PARTS:
                raise BodyChangeError(f"неизвестная часть тела: {part}")
            if not math.isfinite(level) or level < MIN_PART_LEVEL:
                raise BodyChangeError(f"размер «{part}» не может быть меньше {MIN_PART_LEVEL}")
            if self.is_minor and level and part not in MINOR_PARTS:
                raise BodyChangeError(f"у персонажей младше 18 лет «{part}» не меняется")

    def part(self, name: str) -> float:
        return self.parts.get(name, 0.0)

    @property
    def stage(self) -> AgeStage:
        return AgeStage.from_age(self.age_years)

    @property
    def is_minor(self) -> bool:
        return self.age_years < ADULT_AGE

    @property
    def bmi(self) -> float:
        return _bmi(self.height_cm, self.weight_kg)

    @property
    def build(self) -> Build:
        bmi = self.bmi
        # У детей ИМТ ниже, поэтому пороги сдвигаются вниз.
        shift = {AgeStage.CHILD: -3.0, AgeStage.TEEN: -1.5, AgeStage.ADULT: 0.0}[self.stage]
        for limit, build in _BUILD_BMI:
            if bmi < limit + shift:
                return build
        return Build.HEAVY

    @property
    def size_class(self) -> SizeClass:
        for limit, size in _SIZE_LIMITS:
            if self.height_cm < limit:
                return size
        return SizeClass.WORLD

    def sprite_params(self) -> dict:
        """Что нужно Godot, чтобы нарисовать персонажа на карте и в сцене."""
        scale_y = _clamp(self.height_cm / REFERENCE_HEIGHT_CM, *SPRITE_SCALE_RANGE)
        return {
            "lpc_body": "child" if self.stage is AgeStage.CHILD else
                        "teen" if self.stage is AgeStage.TEEN else "adult",
            "build": self.build.value,
            "size": self.size_class.value,
            "framing": _FRAMING[self.size_class],
            "scale_x": round(_BUILD_WIDTH[self.build] * scale_y, 3),
            "scale_y": round(scale_y, 3),
        }

    def portrait_tags(self) -> list[str]:
        """Теги тела для запроса генерации портрета."""
        tags = {
            AgeStage.CHILD: ["child", "young kid"],
            AgeStage.TEEN: ["teenager"],
            AgeStage.ADULT: ["adult"],
        }[self.stage]
        tags += {
            Build.THIN: ["very thin", "gaunt face"],
            Build.SLIM: ["slim"],
            Build.AVERAGE: [],
            Build.PLUMP: ["chubby", "round face"],
            Build.HEAVY: ["fat", "very round face", "double chin"],
        }[self.build]
        tags += {
            SizeClass.MICRO: ["miniature person", "standing on a hand", "size difference"],
            SizeClass.TINY: ["tiny person", "fairy-sized", "size difference"],
            SizeClass.TALL: ["very tall", "towering"],
            SizeClass.GIANT: ["giant", "towering", "low angle"],
            SizeClass.COLOSSAL: ["colossal giant", "low angle", "clouds behind head"],
            SizeClass.TITAN: ["titan", "towering over city", "skyscrapers",
                              "extreme low angle"],
            SizeClass.WORLD: ["planet-sized giant", "above the clouds", "mountains at feet",
                              "view from far away"],
        }.get(self.size_class, [])
        for part in PARTS:
            tags += _part_tags(part, self.part(part))
        return tags

    def visible_state(self) -> tuple:
        """То, что видно на портрете. Если изменилось — портрет рисуется заново."""
        parts = tuple(sorted((p, int(v)) for p, v in self.parts.items() if int(v)))
        return self.build, self.stage, self.size_class, parts

    def to_dict(self) -> dict:
        return {"age_years": self.age_years, "height_cm": self.height_cm,
                "weight_kg": self.weight_kg, "parts": dict(self.parts)}

    @classmethod
    def from_dict(cls, data: dict) -> Body:
        parts = {k: float(v) for k, v in data.get("parts", {}).items()}
        if data.get("chest"):
            # Старый формат: грудь 1–5, где 2 — средняя.
            parts.setdefault("chest", float(data["chest"]) - 2)
        return cls(int(data["age_years"]), float(data["height_cm"]), float(data["weight_kg"]),
                   parts)


@dataclass(frozen=True)
class BodyChange:
    """Изменение тела. Пустые поля не меняются.

    keep_build: при изменении роста вес меняется вместе с ним (пропорционально объёму),
    чтобы персонаж оставался таким же по сложению, просто больше или меньше.
    """

    height_cm: float = 0.0
    weight_kg: float = 0.0
    age_years: int = 0
    parts: dict[str, float] = field(default_factory=dict)
    keep_build: bool = True

    @property
    def fields(self) -> set[str]:
        names = {name for name in ("height_cm", "weight_kg", "age_years") if getattr(self, name)}
        return names | {f"parts.{part}" for part, delta in self.parts.items() if delta}


def apply_change(body: Body, change: BodyChange, rules: BodyRules = DEFAULT_RULES) -> Body:
    """Вернуть новое тело с изменением. Старое тело не меняется."""
    if change.age_years < 0:
        raise BodyChangeError("возраст нельзя уменьшить: время идёт только вперёд")
    if change.age_years > MAX_AGE_STEP:
        raise BodyChangeError(f"возраст за раз растёт не больше чем на {MAX_AGE_STEP} год")

    try:
        height = body.height_cm + change.height_cm
        _check_step("рост", body.height_cm, height, rules)
        weight = body.weight_kg
        if change.height_cm and change.keep_build:
            weight = _weight_for_bmi(height, body.bmi)
        before_explicit = weight
        weight += change.weight_kg
        _check_step("вес", before_explicit, weight, rules)
    except OverflowError:
        raise BodyChangeError("число слишком большое для компьютера") from None

    parts = dict(body.parts)
    for part, delta in change.parts.items():
        if rules.max_part_step is not None and abs(delta) > rules.max_part_step:
            raise BodyChangeError(
                f"«{part}» за раз меняется не больше чем на {rules.max_part_step:g} уровня")
        parts[part] = parts.get(part, 0.0) + delta

    return replace(
        body,
        age_years=body.age_years + change.age_years,
        height_cm=_round(height),
        weight_kg=_round(weight),
        parts=parts,
    )


def portrait_is_stale(old: Body, new: Body) -> bool:
    """Нужно ли перегенерировать портрет: изменилось то, что видно на портрете."""
    return old.visible_state() != new.visible_state()


def _round(value: float) -> float:
    """Округлить до десятых, а очень маленькие и очень большие значения — до 6 значащих цифр."""
    return round(value, 1) if 10 <= value < 1e9 else float(f"{value:.6g}")


def _bmi(height_cm: float, weight_kg: float) -> float:
    ref = _clamp(height_cm, *NORMAL_BMI_HEIGHT_CM)
    normal_weight = weight_kg / (height_cm / ref) ** 3
    return normal_weight / (ref / 100) ** 2


def _weight_for_bmi(height_cm: float, bmi: float) -> float:
    ref = _clamp(height_cm, *NORMAL_BMI_HEIGHT_CM)
    return bmi * (ref / 100) ** 2 * (height_cm / ref) ** 3


def _check_step(label: str, old: float, new: float, rules: BodyRules) -> None:
    _check_positive(label, new)
    factor = rules.max_step_factor
    if factor is not None and not 1 / factor <= new / old <= factor:
        raise BodyChangeError(f"{label} за раз меняется не больше чем в {factor:g} раза")


def _check_positive(label: str, value: float) -> None:
    if not math.isfinite(value):
        raise BodyChangeError(f"{label}: число слишком большое для компьютера")
    if value <= 0:
        raise BodyChangeError(f"{label} должен быть больше нуля")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

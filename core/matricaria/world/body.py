"""Тело персонажа: возраст, рост, вес, пропорции и то, как они видны на экране.

Тело меняется только через `apply_change`: так все изменения проходят
одни и те же проверки, а валидатор может отклонить недопустимые.
Поддерживаются и магические превращения: зелье роста, уменьшение до феи.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

ADULT_AGE = 18

# Допустимые границы для любого персонажа: от 1 см до 1 км.
HEIGHT_RANGE_CM = (1.0, 100_000.0)
WEIGHT_RANGE_KG = (1e-6, 1e11)

# Во сколько раз рост или вес может измениться за одно действие.
# Большие превращения идут несколькими шагами, и каждый попадает в журнал.
MAX_STEP_FACTOR = 2.0
# Возраст за одно действие растёт не больше чем на год; долгое время идёт через симуляцию.
MAX_AGE_STEP = 1

# Размер груди: 0 — не описывается, 1–5 — от маленькой до огромной. Только для взрослых.
CHEST_RANGE = (0, 5)
MAX_CHEST_STEP = 2

# Рост взрослого, при котором спрайт рисуется без масштаба.
REFERENCE_HEIGHT_CM = 170.0
SPRITE_SCALE_RANGE = (0.25, 6.0)


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
    TITAN = "titan"        # больше 100 м: выше небоскрёбов


_SIZE_LIMITS = [(10, SizeClass.MICRO), (60, SizeClass.TINY), (140, SizeClass.SMALL), (220, SizeClass.NORMAL),
                (400, SizeClass.TALL), (1200, SizeClass.GIANT),
                (10_000, SizeClass.COLOSSAL)]

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

# Теги заметны генератору: большая грудь видна на портрете и в одежде.
_CHEST_TAGS = {1: "small breasts", 2: "medium breasts", 3: "large breasts",
               4: "very large breasts, curvy", 5: "huge breasts, gigantic breasts, curvy"}


@dataclass(frozen=True)
class Body:
    age_years: int
    height_cm: float
    weight_kg: float
    chest: int = 0

    def __post_init__(self) -> None:
        if self.age_years < 0:
            raise BodyChangeError("возраст не может быть отрицательным")
        _check_range("рост", self.height_cm, HEIGHT_RANGE_CM)
        _check_range("вес", self.weight_kg, WEIGHT_RANGE_KG)
        _check_range("размер груди", self.chest, CHEST_RANGE)
        if self.is_minor and self.chest:
            raise BodyChangeError("у персонажей младше 18 лет размер груди не задаётся")

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
        return SizeClass.TITAN

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
        }.get(self.size_class, [])
        if self.chest:
            tags.append(_CHEST_TAGS[self.chest])
        return tags

    def to_dict(self) -> dict:
        return {"age_years": self.age_years, "height_cm": self.height_cm,
                "weight_kg": self.weight_kg, "chest": self.chest}

    @classmethod
    def from_dict(cls, data: dict) -> Body:
        return cls(int(data["age_years"]), float(data["height_cm"]), float(data["weight_kg"]),
                   int(data.get("chest", 0)))


@dataclass(frozen=True)
class BodyChange:
    """Изменение тела. Пустые поля не меняются.

    keep_build: при изменении роста вес меняется вместе с ним (пропорционально объёму),
    чтобы персонаж оставался таким же по сложению, просто больше или меньше.
    """

    height_cm: float = 0.0
    weight_kg: float = 0.0
    age_years: int = 0
    chest: int = 0
    keep_build: bool = True

    @property
    def fields(self) -> set[str]:
        return {name for name in ("height_cm", "weight_kg", "age_years", "chest")
                if getattr(self, name)}


def apply_change(body: Body, change: BodyChange) -> Body:
    """Вернуть новое тело с изменением. Старое тело не меняется."""
    if change.age_years < 0:
        raise BodyChangeError("возраст нельзя уменьшить: время идёт только вперёд")
    if change.age_years > MAX_AGE_STEP:
        raise BodyChangeError(f"возраст за раз растёт не больше чем на {MAX_AGE_STEP} год")
    if abs(change.chest) > MAX_CHEST_STEP:
        raise BodyChangeError(f"размер груди за раз меняется не больше чем на {MAX_CHEST_STEP}")

    height = body.height_cm + change.height_cm
    _check_step("рост", body.height_cm, height)
    weight = body.weight_kg
    if change.height_cm and change.keep_build:
        weight = _weight_for_bmi(height, body.bmi)
    before_explicit = weight
    weight += change.weight_kg
    _check_step("вес", before_explicit, weight)

    return replace(
        body,
        age_years=body.age_years + change.age_years,
        height_cm=_round(height),
        weight_kg=_round(weight),
        chest=body.chest + change.chest,
    )


def portrait_is_stale(old: Body, new: Body) -> bool:
    """Нужно ли перегенерировать портрет: изменилось то, что видно на портрете."""
    return (old.build, old.stage, old.size_class, old.chest) != \
           (new.build, new.stage, new.size_class, new.chest)


def _round(value: float) -> float:
    """Округлить до десятых, а маленькие значения — до 4 значащих цифр."""
    return round(value, 1) if value >= 10 else float(f"{value:.4g}")


def _bmi(height_cm: float, weight_kg: float) -> float:
    ref = _clamp(height_cm, *NORMAL_BMI_HEIGHT_CM)
    normal_weight = weight_kg / (height_cm / ref) ** 3
    return normal_weight / (ref / 100) ** 2


def _weight_for_bmi(height_cm: float, bmi: float) -> float:
    ref = _clamp(height_cm, *NORMAL_BMI_HEIGHT_CM)
    return bmi * (ref / 100) ** 2 * (height_cm / ref) ** 3


def _check_step(label: str, old: float, new: float) -> None:
    if new <= 0 or not 1 / MAX_STEP_FACTOR <= new / old <= MAX_STEP_FACTOR:
        raise BodyChangeError(f"{label} за раз меняется не больше чем в {MAX_STEP_FACTOR:g} раза")


def _check_range(label: str, value: float, bounds: tuple[float, float]) -> None:
    low, high = bounds
    if not low <= value <= high:
        raise BodyChangeError(f"{label} {value:g} вне допустимых границ {low:g}–{high:g}")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

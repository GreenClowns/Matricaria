"""Тело персонажа: возраст, рост, вес и то, как они видны на экране.

Тело меняется только через `apply_change`: так все изменения проходят
одни и те же проверки, а валидатор может отклонить недопустимые.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

ADULT_AGE = 18

# Допустимые границы для любого персонажа.
HEIGHT_RANGE_CM = (50.0, 250.0)
WEIGHT_RANGE_KG = (3.0, 300.0)

# Сколько можно изменить за одно действие.
MAX_HEIGHT_STEP_CM = 30.0
MAX_WEIGHT_STEP_KG = 40.0

# Рост взрослого, при котором спрайт рисуется без масштаба.
REFERENCE_HEIGHT_CM = 170.0
SPRITE_SCALE_RANGE = (0.5, 1.3)


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


@dataclass(frozen=True)
class Body:
    age_years: int
    height_cm: float
    weight_kg: float

    def __post_init__(self) -> None:
        if self.age_years < 0:
            raise BodyChangeError("возраст не может быть отрицательным")
        _check_range("рост", self.height_cm, HEIGHT_RANGE_CM)
        _check_range("вес", self.weight_kg, WEIGHT_RANGE_KG)

    @property
    def stage(self) -> AgeStage:
        return AgeStage.from_age(self.age_years)

    @property
    def is_minor(self) -> bool:
        return self.age_years < ADULT_AGE

    @property
    def bmi(self) -> float:
        meters = self.height_cm / 100
        return self.weight_kg / (meters * meters)

    @property
    def build(self) -> Build:
        bmi = self.bmi
        # У детей ИМТ ниже, поэтому пороги сдвигаются вниз.
        shift = {AgeStage.CHILD: -3.0, AgeStage.TEEN: -1.5, AgeStage.ADULT: 0.0}[self.stage]
        for limit, build in _BUILD_BMI:
            if bmi < limit + shift:
                return build
        return Build.HEAVY

    def sprite_params(self) -> dict:
        """Что нужно Godot, чтобы нарисовать персонажа на карте."""
        scale_y = _clamp(self.height_cm / REFERENCE_HEIGHT_CM, *SPRITE_SCALE_RANGE)
        return {
            "lpc_body": "child" if self.stage is AgeStage.CHILD else
                        "teen" if self.stage is AgeStage.TEEN else "adult",
            "build": self.build.value,
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
        build_tags = {
            Build.THIN: ["very thin", "gaunt face"],
            Build.SLIM: ["slim"],
            Build.AVERAGE: [],
            Build.PLUMP: ["chubby", "round face"],
            Build.HEAVY: ["fat", "very round face", "double chin"],
        }[self.build]
        return tags + build_tags

    def to_dict(self) -> dict:
        return {"age_years": self.age_years, "height_cm": self.height_cm,
                "weight_kg": self.weight_kg}

    @classmethod
    def from_dict(cls, data: dict) -> Body:
        return cls(int(data["age_years"]), float(data["height_cm"]), float(data["weight_kg"]))


@dataclass(frozen=True)
class BodyChange:
    """Изменение тела. Пустые поля не меняются."""

    height_cm: float = 0.0
    weight_kg: float = 0.0
    age_years: int = 0

    @property
    def fields(self) -> set[str]:
        return {name for name in ("height_cm", "weight_kg", "age_years") if getattr(self, name)}


def apply_change(body: Body, change: BodyChange) -> Body:
    """Вернуть новое тело с изменением. Старое тело не меняется."""
    if abs(change.height_cm) > MAX_HEIGHT_STEP_CM:
        raise BodyChangeError(f"рост за раз меняется не больше чем на {MAX_HEIGHT_STEP_CM:g} см")
    if abs(change.weight_kg) > MAX_WEIGHT_STEP_KG:
        raise BodyChangeError(f"вес за раз меняется не больше чем на {MAX_WEIGHT_STEP_KG:g} кг")
    if change.age_years < 0:
        raise BodyChangeError("возраст нельзя уменьшить: время идёт только вперёд")
    return replace(
        body,
        age_years=body.age_years + change.age_years,
        height_cm=round(body.height_cm + change.height_cm, 1),
        weight_kg=round(body.weight_kg + change.weight_kg, 1),
    )


def portrait_is_stale(old: Body, new: Body) -> bool:
    """Нужно ли перегенерировать портрет: сменилось телосложение или возраст."""
    return old.build is not new.build or old.stage is not new.stage


def _check_range(label: str, value: float, bounds: tuple[float, float]) -> None:
    low, high = bounds
    if not low <= value <= high:
        raise BodyChangeError(f"{label} {value:g} вне допустимых границ {low:g}–{high:g}")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

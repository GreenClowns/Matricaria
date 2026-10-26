"""Уровень содержания: обычный или откровенный (18+).

Откровенное содержание включается, только когда выполнены все условия:
1. пользователь сам включил его в настройках (по умолчанию выключено);
2. пользователь подтвердил, что ему есть 18 лет;
3. выбранная модель это допускает (её лицензия и описание);
4. все участники — взрослые (18 лет и старше).

Решает возраст, а не рост: взрослый низкого роста — такой же взрослый.
Взрослый персонаж любого роста всегда изображается со взрослым телом и лицом
(см. art/style.py), а детского тела у взрослых в игре не бывает.

Для персонажей младше 18 лет откровенного содержания нет никогда:
это правило не отключается ни настройкой, ни моделью.
"""

from __future__ import annotations

from dataclasses import dataclass

from matricaria.world.body import Body


@dataclass(frozen=True)
class ContentSettings:
    """Настройки пользователя."""

    adult_content: bool = False
    user_confirmed_adult: bool = False


@dataclass(frozen=True)
class ModelInfo:
    """Сведения о модели из менеджера моделей или из настроек API."""

    name: str
    allows_explicit: bool = False


@dataclass(frozen=True)
class ContentDecision:
    explicit: bool
    reason: str


def decide(settings: ContentSettings | None, model: ModelInfo | None,
           participants: list[Body]) -> ContentDecision:
    """Можно ли откровенное содержание для этой сцены или портрета."""
    if any(body.is_minor for body in participants):
        return ContentDecision(False, "в сцене есть персонаж младше 18 лет")
    if settings is None or not settings.adult_content:
        return ContentDecision(False, "откровенное содержание выключено в настройках")
    if not settings.user_confirmed_adult:
        return ContentDecision(False, "пользователь не подтвердил, что ему есть 18 лет")
    if model is None or not model.allows_explicit:
        return ContentDecision(False, "выбранная модель не допускает откровенное содержание")
    if not participants:
        return ContentDecision(False, "нет участников")
    return ContentDecision(True, "все условия выполнены")

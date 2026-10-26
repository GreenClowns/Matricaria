"""Возрастные правила: что можно делать с персонажами младше 18 лет.

Для несовершеннолетних действует белый список. Любое действие, которого
в нём нет (в том числе добавленное позже), для них запрещено автоматически.
"""

from __future__ import annotations

from dataclasses import dataclass

from matricaria.world.body import Body, BodyChange

# Обычные действия из docs/06-ai-formats.md, допустимые с детьми и подростками:
# разговор, отношения, память, передача вещей и денег, перемещение.
MINOR_ALLOWED_ACTIONS = frozenset({
    "relation_change",
    "remember",
    "call",
    "move_to",
    "give_item",
    "take_item",
    "pay",
    "body_change",
})

# Какие поля тела можно менять у несовершеннолетних.
MINOR_BODY_FIELDS = frozenset({"height_cm", "age_years"})


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    reason: str = ""


OK = PolicyResult(True)


def check_action(action_type: str, participants: list[Body],
                 change: BodyChange | None = None) -> PolicyResult:
    """Проверить действие, в котором участвуют персонажи с этими телами.

    participants — тела всех, кого действие касается: и того, кто действует,
    и того, на кого оно направлено.
    """
    if not any(body.is_minor for body in participants):
        return OK
    if action_type not in MINOR_ALLOWED_ACTIONS:
        return PolicyResult(False, f"действие «{action_type}» недоступно с персонажами младше 18 лет")
    if action_type == "body_change":
        if change is None:
            return PolicyResult(False, "у body_change нет данных об изменении")
        extra = change.fields - MINOR_BODY_FIELDS
        if extra:
            names = ", ".join(sorted(extra))
            return PolicyResult(False, f"у персонажей младше 18 лет можно менять только рост и возраст, не {names}")
    return OK

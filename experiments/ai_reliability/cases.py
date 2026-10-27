"""Загрузка тестовых реплик из cases.toml и грубая проверка ответа по правилам."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / "cases.toml"

GROUPS = {
    "facts": "Знание фактов",
    "dead": "Ловушки про мёртвых",
    "knowledge": "Чужие знания",
    "impossible": "Невозможные действия",
    "fabrication": "Выдумки",
    "lie": "Ложь персонажа",
    "style": "Характер и стиль",
}


@dataclass
class Case:
    id: str
    group: str
    npc: str
    turns: list[str]
    expect: str
    must_any: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)

    def check_rules(self, text: str) -> tuple[bool | None, str]:
        """Грубая проверка по ключевым словам.

        Возвращает (True/False, пояснение) или (None, ...), если правил нет.
        """
        if not self.must_any and not self.must_not:
            return None, "правил нет"
        low = text.lower()
        if self.must_any and not any(w in low for w in self.must_any):
            return False, f"нет ни одного из {self.must_any}"
        found = [w for w in self.must_not if w in low]
        if found:
            return False, f"есть запрещённое {found}"
        return True, "правила выполнены"


def load_cases(path: Path | str = DEFAULT_CASES) -> list[Case]:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    cases = []
    for raw in data["cases"]:
        turns = raw.get("turns") or [raw["say"]]
        cases.append(
            Case(
                id=raw["id"],
                group=raw["group"],
                npc=raw["npc"],
                turns=list(turns),
                expect=raw["expect"],
                must_any=[w.lower() for w in raw.get("must_any", [])],
                must_not=[w.lower() for w in raw.get("must_not", [])],
            )
        )
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("в cases.toml повторяются id")
    for c in cases:
        if c.group not in GROUPS:
            raise ValueError(f"{c.id}: неизвестная группа {c.group}")
    return cases

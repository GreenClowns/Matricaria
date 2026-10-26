"""Загрузка тестового мира из world.toml.

Мир здесь только читается: в эксперименте ядра ещё нет,
поэтому это упрощённая «база правды» для валидатора.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_WORLD = HERE / "world.toml"


@dataclass
class Character:
    id: str
    name: str
    role: str
    personality: str
    speech: str
    location: str
    alive: bool
    money: int
    abilities: list[str] = field(default_factory=list)


@dataclass
class Fact:
    id: str
    subject: str
    predicate: str
    object: str
    text: str
    status: str
    known_by: list[str]
    told_by: str | None = None

    def known_to(self, character_id: str) -> bool:
        return "all" in self.known_by or character_id in self.known_by


@dataclass
class World:
    name: str
    setting: str
    rules: list[str]
    player_id: str
    locations: dict[str, str]
    characters: dict[str, Character]
    items: dict[str, dict]
    facts: list[Fact]

    def facts_for(self, character_id: str) -> list[Fact]:
        """Факты, которые знает персонаж (включая его ложь и убеждения)."""
        return [f for f in self.facts if f.known_to(character_id)]

    def items_of(self, character_id: str) -> list[str]:
        return [iid for iid, it in self.items.items() if it["owner"] == character_id]

    def truth(self) -> list[Fact]:
        return [f for f in self.facts if f.status == "truth"]

    def canon(self, subject: str, predicate: str) -> Fact | None:
        """Истинный факт о (subject, predicate), если он есть в базе."""
        for f in self.facts:
            if f.status == "truth" and f.subject == subject and f.predicate == predicate:
                return f
        return None


def load_world(path: Path | str = DEFAULT_WORLD) -> World:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    characters = {
        c["id"]: Character(
            id=c["id"],
            name=c["name"],
            role=c["role"],
            personality=c.get("personality", ""),
            speech=c.get("speech", ""),
            location=c["location"],
            alive=c["alive"],
            money=c.get("money", 0),
            abilities=list(c.get("abilities", [])),
        )
        for c in data["characters"]
    }
    facts = [
        Fact(
            id=f["id"],
            subject=f["subject"],
            predicate=f["predicate"],
            object=str(f["object"]),
            text=f["text"],
            status=f["status"],
            known_by=list(f["known_by"]),
            told_by=f.get("told_by"),
        )
        for f in data["facts"]
    ]
    return World(
        name=data["world"]["name"],
        setting=data["world"]["setting"],
        rules=list(data["world"].get("rules", [])),
        player_id=data["player"]["id"],
        locations={loc["id"]: loc["name"] for loc in data["locations"]},
        characters=characters,
        items={it["id"]: dict(it) for it in data["items"]},
        facts=facts,
    )

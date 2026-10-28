"""Записи мира для чтения: персонаж, место, предмет, факт, событие…

Это только «фотографии» строк базы. Менять мир через них нельзя,
все изменения идут через методы `World`.
"""

import json
import sqlite3
from dataclasses import dataclass, field

from .constants import DEFAULT_BODY, STATS
from .measures import bra_size


@dataclass(frozen=True)
class WorldInfo:
    name: str
    setting: str
    seed: int
    time: int
    rule_mode: str
    scenario_type: str
    travel: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorldInfo":
        return cls(
            name=row["name"],
            setting=row["setting"],
            seed=row["seed"],
            time=row["time"],
            rule_mode=row["rule_mode"],
            scenario_type=row["scenario_type"],
            travel=row["travel"],
        )


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    kind: str
    parent_id: str | None
    x: int | None
    y: int | None
    discovered_at: int | None
    discovered_by: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Location":
        return cls(**{key: row[key] for key in row.keys()})


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    role: str
    profession: str
    personality: dict
    controller: str
    location_id: str | None
    sprite: str | None
    portrait: str | None
    cash: int
    bank: int
    stats: dict[str, int]
    max_health: int
    health: int
    alive: bool
    conditions: tuple[str, ...]
    body: dict = field(default_factory=dict)
    abilities: dict[str, dict] = field(default_factory=dict)
    home_id: str | None = None
    work_id: str | None = None

    @property
    def conscious(self) -> bool:
        return self.alive and "unconscious" not in self.conditions

    def has_ability(self, kind: str) -> bool:
        return kind in self.abilities

    @property
    def bra_size(self) -> str | None:
        """Размер бюстгальтера (США) из обхватов; None, если обхватов нет."""
        return bra_size(self.body.get("bust_cm"), self.body.get("underbust_cm"))


@dataclass(frozen=True)
class Relation:
    from_id: str
    to_id: str
    liking: int = 0
    trust: int = 0
    fear: int = 0
    respect: int = 0
    love: int = 0
    knows_name: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Relation":
        values = {key: row[key] for key in row.keys()}
        values["knows_name"] = bool(values["knows_name"])
        return cls(**values)


@dataclass(frozen=True)
class Item:
    id: int
    kind: str
    name: str
    owner_id: str | None
    location_id: str | None
    base_price: int
    equipped: str | None
    damage_min: int | None
    damage_max: int | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Item":
        return cls(**{key: row[key] for key in row.keys()})


@dataclass(frozen=True)
class Fact:
    id: int
    subject: str
    predicate: str
    object: str
    status: str
    canon: bool
    since: int
    until: int | None
    source: str
    replaced_by: int | None

    @property
    def current(self) -> bool:
        return self.until is None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Fact":
        values = {key: row[key] for key in row.keys()}
        values["canon"] = bool(values["canon"])
        return cls(**values)


@dataclass(frozen=True)
class Knowledge:
    character_id: str
    fact: Fact
    believes: bool
    source: str
    learned_at: int


@dataclass(frozen=True)
class Event:
    id: int
    time: int
    kind: str
    actor_id: str | None
    participants: tuple[str, ...]
    data: dict
    dice: list | None
    basis: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Event":
        return cls(
            id=row["id"],
            time=row["time"],
            kind=row["kind"],
            actor_id=row["actor_id"],
            participants=tuple(json.loads(row["participants"])),
            data=json.loads(row["data"]),
            dice=json.loads(row["dice"]) if row["dice"] is not None else None,
            basis=row["basis"],
        )


def character_from_rows(
    row: sqlite3.Row, stats: sqlite3.Row, abilities: list[sqlite3.Row]
) -> Character:
    """Собирает персонажа из строк `character`, `stats` и `ability`."""
    return Character(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        profession=row["profession"],
        personality=json.loads(row["personality"]),
        controller=row["controller"],
        location_id=row["location_id"],
        sprite=row["sprite"],
        portrait=row["portrait"],
        cash=row["cash"],
        bank=row["bank"],
        stats={name: stats[name] for name in STATS},
        max_health=stats["max_health"],
        health=stats["health"],
        alive=bool(stats["alive"]),
        conditions=tuple(json.loads(stats["conditions"])),
        body={key: stats[key] for key in DEFAULT_BODY},
        abilities={a["kind"]: json.loads(a["params"]) for a in abilities},
        home_id=row["home_id"],
        work_id=row["work_id"],
    )


@dataclass(frozen=True)
class NpcState:
    """Чем занят житель и его потребности (0–100: 100 — всё хорошо)."""

    character_id: str
    activity: str
    level: str
    next_at: int
    updated_at: int
    food: float
    rest: float
    social: float
    safety: float
    company: bool
    owed: int
    shift_day: int | None

    @property
    def needs(self) -> dict[str, int]:
        return {name: round(getattr(self, name)) for name in ("food", "rest", "social", "safety")}

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "NpcState":
        values = {key: row[key] for key in row.keys()}
        values["company"] = bool(values["company"])
        return cls(**values)


@dataclass(frozen=True)
class Snapshot:
    id: int
    time: int
    last_event_id: int | None
    label: str
    file: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Snapshot":
        return cls(**{key: row[key] for key in row.keys()})

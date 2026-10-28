"""Персонажи: создание, профессия, характеристики, здоровье, смерть, способности."""

import json

from .base import WorldBase, _require_choice
from .constants import (
    BODY_SCALES,
    CONTROLLERS,
    DEFAULT_BODY,
    DEFAULT_STAT,
    HEIGHT_MAX_CM,
    HEIGHT_MIN_CM,
    IMMORTALITY,
    STAT_MAX,
    STAT_MIN,
    STATS,
    default_max_health,
)
from .errors import NotFoundError, RuleError
from .models import Character, character_from_rows


class CharactersMixin(WorldBase):
    # --- Чтение --------------------------------------------------------

    def character(self, character_id: str) -> Character:
        row = self._conn.execute("SELECT * FROM character WHERE id = ?", (character_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No character '{character_id}'")
        stats = self._conn.execute(
            "SELECT * FROM stats WHERE character_id = ?", (character_id,)
        ).fetchone()
        abilities = self._conn.execute(
            "SELECT * FROM ability WHERE character_id = ? ORDER BY id", (character_id,)
        ).fetchall()
        return character_from_rows(row, stats, abilities)

    def characters(self, *, location_id: str | None = None) -> list[Character]:
        if location_id is None:
            rows = self._conn.execute("SELECT id FROM character ORDER BY rowid")
        else:
            rows = self._conn.execute(
                "SELECT id FROM character WHERE location_id = ? ORDER BY rowid", (location_id,)
            )
        return [self.character(row["id"]) for row in rows.fetchall()]

    def players(self) -> list[Character]:
        """Персонажи, которыми управляет игрок (обычно один герой)."""
        rows = self._conn.execute(
            "SELECT id FROM character WHERE controller = 'player' ORDER BY rowid"
        ).fetchall()
        return [self.character(row["id"]) for row in rows]

    # --- Создание ------------------------------------------------------

    def add_character(
        self,
        character_id: str,
        name: str,
        *,
        role: str = "",
        profession: str = "",
        controller: str = "ai",
        location_id: str | None = None,
        home_id: str | None = None,
        work_id: str | None = None,
        stats: dict[str, int] | None = None,
        max_health: int | None = None,
        body: dict | None = None,
        personality: dict | None = None,
        cash: int = 0,
        bank: int = 0,
        sprite: str | None = None,
        portrait: str | None = None,
        basis: str = "author",
        actor_id: str | None = None,
    ) -> Character:
        """Добавляет персонажа.

        Характеристики, которых нет в `stats`, равны 5. В `body` можно задать
        рост (`height_cm`), мускулы, полноту и телосложение (D38).
        Дом (`home_id`) и работа (`work_id`) нужны распорядку жителя (0.4);
        если дом не указан, житель живёт там, где появился.
        """
        if not character_id or not name.strip():
            raise RuleError("Character id and name cannot be empty")
        _require_choice("controller", controller, CONTROLLERS)
        values = {stat: DEFAULT_STAT for stat in STATS}
        for stat, value in (stats or {}).items():
            _require_choice("stat", stat, STATS)
            values[stat] = value
        for stat, value in values.items():
            self._check_stat_value(stat, value)
        body_values = self._check_body({**DEFAULT_BODY, **(body or {})})
        if max_health is None:
            max_health = default_max_health(values["endurance"])
        if max_health < 1:
            raise RuleError("Maximum health must be at least 1")
        if cash < 0 or bank < 0:
            raise RuleError("Money cannot be negative")
        with self._change():
            self._check_basis(basis, actor_id, action="Adding a character")
            if self._conn.execute(
                "SELECT 1 FROM character WHERE id = ?", (character_id,)
            ).fetchone():
                raise RuleError(f"Character '{character_id}' already exists")
            if home_id is None and controller == "ai":
                home_id = location_id
            for place in (location_id, home_id, work_id):
                if place is not None:
                    self._location_row(place)
            self._conn.execute(
                "INSERT INTO character (id, name, role, profession, personality, controller,"
                " location_id, home_id, work_id, sprite, portrait, cash, bank)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    character_id,
                    name,
                    role,
                    profession,
                    json.dumps(personality or {}, ensure_ascii=False),
                    controller,
                    location_id,
                    home_id,
                    work_id,
                    sprite,
                    portrait,
                    cash,
                    bank,
                ),
            )
            columns = [*STATS, *DEFAULT_BODY]
            self._conn.execute(
                f"INSERT INTO stats (character_id, {', '.join(columns)}, max_health, health)"
                f" VALUES (?, {', '.join('?' * len(columns))}, ?, ?)",
                (
                    character_id,
                    *(values[stat] for stat in STATS),
                    *(body_values[key] for key in DEFAULT_BODY),
                    max_health,
                    max_health,
                ),
            )
            self._record(
                "character_added",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={
                    "name": name,
                    "role": role,
                    "profession": profession,
                    "controller": controller,
                    "location_id": location_id,
                    "home_id": home_id,
                    "work_id": work_id,
                    "stats": values,
                    "max_health": max_health,
                    "body": body_values,
                    "cash": cash,
                    "bank": bank,
                },
            )
        return self.character(character_id)

    # --- Кто управляет и профессия ---------------------------------------

    def set_controller(self, character_id: str, controller: str, *, basis: str = "author") -> None:
        """Передаёт персонажа игроку или ИИ."""
        _require_choice("controller", controller, CONTROLLERS)
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, None, action="Changing who controls a character",
                              rules_allow=False)
            self._conn.execute(
                "UPDATE character SET controller = ? WHERE id = ?", (controller, character_id)
            )
            self._record(
                "controller_changed",
                basis=basis,
                participants=[character_id],
                data={"from": row["controller"], "to": controller},
            )

    def set_profession(
        self,
        character_id: str,
        profession: str,
        *,
        basis: str = "rules",
        actor_id: str | None = None,
    ) -> None:
        """Смена профессии по ходу игры (D27). По правилам меняет её сам персонаж."""
        with self._change():
            row = self._character_row(character_id)
            if basis == "rules":
                actor_id = actor_id or character_id
            self._check_basis(basis, actor_id, action="Changing profession")
            if row["profession"] == profession:
                raise RuleError(f"{row['name']} is already '{profession}'")
            self._conn.execute(
                "UPDATE character SET profession = ? WHERE id = ?", (profession, character_id)
            )
            self._record(
                "profession_changed",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"from": row["profession"], "to": profession},
            )

    def set_places(
        self,
        character_id: str,
        *,
        home_id: str | None = None,
        work_id: str | None = None,
        basis: str = "author",
    ) -> None:
        """Новый дом или работа жителя. Пустая строка — без дома или без работы.

        По правилам жители сами пока не переезжают: это придёт с целями NPC.
        """
        changes = {key: value for key, value in (("home_id", home_id), ("work_id", work_id))
                   if value is not None}
        if not changes:
            raise RuleError("Nothing to change")
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, None, action="Moving house", rules_allow=False)
            data = {}
            for column, place in changes.items():
                place = place or None
                if place is not None:
                    self._location_row(place)
                self._conn.execute(
                    f"UPDATE character SET {column} = ? WHERE id = ?", (place, character_id)
                )
                data[column] = {"from": row[column], "to": place}
            self._record("places_changed", basis=basis, participants=[character_id], data=data)

    # --- Характеристики ------------------------------------------------

    @staticmethod
    def _check_stat_value(stat: str, value: int) -> None:
        if not isinstance(value, int) or not STAT_MIN <= value <= STAT_MAX:
            raise RuleError(f"{stat} must be from {STAT_MIN} to {STAT_MAX}, got {value}")

    def set_stat(
        self,
        character_id: str,
        stat: str,
        value: int,
        *,
        basis: str = "author",
        actor_id: str | None = None,
    ) -> None:
        """Меняет характеристику. По правилам характеристики пока не растут."""
        _require_choice("stat", stat, STATS)
        self._check_stat_value(stat, value)
        with self._change():
            self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Changing a stat", rules_allow=False)
            old = self._conn.execute(
                f"SELECT {stat} FROM stats WHERE character_id = ?", (character_id,)
            ).fetchone()[0]
            self._conn.execute(
                f"UPDATE stats SET {stat} = ? WHERE character_id = ?", (value, character_id)
            )
            self._record(
                "stat_changed",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"stat": stat, "from": old, "to": value},
            )

    # --- Тело (D38) ----------------------------------------------------

    @staticmethod
    def _check_body(body: dict) -> dict:
        for key in body:
            if key not in DEFAULT_BODY:
                raise RuleError(
                    f"Unknown body part '{key}'; expected one of: {', '.join(DEFAULT_BODY)}"
                )
        height = body["height_cm"]
        if not isinstance(height, int) or not HEIGHT_MIN_CM <= height <= HEIGHT_MAX_CM:
            raise RuleError(f"Height must be from {HEIGHT_MIN_CM} cm to 500 m, got {height}")
        for scale in BODY_SCALES:
            if not isinstance(body[scale], int) or not 0 <= body[scale] <= 100:
                raise RuleError(f"{scale} must be from 0 to 100, got {body[scale]}")
        body["build"] = str(body["build"]).strip()
        return body

    def set_body(
        self,
        character_id: str,
        *,
        basis: str = "author",
        actor_id: str | None = None,
        **changes,
    ) -> None:
        """Меняет рост, мускулы, полноту или телосложение.

        По правилам тело само не меняется: зелье роста и тренировки
        появятся вместе с правилами тела в 0.5.
        """
        if not changes:
            raise RuleError("Nothing to change")
        with self._change():
            self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Changing the body", rules_allow=False)
            old = self.character(character_id).body
            new = self._check_body({**old, **changes})
            for key in changes:
                self._conn.execute(
                    f"UPDATE stats SET {key} = ? WHERE character_id = ?",
                    (new[key], character_id),
                )
            self._record(
                "body_changed",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"from": {key: old[key] for key in changes},
                      "to": {key: new[key] for key in changes}},
            )

    # --- Здоровье и смерть -----------------------------------------------

    def change_health(
        self,
        character_id: str,
        delta: int,
        *,
        basis: str = "rules",
        actor_id: str | None = None,
        cause: str = "",
    ) -> Character:
        """Урон (`delta` < 0) или лечение (`delta` > 0).

        Здоровье не выходит за пределы 0…максимум. У бессмертного
        не опускается ниже 1. На нуле персонаж умирает. Мёртвого
        вылечить нельзя — только воскресить (`revive`).
        """
        if not isinstance(delta, int) or delta == 0:
            raise RuleError("Health change must be a non-zero whole number")
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Changing health")
            if not row["alive"]:
                raise RuleError(f"{row['name']} is dead; only revival can help")
            old = row["health"]
            new = max(0, min(row["max_health"], old + delta))
            if new == 0 and self._has_ability(character_id, IMMORTALITY):
                new = 1
            self._conn.execute(
                "UPDATE stats SET health = ? WHERE character_id = ?", (new, character_id)
            )
            self._record(
                "health_changed",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"from": old, "to": new, "delta": delta, "cause": cause},
            )
            if new == 0:
                self._die(character_id, basis=basis, actor_id=actor_id, cause=cause)
        return self.character(character_id)

    def kill(
        self,
        character_id: str,
        *,
        basis: str = "author",
        actor_id: str | None = None,
        cause: str = "",
    ) -> None:
        """Мгновенная смерть: только волей автора или способностью.

        По правилам персонаж умирает от урона (`change_health`).
        Бессмертного способностью не убить, автор может всё.
        """
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Killing outright", rules_allow=False)
            if not row["alive"]:
                raise RuleError(f"{row['name']} is already dead")
            if basis == "ability" and self._has_ability(character_id, IMMORTALITY):
                raise RuleError(f"{row['name']} is immortal")
            self._conn.execute(
                "UPDATE stats SET health = 0 WHERE character_id = ?", (character_id,)
            )
            self._die(character_id, basis=basis, actor_id=actor_id, cause=cause)

    def _die(self, character_id: str, *, basis: str, actor_id: str | None, cause: str) -> None:
        self._conn.execute(
            "UPDATE stats SET alive = 0, conditions = '[]' WHERE character_id = ?",
            (character_id,),
        )
        self._conn.execute(
            "UPDATE item SET equipped = NULL WHERE owner_id = ?", (character_id,)
        )
        self._record(
            "character_died",
            basis=basis,
            actor_id=actor_id,
            participants=[character_id],
            data={"cause": cause},
        )

    def revive(
        self,
        character_id: str,
        *,
        basis: str = "author",
        actor_id: str | None = None,
        health: int | None = None,
    ) -> None:
        """Воскрешение: волей автора или божественной волей. По умолчанию — с полным здоровьем."""
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Revival", rules_allow=False)
            if row["alive"]:
                raise RuleError(f"{row['name']} is alive")
            health = row["max_health"] if health is None else health
            if not 1 <= health <= row["max_health"]:
                raise RuleError(f"Health after revival must be from 1 to {row['max_health']}")
            self._conn.execute(
                "UPDATE stats SET alive = 1, health = ? WHERE character_id = ?",
                (health, character_id),
            )
            self._record(
                "character_revived",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"health": health},
            )

    # --- Состояния -----------------------------------------------------

    def add_condition(
        self,
        character_id: str,
        condition: str,
        *,
        basis: str = "rules",
        actor_id: str | None = None,
        cause: str = "",
    ) -> None:
        """Добавляет состояние (ранен, оглушён, без сознания…). Список открытый."""
        condition = condition.strip().lower()
        if not condition:
            raise RuleError("Condition cannot be empty")
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Adding a condition")
            if not row["alive"]:
                raise RuleError(f"{row['name']} is dead")
            conditions = json.loads(row["conditions"])
            if condition in conditions:
                raise RuleError(f"{row['name']} is already {condition}")
            conditions.append(condition)
            self._set_conditions(character_id, conditions)
            self._record(
                "condition_added",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"condition": condition, "cause": cause},
            )

    def remove_condition(
        self,
        character_id: str,
        condition: str,
        *,
        basis: str = "rules",
        actor_id: str | None = None,
    ) -> None:
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Removing a condition")
            conditions = json.loads(row["conditions"])
            if condition not in conditions:
                raise RuleError(f"{row['name']} is not {condition}")
            conditions.remove(condition)
            self._set_conditions(character_id, conditions)
            self._record(
                "condition_removed",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"condition": condition},
            )

    def _set_conditions(self, character_id: str, conditions: list[str]) -> None:
        self._conn.execute(
            "UPDATE stats SET conditions = ? WHERE character_id = ?",
            (json.dumps(conditions, ensure_ascii=False), character_id),
        )

    # --- Способности ---------------------------------------------------

    def grant_ability(
        self,
        character_id: str,
        kind: str,
        params: dict | None = None,
        *,
        basis: str = "author",
        actor_id: str | None = None,
    ) -> None:
        """Даёт способность. По правилам способности сами не появляются."""
        kind = kind.strip()
        if not kind:
            raise RuleError("Ability kind cannot be empty")
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Granting an ability", rules_allow=False)
            if self._has_ability(character_id, kind):
                raise RuleError(f"{row['name']} already has {kind}")
            self._conn.execute(
                "INSERT INTO ability (character_id, kind, params) VALUES (?, ?, ?)",
                (character_id, kind, json.dumps(params or {}, ensure_ascii=False)),
            )
            self._record(
                "ability_granted",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"ability": kind, "params": params or {}},
            )

    def remove_ability(
        self,
        character_id: str,
        kind: str,
        *,
        basis: str = "author",
        actor_id: str | None = None,
    ) -> None:
        with self._change():
            row = self._character_row(character_id)
            self._check_basis(basis, actor_id, action="Removing an ability", rules_allow=False)
            if not self._has_ability(character_id, kind):
                raise RuleError(f"{row['name']} has no {kind}")
            self._conn.execute(
                "DELETE FROM ability WHERE character_id = ? AND kind = ?", (character_id, kind)
            )
            self._record(
                "ability_removed",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"ability": kind},
            )

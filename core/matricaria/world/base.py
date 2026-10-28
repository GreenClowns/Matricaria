"""Основа мира: файл базы, транзакции, журнал событий и общие проверки.

Главное правило: любое изменение мира идёт внутри `_change()` и
записывает событие через `_record()`. Если проверка не прошла,
откатывается всё изменение целиком, и журнал не получает лишней записи.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .constants import (
    BASES,
    DEFAULT_RULE_MODE,
    DIVINE_WILL,
    RULE_MODES,
    SCENARIO_TYPES,
    SETTINGS,
    TRAVEL_MODES,
)
from .errors import NotFoundError, RuleError
from .models import Event, WorldInfo
from .schema import SCHEMA_VERSION, check_schema, create_schema, schema_version, upgrade_schema


def _connect(path: Path) -> sqlite3.Connection:
    # autocommit=True: транзакции открываем и закрываем сами в _change().
    conn = sqlite3.connect(path, autocommit=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _require_choice(name: str, value: str, choices: tuple[str, ...]) -> None:
    if value not in choices:
        raise RuleError(f"Unknown {name} '{value}'; expected one of: {', '.join(choices)}")


class WorldBase:
    """Открытый файл мира. Методы изменения добавляют классы-помощники."""

    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self._conn = conn
        self.path = path
        self._depth = 0

    # --- Открыть и создать ---------------------------------------------

    @classmethod
    def create(
        cls,
        path: str | Path,
        name: str,
        *,
        setting: str = "fantasy",
        seed: int = 0,
        rule_mode: str = DEFAULT_RULE_MODE,
        scenario_type: str = "standard",
        travel: str = "map",
    ):
        """Создаёт новый мир в файле `path`. Файл не должен существовать."""
        path = Path(path)
        _require_choice("setting", setting, SETTINGS)
        _require_choice("rule mode", rule_mode, RULE_MODES)
        _require_choice("scenario type", scenario_type, SCENARIO_TYPES)
        _require_choice("travel mode", travel, TRAVEL_MODES)
        if not name.strip():
            raise RuleError("World name cannot be empty")
        if path.exists():
            raise RuleError(f"File {path} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(path)
        create_schema(conn)
        world = cls(conn, path)
        with world._change():
            conn.execute(
                "INSERT INTO world (id, name, setting, seed, rule_mode, scenario_type, travel)"
                " VALUES (1, ?, ?, ?, ?, ?, ?)",
                (name, setting, seed, rule_mode, scenario_type, travel),
            )
            world._record(
                "world_created",
                basis="author",
                data={
                    "name": name,
                    "setting": setting,
                    "seed": seed,
                    "rule_mode": rule_mode,
                    "scenario_type": scenario_type,
                    "travel": travel,
                },
            )
        return world

    @classmethod
    def open(cls, path: str | Path):
        """Открывает существующий мир. Старое сохранение обновляется до новой схемы."""
        path = Path(path)
        if not path.is_file():
            raise NotFoundError(f"World file {path} not found")
        conn = _connect(path)
        try:
            check_schema(conn)
            world = cls(conn, path)
            world._upgrade()
        except Exception:
            conn.close()
            raise
        return world

    def _upgrade(self) -> None:
        """Обновляет схему базы, если мир сохранён старой версией, и пишет это в журнал."""
        if schema_version(self._conn) == SCHEMA_VERSION:
            return
        with self._change():
            old = upgrade_schema(self._conn)
            self._record("schema_upgraded", basis="rules",
                         data={"from": old, "to": SCHEMA_VERSION})

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- Состояние мира ------------------------------------------------

    @property
    def info(self) -> WorldInfo:
        return WorldInfo.from_row(self._conn.execute("SELECT * FROM world").fetchone())

    @property
    def time(self) -> int:
        """Игровое время в минутах от начала мира."""
        return self._conn.execute("SELECT time FROM world").fetchone()[0]

    # --- Журнал --------------------------------------------------------

    def events(
        self,
        *,
        after_id: int = 0,
        limit: int | None = None,
        kind: str | None = None,
        involving: str | None = None,
    ) -> list[Event]:
        """События журнала по порядку. `involving` — персонаж или место среди участников."""
        sql = "SELECT * FROM event WHERE id > ?"
        args: list = [after_id]
        if kind is not None:
            sql += " AND kind = ?"
            args.append(kind)
        if involving is not None:
            sql += " AND (actor_id = ? OR EXISTS (SELECT 1 FROM json_each(participants) WHERE value = ?))"
            args += [involving, involving]
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [Event.from_row(row) for row in self._conn.execute(sql, args)]

    def last_event_id(self) -> int:
        row = self._conn.execute("SELECT MAX(id) FROM event").fetchone()
        return row[0] or 0

    # --- Для классов-помощников ----------------------------------------

    @contextmanager
    def _change(self) -> Iterator[None]:
        """Транзакция «всё или ничего». Вложенные вызовы входят во внешнюю."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self._conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
        finally:
            self._depth = 0

    def _record(
        self,
        kind: str,
        *,
        basis: str,
        actor_id: str | None = None,
        participants: tuple[str, ...] | list[str] = (),
        data: dict | None = None,
        dice: list | None = None,
    ) -> int:
        """Дописывает событие в журнал. Вызывается только внутри `_change()`."""
        assert self._depth, "events are recorded only inside _change()"
        cursor = self._conn.execute(
            "INSERT INTO event (time, kind, actor_id, participants, data, dice, basis)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self.time,
                kind,
                actor_id,
                json.dumps(list(participants), ensure_ascii=False),
                json.dumps(data or {}, ensure_ascii=False),
                json.dumps(dice) if dice is not None else None,
                basis,
            ),
        )
        return cursor.lastrowid

    def _character_row(self, character_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT c.*, s.alive, s.conditions, s.health, s.max_health"
            " FROM character c JOIN stats s ON s.character_id = c.id WHERE c.id = ?",
            (character_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"No character '{character_id}'")
        return row

    def _location_row(self, location_id: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No location '{location_id}'")
        return row

    def _has_ability(self, character_id: str, kind: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM ability WHERE character_id = ? AND kind = ?", (character_id, kind)
        ).fetchone()
        return row is not None

    def _require_able(self, character_id: str) -> sqlite3.Row:
        """Персонаж существует, жив и в сознании — может действовать сам."""
        row = self._character_row(character_id)
        if not row["alive"]:
            raise RuleError(f"{row['name']} is dead")
        if "unconscious" in json.loads(row["conditions"]):
            raise RuleError(f"{row['name']} is unconscious")
        return row

    def _check_basis(
        self,
        basis: str,
        actor_id: str | None,
        *,
        action: str,
        rules_allow: bool = True,
        ability: str | None = None,
    ) -> None:
        """Проверяет основание действия (D22).

        - `rules`: обычное действие; если `rules_allow` ложно, по правилам его не сделать.
          Если указан `actor_id`, этот персонаж должен быть жив и в сознании.
        - `ability`: у `actor_id` должна быть способность `ability`
          (божественная воля подходит для любого чуда).
        - `author`: воля автора, разрешена в любом режиме правил.
        """
        _require_choice("basis", basis, BASES)
        if basis == "author":
            return
        if basis == "rules":
            if not rules_allow:
                raise RuleError(f"{action} is impossible under the rules")
            if actor_id is not None:
                self._require_able(actor_id)
            return
        # basis == "ability"
        if actor_id is None:
            raise RuleError(f"{action} by ability needs a character who has it")
        actor = self._require_able(actor_id)
        allowed = {DIVINE_WILL} | ({ability} if ability else set())
        if not any(self._has_ability(actor_id, kind) for kind in allowed):
            needed = " or ".join(sorted(allowed))
            raise RuleError(f"{actor['name']} has no ability for this ({needed} needed)")

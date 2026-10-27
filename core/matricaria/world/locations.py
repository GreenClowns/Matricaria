"""Места: заданные при создании мира и открытые по ходу игры; перемещения."""

from .base import WorldBase
from .errors import RuleError
from .models import Location


class LocationsMixin(WorldBase):
    def location(self, location_id: str) -> Location:
        return Location.from_row(self._location_row(location_id))

    def locations(self, *, parent_id: str | None = None) -> list[Location]:
        if parent_id is None:
            rows = self._conn.execute("SELECT * FROM location ORDER BY rowid")
        else:
            rows = self._conn.execute(
                "SELECT * FROM location WHERE parent_id = ? ORDER BY rowid", (parent_id,)
            )
        return [Location.from_row(row) for row in rows]

    def add_location(
        self,
        location_id: str,
        name: str,
        kind: str,
        *,
        parent_id: str | None = None,
        x: int | None = None,
        y: int | None = None,
        discovered_by: str | None = None,
        basis: str = "author",
        actor_id: str | None = None,
    ) -> Location:
        """Добавляет место.

        Если указан `discovered_by`, место открыто по ходу игры (D27):
        запоминается, кто и когда его открыл, и оно остаётся в мире навсегда.
        """
        if not location_id or not name.strip() or not kind.strip():
            raise RuleError("Location id, name and kind cannot be empty")
        with self._change():
            self._check_basis(basis, actor_id, action="Adding a location")
            if self._conn.execute(
                "SELECT 1 FROM location WHERE id = ?", (location_id,)
            ).fetchone():
                raise RuleError(f"Location '{location_id}' already exists")
            if parent_id is not None:
                self._location_row(parent_id)
            twin = self._conn.execute(
                "SELECT id FROM location WHERE lower(name) = lower(?) AND parent_id IS ?",
                (name, parent_id),
            ).fetchone()
            if twin:
                raise RuleError(f"There is already a place called '{name}' here ({twin['id']})")
            discovered_at = None
            if discovered_by is not None:
                self._character_row(discovered_by)
                discovered_at = self.time
            self._conn.execute(
                "INSERT INTO location (id, name, kind, parent_id, x, y, discovered_at, discovered_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (location_id, name, kind, parent_id, x, y, discovered_at, discovered_by),
            )
            participants = [location_id] + ([discovered_by] if discovered_by else [])
            self._record(
                "location_added",
                basis=basis,
                actor_id=actor_id,
                participants=participants,
                data={
                    "name": name,
                    "kind": kind,
                    "parent_id": parent_id,
                    "discovered_by": discovered_by,
                },
            )
        return self.location(location_id)

    def move_character(
        self,
        character_id: str,
        location_id: str,
        *,
        basis: str = "rules",
        actor_id: str | None = None,
    ) -> None:
        """Перемещает персонажа. По правилам идёт он сам: живой и в сознании."""
        with self._change():
            row = self._character_row(character_id)
            if basis == "rules":
                actor_id = actor_id or character_id
            self._check_basis(basis, actor_id, action="Moving")
            if basis == "rules" and actor_id != character_id:
                # Чужого персонажа по правилам не переставить: только он сам.
                raise RuleError(f"{row['name']} decides where to go")
            if not row["alive"] and basis == "rules":
                raise RuleError(f"{row['name']} is dead")
            target = self._location_row(location_id)
            if row["location_id"] == location_id:
                raise RuleError(f"{row['name']} is already at {target['name']}")
            self._conn.execute(
                "UPDATE character SET location_id = ? WHERE id = ?", (location_id, character_id)
            )
            self._record(
                "character_moved",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id, location_id]
                + ([row["location_id"]] if row["location_id"] else []),
                data={"from": row["location_id"], "to": location_id},
            )

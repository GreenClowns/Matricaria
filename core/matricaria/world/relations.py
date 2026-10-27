"""Отношения: пять шкал (D28) и знает ли персонаж имя другого."""

from .base import WorldBase
from .constants import RELATION_SCALES
from .errors import RuleError
from .models import Relation


class RelationsMixin(WorldBase):
    def relation(self, from_id: str, to_id: str) -> Relation:
        """Как `from_id` относится к `to_id`. Незнакомцы — все шкалы на нуле."""
        row = self._conn.execute(
            "SELECT * FROM relation WHERE from_id = ? AND to_id = ?", (from_id, to_id)
        ).fetchone()
        if row is None:
            self._character_row(from_id)
            self._character_row(to_id)
            return Relation(from_id, to_id)
        return Relation.from_row(row)

    def relations_of(self, from_id: str) -> list[Relation]:
        rows = self._conn.execute(
            "SELECT * FROM relation WHERE from_id = ? ORDER BY rowid", (from_id,)
        )
        return [Relation.from_row(row) for row in rows]

    def _check_pair(self, from_id: str, to_id: str) -> None:
        if from_id == to_id:
            raise RuleError("A character has no relation to themselves")
        self._character_row(from_id)
        self._character_row(to_id)

    def _write_relation(self, relation: Relation) -> None:
        self._conn.execute(
            "INSERT INTO relation (from_id, to_id, liking, trust, fear, respect, love, knows_name)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (from_id, to_id) DO UPDATE SET liking = excluded.liking,"
            " trust = excluded.trust, fear = excluded.fear, respect = excluded.respect,"
            " love = excluded.love, knows_name = excluded.knows_name",
            (
                relation.from_id,
                relation.to_id,
                relation.liking,
                relation.trust,
                relation.fear,
                relation.respect,
                relation.love,
                int(relation.knows_name),
            ),
        )

    def change_relation(
        self,
        from_id: str,
        to_id: str,
        *,
        basis: str = "rules",
        actor_id: str | None = None,
        reason: str = "",
        **deltas: int,
    ) -> Relation:
        """Сдвигает шкалы на `deltas` (например, `liking=5, fear=-10`).

        Значения упираются в пределы шкалы: симпатия не станет больше 100.
        """
        if not deltas:
            raise RuleError("Nothing to change")
        for scale, delta in deltas.items():
            if scale not in RELATION_SCALES:
                raise RuleError(
                    f"Unknown relation scale '{scale}'; expected one of: "
                    + ", ".join(RELATION_SCALES)
                )
            if not isinstance(delta, int):
                raise RuleError("Relation change must be a whole number")
        with self._change():
            self._check_pair(from_id, to_id)
            self._check_basis(basis, actor_id, action="Changing a relation")
            old = self.relation(from_id, to_id)
            values = {}
            for scale, delta in deltas.items():
                low, high = RELATION_SCALES[scale]
                values[scale] = max(low, min(high, getattr(old, scale) + delta))
            new = Relation(**{**old.__dict__, **values})
            self._write_relation(new)
            self._record(
                "relation_changed",
                basis=basis,
                actor_id=actor_id,
                participants=[from_id, to_id],
                data={
                    "deltas": deltas,
                    "from": {scale: getattr(old, scale) for scale in deltas},
                    "to": values,
                    "reason": reason,
                },
            )
        return new

    def set_relation(
        self,
        from_id: str,
        to_id: str,
        *,
        basis: str = "author",
        actor_id: str | None = None,
        knows_name: bool | None = None,
        **values: int,
    ) -> Relation:
        """Задаёт шкалы точными числами: при создании мира или волей автора."""
        for scale, value in values.items():
            if scale not in RELATION_SCALES:
                raise RuleError(f"Unknown relation scale '{scale}'")
            low, high = RELATION_SCALES[scale]
            if not isinstance(value, int) or not low <= value <= high:
                raise RuleError(f"{scale} must be from {low} to {high}, got {value}")
        with self._change():
            self._check_pair(from_id, to_id)
            self._check_basis(basis, actor_id, action="Setting a relation", rules_allow=False)
            old = self.relation(from_id, to_id)
            changes = dict(values)
            if knows_name is not None:
                changes["knows_name"] = knows_name
            new = Relation(**{**old.__dict__, **changes})
            self._write_relation(new)
            self._record(
                "relation_set",
                basis=basis,
                actor_id=actor_id,
                participants=[from_id, to_id],
                data={"to": changes},
            )
        return new

    def learn_name(self, from_id: str, to_id: str, *, basis: str = "rules") -> None:
        """`from_id` узнаёт имя `to_id` (например, тот представился)."""
        with self._change():
            self._check_pair(from_id, to_id)
            self._check_basis(basis, None, action="Learning a name")
            old = self.relation(from_id, to_id)
            if old.knows_name:
                raise RuleError("The name is already known")
            self._write_relation(Relation(**{**old.__dict__, "knows_name": True}))
            self._record(
                "name_learned", basis=basis, participants=[from_id, to_id], data={}
            )

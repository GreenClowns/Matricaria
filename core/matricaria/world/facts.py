"""Факты о мире и знания персонажей.

Факт — тройка «субъект — свойство — значение» со статусом
(`truth`, `belief`, `rumor`, `lie`). Изменённый факт не стирается:
у старого ставится время окончания и ссылка на новый. Поэтому NPC,
который знал старый факт, по-прежнему его «помнит» — и может ошибаться,
пока не узнает новость.
"""

from .base import WorldBase, _require_choice
from .constants import FACT_STATUSES, OMNISCIENCE
from .errors import NotFoundError, RuleError
from .models import Fact, Knowledge


class FactsMixin(WorldBase):
    # --- Чтение --------------------------------------------------------

    def fact(self, fact_id: int) -> Fact:
        return Fact.from_row(self._fact_row(fact_id))

    def _fact_row(self, fact_id: int):
        row = self._conn.execute("SELECT * FROM fact WHERE id = ?", (fact_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No fact #{fact_id}")
        return row

    def facts(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        status: str | None = None,
        current_only: bool = True,
    ) -> list[Fact]:
        sql = "SELECT * FROM fact WHERE 1"
        args: list = []
        for column, value in (("subject", subject), ("predicate", predicate), ("status", status)):
            if value is not None:
                sql += f" AND {column} = ?"
                args.append(value)
        if current_only:
            sql += " AND until IS NULL"
        sql += " ORDER BY id"
        return [Fact.from_row(row) for row in self._conn.execute(sql, args)]

    # --- Факты: изменения ----------------------------------------------

    def add_fact(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        status: str = "truth",
        canon: bool = False,
        multiple: bool = False,
        source: str = "",
        basis: str = "rules",
        actor_id: str | None = None,
    ) -> Fact:
        """Записывает новый факт.

        Правда (`truth`) не может противоречить другой текущей правде:
        у «spouse_name» одно значение. Если у свойства может быть несколько
        значений (дети, друзья), передайте `multiple=True`. Изменить правду —
        `change_fact`. Канон задаёт только автор.
        """
        _require_choice("fact status", status, FACT_STATUSES)
        if not subject.strip() or not predicate.strip() or not str(object).strip():
            raise RuleError("Fact subject, predicate and object cannot be empty")
        object = str(object)
        with self._change():
            self._check_basis(basis, actor_id, action="Adding a fact")
            if canon and basis != "author":
                raise RuleError("Only the author can add canon facts")
            same = self._conn.execute(
                "SELECT id, object FROM fact WHERE subject = ? AND predicate = ?"
                " AND status = ? AND until IS NULL",
                (subject, predicate, status),
            ).fetchall()
            for row in same:
                if row["object"] == object:
                    raise RuleError(f"This is already fact #{row['id']}")
            if status == "truth" and same and not multiple:
                raise RuleError(
                    f"Contradicts fact #{same[0]['id']} ({subject} {predicate} = "
                    f"{same[0]['object']}); change that fact instead"
                )
            fact_id = self._insert_fact(subject, predicate, object, status, canon, source)
            self._record(
                "fact_added",
                basis=basis,
                actor_id=actor_id,
                participants=[subject],
                data={
                    "fact_id": fact_id,
                    "subject": subject,
                    "predicate": predicate,
                    "object": object,
                    "status": status,
                    "canon": canon,
                    "source": source,
                },
            )
        return self.fact(fact_id)

    def _insert_fact(
        self, subject: str, predicate: str, object: str, status: str, canon: bool, source: str
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO fact (subject, predicate, object, status, canon, since, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (subject, predicate, object, status, int(canon), self.time, source),
        )
        return cursor.lastrowid

    def _require_current(self, fact_id: int, basis: str):
        row = self._fact_row(fact_id)
        if row["until"] is not None:
            raise RuleError(f"Fact #{fact_id} is already out of date")
        if row["canon"] and basis != "author":
            raise RuleError(f"Fact #{fact_id} is canon; only the author can change it")
        return row

    def change_fact(
        self,
        fact_id: int,
        new_object: str,
        *,
        source: str = "",
        basis: str = "rules",
        actor_id: str | None = None,
    ) -> Fact:
        """Факт изменился (кузнец женился снова). Старый факт остаётся в истории."""
        new_object = str(new_object)
        if not new_object.strip():
            raise RuleError("Fact object cannot be empty")
        with self._change():
            old = self._require_current(fact_id, basis)
            self._check_basis(basis, actor_id, action="Changing a fact")
            if old["object"] == new_object:
                raise RuleError(f"Fact #{fact_id} already says {new_object}")
            new_id = self._insert_fact(
                old["subject"], old["predicate"], new_object, old["status"],
                bool(old["canon"]), source,
            )
            self._conn.execute(
                "UPDATE fact SET until = ?, replaced_by = ? WHERE id = ?",
                (self.time, new_id, fact_id),
            )
            self._record(
                "fact_changed",
                basis=basis,
                actor_id=actor_id,
                participants=[old["subject"]],
                data={
                    "fact_id": fact_id,
                    "new_fact_id": new_id,
                    "predicate": old["predicate"],
                    "from": old["object"],
                    "to": new_object,
                    "source": source,
                },
            )
        return self.fact(new_id)

    def end_fact(
        self,
        fact_id: int,
        *,
        basis: str = "rules",
        actor_id: str | None = None,
        reason: str = "",
    ) -> None:
        """Факт перестал быть верным, и замены у него нет (лавка закрылась)."""
        with self._change():
            old = self._require_current(fact_id, basis)
            self._check_basis(basis, actor_id, action="Ending a fact")
            self._conn.execute("UPDATE fact SET until = ? WHERE id = ?", (self.time, fact_id))
            self._record(
                "fact_ended",
                basis=basis,
                actor_id=actor_id,
                participants=[old["subject"]],
                data={"fact_id": fact_id, "reason": reason},
            )

    # --- Знания --------------------------------------------------------

    def learn_fact(
        self,
        character_id: str,
        fact_id: int,
        *,
        believes: bool = True,
        source: str = "",
        basis: str = "rules",
    ) -> None:
        """Персонаж узнаёт факт: увидел сам, услышал слух, ему соврали.

        Если факт уже известен, обновляется только «верит ли».
        """
        with self._change():
            row = self._character_row(character_id)
            self._fact_row(fact_id)
            self._check_basis(basis, None, action="Learning a fact")
            old = self._conn.execute(
                "SELECT believes FROM knowledge WHERE character_id = ? AND fact_id = ?",
                (character_id, fact_id),
            ).fetchone()
            if old is not None and bool(old["believes"]) == believes:
                raise RuleError(f"{row['name']} already knows fact #{fact_id}")
            self._conn.execute(
                "INSERT INTO knowledge (character_id, fact_id, believes, source, learned_at)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT (character_id, fact_id)"
                " DO UPDATE SET believes = excluded.believes, source = excluded.source,"
                " learned_at = excluded.learned_at",
                (character_id, fact_id, int(believes), source, self.time),
            )
            self._record(
                "fact_learned",
                basis=basis,
                participants=[character_id],
                data={"fact_id": fact_id, "believes": believes, "source": source},
            )

    def knowledge(self, character_id: str) -> list[Knowledge]:
        """Что знает персонаж. Всеведущий знает всю текущую правду мира."""
        self._character_row(character_id)
        rows = self._conn.execute(
            "SELECT k.believes, k.source AS k_source, k.learned_at, f.*"
            " FROM knowledge k JOIN fact f ON f.id = k.fact_id"
            " WHERE k.character_id = ? ORDER BY f.id",
            (character_id,),
        ).fetchall()
        known = [
            Knowledge(
                character_id=character_id,
                fact=self._fact_from_joined(row),
                believes=bool(row["believes"]),
                source=row["k_source"],
                learned_at=row["learned_at"],
            )
            for row in rows
        ]
        if self._has_ability(character_id, OMNISCIENCE):
            seen = {k.fact.id for k in known}
            for fact in self.facts(status="truth"):
                if fact.id not in seen:
                    known.append(Knowledge(character_id, fact, True, OMNISCIENCE, fact.since))
            known.sort(key=lambda k: k.fact.id)
        return known

    def knows(self, character_id: str, fact_id: int) -> bool:
        """Знает ли персонаж факт (верит он ему или нет)."""
        return any(k.fact.id == fact_id for k in self.knowledge(character_id))

    def who_knows(self, fact_id: int) -> list[str]:
        """Кто знает факт (без учёта всеведущих)."""
        self._fact_row(fact_id)
        rows = self._conn.execute(
            "SELECT character_id FROM knowledge WHERE fact_id = ? ORDER BY rowid", (fact_id,)
        )
        return [row["character_id"] for row in rows]

    @staticmethod
    def _fact_from_joined(row) -> Fact:
        return Fact(
            id=row["id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            status=row["status"],
            canon=bool(row["canon"]),
            since=row["since"],
            until=row["until"],
            source=row["source"],
            replaced_by=row["replaced_by"],
        )

"""Снимки и откат (D7, D43).

Снимок — полная копия базы мира в папке `snapshots/` рядом с `world.db`.
Откат — восстановить копию. Перед откатом ядро само делает снимок
«до отката», поэтому отменённое будущее не теряется: к нему можно вернуться.

Список снимков хранится в таблице `snapshot`. При откате база заменяется
старой копией, поэтому список переносится в неё из текущей базы, а в журнал
восстановленного мира дописывается событие `rolled_back`.
"""

import sqlite3
from pathlib import Path

from .base import WorldBase
from .errors import NotFoundError, RuleError
from .models import Snapshot
from .schema import check_schema


class SnapshotsMixin(WorldBase):
    @property
    def snapshot_dir(self) -> Path:
        return self.path.parent / "snapshots"

    def snapshots(self) -> list[Snapshot]:
        rows = self._conn.execute("SELECT * FROM snapshot ORDER BY id")
        return [Snapshot.from_row(row) for row in rows]

    def snapshot(self, snapshot_id: int) -> Snapshot:
        row = self._conn.execute(
            "SELECT * FROM snapshot WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"No snapshot #{snapshot_id}")
        return Snapshot.from_row(row)

    def take_snapshot(self, label: str = "") -> Snapshot:
        """Сохраняет копию мира как есть сейчас."""
        if self._depth:
            raise RuleError("Cannot take a snapshot in the middle of a change")
        row = self._conn.execute("SELECT MAX(id) FROM snapshot").fetchone()
        snapshot_id = (row[0] or 0) + 1
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        name = f"{snapshot_id:04d}.db"
        target_path = self.snapshot_dir / name
        if target_path.exists():
            raise RuleError(f"Snapshot file {target_path} already exists")
        target = sqlite3.connect(target_path)
        try:
            self._conn.backup(target)
        finally:
            target.close()
        self._conn.execute(
            "INSERT INTO snapshot (id, time, last_event_id, label, file) VALUES (?, ?, ?, ?, ?)",
            (snapshot_id, self.time, self.last_event_id(), label, name),
        )
        return self.snapshot(snapshot_id)

    def rollback(self, snapshot_id: int) -> Snapshot:
        """Возвращает мир к снимку. Возвращает снимок «до отката» (D43)."""
        if self._depth:
            raise RuleError("Cannot roll back in the middle of a change")
        target = self.snapshot(snapshot_id)
        source_path = self.snapshot_dir / target.file
        if not source_path.is_file():
            raise NotFoundError(f"Snapshot file {source_path} is missing")
        before = self.take_snapshot(f"before rollback to #{snapshot_id}")
        index = [tuple(row) for row in self._conn.execute("SELECT * FROM snapshot ORDER BY id")]
        source = sqlite3.connect(source_path)
        try:
            check_schema(source)
            source.backup(self._conn)
        finally:
            source.close()
        with self._change():
            self._conn.execute("DELETE FROM snapshot")
            self._conn.executemany(
                "INSERT INTO snapshot (id, time, last_event_id, label, file) VALUES (?, ?, ?, ?, ?)",
                index,
            )
            self._record(
                "rolled_back",
                basis="author",
                data={
                    "snapshot_id": snapshot_id,
                    "label": target.label,
                    "before_rollback_snapshot_id": before.id,
                },
            )
        return before

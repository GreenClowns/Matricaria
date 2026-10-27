"""Настройки мира, которые меняются по ходу игры: режим правил и время."""

from .base import WorldBase, _require_choice
from .constants import RULE_MODES
from .errors import RuleError


class SettingsMixin(WorldBase):
    def set_rule_mode(self, mode: str, *, basis: str = "author") -> None:
        """Режим правил меняется в любой момент (D22), но только волей автора."""
        _require_choice("rule mode", mode, RULE_MODES)
        with self._change():
            self._check_basis(basis, None, action="Changing the rule mode", rules_allow=False)
            old = self.info.rule_mode
            if old == mode:
                raise RuleError(f"Rule mode is already {mode}")
            self._conn.execute("UPDATE world SET rule_mode = ?", (mode,))
            self._record("rule_mode_changed", basis=basis, data={"from": old, "to": mode})

    def advance_time(self, minutes: int, *, basis: str = "author", reason: str = "") -> int:
        """Переносит время вперёд. Назад время идёт только откатом к снимку.

        Симуляции пока нет (0.4): за пропущенное время в мире ничего не происходит.
        """
        if not isinstance(minutes, int) or minutes <= 0:
            raise RuleError("Time can only move forward by a positive number of minutes")
        with self._change():
            self._check_basis(basis, None, action="Moving time")
            old = self.time
            self._conn.execute("UPDATE world SET time = time + ?", (minutes,))
            self._record(
                "time_advanced",
                basis=basis,
                data={"from": old, "to": old + minutes, "minutes": minutes, "reason": reason},
            )
        return old + minutes

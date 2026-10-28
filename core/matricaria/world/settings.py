"""Настройки мира, которые меняются по ходу игры: режим правил.

Ход времени — в `simulation.py`.
"""

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

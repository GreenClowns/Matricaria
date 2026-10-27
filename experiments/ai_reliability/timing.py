"""Куда уходит время: разбивка по запросам к модели.

Пример:
    python3 timing.py results/mimo.jsonl
"""

from __future__ import annotations

import json
import sys

ROLES = {"npc": "ответ NPC", "npc_format_retry": "повтор формата", "check": "проверка текста"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    for name in argv:
        with open(name, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        print(f"Файл {name}")
        print(f"{'реплика':14} {'запрос':16} {'секунд':>7} {'токены вых.':>11} {'из них размышл.':>15}")
        for r in records:
            for t in r["turns"]:
                for c in t["calls"]:
                    print(f"{r['case_id']:14} {ROLES.get(c['role'], c['role']):16} {c['latency']:7.1f} "
                          f"{c['completion_tokens']:11} {c.get('reasoning_tokens', 0):15}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

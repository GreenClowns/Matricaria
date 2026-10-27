"""Таблицы с результатами для REPORT.md.

Пример:
    python report.py results/*.jsonl > results/tables.md
    python report.py results/A.jsonl --sample 10 > results/manual-A.md   # выборка для ручной проверки
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path

from cases import GROUPS, load_cases
from judge import conversation_text
from world import load_world


def case_ok(record: dict, which: str) -> bool | None:
    """Итог по одной реплике: судья, а если его нет — правила. None — не оценено."""
    ev = record.get("eval") or {}
    if (ev.get("invalid_actions") or {}).get(which, 0) > 0:
        return False
    judge = (ev.get("judge") or {}).get(which)
    if judge and judge.get("ok") is not None:
        return judge["ok"]
    return ((ev.get("rules") or {}).get(which) or {}).get("ok")


def pct(part: int, whole: int) -> str:
    return "—" if whole == 0 else f"{100 * part / whole:.1f}%"


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def summarize(records: list[dict]) -> dict:
    turns = [t for r in records for t in r["turns"]]
    calls = [c for t in turns for c in t["calls"]]
    npc_lat = [c["latency"] for c in calls if c["role"].startswith("npc")]
    turn_secs = [t["seconds"] for t in turns]
    out = {
        "model": records[0]["model"],
        "model_name": records[0].get("model_name", ""),
        "validator": records[0].get("validator", ""),
        "cases": len(records),
        "turns": len(turns),
        "broken_first": sum(t["raw"]["broken_first"] for t in turns),
        "broken": sum(t["raw"]["broken"] for t in turns),
        "regenerated": sum(t["final"]["attempts"] > 1 for t in turns),
        "fallback": sum(t["final"]["source"] == "fallback" for t in turns),
        "actions_dropped": sum(t["final"]["source"] == "actions_dropped" for t in turns),
        "npc_median": statistics.median(npc_lat) if npc_lat else 0.0,
        "turn_median": statistics.median(turn_secs) if turn_secs else 0.0,
        "turn_p90": quantile(turn_secs, 0.9),
        "turn_max": max(turn_secs, default=0.0),
        "turn_le10": sum(s <= 10 for s in turn_secs),
        "cost": sum(c["cost"] for c in calls),
        "tokens_in": sum(c["prompt_tokens"] for c in calls),
        "tokens_out": sum(c["completion_tokens"] for c in calls),
        "judge_cost": sum(
            ((r.get("eval") or {}).get("judge") or {}).get(w, {}).get("cost", 0.0)
            for r in records for w in ("raw", "final")
        ),
        "judged": sum(bool((r.get("eval") or {}).get("judge")) for r in records),
    }
    for which in ("raw", "final"):
        verdicts = [case_ok(r, which) for r in records]
        out[f"{which}_evaluated"] = sum(v is not None for v in verdicts)
        out[f"{which}_errors"] = sum(v is False for v in verdicts)
        out[f"{which}_invalid_actions"] = sum(
            ((r.get("eval") or {}).get("invalid_actions") or {}).get(which, 0) for r in records
        )
        out[f"{which}_groups"] = {}
        for g in GROUPS:
            vs = [case_ok(r, which) for r in records if r["group"] == g]
            out[f"{which}_groups"][g] = (sum(v is False for v in vs), sum(v is not None for v in vs))
    out["disagree"] = [
        r["case_id"] for r in records
        if (j := ((r.get("eval") or {}).get("judge") or {}).get("final"))
        and (ru := ((r.get("eval") or {}).get("rules") or {}).get("final"))
        and ru.get("ok") is not None and j.get("ok") is not None and ru["ok"] != j["ok"]
    ]
    return out


def render(summaries: list[dict]) -> str:
    lines = ["## Сводка", ""]
    head = "| Метрика | " + " | ".join(f"{s['model']} ({s['validator']})" for s in summaries) + " |"
    lines += [head, "|---" * (len(summaries) + 1) + "|"]

    def row(name, fn):
        lines.append(f"| {name} | " + " | ".join(fn(s) for s in summaries) + " |")

    row("Модель", lambda s: s["model_name"])
    row("Реплик / ответов NPC", lambda s: f"{s['cases']} / {s['turns']}")
    row("Оценено судьёй", lambda s: f"{s['judged']} из {s['cases']}")
    row("Ошибки без валидатора", lambda s: f"{s['raw_errors']} из {s['raw_evaluated']} ({pct(s['raw_errors'], s['raw_evaluated'])})")
    row("**Ошибки, прошедшие через валидатор** (цель ≤ 2%)",
        lambda s: f"{s['final_errors']} из {s['final_evaluated']} ({pct(s['final_errors'], s['final_evaluated'])})")
    row("Сломанный JSON с первого раза", lambda s: pct(s["broken_first"], s["turns"]))
    row("Сломанный JSON после повтора (цель ≤ 1%)", lambda s: pct(s["broken"], s["turns"]))
    row("Невозможные действия: без валидатора", lambda s: str(s["raw_invalid_actions"]))
    row("**Невозможные действия, принятые ядром** (цель 0)", lambda s: str(s["final_invalid_actions"]))
    row("Пересоздано валидатором", lambda s: f"{s['regenerated']} ответов")
    row("Запасной ответ / действия убраны", lambda s: f"{s['fallback']} / {s['actions_dropped']}")
    row("Время одного запроса к модели (медиана)", lambda s: f"{s['npc_median']:.1f} с")
    row("Время ответа NPC с проверками: медиана / 90% / макс.",
        lambda s: f"{s['turn_median']:.1f} / {s['turn_p90']:.1f} / {s['turn_max']:.1f} с")
    row("Ответов не дольше 10 с (цель — все)", lambda s: pct(s["turn_le10"], s["turns"]))
    row("Токены: вход / выход", lambda s: f"{s['tokens_in']} / {s['tokens_out']}")
    row("Цена прогона (модель + проверки)", lambda s: f"${s['cost']:.4f}")
    row("Цена судьи", lambda s: f"${s['judge_cost']:.4f}")

    lines += ["", "## Ошибки по группам (без валидатора → с валидатором)", ""]
    lines += ["| Группа | " + " | ".join(s["model"] for s in summaries) + " |",
              "|---" * (len(summaries) + 1) + "|"]
    for g, title in GROUPS.items():
        cells = []
        for s in summaries:
            re_, rn = s["raw_groups"][g]
            fe, fn = s["final_groups"][g]
            cells.append(f"{re_}/{rn} → {fe}/{fn}")
        lines.append(f"| {title} | " + " | ".join(cells) + " |")

    lines += ["", "## Правила и судья не согласны (проверить вручную)", ""]
    for s in summaries:
        lines.append(f"- {s['model']}: " + (", ".join(s["disagree"]) or "нет"))
    return "\n".join(lines) + "\n"


def render_sample(records: list[dict], size: int, seed: int) -> str:
    world = load_world()
    cases = {c.id: c for c in load_cases()}
    rng = random.Random(seed)
    picked = rng.sample(records, min(size, len(records)))
    lines = [f"# Ручная проверка: {records[0]['model']}, {len(picked)} реплик", ""]
    for r in sorted(picked, key=lambda x: x["case_id"]):
        case = cases[r["case_id"]]
        ev = r.get("eval") or {}
        lines += [
            f"## {r['case_id']} ({GROUPS[r['group']]})",
            f"**Ожидалось:** {case.expect}",
            "",
            "```",
            conversation_text(world, case, r["turns"], "final"),
            "```",
            f"Автомат: {case_ok(r, 'final')}; судья: {((ev.get('judge') or {}).get('final') or {}).get('reason', '—')}",
            "",
            "Моя оценка: [ ] верно  [ ] ошибка — ",
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Таблицы результатов эксперимента")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--sample", type=int, default=0, help="выборка реплик для ручной проверки")
    parser.add_argument("--seed", type=int, default=2, help="зерно случайной выборки")
    args = parser.parse_args(argv)

    all_records = []
    for name in args.files:
        with open(Path(name), encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        if records:
            all_records.append(records)
    if not all_records:
        print("Нет результатов.")
        return 1
    if args.sample:
        for records in all_records:
            print(render_sample(records, args.sample, args.seed))
    else:
        print(render([summarize(r) for r in all_records]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

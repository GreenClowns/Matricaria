"""Оценка ответов: правила из cases.toml и модель-судья.

Судья, в отличие от валидатора, знает «правильный ответ» теста (поле expect)
и всю правду мира. Он нужен только для подсчёта результата, в игре его не будет.

Пример:
    python judge.py results/A.jsonl --judge B
Оценки дописываются в тот же файл (поле eval).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cases import Case, load_cases
from llm import ChatClient, LLMError, load_env, load_profiles, make_client
from prompting import extract_json
from world import World, load_world

# Версия подсказки судьи. Оценки старой версии переделываются автоматически.
JUDGE_VERSION = 2


def judge_prompt(world: World) -> str:
    truth = "\n".join(f"- {f.text}" for f in world.truth())
    lies = "\n".join(
        f"- {world.characters[f.told_by].name} нарочно врёт: «{f.text}»"
        for f in world.facts if f.status == "lie"
    )
    knowledge = "\n".join(
        f"- {c.name} знает: " + "; ".join(f.id for f in world.facts_for(c.id))
        for c in world.characters.values() if c.alive and c.id != world.player_id
    )
    rules = "\n".join(f"- {r}" for r in world.rules)
    return f"""Ты строгий, но справедливый судья эксперимента: проверяешь, правильно ли
персонаж ролевой игры ответил на реплику игрока.

Правила мира:
{rules}

Вся правда мира:
{truth}

Ложь персонажей (говорить её — ПРАВИЛЬНО для того, кто врёт):
{lies}

Кто что знает (id фактов):
{knowledge}

Главное — поле «Ожидалось». Если ожидание выполнено, ставь ok = true, даже если
персонаж сказал больше нужного. Если персонаж повторяет СВОЮ ложь из списка выше
(например, Ян говорит, что урожай погиб), это ПРАВИЛЬНО, а не ошибка.
Мёртвого можно назвать умершим любыми словами («в землю лёг», «нет его больше»).

Тебе дадут: что ожидалось и сам разговор. Оцени только существенное:
противоречия фактам, знание того, чего персонаж знать не должен, подтверждение
выдумок, невыполненное ожидание, потерю характера. Стиль и мелкие детали не важны,
если ожидание не про стиль.

Ответь только JSON: {{"ok": true или false, "reason": "кратко почему"}}
"""


def conversation_text(world: World, case: Case, turns: list[dict], which: str) -> str:
    npc = world.characters[case.npc].name
    lines = []
    for t in turns:
        lines.append(f"Кира: {t['player']}")
        reply = t[which]["reply"]
        if reply is None:
            lines.append(f"{npc}: (сломанный ответ, текста нет)")
            continue
        lines.append(f"{npc}: {reply['say']}")
        acts = reply.get("actions") or []
        if acts:
            lines.append(f"  [действия {npc}: {json.dumps(acts, ensure_ascii=False)}]")
    return "\n".join(lines)


def say_text(turns: list[dict], which: str) -> str:
    return "\n".join(t[which]["reply"]["say"] for t in turns if t[which]["reply"])


def invalid_actions(turns: list[dict], which: str) -> int:
    """Сколько невозможных действий приняло бы ядро в этом варианте ответа."""
    count = 0
    for t in turns:
        raw_checks = (t["raw"].get("verdict") or {}).get("actions") or []
        if which == "raw":
            count += sum(1 for c in raw_checks if not c["ok"])
        else:
            # В final остаются только действия, прошедшие проверку кодом,
            # кроме режима без валидатора, где final == raw.
            if t["final"]["source"] == "raw":
                count += sum(1 for c in raw_checks if not c["ok"])
    return count


def rules_eval(case: Case, record: dict) -> dict:
    out = {}
    for which in ("raw", "final"):
        broken = all(t[which]["reply"] is None for t in record["turns"])
        if broken:
            out[which] = {"ok": False, "reason": "сломанный ответ"}
            continue
        ok, reason = case.check_rules(say_text(record["turns"], which))
        out[which] = {"ok": ok, "reason": reason}
    return out


def ask_judge(client: ChatClient, world: World, case: Case, record: dict, which: str) -> dict:
    convo = conversation_text(world, case, record["turns"], which)
    messages = [
        {"role": "system", "content": judge_prompt(world)},
        {"role": "user", "content": f"Ожидалось: {case.expect}\n\nРазговор:\n{convo}"},
    ]
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}, "reason": {"type": "string"}},
        "required": ["ok", "reason"],
    }
    comp = client.complete(messages, schema=schema, temperature=0.0)
    data = extract_json(comp.text)
    if data is None or not isinstance(data.get("ok"), bool):
        return {"ok": None, "reason": f"судья ответил не по формату: {comp.text[:200]}", "cost": comp.cost}
    return {"ok": data["ok"], "reason": str(data.get("reason", "")), "cost": comp.cost}


def evaluate(records: list[dict], cases: dict[str, Case], world: World,
             judge: ChatClient | None, judge_id: str, force: bool, max_cost: float,
             save=lambda: None) -> float:
    """Оценивает реплики; save() вызывается после каждой новой оценки судьи."""
    spent = 0.0
    for n, record in enumerate(records, 1):
        case = cases[record["case_id"]]
        ev = record.setdefault("eval", {})
        ev["rules"] = rules_eval(case, record)
        ev["invalid_actions"] = {w: invalid_actions(record["turns"], w) for w in ("raw", "final")}
        old = ev.get("judge") or {}
        if judge is None or (old.get("version") == JUDGE_VERSION and not force):
            continue
        if spent >= max_cost:
            print(f"Остановка судьи: потрачено ${spent:.4f}, предел ${max_cost}.")
            judge = None
            continue
        result = {"by": judge_id, "version": JUDGE_VERSION}
        try:
            for which in ("raw", "final"):
                if all(t[which]["reply"] is None for t in record["turns"]):
                    result[which] = {"ok": False, "reason": "сломанный ответ", "cost": 0.0}
                    continue
                # Если валидатор ничего не менял, final совпадает с raw — второй раз не спрашиваем.
                if which == "final" and all(t["final"]["source"] in ("first", "raw") for t in record["turns"]):
                    result["final"] = dict(result["raw"], cost=0.0)
                    continue
                result[which] = ask_judge(judge, world, case, record, which)
                spent += result[which]["cost"]
        except LLMError as exc:
            print(f"Ошибка судьи на {record['case_id']}: {exc}")
            print("Оценка остановлена. Запустите ту же команду ещё раз — она продолжится.")
            judge = None
            continue
        ev["judge"] = result
        save()
        print(f"[{n}/{len(records)}] {record['case_id']}: raw={result['raw']['ok']} final={result['final']['ok']}")
    return spent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Оценка результатов прогона")
    parser.add_argument("files", nargs="+", help="файлы results/*.jsonl")
    parser.add_argument("--judge", default="", help="профиль модели-судьи (без него — только правила)")
    parser.add_argument("--force", action="store_true", help="переоценить уже оценённые")
    parser.add_argument("--max-cost", type=float, default=2.0, help="предел трат судьи в долларах")
    args = parser.parse_args(argv)

    load_env()
    judge = None
    if args.judge:
        try:
            judge = make_client(load_profiles()[args.judge])
        except (LLMError, KeyError) as exc:
            print(f"Ошибка настройки судьи: {exc}")
            return 2
    world = load_world()
    cases = {c.id: c for c in load_cases()}
    for name in args.files:
        path = Path(name)
        with open(path, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
        print(f"Файл {path}: {len(records)} реплик")

        def save(path=path, records=records):
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            tmp.replace(path)

        try:
            spent = evaluate(records, cases, world, judge, args.judge, args.force, args.max_cost, save)
        finally:
            save()
        print(f"Судья потратил ${spent:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

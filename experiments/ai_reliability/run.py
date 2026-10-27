"""Прогон 100 реплик на одной модели.

Каждый ответ сохраняется в двух видах:
- raw   — первый ответ модели, как если бы валидатора не было;
- final — ответ после валидатора (с пересозданием и запасным ответом).
Так один прогон даёт сразу оба режима «без валидатора» и «с валидатором»,
и сравнение честное: у них один и тот же первый ответ.

Примеры:
    python run.py --model fake            # проверка скрипта без сети
    python run.py --model A --limit 10    # первые 10 реплик, оценка цены
    python run.py --model A               # все 100 (продолжит с места остановки)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from cases import Case, load_cases
from llm import ChatClient, LLMError, load_env, load_profiles, make_client
from prompting import (
    FALLBACK_SAY, FORMAT_RETRY, build_messages, compact, parse_reply, reply_schema,
)
from validator import Verdict, check_actions, check_facts, check_text
from world import World, load_world

HERE = Path(__file__).resolve().parent
MAX_REGENERATIONS = 2


def ask_npc(client: ChatClient, messages: list[dict], calls: list[dict]) -> tuple[dict | None, dict]:
    """Один ответ NPC с одним повтором при сломанном формате."""
    comp = client.complete(messages, schema=reply_schema())
    calls.append(comp.stats("npc"))
    reply, error = parse_reply(comp.text)
    info = {"broken_first": reply is None, "format_error": error, "text": comp.text[:2000]}
    if reply is None:
        retry = messages + [
            {"role": "assistant", "content": comp.text[:2000]},
            {"role": "user", "content": FORMAT_RETRY},
        ]
        comp = client.complete(retry, schema=reply_schema())
        calls.append(comp.stats("npc_format_retry"))
        reply, error = parse_reply(comp.text)
        info["text_retry"] = comp.text[:2000]
    info["broken"] = reply is None
    return reply, info


def verify(world: World, npc_id: str, line: str, reply: dict,
           checker: ChatClient | None, calls: list[dict]) -> Verdict:
    verdict = Verdict(
        actions=check_actions(world, npc_id, reply["actions"]),
        facts=check_facts(world, npc_id, reply["facts"]),
    )
    if checker is not None:
        verdict.text = check_text(checker, world, npc_id, line, reply["say"])
        if verdict.text.completion is not None:
            calls.append(verdict.text.completion.stats("check"))
    return verdict


def run_turn(world: World, npc_id: str, history: list[tuple[str, str]], line: str,
             client: ChatClient, checker: ChatClient | None, use_validator: bool) -> dict:
    calls: list[dict] = []
    started = time.monotonic()
    messages = build_messages(world, npc_id, history, line)
    reply, info = ask_npc(client, messages, calls)

    raw = {"reply": reply, **info, "verdict": None}
    if reply is not None:
        # Действия и факты проверяются кодом и для raw: так видно,
        # сколько невозможного ядро приняло бы без валидатора.
        verdict = verify(world, npc_id, line, reply, checker if use_validator else None, calls)
        raw["verdict"] = verdict.to_dict()
    else:
        verdict = None

    if not use_validator:
        final = {"reply": reply, "source": "raw", "attempts": 1, "rejections": []}
    else:
        final = validate_loop(world, npc_id, line, messages, reply, verdict, client, checker, calls)

    return {
        "player": line,
        "raw": raw,
        "final": final,
        "calls": calls,
        "seconds": round(time.monotonic() - started, 3),
    }


def validate_loop(world, npc_id, line, messages, reply, verdict, client, checker, calls) -> dict:
    """Пересоздание ответа до MAX_REGENERATIONS раз, затем запасной ответ."""
    rejections = []
    attempts = 1
    while True:
        if reply is None:
            problems = ["сломанный формат JSON"]
        else:
            problems = verdict.problems
        if not problems:
            source = "first" if attempts == 1 else "regenerated"
            return {"reply": reply, "source": source, "attempts": attempts, "rejections": rejections}
        rejections.append(problems)
        if attempts > MAX_REGENERATIONS:
            break
        feedback = (
            "Ответ отклонён проверкой мира:\n- " + "\n- ".join(problems)
            + "\nОтветь заново, по-прежнему в роли и только JSON."
        )
        retry = messages + [
            {"role": "assistant", "content": compact(reply) if reply else "(сломанный ответ)"},
            {"role": "user", "content": feedback},
        ]
        reply, _ = ask_npc(client, retry, calls)
        attempts += 1
        if reply is not None:
            verdict = verify(world, npc_id, line, reply, checker, calls)

    # Попытки кончились. Если плохи только действия — убираем их, реплику оставляем.
    if reply is not None and verdict.only_actions_bad:
        good = [c.action for c in verdict.actions if c.ok]
        safe = {**reply, "actions": good}
        return {"reply": safe, "source": "actions_dropped", "attempts": attempts, "rejections": rejections}
    safe = {"say": FALLBACK_SAY, "emotion": "neutral", "actions": [], "facts": []}
    return {"reply": safe, "source": "fallback", "attempts": attempts, "rejections": rejections}


def run_case(case: Case, world: World, client: ChatClient,
             checker: ChatClient | None, use_validator: bool) -> dict:
    history: list[tuple[str, str]] = []
    turns = []
    for line in case.turns:
        turn = run_turn(world, case.npc, history, line, client, checker, use_validator)
        turns.append(turn)
        # В историю беседы идёт ответ после валидатора.
        final_reply = turn["final"]["reply"]
        history.append((line, compact(final_reply) if final_reply else "{}"))
    return {"case_id": case.id, "group": case.group, "npc": case.npc, "turns": turns}


def load_done(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def total_cost(records: list[dict]) -> float:
    return sum(c["cost"] for r in records for t in r["turns"] for c in t["calls"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Прогон тестовых реплик на модели")
    parser.add_argument("--model", required=True, help="профиль из models.toml (A, B, C, D, fake)")
    parser.add_argument("--validator", default="self",
                        help="кто проверяет текст: self — та же модель, none — без валидатора, "
                             "или другой профиль (по умолчанию self)")
    parser.add_argument("--limit", type=int, default=0, help="сколько реплик прогнать (0 — все)")
    parser.add_argument("--group", default="", help="только одна группа реплик")
    parser.add_argument("--only", default="", help="только эти id через запятую")
    parser.add_argument("--max-cost", type=float, default=2.0, help="предел трат в долларах (по умолчанию 2)")
    parser.add_argument("--out", default="", help="файл результатов (по умолчанию results/<модель>.jsonl)")
    parser.add_argument("--fresh", action="store_true", help="начать заново, стерев прошлые результаты")
    args = parser.parse_args(argv)

    load_env()
    profiles = load_profiles()
    if args.model not in profiles:
        print(f"Нет профиля {args.model!r} в models.toml. Есть: {', '.join(profiles)}")
        return 2
    profile = profiles[args.model]
    try:
        client = make_client(profile)
        use_validator = args.validator != "none"
        if not use_validator:
            checker = None
        elif args.validator == "self":
            checker = client
        else:
            checker = make_client(profiles[args.validator])
    except (LLMError, KeyError) as exc:
        print(f"Ошибка настройки: {exc}")
        return 2

    world = load_world()
    cases = load_cases()
    if args.group:
        cases = [c for c in cases if c.group == args.group]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.id in wanted]

    suffix = "" if args.validator == "self" else f"-check-{args.validator}"
    out = Path(args.out) if args.out else HERE / "results" / f"{args.model}{suffix}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.fresh and out.exists():
        out.unlink()
    done = load_done(out)
    done_ids = {r["case_id"] for r in done}
    todo = [c for c in cases if c.id not in done_ids]
    if args.limit:
        todo = todo[: max(0, args.limit - len([c for c in cases if c.id in done_ids]))]

    spent = total_cost(done)
    print(f"Модель {profile.id}: {profile.name} ({profile.model})")
    print(f"Валидатор: {args.validator}. Уже готово: {len(done_ids)}, осталось прогнать: {len(todo)}")
    print(f"Результаты: {out}")
    if not profile.is_fake and not profile.has_prices and "127.0.0.1" not in profile.url and "localhost" not in profile.url:
        print("ВНИМАНИЕ: в models.toml не указаны цены — стоимость будет 0, предел трат не сработает.")

    with open(out, "a", encoding="utf-8") as fh:
        for n, case in enumerate(todo, 1):
            if spent >= args.max_cost:
                print(f"Остановка: потрачено ${spent:.4f}, предел ${args.max_cost}. "
                      f"Увеличьте --max-cost, чтобы продолжить.")
                break
            try:
                record = run_case(case, world, client, checker, use_validator)
            except LLMError as exc:
                print(f"Ошибка запроса на {case.id}: {exc}")
                print("Прогон остановлен. Запустите ту же команду ещё раз — он продолжится с этого места.")
                return 1
            record.update({"model": profile.id, "model_name": profile.model, "validator": args.validator})
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            cost = total_cost([record])
            spent += cost
            secs = sum(t["seconds"] for t in record["turns"])
            src = ",".join(t["final"]["source"] for t in record["turns"])
            print(f"[{n}/{len(todo)}] {case.id}: {secs:.1f} с, ${cost:.4f}, итог: {src}")
            if n == 10 and len(todo) > 10:
                print(f"--- После 10 реплик потрачено ${spent:.4f}; на 100 реплик примерно ${spent * 10:.2f}")
    print(f"Готово. Всего потрачено на этот файл: ${spent:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

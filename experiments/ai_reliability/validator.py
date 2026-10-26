"""Упрощённый валидатор (docs/07-validator.md).

Три проверки:
1. действия — кодом, ошибиться не может;
2. поле facts — сверка с базой кодом;
3. текст реплики — модель-проверщик с низкой температурой (помощник, не последняя линия).

Валидатор не знает «правильных ответов» тестов: он видит только мир.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from llm import ChatClient, Completion, LLMError
from prompting import extract_json
from world import World

MAX_TRUST_CHANGE = 10


@dataclass
class ActionCheck:
    action: dict
    ok: bool
    reason: str


def check_actions(world: World, speaker_id: str, actions: list[dict]) -> list[ActionCheck]:
    """Проверяет действия по порядку, как если бы ядро их применяло."""
    owners = {iid: it["owner"] for iid, it in world.items.items()}
    money = {cid: c.money for cid, c in world.characters.items()}
    speaker = world.characters[speaker_id]
    results = []

    def alive(cid) -> bool:
        return cid in world.characters and world.characters[cid].alive

    for act in actions:
        kind = act.get("type")
        ok, reason = True, "ок"
        if kind == "relation_change":
            trust = act.get("trust")
            if not alive(act.get("target")):
                ok, reason = False, f"нет живого персонажа {act.get('target')!r}"
            elif not isinstance(trust, int) or abs(trust) > MAX_TRUST_CHANGE:
                ok, reason = False, f"изменение отношения {trust!r} вне ±{MAX_TRUST_CHANGE}"
        elif kind == "give_item":
            item, to = act.get("item"), act.get("to")
            if item not in owners:
                ok, reason = False, f"предмета {item!r} нет в мире"
            elif owners[item] != speaker_id:
                ok, reason = False, f"предмет {item!r} не у {speaker.name}"
            elif not alive(to) or to == speaker_id:
                ok, reason = False, f"некому отдать: {to!r}"
            else:
                owners[item] = to
        elif kind == "take_item":
            item, frm = act.get("item"), act.get("from")
            if item not in owners:
                ok, reason = False, f"предмета {item!r} нет в мире"
            elif owners[item] != frm or frm == speaker_id:
                ok, reason = False, f"предмет {item!r} не у {frm!r}"
            else:
                owners[item] = speaker_id
        elif kind == "pay":
            to, amount = act.get("to"), act.get("amount")
            if not alive(to) or to == speaker_id:
                ok, reason = False, f"некому платить: {to!r}"
            elif not isinstance(amount, int) or amount <= 0:
                ok, reason = False, f"неверная сумма {amount!r}"
            elif money[speaker_id] < amount:
                ok, reason = False, f"у {speaker.name} {money[speaker_id]} монет, нужно {amount}"
            else:
                money[speaker_id] -= amount
                money[to] += amount
        elif kind == "move_to":
            if act.get("location") not in world.locations:
                ok, reason = False, f"места {act.get('location')!r} нет в мире"
        elif kind == "call":
            who = act.get("character")
            if who not in world.characters:
                ok, reason = False, f"персонажа {who!r} нет в мире"
            elif not world.characters[who].alive:
                ok, reason = False, f"{world.characters[who].name} мёртв"
        elif kind == "remember":
            # Модели иногда кладут текст памяти не в то поле — для записи
            # в память важен сам текст, поэтому берём любое непустое строковое поле.
            texts = [x for k, x in act.items() if k != "type" and isinstance(x, str) and x.strip()]
            if not texts:
                ok, reason = False, "пустая запись"
        elif kind == "miracle":
            if not speaker.abilities:
                ok, reason = False, f"у {speaker.name} нет способности к чудесам"
        else:
            ok, reason = False, f"неизвестное действие {kind!r}"
        results.append(ActionCheck(act, ok, reason))
    return results


def _norm(value: str) -> str:
    return " ".join(str(value).lower().replace("ё", "е").split())


@dataclass
class FactCheck:
    fact: dict
    verdict: str  # match | contradiction | new
    reason: str


# Слова-связки, которые модели ставят в predicate вместо настоящего ключа.
FILLER_PREDICATES = {"", "is", "=", "==", "равно", "это", "есть", "value", "значение"}


def normalize_fact(world: World, fact: dict) -> dict:
    """Приводит факт к ключам базы, если модель записала его по-своему.

    Примеры: {"tavern.room_price", "равно", "20"} → {"tavern", "room_price", "20"};
    {"Гордей", "alive", "нет"} → {"gordey", "alive", "нет"}.
    """
    subject, predicate, obj = fact["subject"].strip(), fact["predicate"].strip(), fact["object"].strip()
    names = {c.name.lower(): cid for cid, c in world.characters.items()}
    names.update({name.lower(): lid for lid, name in world.locations.items()})
    subject = names.get(subject.lower(), subject)
    if "." in subject:
        head, tail = subject.split(".", 1)
        head = names.get(head.lower(), head)
        if world.canon(head, tail) is not None or any(
            x.subject == head and x.predicate == tail for x in world.facts
        ):
            if predicate.lower() not in FILLER_PREDICATES:
                obj = f"{predicate} {obj}".strip()
            subject, predicate = head, tail
    return {"subject": subject, "predicate": predicate, "object": obj}


def check_facts(world: World, speaker_id: str, facts: list[dict]) -> list[FactCheck]:
    """Сверяет утверждения из поля facts с базой."""
    results = []
    for f in (normalize_fact(world, x) for x in facts):
        canon = world.canon(f["subject"], f["predicate"])
        if canon is None:
            results.append(FactCheck(f, "new", "в базе нет такого факта — новая деталь"))
            continue
        said, true = _norm(f["object"]), _norm(canon.object)
        if said == true or true in said or said in true:
            results.append(FactCheck(f, "match", "совпадает с базой"))
            continue
        # Персонаж может повторять свою ложь или то, во что верит.
        allowed = [
            x for x in world.facts_for(speaker_id)
            if x.status in ("lie", "belief")
            and x.subject == f["subject"] and x.predicate == f["predicate"]
            and (_norm(x.object) in said or said in _norm(x.object))
        ]
        if allowed:
            results.append(FactCheck(f, "match", f"это {allowed[0].status} персонажа"))
        else:
            results.append(
                FactCheck(f, "contradiction", f"в базе {canon.object!r}, сказано {f['object']!r}")
            )
    return results


def checker_prompt(world: World, speaker_id: str) -> str:
    npc = world.characters[speaker_id]
    known = []
    for f in world.facts_for(speaker_id):
        if f.status == "lie":
            known.append(f"- {f.text} (это ЛОЖЬ, которую {npc.name} рассказывает нарочно — ему так говорить МОЖНО)")
        elif f.status == "belief":
            known.append(f"- {f.text} ({npc.name} в это верит — так говорить МОЖНО)")
        else:
            known.append(f"- {f.text}")
    dead = ", ".join(c.name for c in world.characters.values() if not c.alive) or "никто"
    people = ", ".join(c.name for c in world.characters.values() if c.alive)
    rules = "\n".join(f"- {r}" for r in world.rules)
    return f"""Ты проверяешь реплику персонажа ролевой игры на противоречия с миром.
Персонаж: {npc.name}, {npc.role}.

Правила мира:
{rules}
Живые персонажи: {people}. Умершие: {dead}.

Что знает {npc.name} (это правда, если не сказано иное):
{chr(10).join(known)}

Противоречие — это когда реплика:
- утверждает что-то, что спорит с фактами выше (числа, имена, кто жив, кто умер);
- говорит о том, чего {npc.name} знать не может, как о точном знании;
- всерьёз утверждает выдуманное важное: новых людей, события, магию, чудовищ, места;
- говорит о мёртвом как о живом.
НЕ противоречие: «не знаю», отказ, шутка, мнение, мелкие бытовые детали
(погода, блюдо, цвет), а также ложь и убеждения, отмеченные выше как разрешённые.

Ответь только JSON: {{"contradiction": true или false, "reason": "кратко почему"}}
"""


@dataclass
class TextCheck:
    contradiction: bool
    reason: str
    completion: Completion | None = None
    error: str = ""


def check_text(client: ChatClient, world: World, speaker_id: str, player_line: str, say: str) -> TextCheck:
    messages = [
        {"role": "system", "content": checker_prompt(world, speaker_id)},
        {"role": "user", "content": f"Собеседник сказал: {player_line}\nРеплика персонажа: {say}"},
    ]
    schema = {
        "type": "object",
        "properties": {"contradiction": {"type": "boolean"}, "reason": {"type": "string"}},
        "required": ["contradiction", "reason"],
    }
    try:
        comp = client.complete(messages, schema=schema, temperature=0.0)
    except LLMError as exc:
        return TextCheck(False, "", None, error=str(exc))
    data = extract_json(comp.text)
    if data is None or not isinstance(data.get("contradiction"), bool):
        return TextCheck(False, "", comp, error=f"проверщик ответил не по формату: {comp.text[:200]}")
    return TextCheck(data["contradiction"], str(data.get("reason", "")), comp)


@dataclass
class Verdict:
    """Итог проверки одного варианта ответа."""

    actions: list[ActionCheck] = field(default_factory=list)
    facts: list[FactCheck] = field(default_factory=list)
    text: TextCheck | None = None

    @property
    def problems(self) -> list[str]:
        out = [f"действие {json.dumps(a.action, ensure_ascii=False)}: {a.reason}" for a in self.actions if not a.ok]
        out += [f"факт {f.fact}: {f.reason}" for f in self.facts if f.verdict == "contradiction"]
        if self.text and self.text.contradiction:
            out.append(f"текст: {self.text.reason}")
        return out

    @property
    def only_actions_bad(self) -> bool:
        return (
            any(not a.ok for a in self.actions)
            and not any(f.verdict == "contradiction" for f in self.facts)
            and not (self.text and self.text.contradiction)
        )

    def to_dict(self) -> dict:
        return {
            "actions": [{"action": a.action, "ok": a.ok, "reason": a.reason} for a in self.actions],
            "facts": [{"fact": f.fact, "verdict": f.verdict, "reason": f.reason} for f in self.facts],
            "text": None if self.text is None else {
                "contradiction": self.text.contradiction,
                "reason": self.text.reason,
                "error": self.text.error,
            },
        }

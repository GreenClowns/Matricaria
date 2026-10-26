"""Сборка запроса для NPC и разбор его JSON-ответа (формат из docs/06-ai-formats.md)."""

from __future__ import annotations

import json
import re

from world import World

EMOTIONS = [
    "neutral", "happy", "angry", "sad",
    "surprised", "embarrassed", "suspicious", "scared",
]

# Действия, которые NPC может предложить в эксперименте, и их поля.
ACTIONS = {
    "relation_change": "изменить отношение: {\"type\": \"relation_change\", \"target\": id персонажа, \"trust\": число от -10 до 10}",
    "give_item": "отдать свой предмет: {\"type\": \"give_item\", \"item\": id предмета, \"to\": id персонажа}",
    "take_item": "взять предмет у другого: {\"type\": \"take_item\", \"item\": id предмета, \"from\": id персонажа}",
    "pay": "заплатить: {\"type\": \"pay\", \"to\": id персонажа, \"amount\": число монет}",
    "move_to": "уйти в другое место: {\"type\": \"move_to\", \"location\": id места}",
    "call": "позвать персонажа в сцену: {\"type\": \"call\", \"character\": id персонажа}",
    "remember": "запомнить событие: {\"type\": \"remember\", \"text\": \"что запомнить\"}",
    "miracle": "чудо (только если есть способность): {\"type\": \"miracle\", \"text\": \"что произойдёт\"}",
}

FALLBACK_SAY = "Хм... Даже не знаю, что тебе на это сказать."


def reply_schema() -> dict:
    """JSON-схема ответа для сайтов, которые её поддерживают.

    Схема нарочно простая: тонкую проверку id и предметов делает код валидатора.
    """
    return {
        "type": "object",
        "properties": {
            "say": {"type": "string"},
            "emotion": {"type": "string", "enum": EMOTIONS},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": list(ACTIONS)},
                        "target": {"type": "string"},
                        "trust": {"type": "integer"},
                        "item": {"type": "string"},
                        "to": {"type": "string"},
                        "from": {"type": "string"},
                        "amount": {"type": "integer"},
                        "location": {"type": "string"},
                        "character": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["type"],
                },
            },
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                    },
                    "required": ["subject", "predicate", "object"],
                },
            },
        },
        "required": ["say", "emotion", "actions", "facts"],
    }


def _fact_line(fact) -> str:
    key = f"[{fact.subject}.{fact.predicate} = {fact.object}]"
    if fact.status == "lie":
        return (
            f"- ТВОЯ ЛОЖЬ: ты всем говоришь: «{fact.text}» Это неправда, "
            f"но ты держишься этой версии и правду не выдаёшь. {key}"
        )
    if fact.status == "belief":
        return f"- ТЫ В ЭТО ВЕРИШЬ (но точно не знаешь): {fact.text} {key}"
    return f"- {fact.text} {key}"


def system_prompt(world: World, npc_id: str) -> str:
    npc = world.characters[npc_id]
    player = world.characters[world.player_id]
    place = world.locations[npc.location]
    facts = "\n".join(_fact_line(f) for f in world.facts_for(npc_id))
    rules = "\n".join(f"- {r}" for r in world.rules)
    own_items = ", ".join(
        f"{world.items[i]['name']} (id: {i})" for i in world.items_of(npc_id)
    ) or "ничего"
    player_items = ", ".join(
        f"{world.items[i]['name']} (id: {i})" for i in world.items_of(player.id)
    ) or "ничего"
    people = "\n".join(
        f"- {c.name} (id: {c.id}) — {c.role}" + ("" if c.alive else ", УМЕР")
        for c in world.characters.values()
    )
    places = "\n".join(f"- {name} (id: {lid})" for lid, name in world.locations.items())
    abilities = ", ".join(npc.abilities) or "нет (чудеса тебе недоступны)"
    actions = "\n".join(f"- {d}" for d in ACTIONS.values())
    return f"""Ты играешь роль персонажа в ролевой игре. Отвечай по-русски.

## Мир
{world.setting}
Правила мира:
{rules}

## Твой персонаж
Ты — {npc.name}, {npc.role}.
Характер: {npc.personality}.
Манера речи: {npc.speech}.
Способности: {abilities}.
У тебя есть: {own_items}. Денег: {npc.money} монет.

## Сцена
Место: {place}. С тобой говорит {player.name} ({player.role}).
У {player.name} есть: {player_items}.

## Что ты знаешь
{facts}

## Кто есть в мире
{people}

## Места
{places}

## Главное правило
Опирайся только на эти факты. Если чего-то нет в списке «Что ты знаешь» — ты этого не знаешь,
так и скажи по-своему. Не выдумывай новых людей, мест, событий, магию и чудовищ.
Мёртвые не оживают и не приходят. Ты можешь отказать собеседнику.

## Формат ответа
Ответь ТОЛЬКО одним объектом JSON без пояснений:
{{"say": "твоя реплика", "emotion": "одно из: {', '.join(EMOTIONS)}", "actions": [], "facts": []}}

actions — действия, которые ты совершаешь прямо сейчас (обычно пусто). Можно только с существующими id:
{actions}
facts — факты, которые ты утверждаешь в реплике, в виде {{"subject": ..., "predicate": ..., "object": ...}}
с ключами из квадратных скобок выше (если утверждаешь известный факт). Можно оставить пустым.
"""


def player_message(world: World, line: str) -> str:
    player = world.characters[world.player_id]
    return f"{player.name}: {line}"


def build_messages(
    world: World, npc_id: str, history: list[tuple[str, str]], line: str
) -> list[dict]:
    """history — пары (реплика игрока, JSON-ответ NPC) из прошлых ходов беседы."""
    messages = [{"role": "system", "content": system_prompt(world, npc_id)}]
    for player_line, npc_json in history:
        messages.append({"role": "user", "content": player_message(world, player_line)})
        messages.append({"role": "assistant", "content": npc_json})
    messages.append({"role": "user", "content": player_message(world, line)})
    return messages


FORMAT_RETRY = (
    "Ответ не удалось разобрать. Ответь ещё раз: только JSON вида "
    '{"say": "...", "emotion": "...", "actions": [], "facts": []} без других слов.'
)


def extract_json(text: str) -> dict | None:
    """Достаёт первый объект JSON из текста (убирает ```json и <think>)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.replace("```json", "").replace("```", "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_reply(text: str) -> tuple[dict | None, str]:
    """Разбирает и проверяет форму ответа NPC. Возвращает (ответ, ошибка)."""
    data = extract_json(text)
    if data is None:
        return None, "не JSON"
    say = data.get("say")
    if not isinstance(say, str) or not say.strip():
        return None, "нет поля say"
    if data.get("emotion") not in EMOTIONS:
        return None, f"неизвестная эмоция {data.get('emotion')!r}"
    actions = data.get("actions") or []
    facts = data.get("facts") or []
    if not isinstance(actions, list) or not all(
        isinstance(a, dict) and isinstance(a.get("type"), str) for a in actions
    ):
        return None, "actions не список действий"
    if not isinstance(facts, list) or not all(
        isinstance(f, dict) and all(k in f for k in ("subject", "predicate", "object"))
        for f in facts
    ):
        return None, "facts не список фактов"
    return {
        "say": say.strip(),
        "emotion": data["emotion"],
        "actions": actions,
        "facts": [{k: str(f[k]) for k in ("subject", "predicate", "object")} for f in facts],
    }, ""


def compact(reply: dict) -> str:
    return json.dumps(reply, ensure_ascii=False)

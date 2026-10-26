"""Тесты стенда эксперимента 0.2 (без сети: только поддельные модели)."""

import json
from collections import Counter

import pytest

import run
from cases import load_cases
from llm import ChatClient, Completion, Profile
from prompting import parse_reply, system_prompt
from report import case_ok, summarize
from validator import check_actions, check_facts
from world import load_world


@pytest.fixture(scope="module")
def world():
    return load_world()


class ScriptedClient(ChatClient):
    """Отвечает заранее заданными текстами по очереди."""

    def __init__(self, texts):
        super().__init__(Profile(id="s", name="s", url="fake://", model="s"))
        self.texts = list(texts)
        self.seen = []

    def complete(self, messages, schema=None, temperature=None):
        self.seen.append(messages)
        return Completion(self.texts.pop(0), 10, 5, 0.1, 0.0)


def reply(say="Ну.", actions=(), facts=()):
    return json.dumps(
        {"say": say, "emotion": "neutral", "actions": list(actions), "facts": list(facts)},
        ensure_ascii=False,
    )


NO_CONTRADICTION = '{"contradiction": false, "reason": "ок"}'


# --- Мир и реплики ---

def test_world_matches_plan(world):
    living = [c for c in world.characters.values() if c.alive and c.id != world.player_id]
    assert {c.name for c in living} == {"Борис", "Лина", "Ян"}
    assert not world.characters["gordey"].alive
    assert 18 <= len(world.facts) <= 25
    assert world.items["room_key"]["owner"] == "boris"
    assert world.characters["boris"].money == 40


def test_knowledge_limits(world):
    lina = {f.id for f in world.facts_for("lina")}
    boris = {f.id for f in world.facts_for("boris")}
    assert "wedding" not in lina
    assert "lina_wounded" not in boris
    assert "grain_price_secret" not in boris | lina
    assert "gordey_dead" in lina & boris


def test_cases_count_by_group():
    counts = Counter(c.group for c in load_cases())
    assert counts == {
        "facts": 20, "dead": 15, "knowledge": 15, "impossible": 15,
        "fabrication": 15, "lie": 10, "style": 10,
    }


def test_cases_refer_to_living_npcs(world):
    for case in load_cases():
        assert world.characters[case.npc].alive and case.npc != world.player_id


def test_rules_check():
    case = next(c for c in load_cases() if c.id == "facts-01")
    assert case.check_rules("Двадцать монет, и не торгуйся.")[0] is True
    assert case.check_rules("Тридцать монет.")[0] is False
    style = next(c for c in load_cases() if c.group == "style")
    assert style.check_rules("что угодно")[0] is None


# --- Запрос ---

def test_prompt_hides_unknown_facts(world):
    lina = system_prompt(world, "lina")
    assert "Соня" not in lina and "свадьб" not in lina
    yan = system_prompt(world, "yan")
    assert "ТВОЯ ЛОЖЬ" in yan and "Урожай погиб" in yan
    assert "УМЕР" in system_prompt(world, "boris")


def test_parse_reply_variants():
    good, err = parse_reply("<think>хм</think>```json\n" + reply("Привет") + "\n```")
    assert good["say"] == "Привет" and err == ""
    assert parse_reply("просто текст")[0] is None
    bad_emotion = json.dumps({"say": "а", "emotion": "furious", "actions": [], "facts": []})
    assert parse_reply(bad_emotion)[0] is None
    no_lists = json.dumps({"say": "а", "emotion": "happy"})
    assert parse_reply(no_lists)[0] == {"say": "а", "emotion": "happy", "actions": [], "facts": []}


# --- Проверка действий кодом ---

def oks(world, speaker, actions):
    return [c.ok for c in check_actions(world, speaker, actions)]


def test_actions_items(world):
    assert oks(world, "boris", [{"type": "give_item", "item": "room_key", "to": "kira"}]) == [True]
    assert oks(world, "lina", [{"type": "give_item", "item": "bow", "to": "kira"}]) == [False]
    assert oks(world, "boris", [{"type": "give_item", "item": "lina_sword", "to": "kira"}]) == [False]
    # Ключ один: второй раз отдать нельзя.
    twice = [{"type": "give_item", "item": "room_key", "to": "kira"}] * 2
    assert oks(world, "boris", twice) == [True, False]


def test_actions_money_people_places(world):
    assert oks(world, "boris", [{"type": "pay", "to": "kira", "amount": 100}]) == [False]
    assert oks(world, "boris", [{"type": "pay", "to": "kira", "amount": 40}]) == [True]
    assert oks(world, "yan", [{"type": "call", "character": "gordey"}]) == [False]
    assert oks(world, "yan", [{"type": "call", "character": "foma"}]) == [False]
    assert oks(world, "lina", [{"type": "move_to", "location": "castle"}]) == [False]
    assert oks(world, "lina", [{"type": "move_to", "location": "tavern"}]) == [True]
    assert oks(world, "lina", [{"type": "miracle", "text": "Гордей оживает"}]) == [False]
    assert oks(world, "lina", [{"type": "relation_change", "target": "kira", "trust": 50}]) == [False]
    assert oks(world, "lina", [{"type": "relation_change", "target": "kira", "trust": -5}]) == [True]
    assert oks(world, "lina", [{"type": "fly"}]) == [False]


# --- Сверка фактов ---

def verdicts(world, speaker, facts):
    return [c.verdict for c in check_facts(world, speaker, facts)]


def test_facts_against_canon(world):
    assert verdicts(world, "boris", [{"subject": "tavern", "predicate": "room_price", "object": "20 монет"}]) == ["match"]
    assert verdicts(world, "boris", [{"subject": "tavern", "predicate": "room_price", "object": "30"}]) == ["contradiction"]
    assert verdicts(world, "boris", [{"subject": "tavern", "predicate": "sign_color", "object": "синий"}]) == ["new"]


def test_lies_and_beliefs_allowed_only_for_owner(world):
    harvest = [{"subject": "olkhovka", "predicate": "harvest", "object": "погиб"}]
    assert verdicts(world, "yan", harvest) == ["match"]
    assert verdicts(world, "boris", harvest) == ["match"]
    assert verdicts(world, "lina", harvest) == ["contradiction"]


# --- Цикл валидатора ---

def test_invalid_action_regenerated(world):
    bad = reply("Держи лук.", actions=[{"type": "give_item", "item": "bow", "to": "kira"}])
    client = ScriptedClient([bad, NO_CONTRADICTION, reply("Лука у меня нет."), NO_CONTRADICTION])
    turn = run.run_turn(world, "lina", [], "Дай лук", client, client, True)
    assert turn["final"]["source"] == "regenerated"
    assert turn["final"]["reply"]["say"] == "Лука у меня нет."
    # Без валидатора невозможное действие прошло бы.
    assert [a["ok"] for a in turn["raw"]["verdict"]["actions"]] == [False]
    assert "Ответ отклонён" in client.seen[2][-1]["content"]


def test_only_bad_actions_are_dropped(world):
    bad = reply("Держи.", actions=[
        {"type": "give_item", "item": "room_key", "to": "kira"},
        {"type": "give_item", "item": "room_key", "to": "kira"},
    ])
    client = ScriptedClient([bad, NO_CONTRADICTION] * 3)
    turn = run.run_turn(world, "boris", [], "Два ключа", client, client, True)
    assert turn["final"]["source"] == "actions_dropped"
    assert len(turn["final"]["reply"]["actions"]) == 1


def test_contradiction_leads_to_fallback(world):
    wrong = reply("Комната — 30 монет.", facts=[{"subject": "tavern", "predicate": "room_price", "object": "30"}])
    client = ScriptedClient([wrong, NO_CONTRADICTION] * 3)
    turn = run.run_turn(world, "boris", [], "Цена?", client, client, True)
    assert turn["final"]["source"] == "fallback"
    assert turn["final"]["attempts"] == 3
    assert turn["final"]["reply"]["actions"] == []


def test_text_checker_rejects(world):
    yes = '{"contradiction": true, "reason": "Гордей жив"}'
    client = ScriptedClient([reply("Гордей в кузнице."), yes, reply("Гордей умер."), NO_CONTRADICTION])
    turn = run.run_turn(world, "boris", [], "Где Гордей?", client, client, True)
    assert turn["final"]["source"] == "regenerated"
    assert turn["raw"]["verdict"]["text"]["contradiction"] is True


def test_broken_json_retried_once(world):
    client = ScriptedClient(["не json", reply("Ладно."), NO_CONTRADICTION])
    turn = run.run_turn(world, "boris", [], "Привет", client, client, True)
    assert turn["raw"]["broken_first"] and not turn["raw"]["broken"]
    assert turn["final"]["source"] == "first"


def test_without_validator_keeps_raw(world):
    bad = reply("Держи лук.", actions=[{"type": "give_item", "item": "bow", "to": "kira"}])
    client = ScriptedClient([bad])
    turn = run.run_turn(world, "lina", [], "Дай лук", client, None, False)
    assert turn["final"]["source"] == "raw"


# --- Прогон целиком и отчёт ---

def test_fake_run_resume_and_report(tmp_path):
    out = tmp_path / "fake.jsonl"
    assert run.main(["--model", "fake", "--limit", "5", "--out", str(out)]) == 0
    assert run.main(["--model", "fake", "--limit", "5", "--out", str(out)]) == 0
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 5

    import judge
    assert judge.main([str(out)]) == 0
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert all("rules" in r["eval"] for r in records)
    summary = summarize(records)
    assert summary["cases"] == 5
    assert summary["final_invalid_actions"] == 0


def test_case_ok_prefers_judge_and_counts_actions():
    rec = {"eval": {"rules": {"final": {"ok": False}}, "judge": {"final": {"ok": True}},
                    "invalid_actions": {"final": 0}}}
    assert case_ok(rec, "final") is True
    rec["eval"]["invalid_actions"]["final"] = 1
    assert case_ok(rec, "final") is False


def test_list_models_filter():
    from list_models import filter_ids
    ids = ["xiaomi/mimo-v2.6-pro", "xiaomi/mimo-v2-flash", "deepseek-chat"]
    assert filter_ids(ids, "mimo pro") == ["xiaomi/mimo-v2.6-pro"]
    assert filter_ids(ids, "MIMO") == ids[:2]
    assert filter_ids(ids, "") == ids


def test_mimo_profile_loads():
    from llm import load_profiles
    mimo = load_profiles()["mimo"]
    assert mimo.url == "https://nano-gpt.com/api/v1"
    assert mimo.has_prices and mimo.max_tokens >= 2000


def test_profile_extra_goes_into_request():
    from llm import load_profiles
    client = ChatClient(load_profiles()["mimo-fast"], "key")
    sent = {}

    def fake_post(body):
        sent.update(body)
        return {"choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2,
                          "completion_tokens_details": {"reasoning_tokens": 0}}}

    client._post = fake_post
    comp = client.complete([{"role": "user", "content": "привет"}])
    assert sent["reasoning_effort"] == "none"
    assert comp.reasoning_tokens == 0 and comp.stats("npc")["reasoning_tokens"] == 0


def test_timing_script(tmp_path, capsys):
    import timing
    out = tmp_path / "fake.jsonl"
    assert run.main(["--model", "fake", "--limit", "2", "--out", str(out)]) == 0
    assert timing.main([str(out)]) == 0
    assert "ответ NPC" in capsys.readouterr().out

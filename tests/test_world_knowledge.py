"""Тесты ядра мира (версия 0.3): отношения, факты и знания NPC."""

import pytest

from matricaria.world import RuleError, World


@pytest.fixture
def world(tmp_path):
    w = World.create(tmp_path / "world.db", "Test village", seed=7)
    w.add_location("tavern", "Tavern", "tavern")
    w.add_character("hero", "Ash", controller="player", location_id="tavern")
    w.add_character("boris", "Boris", location_id="tavern")
    w.add_character("marta", "Marta", location_id="tavern")
    yield w
    w.close()


# --- Отношения --------------------------------------------------------------


def test_strangers_have_neutral_relation(world):
    relation = world.relation("boris", "hero")
    assert (relation.liking, relation.trust, relation.love) == (0, 0, 0)
    assert not relation.knows_name
    assert world.relations_of("boris") == []


def test_change_relation_clamps_to_scale(world):
    relation = world.change_relation("boris", "hero", liking=30, fear=-500, reason="gift")
    assert relation.liking == 30 and relation.fear == -100
    relation = world.change_relation("boris", "hero", love=-10)
    assert relation.love == 0  # любовь от 0 до 100
    event = world.events()[-2]
    assert event.data["to"] == {"liking": 30, "fear": -100}
    assert world.relation("hero", "boris").liking == 0  # отношения не симметричны


def test_change_relation_validation(world):
    with pytest.raises(RuleError):
        world.change_relation("boris", "hero", hatred=5)
    with pytest.raises(RuleError):
        world.change_relation("boris", "hero")
    with pytest.raises(RuleError):
        world.change_relation("boris", "boris", liking=5)


def test_set_relation_by_author(world):
    relation = world.set_relation("marta", "boris", liking=80, love=90, knows_name=True)
    assert relation.love == 90 and relation.knows_name
    with pytest.raises(RuleError):
        world.set_relation("marta", "boris", love=-5)
    with pytest.raises(RuleError):
        world.set_relation("marta", "boris", liking=5, basis="rules")


def test_learn_name(world):
    world.change_relation("boris", "hero", trust=10)
    world.learn_name("boris", "hero")
    relation = world.relation("boris", "hero")
    assert relation.knows_name and relation.trust == 10
    with pytest.raises(RuleError):
        world.learn_name("boris", "hero")


# --- Факты ------------------------------------------------------------------


def test_add_fact_and_contradiction(world):
    fact = world.add_fact("boris", "spouse_name", "Marta", source="setup")
    assert fact.status == "truth" and fact.current and not fact.canon
    with pytest.raises(RuleError, match="Contradicts"):
        world.add_fact("boris", "spouse_name", "Olga")
    with pytest.raises(RuleError, match="already fact"):
        world.add_fact("boris", "spouse_name", "Marta")
    # Слух может спорить с правдой: так и рождаются истории.
    rumor = world.add_fact("boris", "spouse_name", "Olga", status="rumor")
    assert rumor.status == "rumor"


def test_multiple_values(world):
    world.add_fact("boris", "child", "Ivan")
    world.add_fact("boris", "child", "Lena", multiple=True)
    assert [f.object for f in world.facts(subject="boris", predicate="child")] == ["Ivan", "Lena"]


def test_bad_fact(world):
    with pytest.raises(RuleError):
        world.add_fact("boris", "mood", "happy", status="maybe")
    with pytest.raises(RuleError):
        world.add_fact("boris", "", "x")


def test_change_fact_keeps_history(world):
    old = world.add_fact("boris", "job", "innkeeper")
    world.learn_fact("hero", old.id)
    new = world.change_fact(old.id, "farmer", source="dialog_3")
    assert new.object == "farmer" and new.current
    old = world.fact(old.id)
    assert not old.current and old.replaced_by == new.id
    assert [f.id for f in world.facts(subject="boris")] == [new.id]
    assert len(world.facts(subject="boris", current_only=False)) == 2
    # Герой помнит старое, пока не узнает новость.
    assert [k.fact.object for k in world.knowledge("hero")] == ["innkeeper"]
    with pytest.raises(RuleError, match="out of date"):
        world.change_fact(old.id, "miller")


def test_canon_only_by_author(world):
    with pytest.raises(RuleError, match="canon"):
        world.add_fact("world", "religion", "Sun", canon=True)
    canon = world.add_fact("world", "religion", "Sun", canon=True, basis="author")
    with pytest.raises(RuleError, match="canon"):
        world.change_fact(canon.id, "Moon")
    with pytest.raises(RuleError, match="canon"):
        world.end_fact(canon.id)
    assert world.change_fact(canon.id, "Moon", basis="author").canon


def test_end_fact(world):
    fact = world.add_fact("tavern", "is_open", "yes")
    world.end_fact(fact.id, reason="fire")
    assert world.facts(subject="tavern") == []
    assert world.events()[-1].kind == "fact_ended"


# --- Знания -----------------------------------------------------------------


def test_learn_and_believe(world):
    lie = world.add_fact("hero", "title", "prince", status="lie", source="hero told")
    world.learn_fact("boris", lie.id, believes=True, source="hero")
    world.learn_fact("marta", lie.id, believes=False, source="hero")
    knowledge = {k.character_id: k for k in
                 world.knowledge("boris") + world.knowledge("marta")}
    assert knowledge["boris"].believes and not knowledge["marta"].believes
    assert world.who_knows(lie.id) == ["boris", "marta"]
    assert world.knows("boris", lie.id) and not world.knows("hero", lie.id)
    with pytest.raises(RuleError, match="already knows"):
        world.learn_fact("boris", lie.id)
    # Марту переубедили.
    world.learn_fact("marta", lie.id, believes=True, source="boris")
    assert world.knowledge("marta")[0].believes


def test_omniscience_knows_all_truth(world):
    truth = world.add_fact("boris", "secret", "owes money")
    rumor = world.add_fact("boris", "secret", "is a spy", status="rumor")
    world.grant_ability("marta", "omniscience")
    known = [k.fact.id for k in world.knowledge("marta")]
    assert truth.id in known and rumor.id not in known
    assert world.knows("marta", truth.id)
    assert world.who_knows(truth.id) == []

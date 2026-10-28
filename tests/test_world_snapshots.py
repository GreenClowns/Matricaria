"""Тесты ядра мира (версия 0.3, часть 2): снимки, откат, режимы, время, тело, шаблоны."""

import pytest

from matricaria.world import RuleError, World
from matricaria.world.templates import (
    create_from_template,
    fill_world,
    read_template,
    template_names,
)


@pytest.fixture
def world(tmp_path):
    w = create_from_template(tmp_path / "demo" / "world.db", read_template("village"), seed=3)
    yield w
    w.close()


# --- Снимки и откат ---------------------------------------------------------


def test_snapshot_and_rollback(world):
    snap = world.take_snapshot("start")
    assert (world.snapshot_dir / snap.file).is_file()
    assert snap.last_event_id == world.last_event_id()
    world.kill("hero", cause="test")
    world.advance_time(60)
    before = world.rollback(snap.id)
    assert world.character("hero").alive
    assert world.time == 0
    event = world.events()[-1]
    assert event.kind == "rolled_back" and event.basis == "author"
    assert event.data["before_rollback_snapshot_id"] == before.id
    assert [s.id for s in world.snapshots()] == [snap.id, before.id]


def test_undone_future_is_kept(world):
    snap = world.take_snapshot()
    world.kill("hero")
    before = world.rollback(snap.id)
    world.rollback(before.id)
    assert not world.character("hero").alive
    assert [s.id for s in world.snapshots()] == [1, 2, 3]


def test_rollback_survives_reopen(tmp_path, world):
    snap = world.take_snapshot()
    world.grant_money("hero", 1000)
    world.rollback(snap.id)
    world.close()
    with World.open(tmp_path / "demo" / "world.db") as again:
        assert again.character("hero").cash == 30
        assert len(again.snapshots()) == 2


def test_rollback_errors(world):
    with pytest.raises(RuleError):
        world.rollback(99)
    snap = world.take_snapshot()
    (world.snapshot_dir / snap.file).unlink()
    with pytest.raises(RuleError, match="missing"):
        world.rollback(snap.id)


# --- Режим правил и время -----------------------------------------------------


def test_rule_mode(world):
    world.set_rule_mode("strict")
    assert world.info.rule_mode == "strict"
    assert world.events()[-1].data == {"from": "narrative", "to": "strict"}
    with pytest.raises(RuleError):
        world.set_rule_mode("strict")
    with pytest.raises(RuleError):
        world.set_rule_mode("chaos")
    with pytest.raises(RuleError):
        world.set_rule_mode("free", basis="rules")


def test_narrator_works_in_any_rule_mode(world):
    for mode in ("strict", "free"):
        world.set_rule_mode(mode)
        world.grant_money("hero", 1)
    assert world.character("hero").cash == 32


def test_advance_time(world):
    assert world.advance_time(90) == 90
    world.move_character("hero", "tavern")
    assert world.events()[-1].time == 90
    with pytest.raises(RuleError):
        world.advance_time(-5)
    with pytest.raises(RuleError):
        world.advance_time(0)


# --- Тело (D38) --------------------------------------------------------------


def test_body_defaults_and_template(world):
    assert world.character("hero").body == {
        "height_cm": 170, "muscles": 30, "fatness": 30, "build": "average",
        "bust_cm": None, "underbust_cm": None, "waist_cm": None, "hips_cm": None,
    }
    assert world.character("pip").body["height_cm"] == 15


def test_set_body(world):
    world.set_body("pip", height_cm=50_000, build="giant")
    body = world.character("pip").body
    assert body["height_cm"] == 50_000 and body["build"] == "giant"
    assert world.events()[-1].data["from"] == {"height_cm": 15, "build": "slender"}
    with pytest.raises(RuleError):
        world.set_body("pip", height_cm=50_001)
    with pytest.raises(RuleError):
        world.set_body("pip", height_cm=0)
    with pytest.raises(RuleError):
        world.set_body("pip", muscles=101)
    with pytest.raises(RuleError):
        world.set_body("pip", wings=2)
    with pytest.raises(RuleError):
        world.set_body("pip", muscles=50, basis="rules")


# --- Предметы ---------------------------------------------------------------


def test_remove_item(world):
    bread = world.items(owner_id="boris")[0]
    with pytest.raises(RuleError):
        world.remove_item(bread.id, basis="rules")
    world.remove_item(bread.id, reason="eaten by a ghost")
    assert world.items(owner_id="boris") == []
    assert world.events()[-1].data["name"] == "Rye bread"


# --- Шаблоны ----------------------------------------------------------------


def test_builtin_templates_load(tmp_path):
    assert {"village", "city"} <= set(template_names())
    for name in template_names():
        with create_from_template(tmp_path / name / "world.db", read_template(name),
                                  seed=1) as w:
            assert w.players(), name
            assert all(e.basis == "author" for e in w.events())


def test_village_contents(world):
    assert world.info.setting == "fantasy"
    assert world.item(1).equipped == "held"
    yan = {k.fact.object: k.believes for k in world.knowledge("yan")}
    assert yan["the capital"] is True  # Ян поверил лжи Бориса
    assert world.relation("boris", "marta").love == 75


def test_city_is_modern(tmp_path):
    with create_from_template(tmp_path / "c.db", read_template("city"), seed=1) as w:
        assert w.info.setting == "modern"
        pistol = next(i for i in w.items(owner_id="ross") if i.kind == "weapon")
        assert (pistol.damage_min, pistol.damage_max) == (3, 12)


def test_bad_template_names_the_entry(tmp_path):
    with pytest.raises(RuleError, match="Template character 'x'"):
        create_from_template(tmp_path / "bad.db", {
            "characters": [{"id": "x", "name": "X", "location": "moon"}],
        }, seed=1)
    assert not (tmp_path / "bad.db").exists()
    with World.create(tmp_path / "w.db", "W") as w:
        with pytest.raises(RuleError, match="has no field"):
            fill_world(w, {"locations": [{"id": "a"}]})
    with pytest.raises(RuleError, match="No world template"):
        read_template("atlantis")

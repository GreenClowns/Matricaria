"""Тесты ядра мира (версия 0.3): база, журнал, персонажи, предметы, деньги, места."""

import sqlite3

import pytest

from matricaria.world import NotFoundError, RuleError, SchemaError, World, format_time


@pytest.fixture
def world(tmp_path):
    """Маленькая деревня: площадь, таверна, герой, трактирщик и стражник."""
    w = World.create(tmp_path / "world.db", "Test village", seed=7)
    w.add_location("village", "Alder Village", "village")
    w.add_location("square", "Square", "square", parent_id="village")
    w.add_location("tavern", "Tavern", "tavern", parent_id="village")
    w.add_character("hero", "Ash", controller="player", location_id="square", cash=50)
    w.add_character("boris", "Boris", role="innkeeper", profession="innkeeper",
                    location_id="tavern", cash=100, bank=500)
    w.add_character("guard", "Yan", profession="guard", location_id="square",
                    stats={"endurance": 8, "strength": 7})
    yield w
    w.close()


# --- Мир и журнал --------------------------------------------------------


def test_create_and_reopen(tmp_path, world):
    info = world.info
    assert (info.name, info.setting, info.seed) == ("Test village", "fantasy", 7)
    assert info.rule_mode == "narrative"
    world.close()
    again = World.open(tmp_path / "world.db")
    assert again.character("boris").name == "Boris"
    assert again.events()[0].kind == "world_created"
    again.close()


def test_create_rejects_bad_settings(tmp_path):
    with pytest.raises(RuleError):
        World.create(tmp_path / "a.db", "A", setting="space")
    with pytest.raises(RuleError):
        World.create(tmp_path / "b.db", "B", rule_mode="chaos")
    with pytest.raises(RuleError):
        World.create(tmp_path / "c.db", "  ")


def test_create_refuses_existing_file(tmp_path, world):
    with pytest.raises(RuleError):
        World.create(tmp_path / "world.db", "Again")


def test_open_rejects_foreign_file(tmp_path):
    path = tmp_path / "other.db"
    sqlite3.connect(path).close()
    with pytest.raises(SchemaError):
        World.open(path)
    with pytest.raises(NotFoundError):
        World.open(tmp_path / "missing.db")


def test_event_log_is_append_only(world):
    count = len(world.events())
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        world._conn.execute("UPDATE event SET kind = 'forged'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        world._conn.execute("DELETE FROM event")
    assert len(world.events()) == count


def test_failed_change_leaves_no_trace(world):
    before = world.last_event_id()
    with pytest.raises(RuleError):
        world.pay("hero", "guard", 1000)
    assert world.last_event_id() == before
    assert world.character("hero").cash == 50


def test_events_filters(world):
    world.move_character("hero", "tavern")
    moved = world.events(kind="character_moved")
    assert len(moved) == 1 and moved[0].actor_id == "hero"
    assert moved[0].basis == "rules"
    assert all(e.kind != "world_created" for e in world.events(involving="hero"))
    assert world.events(involving="tavern")[-1].kind == "character_moved"
    assert len(world.events(limit=2)) == 2


def test_format_time():
    assert format_time(0) == "Day 1, 00:00"
    assert format_time(2 * 1440 + 14 * 60 + 20) == "Day 3, 14:20"


# --- Персонажи --------------------------------------------------------------


def test_character_defaults(world):
    guard = world.character("guard")
    assert guard.stats["strength"] == 7 and guard.stats["agility"] == 5
    assert guard.max_health == guard.health == 26  # 10 + 2 × выносливость 8
    assert guard.alive and guard.conscious
    assert [p.id for p in world.players()] == ["hero"]
    assert [c.id for c in world.characters(location_id="square")] == ["hero", "guard"]


def test_character_validation(world):
    with pytest.raises(RuleError, match="already exists"):
        world.add_character("hero", "Another")
    with pytest.raises(RuleError):
        world.add_character("x", "X", stats={"strength": 11})
    with pytest.raises(RuleError):
        world.add_character("x", "X", stats={"luck": 3})
    with pytest.raises(RuleError):
        world.add_character("x", "X", controller="robot")
    with pytest.raises(NotFoundError):
        world.add_character("x", "X", location_id="moon")
    with pytest.raises(NotFoundError):
        world.character("nobody")


def test_profession_change(world):
    world.set_profession("hero", "blacksmith")
    assert world.character("hero").profession == "blacksmith"
    event = world.events()[-1]
    assert event.data == {"from": "", "to": "blacksmith"}
    with pytest.raises(RuleError):
        world.set_profession("hero", "blacksmith")


def test_controller_change_only_by_author(world):
    with pytest.raises(RuleError):
        world.set_controller("boris", "player", basis="rules")
    world.set_controller("boris", "player")
    assert {p.id for p in world.players()} == {"hero", "boris"}


def test_stats_change(world):
    world.set_stat("hero", "charisma", 9)
    assert world.character("hero").stats["charisma"] == 9
    with pytest.raises(RuleError):
        world.set_stat("hero", "charisma", 0)
    with pytest.raises(RuleError, match="impossible under the rules"):
        world.set_stat("hero", "charisma", 8, basis="rules")


def test_damage_and_heal_stay_in_bounds(world):
    hero = world.change_health("hero", -5, cause="fall")
    assert hero.health == 15
    hero = world.change_health("hero", 100)
    assert hero.health == hero.max_health
    with pytest.raises(RuleError):
        world.change_health("hero", 0)


def test_death_from_damage(world):
    boris = world.change_health("boris", -999, actor_id="guard", cause="sword")
    assert boris.health == 0 and not boris.alive
    kinds = [e.kind for e in world.events()[-2:]]
    assert kinds == ["health_changed", "character_died"]
    with pytest.raises(RuleError, match="only revival"):
        world.change_health("boris", 5)
    with pytest.raises(RuleError, match="dead"):
        world.move_character("boris", "square")


def test_immortal_never_drops_below_one(world):
    world.grant_ability("hero", "immortality")
    hero = world.change_health("hero", -999)
    assert hero.health == 1 and hero.alive


def test_kill_and_revive_need_author_or_ability(world):
    with pytest.raises(RuleError):
        world.kill("boris", basis="rules")
    world.kill("boris", cause="author's will")
    assert not world.character("boris").alive
    with pytest.raises(RuleError):
        world.revive("boris", basis="rules")
    with pytest.raises(RuleError, match="no ability"):
        world.revive("boris", basis="ability", actor_id="hero")
    world.grant_ability("hero", "divine_will")
    world.revive("boris", basis="ability", actor_id="hero", health=3)
    boris = world.character("boris")
    assert boris.alive and boris.health == 3
    assert world.events()[-1].basis == "ability"


def test_immortal_cannot_be_killed_by_ability(world):
    world.grant_ability("hero", "divine_will")
    world.grant_ability("guard", "immortality")
    with pytest.raises(RuleError, match="immortal"):
        world.kill("guard", basis="ability", actor_id="hero")
    world.kill("guard")  # автор может всё
    assert not world.character("guard").alive


def test_dead_or_unconscious_cannot_act(world):
    world.add_condition("hero", "unconscious")
    assert not world.character("hero").conscious
    with pytest.raises(RuleError, match="unconscious"):
        world.move_character("hero", "tavern")
    world.remove_condition("hero", "unconscious")
    world.move_character("hero", "tavern")


def test_conditions(world):
    world.add_condition("guard", "Wounded", cause="arrow")
    assert world.character("guard").conditions == ("wounded",)
    with pytest.raises(RuleError):
        world.add_condition("guard", "wounded")
    with pytest.raises(RuleError):
        world.remove_condition("guard", "stunned")
    world.kill("guard")
    assert world.character("guard").conditions == ()


def test_abilities(world):
    with pytest.raises(RuleError):
        world.grant_ability("hero", "magic:fire", basis="rules")
    world.grant_ability("hero", "magic:fire", {"power": 2})
    hero = world.character("hero")
    assert hero.has_ability("magic:fire") and hero.abilities["magic:fire"] == {"power": 2}
    with pytest.raises(RuleError):
        world.grant_ability("hero", "magic:fire")
    world.remove_ability("hero", "magic:fire")
    assert not world.character("hero").has_ability("magic:fire")


def test_dead_character_cannot_use_ability(world):
    world.grant_ability("hero", "divine_will")
    world.kill("boris")
    world.kill("hero")
    with pytest.raises(RuleError, match="dead"):
        world.revive("boris", basis="ability", actor_id="hero")


# --- Места и перемещения -----------------------------------------------------


def test_locations(world):
    assert [loc.id for loc in world.locations(parent_id="village")] == ["square", "tavern"]
    with pytest.raises(RuleError, match="already a place"):
        world.add_location("tavern2", "tavern", "tavern", parent_id="village")
    with pytest.raises(NotFoundError):
        world.add_location("x", "X", "house", parent_id="nowhere")


def test_location_discovered_during_play(world):
    world.add_location("mill", "Old mill", "mill", parent_id="village",
                       discovered_by="hero", basis="rules", actor_id="hero")
    mill = world.location("mill")
    assert mill.discovered_by == "hero" and mill.discovered_at == world.time
    event = world.events()[-1]
    assert event.kind == "location_added" and set(event.participants) == {"mill", "hero"}


def test_move(world):
    world.move_character("hero", "tavern")
    assert world.character("hero").location_id == "tavern"
    assert world.events()[-1].data == {"from": "square", "to": "tavern"}
    with pytest.raises(RuleError, match="already"):
        world.move_character("hero", "tavern")
    with pytest.raises(NotFoundError):
        world.move_character("hero", "moon")
    with pytest.raises(RuleError, match="decides"):
        world.move_character("boris", "square", actor_id="hero")
    world.move_character("boris", "square", basis="author")


# --- Предметы ---------------------------------------------------------------


def test_items_appear_only_by_author_or_ability(world):
    with pytest.raises(RuleError):
        world.create_item("food", "Bread", owner_id="hero", basis="rules")
    bread = world.create_item("food", "Bread", owner_id="hero", base_price=2)
    assert world.items(owner_id="hero") == [bread]
    with pytest.raises(RuleError):
        world.create_item("food", "Bread")
    with pytest.raises(RuleError):
        world.create_item("weapon", "Bad", owner_id="hero", damage=(5, 2))


def test_give_item_rules(world):
    sword = world.create_item("weapon", "Sword", owner_id="hero", damage=(2, 8))
    with pytest.raises(RuleError, match="not here"):
        world.give_item(sword.id, "boris")
    world.give_item(sword.id, "guard")
    assert world.item(sword.id).owner_id == "guard"
    with pytest.raises(RuleError, match="Only the owner"):
        world.give_item(sword.id, "hero", actor_id="hero")
    world.give_item(sword.id, "boris", basis="author")
    assert world.item(sword.id).owner_id == "boris"


def test_pick_up_and_drop(world):
    coin = world.create_item("trinket", "Old coin", location_id="tavern")
    with pytest.raises(RuleError, match="not here"):
        world.pick_up(coin.id, "hero")
    world.pick_up(coin.id, "boris")
    assert world.item(coin.id).owner_id == "boris"
    with pytest.raises(RuleError, match="does not have"):
        world.drop_item(coin.id, "hero")
    world.drop_item(coin.id, "boris")
    assert world.item(coin.id).location_id == "tavern"
    assert world.items(location_id="tavern")[0].id == coin.id


def test_place_item_by_author(world):
    ring = world.create_item("jewel", "Ring", owner_id="hero")
    with pytest.raises(RuleError):
        world.place_item(ring.id, "tavern", basis="rules")
    world.place_item(ring.id, "tavern")
    assert world.item(ring.id).location_id == "tavern"


def test_equip(world):
    sword = world.create_item("weapon", "Sword", owner_id="hero")
    world.equip(sword.id, "held")
    assert world.item(sword.id).equipped == "held"
    with pytest.raises(RuleError):
        world.equip(sword.id, "held")
    with pytest.raises(RuleError):
        world.equip(sword.id, "thrown")
    world.give_item(sword.id, "guard")
    assert world.item(sword.id).equipped is None


def test_dead_drop_their_weapons(world):
    sword = world.create_item("weapon", "Sword", owner_id="guard")
    world.equip(sword.id, "held")
    world.kill("guard")
    assert world.item(sword.id).equipped is None
    assert world.item(sword.id).owner_id == "guard"


def test_missing_item(world):
    with pytest.raises(NotFoundError):
        world.give_item(999, "hero")


# --- Деньги -----------------------------------------------------------------


def test_cash_payment_in_person(world):
    with pytest.raises(RuleError, match="not here"):
        world.pay("hero", "boris", 10)
    world.move_character("hero", "tavern")
    world.pay("hero", "boris", 10, reason="room")
    assert world.character("hero").cash == 40
    assert world.character("boris").cash == 110
    with pytest.raises(RuleError, match="has only"):
        world.pay("hero", "boris", 41)
    with pytest.raises(RuleError):
        world.pay("hero", "boris", -5)
    with pytest.raises(RuleError):
        world.pay("hero", "hero", 5)


def test_bank_transfer_works_at_distance(world):
    world.pay("boris", "hero", 200, account="bank")
    assert world.character("hero").bank == 200
    assert world.character("boris").bank == 300


def test_deposit_and_withdraw(world):
    world.deposit("hero", 30)
    hero = world.character("hero")
    assert (hero.cash, hero.bank) == (20, 30)
    world.withdraw("hero", 10)
    hero = world.character("hero")
    assert (hero.cash, hero.bank) == (30, 20)
    with pytest.raises(RuleError):
        world.withdraw("hero", 100)


def test_dead_cannot_pay(world):
    world.kill("boris")
    with pytest.raises(RuleError, match="dead"):
        world.pay("boris", "hero", 1, account="bank")


def test_grant_money(world):
    with pytest.raises(RuleError):
        world.grant_money("hero", 100, basis="rules")
    world.grant_money("hero", 100, reason="treasure")
    assert world.character("hero").cash == 150
    world.grant_money("hero", -150)
    assert world.character("hero").cash == 0
    with pytest.raises(RuleError, match="has only"):
        world.grant_money("hero", -1)

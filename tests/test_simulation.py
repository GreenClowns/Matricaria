"""Тесты симуляции мира (версия 0.4, часть 1): календарь, seed, распорядок, деньги."""

import json
import shutil
import sqlite3
import time

import pytest

from matricaria.cli import main, parse_duration
from matricaria.server import Session
from matricaria.world import CLOCK, RuleError, World, format_date
from matricaria.world.calendar import date_of
from matricaria.world.chance import rng
from matricaria.world.routines import _payday, load_rules
from matricaria.world.schema import NPC_STATE, SCHEMA
from matricaria.world.templates import create_from_template, read_template

DAY = 1440


def make(tmp_path, name="village", seed=7, folder="w"):
    return create_from_template(tmp_path / folder / "world.db", read_template(name), seed=seed)


def story(world):
    """Журнал без отметок о пропуске времени: их число зависит от того, как пропускали."""
    return [(e.time, e.kind, e.actor_id, e.participants, e.data)
            for e in world.events() if e.kind != "time_advanced"]


# --- Календарь и случайность --------------------------------------------------


def test_calendar():
    start = date_of(0)
    assert (start.year, start.month, start.day, start.weekday) == (1, 1, 1, 0)
    assert start.month_name == "Early Spring"
    assert date_of(90 * DAY).season == "summer"
    assert date_of(360 * DAY).year == 2
    assert date_of(7 * DAY).weekday == 0
    assert format_date(6 * DAY + 14 * 60 + 5) == "Sunday, Early Spring 7, Year 1, 14:05"


def test_rng_depends_only_on_seed_and_keys():
    assert rng(1, "a", 5).random() == rng(1, "a", 5).random()
    assert rng(1, "a", 5).random() != rng(2, "a", 5).random()
    assert rng(1, "a", 5).random() != rng(1, "a", 6).random()


def test_routines():
    innkeeper = load_rules("fantasy").routine("innkeeper")
    assert innkeeper.block_at(3 * 60) == "sleep"
    assert innkeeper.block_at(12 * 60) == "work"
    assert innkeeper.block_at(23 * 60 + 10) == "free"
    assert innkeeper.next_change(12 * 60) == 23 * 60
    guard = load_rules("fantasy").routine("guard")
    assert guard.block_at(6 * DAY + 12 * 60) == "free"  # воскресенье — выходной
    assert load_rules("modern").routine("nobody").days_off == {"sat", "sun"}
    # Выходной в день выплаты — платят накануне.
    assert _payday("fri", frozenset({"fri"})) == "thu"


def test_parse_duration():
    assert parse_duration("2w") == 14 * DAY
    assert parse_duration("1mo") == 30 * DAY
    assert parse_duration("1y2d") == 362 * DAY
    assert parse_duration("90m") == 90
    assert parse_duration("morning", now=5 * 60) == 2 * 60
    assert parse_duration("morning", now=8 * 60) == 23 * 60


# --- Детерминированность ------------------------------------------------------


@pytest.mark.parametrize("template", ["village", "city"])
def test_same_seed_same_story(tmp_path, template):
    stories = []
    for folder, seed in (("a", 5), ("b", 5), ("c", 6)):
        with make(tmp_path, template, seed=seed, folder=folder) as world:
            world.advance_time(30 * DAY)
            stories.append(story(world))
    assert stories[0] == stories[1]
    assert stories[0] != stories[2]
    assert len(stories[0]) > 200


def test_skip_in_parts_is_the_same_as_at_once(tmp_path):
    with make(tmp_path, folder="once") as world:
        world.advance_time(10 * DAY)
        once = story(world)
    with make(tmp_path, folder="days") as world:
        for _ in range(10):
            world.advance_time(DAY)
        assert story(world) == once
    with make(tmp_path, folder="clock") as world:
        for _ in range(300):
            world.advance_time(1, reason=CLOCK)
        world.advance_time(10 * DAY - 300)
        assert story(world) == once


def test_month_is_fast(tmp_path):
    with make(tmp_path) as world:
        started = time.perf_counter()
        world.advance_time(30 * DAY)
        assert time.perf_counter() - started < 5


def test_rollback_replays_the_same_future(tmp_path):
    with make(tmp_path) as world:
        snap = world.take_snapshot()
        report = world.skip_time(3 * DAY)
        first = story(world)[-report.events + 1:]
        world.rollback(snap.id)
        report = world.skip_time(3 * DAY)
        assert story(world)[-report.events + 1:] == first


# --- Распорядок ---------------------------------------------------------------


def test_villagers_follow_their_routine(tmp_path):
    with make(tmp_path) as world:
        world.advance_time(3 * 60)  # понедельник, 03:00: все спят дома
        assert world.character("boris").location_id == "marta_house"
        assert world.character("yan").location_id == "guardhouse"
        assert world.npc_state("boris").activity == "sleep"
        world.advance_time(11 * 60)  # 14:00: Борис в трактире
        assert world.character("boris").location_id == "tavern"
        assert world.npc_state("boris").activity in ("work", "eat")
        assert world.npc_state("hero") is None  # героем управляет игрок


def test_needs_stay_in_bounds(tmp_path):
    with make(tmp_path) as world:
        world.advance_time(20 * DAY)
        for c in world.characters():
            state = world.npc_state(c.id)
            if state:
                assert all(0 <= value <= 100 for value in state.needs.values())


def test_dead_do_not_walk(tmp_path):
    with make(tmp_path) as world:
        world.kill("yan")
        world.advance_time(3 * DAY)
        assert world.character("yan").location_id == "square"
        assert not world.events(involving="yan", kind="character_moved")


def test_clock_ticks_are_not_logged(tmp_path):
    with make(tmp_path) as world:
        for _ in range(30):
            world.advance_time(2, reason=CLOCK)
        assert world.time == 60
        assert not world.events(kind="time_advanced")
        world.advance_time(60, reason="test")
        assert world.events(kind="time_advanced")[-1].data["reason"] == "test"


# --- Деньги -------------------------------------------------------------------


def test_money_moves_through_the_village(tmp_path):
    with make(tmp_path) as world:
        total = sum(c.cash + c.bank for c in world.characters())
        report = world.skip_time(7 * DAY)
        wages = world.events(kind="money_earned", involving="yan")
        assert wages and wages[0].data["source"] == "wage"
        assert date_of(wages[0].time).weekday == 4  # пятница
        assert world.events(kind="money_earned", involving="boris")
        meals = world.events(kind="money_paid")
        assert meals and all(e.participants[1] == "boris" for e in meals)
        earned = sum(e.data["amount"] for e in world.events(kind="money_earned"))
        assert sum(c.cash + c.bank for c in world.characters()) == total + earned
        assert report.money["boris"] > 0
        assert all(e.basis == "rules" for e in world.events(after_id=report.first_event_id))


def _bar(tmp_path, setting, guest_cash, guest_bank):
    """Маленький мир: одно заведение, хозяин и гость, которому некуда идти."""
    place = "tavern" if setting == "fantasy" else "cafe"
    world = World.create(tmp_path / setting / "world.db", "Bar", setting=setting, seed=1)
    world.add_location(place, "The Place", place)
    owner = "innkeeper" if setting == "fantasy" else "barista"
    world.add_character("owner", "Owner", profession=owner, location_id=place, work_id=place)
    world.add_character("guest", "Guest", location_id=place, cash=guest_cash, bank=guest_bank)
    world.set_places("guest", home_id="")
    return world


def test_broke_guest_cannot_pay(tmp_path):
    with _bar(tmp_path, "fantasy", 0, 500) as world:
        world.advance_time(DAY)
        assert world.events(kind="could_not_afford", involving="guest")
        assert not world.events(kind="money_paid")
        assert world.character("guest").bank == 500  # в фэнтези картой не платят


def test_modern_guest_pays_by_card(tmp_path):
    with _bar(tmp_path, "modern", 0, 50_000) as world:
        world.advance_time(DAY)
        paid = world.events(kind="money_paid", involving="guest")
        assert paid and paid[0].data["account"] == "bank"
        assert not world.events(kind="could_not_afford")


def test_earn_and_spend_follow_the_rules(tmp_path):
    with make(tmp_path) as world:
        with pytest.raises(RuleError):
            world.earn_money("yan", 5, source="theft")
        with pytest.raises(RuleError):
            world.spend_money("yan", 10_000)
        world.kill("pip")
        with pytest.raises(RuleError):
            world.earn_money("pip", 5, source="wage")


# --- Уровни детализации ------------------------------------------------------


def test_detail_levels(tmp_path):
    with make(tmp_path) as world:
        world.advance_time(DAY)
        assert world.npc_state("pip").level == "far"  # лес — другое место мира
        assert not world.events(kind="character_moved", involving="pip")
        world.move_character("hero", "forest")
        world.advance_time(1, reason=CLOCK)
        assert world.npc_state("pip").level == "near"


def test_long_skip_counts_weeks(tmp_path):
    with make(tmp_path) as world:
        report = world.skip_time(90 * DAY)
        assert world.npc_state("boris").level == "summary"
        assert report.counts.get("money_spent")
        assert report.counts.get("character_moved", 0) < 10
        weekly = [e for e in world.events(kind="money_earned", involving="boris")]
        assert "for 7 days" in weekly[1].data["note"]


# --- Старые сохранения -------------------------------------------------------


def _old_world(path):
    """Мир, сохранённый версией 0.3 (схема 1)."""
    sql = (SCHEMA.replace(NPC_STATE, "")
           .replace("    home_id     TEXT    REFERENCES location(id),\n", "")
           .replace("    work_id     TEXT    REFERENCES location(id),\n", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(sql)
    conn.executescript("""
        INSERT INTO world (id, name, setting, seed, rule_mode, scenario_type, travel)
            VALUES (1, 'Old', 'fantasy', 1, 'narrative', 'standard', 'map');
        INSERT INTO location (id, name, kind) VALUES ('tavern', 'Tavern', 'tavern');
        INSERT INTO character (id, name, profession, controller, location_id)
            VALUES ('boris', 'Boris', 'innkeeper', 'ai', 'tavern');
        INSERT INTO stats (character_id, strength, agility, endurance, intellect, charisma,
            max_health, health, height_cm, muscles, fatness)
            VALUES ('boris', 5, 5, 5, 5, 5, 20, 20, 170, 30, 30);
        INSERT INTO event (time, kind, basis) VALUES (0, 'world_created', 'author');
        PRAGMA user_version = 1;
    """)
    conn.close()


def test_old_save_is_upgraded(tmp_path):
    path = tmp_path / "old" / "world.db"
    _old_world(path)
    with World.open(path) as world:
        assert world.events()[-1].kind == "schema_upgraded"
        boris = world.character("boris")
        assert boris.home_id == boris.work_id == "tavern"
        world.advance_time(DAY)
        assert world.events(kind="money_earned")
    with World.open(path) as world:  # второй раз обновлять нечего
        assert len(world.events(kind="schema_upgraded")) == 1


def test_rollback_to_old_snapshot(tmp_path):
    path = tmp_path / "old" / "world.db"
    _old_world(path)
    (path.parent / "snapshots").mkdir()
    shutil.copy(path, path.parent / "snapshots" / "0001.db")
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO snapshot (id, time, last_event_id, file) VALUES (1, 0, 1, '0001.db')")
    conn.commit()
    conn.close()
    with World.open(path) as world:
        world.advance_time(DAY)
        world.rollback(1)
        assert world.time == 0 and world.npc_state("boris") is None
        world.advance_time(DAY)
        assert world.npc_state("boris").activity


# --- Консоль и окно -----------------------------------------------------------


def test_cli_wait_prints_a_report(tmp_path, capsys):
    assert main(["--saves", str(tmp_path), "new", "demo", "--seed", "1"]) == 0
    assert main(["--saves", str(tmp_path), "wait", "demo", "1w"]) == 0
    out = capsys.readouterr().out
    assert "7 days passed" in out and "moves" in out and "Money: Boris +" in out
    assert main(["--saves", str(tmp_path), "show", "demo", "yan"]) == 0
    out = capsys.readouterr().out
    assert "Home: guardhouse. Work: square." in out and "Needs: food" in out
    assert main(["--saves", str(tmp_path), "places", "demo", "yan", "--home", "tavern"]) == 0
    assert main(["--saves", str(tmp_path), "status", "demo"]) == 0
    assert "Early Spring 8" in capsys.readouterr().out


def test_window_clock_and_report(tmp_path):
    with make(tmp_path) as world:
        session = Session(world)

        def ask(kind, data):
            return session.handle(json.dumps({"type": kind, "id": 1, "data": data}))

        reply = ask("time.tick", {"minutes": 4})
        assert reply["type"] == "world.state" and reply["data"]["world"]["time"] == 4
        assert not world.events(kind="time_advanced")
        assert ask("time.tick", {"minutes": 500})["data"]["code"] == "rule"
        reply = ask("time.skip", {"minutes": DAY})
        state = reply["data"]
        assert "things happened" in state["report"][1]
        assert state["world"]["date_text"].startswith("Tuesday")
        boris = next(c for c in state["characters"] if c["id"] == "boris")
        assert boris["activity"]
        sheet = ask("character.get", {"id": "yan"})["data"]
        assert sheet["home_id"] == "guardhouse" and set(sheet["needs"]) >= {"food", "rest"}

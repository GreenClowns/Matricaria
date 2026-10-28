"""Тесты обхватов тела и размера бюстгальтера (идея И1, D58)."""

import json
import sqlite3

import pytest

from matricaria.cli import main
from matricaria.server import Session
from matricaria.world import RuleError, World
from matricaria.world.measures import bra_size, format_length
from matricaria.world.schema import NPC_STATE, SCHEMA, schema_version
from matricaria.world.templates import create_from_template, read_template
from test_simulation import without_measures


def test_bra_size():
    assert bra_size(84, 76) == "30C"
    assert bra_size(87, 72) == "28DDD"
    assert bra_size(110, 74) == "30M"
    assert bra_size(8, 7) == "4AA"
    assert bra_size(80, 80) == "32AA"  # грудь не больше пояса — самая маленькая чашка
    assert bra_size(600_000, 78) == "32, cup off the chart"
    assert bra_size(None, 76) is None and bra_size(84, None) is None


def test_format_length():
    assert format_length(92) == "92 cm"
    assert format_length(1500) == "15 m"
    assert format_length(600_000) == "6 km"
    assert format_length(92, "in") == "36.2 in"
    assert format_length(600_000, "in") == "3.7 mi"


@pytest.fixture
def city(tmp_path):
    w = create_from_template(tmp_path / "town" / "world.db", read_template("city"), seed=1)
    yield w
    w.close()


def test_five_sizes_in_starting_worlds(city, tmp_path):
    sizes = {cid: city.character(cid).bra_size for cid in ("nina", "kim", "vera", "ross")}
    assert sizes == {"nina": "28DDD", "kim": "30M", "vera": "32, cup off the chart", "ross": None}
    assert city.character("vera").body["bust_cm"] == 600_000
    with create_from_template(tmp_path / "v" / "world.db", read_template("village"), seed=1) as v:
        assert v.character("pip").bra_size == "4AA"
        assert v.character("marta").bra_size == "30C"
        assert v.character("boris").bra_size is None


def test_measurements_are_checked(city):
    with pytest.raises(RuleError):
        city.set_body("nina", underbust_cm=100)  # больше груди
    with pytest.raises(RuleError):
        city.set_body("nina", bust_cm=0)
    with pytest.raises(RuleError):
        city.set_body("nina", waist_cm=2_000_000)  # больше 10 км
    city.set_body("nina", bust_cm=95)
    assert city.character("nina").bra_size == "28I"
    city.set_body("nina", bust_cm=None)
    assert city.character("nina").bra_size is None
    event = city.events()[-1]
    assert event.kind == "body_changed" and event.data["to"] == {"bust_cm": None}


def test_cli_show_and_body(tmp_path, capsys):
    saves = ["--saves", str(tmp_path)]
    assert main([*saves, "new", "town", "--template", "city", "--seed", "1"]) == 0
    assert main([*saves, "show", "town", "kim"]) == 0
    assert "bust 110 cm" in capsys.readouterr().out
    assert main([*saves, "show", "town", "vera", "--inches"]) == 0
    out = capsys.readouterr().out
    assert "bust 3.7 mi" in out and "cup off the chart" in out
    assert main([*saves, "body", "town", "ross", "--bust", "100", "--underbust", "90"]) == 0
    assert "Bra size (US): 36C" in capsys.readouterr().out
    assert main([*saves, "body", "town", "ross", "--bust", "0"]) == 0
    assert "Bra size" not in capsys.readouterr().out
    assert main([*saves, "show", "town", "ross"]) == 0
    assert "Measurements: underbust 90 cm" in capsys.readouterr().out


def test_window_sheet_has_measurements(city):
    reply = Session(city).handle(json.dumps({"type": "character.get", "data": {"id": "nina"}}))
    sheet = reply["data"]
    assert sheet["bra_size"] == "28DDD" and sheet["body"]["hips_cm"] == 94


def test_world_from_0_4_part_1_is_upgraded(tmp_path):
    """Мир схемы 2 (0.4, часть 1) получает столбцы обхватов, они пустые."""
    path = tmp_path / "w" / "world.db"
    path.parent.mkdir()
    conn = sqlite3.connect(path)
    conn.executescript(without_measures(SCHEMA))
    conn.executescript("""
        INSERT INTO world (id, name, setting, seed, rule_mode, scenario_type, travel)
            VALUES (1, 'Old', 'modern', 1, 'narrative', 'standard', 'map');
        INSERT INTO character (id, name, controller) VALUES ('nina', 'Nina', 'ai');
        INSERT INTO stats (character_id, strength, agility, endurance, intellect, charisma,
            max_health, health, height_cm, muscles, fatness)
            VALUES ('nina', 5, 5, 5, 5, 5, 20, 20, 170, 30, 30);
        PRAGMA user_version = 2;
    """)
    conn.close()
    assert NPC_STATE in SCHEMA
    with World.open(path) as world:
        assert schema_version(world._conn) == 3
        assert world.events()[-1].data == {"from": 2, "to": 3}
        assert world.character("nina").bra_size is None
        world.set_body("nina", bust_cm=90, underbust_cm=75)
        assert world.character("nina").bra_size == "30DD"

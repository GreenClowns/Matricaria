"""Тесты консольной программы `matricaria` (версия 0.3)."""

import pytest

from matricaria.cli import main, parse_duration


@pytest.fixture
def run(tmp_path, capsys):
    """Запускает команду и возвращает (код выхода, вывод, ошибки)."""

    def _run(*args):
        code = main(["--saves", str(tmp_path), *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def demo(run):
    code, out, _ = run("new", "demo", "--seed", "42")
    assert code == 0 and "Alder Village" in out
    return run


def test_new_status_show(demo):
    code, out, _ = demo("status", "demo")
    assert code == 0 and "Hero: Ash" in out and "Seed: 42" in out
    code, out, _ = demo("show", "demo", "boris")
    assert "owes_money_to = yan" in out and "[lie]" in out
    code, out, _ = demo("worlds")
    assert "demo" in out


def test_new_refuses_existing(demo):
    code, _, err = demo("new", "demo")
    assert code == 1 and "already exists" in err


def test_new_city_and_empty(run):
    code, out, _ = run("new", "town", "--template", "city", "--rules", "strict")
    assert code == 0 and "(modern)" in out and "strict" in out
    code, out, _ = run("new", "blank", "--template", "empty", "--setting", "modern")
    assert code == 0
    code, out, _ = run("status", "blank")
    assert "modern" in out


def test_snapshot_rollback_cycle(demo):
    assert demo("snapshot", "demo", "start")[0] == 0
    assert demo("kill", "demo", "hero", "--cause", "storm")[0] == 0
    code, out, _ = demo("show", "demo", "hero")
    assert "DEAD" in out
    code, out, _ = demo("rollback", "demo", "1")
    assert code == 0 and "snapshot #2" in out
    code, out, _ = demo("show", "demo", "hero")
    assert "alive" in out
    code, out, _ = demo("snapshots", "demo")
    assert "start" in out and "before rollback" in out
    code, out, _ = demo("log", "demo", "--last", "1")
    assert "rolled back" in out


def test_narrator_commands(demo):
    assert demo("kill", "demo", "boris")[0] == 0
    code, out, _ = demo("revive", "demo", "boris", "--health", "5")
    assert "5/20" in out
    code, out, _ = demo("give", "demo", "hero", "weapon", "Magic axe", "--damage", "3-9")
    assert code == 0 and "Magic axe" in out
    item_id = out.split("#")[1].split()[0]
    assert demo("take", "demo", item_id)[0] == 0
    code, out, _ = demo("money", "demo", "hero", "70")
    assert "cash 100 copper" in out
    assert demo("move", "demo", "hero", "forest")[0] == 0
    assert demo("stat", "demo", "hero", "charisma", "9")[0] == 0
    code, out, _ = demo("body", "demo", "pip", "--height", "50000")
    assert "500 m" in out
    assert demo("relation", "demo", "yan", "hero", "--trust", "40", "--knows-name")[0] == 0
    assert demo("ability", "demo", "hero", "immortality")[0] == 0
    assert demo("controller", "demo", "marta", "player")[0] == 0
    assert demo("health", "demo", "hero", "-100")[0] == 0
    code, out, _ = demo("show", "demo", "hero")
    assert "Health: 1/" in out and "immortality" in out and "charisma 9" in out
    code, out, _ = demo("log", "demo", "--last", "0")
    assert out.count("[author]") >= 12


def test_fact_commands(demo):
    code, out, _ = demo("fact", "demo", "add", "boris", "favourite_food", "mushrooms")
    fact_id = out.split("#")[1].rstrip(".\n")
    assert demo("teach", "demo", "hero", fact_id, "--disbelieve")[0] == 0
    code, out, _ = demo("show", "demo", "hero")
    assert "does not believe" in out
    code, out, _ = demo("fact", "demo", "change", fact_id, "turnips")
    assert "replaced by" in out
    code, out, _ = demo("facts", "demo", "--about", "boris", "--all")
    assert "mushrooms" in out and "turnips" in out
    code, _, err = demo("fact", "demo", "add", "only", "two")
    assert code == 1 and "Usage" in err


def test_rules_and_wait(demo):
    code, out, _ = demo("rules", "demo", "free")
    assert "free" in out
    code, out, _ = demo("wait", "demo", "1d6h")
    assert "Day 2, 06:00" in out
    code, _, err = demo("wait", "demo", "soon")
    assert code == 1 and "Cannot read duration" in err


def test_errors_are_friendly(demo):
    code, _, err = demo("money", "demo", "hero", "-1000")
    assert code == 1 and err.startswith("Error:") and "has only" in err
    code, _, err = demo("status", "nowhere")
    assert code == 1 and "not found" in err
    code, _, err = demo("show", "demo", "ghost")
    assert code == 1 and "No character" in err


def test_parse_duration():
    assert parse_duration("90") == 90
    assert parse_duration("45m") == 45
    assert parse_duration("2h") == 120
    assert parse_duration("1d6h30m") == 1440 + 360 + 30

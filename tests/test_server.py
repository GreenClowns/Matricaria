"""Тесты сервера ядра для окна Godot (версия 0.3.5)."""

import asyncio
import json

import pytest

from matricaria.server import Session, layout, serve
from matricaria.world.templates import create_from_template, read_template


@pytest.fixture
def world(tmp_path):
    w = create_from_template(tmp_path / "demo" / "world.db", read_template("village"), seed=1)
    yield w
    w.close()


@pytest.fixture
def session(world):
    return Session(world)


def ask(session, kind, data=None, message_id=1):
    return session.handle(json.dumps({"type": kind, "id": message_id, "data": data or {}}))


def inside(inner, outer):
    return (outer["x"] <= inner["x"] and outer["y"] <= inner["y"]
            and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
            and inner["y"] + inner["h"] <= outer["y"] + outer["h"])


def overlap(a, b):
    return not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"]
                or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def test_layout_nests_and_does_not_overlap(world):
    rects = layout(world)
    assert set(rects) == {loc.id for loc in world.locations()}
    for child in ("square", "tavern", "marta_house"):
        assert inside(rects[child], rects["alder"])
        assert rects[child]["depth"] == 1
    assert not overlap(rects["alder"], rects["forest"])
    assert not overlap(rects["square"], rects["tavern"])
    assert not overlap(rects["tavern"], rects["marta_house"])


def test_world_state(session):
    reply = ask(session, "world.get", message_id=7)
    assert reply["type"] == "world.state" and reply["id"] == 7
    state = reply["data"]
    assert state["world"]["name"] == "Alder Village"
    assert state["world"]["time_text"] == "Day 1, 00:00"
    assert state["player_id"] == "hero"
    pip = next(c for c in state["characters"] if c["id"] == "pip")
    assert pip["height_cm"] == 15 and pip["location_id"] == "forest"
    assert any(i["name"] == "Rusty cellar key" for i in state["items"])
    assert len(state["log"]) == 40 and "fact learned" in state["log"][-1]


def test_character_sheet(session):
    reply = ask(session, "character.get", {"id": "boris"})
    sheet = reply["data"]
    assert reply["type"] == "character.sheet"
    assert sheet["stats"]["strength"] == 7
    assert any(k["status"] == "lie" for k in sheet["knows"])
    assert sheet["items"][0]["name"] == "Rye bread"


def test_player_move_goes_through_rules(session, world):
    reply = ask(session, "player.move", {"to": "tavern"})
    hero = next(c for c in reply["data"]["characters"] if c["id"] == "hero")
    assert hero["location_id"] == "tavern"
    assert world.events()[-1].basis == "rules"
    world.kill("hero")
    reply = ask(session, "player.move", {"to": "square"})
    assert reply["type"] == "error" and "dead" in reply["data"]["message"]


def test_time_snapshot_rollback(session):
    ask(session, "snapshot.take", {"label": "start"})
    reply = ask(session, "time.skip", {"minutes": 60})
    assert reply["data"]["world"]["time_text"] == "Day 1, 01:00"
    reply = ask(session, "snapshot.restore", {"id": 1})
    state = reply["data"]
    assert state["world"]["time"] == 0
    assert [s["label"] for s in state["snapshots"]] == ["start", "before rollback to #1"]


def test_rule_mode(session):
    reply = ask(session, "rules.set_mode", {"mode": "strict"})
    assert reply["data"]["world"]["rule_mode"] == "strict"


def test_errors(session):
    assert session.handle("not json")["data"]["code"] == "bad_message"
    assert ask(session, "fly.away")["data"]["code"] == "unknown_type"
    assert ask(session, "character.get")["data"]["code"] == "bad_message"
    reply = ask(session, "character.get", {"id": "ghost"})
    assert reply["data"]["code"] == "rule"
    assert ask(session, "time.skip", {"minutes": -5})["data"]["code"] == "rule"


def test_websocket_round_trip(world):
    pytest.importorskip("websockets")
    from websockets.asyncio.client import connect

    async def scenario():
        started = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(serve(world, 0, ready=started.set_result))
        server = await started
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"type": "player.move", "id": 3, "data": {"to": "tavern"}}))
            reply = json.loads(await ws.recv())
        task.cancel()
        return reply

    reply = asyncio.run(scenario())
    assert reply["id"] == 3 and reply["type"] == "world.state"

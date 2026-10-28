"""Сервер ядра для окна Godot (D5, docs/05-protocol.md).

Godot подключается по WebSocket к `ws://127.0.0.1:<порт>` и присылает
намерения игрока. Ядро проверяет их, меняет мир и отвечает состоянием.
Godot ничего не решает сам (D4): он только рисует то, что прислало ядро.

Каждое сообщение — JSON `{"type": ..., "id": ..., "data": {...}}`.
Ответ приходит с тем же `id`. Ошибка — сообщение `error`.
"""

import asyncio
import json
import math
from collections.abc import Callable

from .cli import describe, report_lines
from .world import CLOCK, RuleError, SchemaError, World, format_date, format_time

DEFAULT_PORT = 8765

# Самый долгий шаг часов за одно сообщение `time.tick` (минуты).
MAX_TICK = 60

# Размеры на карте в клетках: место без вложенных мест и отступы.
PLACE_W, PLACE_H = 7, 5
GAP = 1
HEADER = 1
YARD_H = 4

LOG_SIZE = 40


# --- Раскладка карты ------------------------------------------------------------


def layout(world: World) -> dict[str, dict]:
    """Прямоугольники мест на схеме: {id: {x, y, w, h, depth}}.

    Пока у мест нет настоящей карты (0.7), ядро раскладывает их само:
    места верхнего уровня — в ряд, вложенные — сеткой внутри родителя.
    У места с вложенными местами внизу есть «двор» для тех, кто стоит
    в нём самом (например, на улице деревни).
    """
    locations = world.locations()
    children: dict[str | None, list[str]] = {}
    for location in locations:
        children.setdefault(location.parent_id, []).append(location.id)
    rects: dict[str, dict] = {}

    def size(location_id: str) -> tuple[int, int]:
        kids = children.get(location_id, [])
        if not kids:
            return PLACE_W, PLACE_H
        sizes = [size(kid) for kid in kids]
        columns = math.ceil(math.sqrt(len(kids)))
        rows = math.ceil(len(kids) / columns)
        cell_w = max(w for w, _ in sizes)
        cell_h = max(h for _, h in sizes)
        width = columns * cell_w + (columns + 1) * GAP
        height = HEADER + rows * cell_h + (rows + 1) * GAP + YARD_H
        return width, height

    def place(location_id: str, x: int, y: int, depth: int) -> None:
        w, h = size(location_id)
        rects[location_id] = {"x": x, "y": y, "w": w, "h": h, "depth": depth}
        kids = children.get(location_id, [])
        if not kids:
            return
        sizes = [size(kid) for kid in kids]
        columns = math.ceil(math.sqrt(len(kids)))
        cell_w = max(sw for sw, _ in sizes)
        cell_h = max(sh for _, sh in sizes)
        for index, kid in enumerate(kids):
            row, column = divmod(index, columns)
            place(
                kid,
                x + GAP + column * (cell_w + GAP),
                y + HEADER + GAP + row * (cell_h + GAP),
                depth + 1,
            )

    x = 0
    for root in children.get(None, []):
        place(root, x, 0, 0)
        x += rects[root]["w"] + GAP * 2
    return rects


# --- Состояние для окна ------------------------------------------------------


def world_state(world: World, report: list[str] | None = None) -> dict:
    """Всё, что нужно окну, чтобы нарисовать мир. `report` — сводка после пропуска."""
    info = world.info
    rects = layout(world)
    players = world.players()
    return {
        "world": {
            "name": info.name,
            "setting": info.setting,
            "seed": info.seed,
            "time": info.time,
            "time_text": format_time(info.time),
            "date_text": format_date(info.time),
            "rule_mode": info.rule_mode,
            "scenario_type": info.scenario_type,
        },
        "player_id": players[0].id if players else None,
        "locations": [
            {
                "id": loc.id,
                "name": loc.name,
                "kind": loc.kind,
                "parent_id": loc.parent_id,
                "discovered_by": loc.discovered_by,
                **rects[loc.id],
            }
            for loc in world.locations()
        ],
        "characters": [
            {
                "id": c.id,
                "name": c.name,
                "role": c.role,
                "location_id": c.location_id,
                "controller": c.controller,
                "alive": c.alive,
                "health": c.health,
                "max_health": c.max_health,
                "height_cm": c.body["height_cm"],
                "activity": _activity(world, c.id),
            }
            for c in world.characters()
        ],
        "items": [
            {"id": item.id, "name": item.name, "kind": item.kind,
             "location_id": item.location_id}
            for item in world.items()
            if item.location_id is not None
        ],
        "snapshots": [
            {"id": s.id, "time_text": format_time(s.time), "label": s.label}
            for s in world.snapshots()
        ],
        "log": [
            describe(event)
            for event in world.events(after_id=max(0, world.last_event_id() - LOG_SIZE))
        ],
        "report": report or [],
    }


def _activity(world: World, character_id: str) -> str | None:
    state = world.npc_state(character_id)
    return state.activity if state else None


def character_sheet(world: World, character_id: str) -> dict:
    """Лист персонажа: всё, что о нём знает ядро, включая его знания."""
    c = world.character(character_id)
    npc = world.npc_state(c.id)
    return {
        "id": c.id,
        "name": c.name,
        "role": c.role,
        "profession": c.profession,
        "controller": c.controller,
        "location_id": c.location_id,
        "home_id": c.home_id,
        "work_id": c.work_id,
        "activity": npc.activity if npc else None,
        "needs": npc.needs if npc else None,
        "wage_owed": npc.owed if npc else 0,
        "alive": c.alive,
        "health": c.health,
        "max_health": c.max_health,
        "conditions": list(c.conditions),
        "stats": c.stats,
        "body": c.body,
        "cash": c.cash,
        "bank": c.bank,
        "abilities": list(c.abilities),
        "personality": c.personality,
        "items": [
            {"id": i.id, "name": i.name, "kind": i.kind, "equipped": i.equipped}
            for i in world.items(owner_id=c.id)
        ],
        "relations": [
            {"to": r.to_id, "liking": r.liking, "trust": r.trust, "fear": r.fear,
             "respect": r.respect, "love": r.love, "knows_name": r.knows_name}
            for r in world.relations_of(c.id)
        ],
        "knows": [
            {"id": k.fact.id, "text": f"{k.fact.subject} {k.fact.predicate} = {k.fact.object}",
             "status": k.fact.status, "believes": k.believes, "current": k.fact.current}
            for k in world.knowledge(c.id)
        ],
    }


# --- Обработка сообщений --------------------------------------------------------


class Session:
    """Обрабатывает сообщения окна для одного открытого мира.

    Отделено от сети, чтобы тесты проверяли протокол без WebSocket.
    """

    def __init__(self, world: World) -> None:
        self.world = world
        self.handlers: dict[str, Callable[[dict], tuple[str, dict]]] = {
            "world.get": self._world_get,
            "character.get": self._character_get,
            "player.move": self._player_move,
            "time.skip": self._time_skip,
            "time.tick": self._time_tick,
            "snapshot.take": self._snapshot_take,
            "snapshot.restore": self._snapshot_restore,
            "rules.set_mode": self._rules_set_mode,
        }

    def handle(self, raw: str) -> dict:
        """Принимает текст сообщения, возвращает ответ (словарь)."""
        try:
            message = json.loads(raw)
            kind = message["type"]
            data = message.get("data") or {}
        except (json.JSONDecodeError, KeyError, TypeError):
            return error(None, "bad_message", "Message must be JSON with 'type'")
        message_id = message.get("id")
        handler = self.handlers.get(kind)
        if handler is None:
            return error(message_id, "unknown_type", f"Unknown message type '{kind}'")
        try:
            reply_type, reply = handler(data)
        except KeyError as missing:
            return error(message_id, "bad_message", f"Field {missing} is missing")
        except (RuleError, SchemaError) as rule:
            return error(message_id, "rule", str(rule))
        return {"type": reply_type, "id": message_id, "data": reply}

    def _state(self) -> tuple[str, dict]:
        return "world.state", world_state(self.world)

    def _world_get(self, data: dict):
        return self._state()

    def _character_get(self, data: dict):
        return "character.sheet", character_sheet(self.world, data["id"])

    def _player_move(self, data: dict):
        players = self.world.players()
        if not players:
            raise RuleError("There is no hero in this world")
        self.world.move_character(players[0].id, data["to"])
        return self._state()

    def _time_skip(self, data: dict):
        report = self.world.skip_time(int(data["minutes"]), reason="skipped in the window")
        return "world.state", world_state(self.world, report_lines(self.world, report))

    def _time_tick(self, data: dict):
        """Ход часов в окне (пауза, ×1, ×4): шаг в несколько минут без записи в журнал."""
        minutes = int(data["minutes"])
        if not 1 <= minutes <= MAX_TICK:
            raise RuleError(f"A clock tick is 1 to {MAX_TICK} minutes")
        self.world.advance_time(minutes, reason=CLOCK)
        return self._state()

    def _snapshot_take(self, data: dict):
        self.world.take_snapshot(data.get("label", ""))
        return self._state()

    def _snapshot_restore(self, data: dict):
        self.world.rollback(int(data["id"]))
        return self._state()

    def _rules_set_mode(self, data: dict):
        self.world.set_rule_mode(data["mode"])
        return self._state()


def error(message_id, code: str, text: str) -> dict:
    return {"type": "error", "id": message_id, "data": {"code": code, "message": text}}


# --- Сеть -----------------------------------------------------------------------


async def serve(world: World, port: int = DEFAULT_PORT, *, ready=None) -> None:
    """Слушает `ws://127.0.0.1:<port>` до остановки (Ctrl+C)."""
    from websockets.asyncio.server import serve as ws_serve
    from websockets.exceptions import ConnectionClosed

    session = Session(world)

    async def connection(websocket) -> None:
        try:
            async for raw in websocket:
                await websocket.send(json.dumps(session.handle(raw), ensure_ascii=False))
        except ConnectionClosed:
            # Окно закрыли без прощания: это не ошибка ядра.
            pass

    async with ws_serve(connection, "127.0.0.1", port) as server:
        if ready is not None:
            ready(server)
        await asyncio.get_running_loop().create_future()

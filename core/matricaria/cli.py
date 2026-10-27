"""Консольная программа `matricaria`: создать мир, посмотреть, изменить, откатиться.

Все команды и сообщения по-английски (D40). Команды рассказчика
меняют мир волей автора: в журнал они пишутся с основанием `author` (D44).

Мир задаётся именем папки в `saves/` или путём к файлу `.db`.
"""

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

from .world import RuleError, SchemaError, World, format_time
from .world.constants import (
    CONTROLLERS,
    DEFAULT_BODY,
    FACT_STATUSES,
    RELATION_SCALES,
    RULE_MODES,
    SCENARIO_TYPES,
    SETTINGS,
    STATS,
    TRAVEL_MODES,
)
from .world.models import Event
from .world.templates import create_from_template, read_template, template_names

WORLD_FILE = "world.db"


# --- Где лежат миры ---------------------------------------------------------


def saves_dir(args) -> Path:
    return Path(args.saves or os.environ.get("MATRICARIA_SAVES") or "saves")


def world_path(args) -> Path:
    if args.world.endswith(".db"):
        return Path(args.world)
    return saves_dir(args) / args.world / WORLD_FILE


def open_world(args) -> World:
    return World.open(world_path(args))


# --- Вывод ------------------------------------------------------------------


def money(world: World, amount: int) -> str:
    unit = "copper" if world.info.setting == "fantasy" else "cents"
    return f"{amount} {unit}"


def height(cm: int) -> str:
    return f"{cm / 100:g} m" if cm >= 1000 else f"{cm} cm"


def describe(event: Event) -> str:
    """Строка журнала: номер, время, основание, что случилось."""
    head = f"#{event.id:<4} {format_time(event.time)}  [{event.basis}]"
    who = f"{event.actor_id}: " if event.actor_id else ""
    data = dict(event.data)
    kind = event.kind.replace("_", " ")
    if event.kind == "character_moved":
        text = f"{event.participants[0]} moved {data['from']} -> {data['to']}"
    elif event.kind == "health_changed":
        text = f"{event.participants[0]} health {data['from']} -> {data['to']}"
        if data.get("cause"):
            text += f" ({data['cause']})"
    elif event.kind in ("fact_added", "fact_changed") and "predicate" in data:
        target = data.get("object", data.get("to"))
        subject = data.get("subject", event.participants[0] if event.participants else "?")
        text = f"{kind} #{data.get('new_fact_id', data.get('fact_id'))}: " \
               f"{subject} {data['predicate']} = {target}"
        if data.get("status", "truth") != "truth":
            text += f" [{data['status']}]"
    else:
        details = ", ".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}"
            for key, value in data.items()
            if value not in (None, "", {}, [])
        )
        parts = " ".join(event.participants)
        text = f"{kind} {parts}".rstrip() + (f" ({details})" if details else "")
    return f"{head} {who}{text}"


def out(text: str = "") -> None:
    print(text)


# --- Команды: мир -----------------------------------------------------------


def cmd_new(args) -> None:
    if args.template == "empty":
        create_empty(args)
        return
    path = world_path(args)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    template = read_template(args.template)
    if args.setting:
        template.setdefault("world", {})["setting"] = args.setting
    world = create_from_template(
        path,
        template,
        seed=seed,
        name=args.name,
        rule_mode=args.rules,
        scenario_type=args.scenario,
        travel=args.travel,
    )
    with world:
        info = world.info
        out(f"Created world '{info.name}' ({info.setting}) in {path}")
        out(f"Seed: {info.seed}. Rule mode: {info.rule_mode}.")
        out(f"{len(world.characters())} characters, {len(world.locations())} places, "
            f"{len(world.items())} items, {len(world.facts())} facts.")


def cmd_worlds(args) -> None:
    root = saves_dir(args)
    paths = sorted(root.glob(f"*/{WORLD_FILE}")) if root.is_dir() else []
    if not paths:
        out(f"No worlds in {root}. Create one: matricaria new <name>")
        return
    for path in paths:
        try:
            with World.open(path) as world:
                info = world.info
                out(f"{path.parent.name:<20} {info.name} ({info.setting}), {format_time(info.time)}")
        except (SchemaError, RuleError) as error:
            out(f"{path.parent.name:<20} cannot open: {error}")


def cmd_status(args) -> None:
    with open_world(args) as world:
        info = world.info
        out(f"{info.name} — {info.setting}, {format_time(info.time)}")
        out(f"Rule mode: {info.rule_mode}. Scenario: {info.scenario_type}. "
            f"Travel: {info.travel}. Seed: {info.seed}.")
        for player in world.players():
            out(f"Hero: {player.name} ({player.id}) at {player.location_id or 'nowhere'}, "
                f"health {player.health}/{player.max_health}, "
                f"cash {money(world, player.cash)}, bank {money(world, player.bank)}")
        out()
        out("Places:")
        for location in world.locations():
            people = [
                c.name + ("" if c.alive else " (dead)")
                for c in world.characters(location_id=location.id)
            ]
            things = [i.name for i in world.items(location_id=location.id)]
            line = f"  {location.id:<14} {location.name}"
            if location.discovered_by:
                line += f" [found by {location.discovered_by}]"
            out(line)
            if people:
                out(f"      people: {', '.join(people)}")
            if things:
                out(f"      items:  {', '.join(things)}")
        nowhere = [c.name for c in world.characters() if c.location_id is None]
        if nowhere:
            out(f"  (nowhere)      people: {', '.join(nowhere)}")
        out()
        out(f"Events: {world.last_event_id()}. Snapshots: {len(world.snapshots())}.")


def cmd_show(args) -> None:
    """Лист персонажа и «подслушать»: что он знает и как относится к другим."""
    with open_world(args) as world:
        c = world.character(args.character)
        state = "alive" if c.alive else "DEAD"
        out(f"{c.name} ({c.id}) — {c.role or 'no role'}, profession: {c.profession or 'none'}")
        out(f"Controlled by: {c.controller}. Location: {c.location_id or 'nowhere'}. {state}.")
        out(f"Health: {c.health}/{c.max_health}"
            + (f". Conditions: {', '.join(c.conditions)}" if c.conditions else ""))
        out("Stats: " + ", ".join(f"{name} {value}" for name, value in c.stats.items()))
        b = c.body
        out(f"Body: {height(b['height_cm'])}, muscles {b['muscles']}, fatness {b['fatness']}"
            + (f", {b['build']}" if b["build"] else ""))
        out(f"Money: cash {money(world, c.cash)}, bank {money(world, c.bank)}")
        if c.abilities:
            out("Abilities: " + ", ".join(c.abilities))
        if c.personality:
            out("Personality: " + json.dumps(c.personality, ensure_ascii=False))
        items = world.items(owner_id=c.id)
        out("Items:" if items else "Items: none")
        for item in items:
            extra = []
            if item.equipped:
                extra.append(item.equipped)
            if item.damage_max is not None:
                extra.append(f"damage {item.damage_min}-{item.damage_max}")
            out(f"  #{item.id} {item.name} ({item.kind})"
                + (f" [{', '.join(extra)}]" if extra else ""))
        relations = world.relations_of(c.id)
        if relations:
            out("Feels about others:")
            for r in relations:
                scales = ", ".join(f"{s} {getattr(r, s)}" for s in RELATION_SCALES)
                name = "" if r.knows_name else " (name unknown)"
                out(f"  {r.to_id}{name}: {scales}")
        known = world.knowledge(c.id)
        out("Knows:" if known else "Knows: nothing")
        for k in known:
            f = k.fact
            flags = [f.status] if f.status != "truth" else []
            if not k.believes:
                flags.append("does not believe")
            if not f.current:
                flags.append("out of date")
            out(f"  #{f.id} {f.subject} {f.predicate} = {f.object}"
                + (f" [{', '.join(flags)}]" if flags else ""))


def cmd_log(args) -> None:
    with open_world(args) as world:
        events = world.events(involving=args.about)
        for event in events[-args.last:] if args.last else events:
            out(describe(event))


def cmd_facts(args) -> None:
    with open_world(args) as world:
        facts = world.facts(subject=args.about, current_only=not args.all)
        if not facts:
            out("No facts.")
        for f in facts:
            flags = [f.status]
            if f.canon:
                flags.append("canon")
            if not f.current:
                flags.append(f"replaced by #{f.replaced_by}" if f.replaced_by else "ended")
            who = world.who_knows(f.id)
            out(f"#{f.id:<4} {f.subject} {f.predicate} = {f.object} [{', '.join(flags)}]"
                + (f" — known by {', '.join(who)}" if who else ""))


def cmd_snapshot(args) -> None:
    with open_world(args) as world:
        snap = world.take_snapshot(args.label or "")
        out(f"Snapshot #{snap.id} saved at {format_time(snap.time)} "
            f"(after event #{snap.last_event_id}).")


def cmd_snapshots(args) -> None:
    with open_world(args) as world:
        snaps = world.snapshots()
        if not snaps:
            out("No snapshots yet. Make one: matricaria snapshot <world>")
        for snap in snaps:
            out(f"#{snap.id:<4} {format_time(snap.time)}  after event #{snap.last_event_id}"
                + (f"  {snap.label}" if snap.label else ""))


def cmd_rollback(args) -> None:
    with open_world(args) as world:
        before = world.rollback(args.snapshot)
        out(f"Rolled back to snapshot #{args.snapshot}. Now: {format_time(world.time)}.")
        out(f"The undone future is kept as snapshot #{before.id}: "
            f"matricaria rollback {args.world} {before.id}")


def cmd_rules(args) -> None:
    with open_world(args) as world:
        world.set_rule_mode(args.mode)
        out(f"Rule mode: {args.mode}.")


def parse_duration(text: str) -> int:
    """`90`, `90m`, `2h`, `3d`, `1d6h` → минуты."""
    if text.isdigit():
        return int(text)
    parts = re.fullmatch(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?", text)
    if not parts or not any(parts.groups()):
        raise RuleError(f"Cannot read duration '{text}'; examples: 90, 45m, 2h, 3d, 1d6h")
    days, hours, minutes = (int(value or 0) for value in parts.groups())
    return days * 1440 + hours * 60 + minutes


def cmd_wait(args) -> None:
    with open_world(args) as world:
        world.advance_time(parse_duration(args.duration), reason=args.reason or "")
        out(f"Now: {format_time(world.time)}. (Nothing happens yet: simulation comes in 0.4.)")


# --- Команды рассказчика ------------------------------------------------------


def cmd_revive(args) -> None:
    with open_world(args) as world:
        world.revive(args.character, health=args.health)
        c = world.character(args.character)
        out(f"{c.name} lives again with {c.health}/{c.max_health} health.")


def cmd_kill(args) -> None:
    with open_world(args) as world:
        world.kill(args.character, cause=args.cause or "")
        out(f"{world.character(args.character).name} is dead.")


def cmd_health(args) -> None:
    with open_world(args) as world:
        c = world.change_health(args.character, args.delta, basis="author",
                                cause=args.cause or "")
        out(f"{c.name}: health {c.health}/{c.max_health}" + ("" if c.alive else ", dead"))


def cmd_give(args) -> None:
    damage = None
    if args.damage:
        match = re.fullmatch(r"(\d+)-(\d+)", args.damage)
        if not match:
            raise RuleError("Damage must look like 2-8")
        damage = (int(match[1]), int(match[2]))
    with open_world(args) as world:
        owner = location = None
        if args.to in {c.id for c in world.characters()}:
            owner = args.to
        else:
            location = args.to
        item = world.create_item(args.kind, args.name, owner_id=owner, location_id=location,
                                 base_price=args.price, damage=damage)
        out(f"Created item #{item.id} '{item.name}' for {args.to}.")


def cmd_take(args) -> None:
    with open_world(args) as world:
        item = world.item(args.item)
        world.remove_item(args.item, reason=args.reason or "")
        out(f"Item #{item.id} '{item.name}' is gone.")


def cmd_money(args) -> None:
    with open_world(args) as world:
        account = "bank" if args.bank else "cash"
        world.grant_money(args.character, args.amount, account=account,
                          reason=args.reason or "")
        c = world.character(args.character)
        out(f"{c.name}: cash {money(world, c.cash)}, bank {money(world, c.bank)}")


def cmd_move(args) -> None:
    with open_world(args) as world:
        world.move_character(args.character, args.location, basis="author")
        out(f"{world.character(args.character).name} is now at "
            f"{world.location(args.location).name}.")


def cmd_stat(args) -> None:
    with open_world(args) as world:
        world.set_stat(args.character, args.stat, args.value)
        out(f"{args.character}: {args.stat} = {args.value}")


def cmd_body(args) -> None:
    changes = {key: getattr(args, key) for key in DEFAULT_BODY if getattr(args, key) is not None}
    with open_world(args) as world:
        world.set_body(args.character, **changes)
        b = world.character(args.character).body
        out(f"{args.character}: {height(b['height_cm'])}, muscles {b['muscles']}, "
            f"fatness {b['fatness']}, {b['build'] or 'no build'}")


def cmd_relation(args) -> None:
    values = {scale: getattr(args, scale) for scale in RELATION_SCALES
              if getattr(args, scale) is not None}
    knows = True if args.knows_name else False if args.forget_name else None
    with open_world(args) as world:
        r = world.set_relation(args.from_id, args.to_id, knows_name=knows, **values)
        out(f"{r.from_id} -> {r.to_id}: "
            + ", ".join(f"{s} {getattr(r, s)}" for s in RELATION_SCALES)
            + f", knows name: {'yes' if r.knows_name else 'no'}")


def cmd_ability(args) -> None:
    with open_world(args) as world:
        if args.remove:
            world.remove_ability(args.character, args.kind)
            out(f"{args.character} lost {args.kind}.")
        else:
            world.grant_ability(args.character, args.kind)
            out(f"{args.character} gained {args.kind}.")


def cmd_controller(args) -> None:
    with open_world(args) as world:
        world.set_controller(args.character, args.controller)
        out(f"{args.character} is now controlled by {args.controller}.")


def cmd_fact(args) -> None:
    with open_world(args) as world:
        if args.action == "add":
            if len(args.values) != 3:
                raise RuleError("Usage: fact <world> add <subject> <predicate> <object>")
            f = world.add_fact(*args.values, status=args.status, canon=args.canon,
                               multiple=args.multiple, source="author", basis="author")
            out(f"Added fact #{f.id}.")
        elif args.action == "change":
            if len(args.values) != 2:
                raise RuleError("Usage: fact <world> change <fact id> <new object>")
            f = world.change_fact(int(args.values[0]), args.values[1], source="author",
                                  basis="author")
            out(f"Fact #{args.values[0]} replaced by #{f.id}.")
        else:
            if len(args.values) != 1:
                raise RuleError("Usage: fact <world> end <fact id>")
            world.end_fact(int(args.values[0]), basis="author")
            out(f"Fact #{args.values[0]} is no longer true.")


def cmd_teach(args) -> None:
    with open_world(args) as world:
        world.learn_fact(args.character, args.fact, believes=not args.disbelieve,
                         source="author", basis="author")
        out(f"{args.character} now knows fact #{args.fact}"
            + (" but does not believe it." if args.disbelieve else "."))


# --- Разбор командной строки ---------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matricaria",
        description="Matricaria world core: create a world, inspect it, change it, roll back.",
    )
    parser.add_argument("--saves", help="folder with worlds (default: ./saves)")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def command(name, func, help_text):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.set_defaults(func=func)
        return p

    def with_world(name, func, help_text):
        p = command(name, func, help_text)
        p.add_argument("world", help="world name in saves/ or path to a .db file")
        return p

    p = with_world("new", cmd_new, "create a new world")
    p.add_argument("--template", default="village",
                   help=f"starting world: {', '.join(template_names())}, empty, or a .toml path")
    p.add_argument("--name", help="world title (default: from the template)")
    p.add_argument("--seed", type=int, help="world seed (default: random)")
    p.add_argument("--setting", choices=SETTINGS)
    p.add_argument("--rules", choices=RULE_MODES)
    p.add_argument("--scenario", choices=SCENARIO_TYPES)
    p.add_argument("--travel", choices=TRAVEL_MODES)

    command("worlds", cmd_worlds, "list saved worlds")
    with_world("status", cmd_status, "show the world: time, hero, places, people")

    p = with_world("show", cmd_show, "character sheet, relations and what they know")
    p.add_argument("character")

    p = with_world("log", cmd_log, "show the event log")
    p.add_argument("--last", type=int, default=20, help="how many events (0 = all)")
    p.add_argument("--about", help="only events with this character or place")

    p = with_world("facts", cmd_facts, "list facts and who knows them")
    p.add_argument("--about", help="only facts about this subject")
    p.add_argument("--all", action="store_true", help="include out-of-date facts")

    p = with_world("snapshot", cmd_snapshot, "save a snapshot to roll back to")
    p.add_argument("label", nargs="?", help="short note")
    with_world("snapshots", cmd_snapshots, "list snapshots")
    p = with_world("rollback", cmd_rollback, "return the world to a snapshot")
    p.add_argument("snapshot", type=int)

    p = with_world("rules", cmd_rules, "change the rule mode")
    p.add_argument("mode", choices=RULE_MODES)
    p = with_world("wait", cmd_wait, "move time forward: 90, 45m, 2h, 3d, 1d6h")
    p.add_argument("duration")
    p.add_argument("--reason")

    # Рассказчик (основание author).
    p = with_world("revive", cmd_revive, "narrator: bring a dead character back")
    p.add_argument("character")
    p.add_argument("--health", type=int, help="health after revival (default: full)")
    p = with_world("kill", cmd_kill, "narrator: kill a character")
    p.add_argument("character")
    p.add_argument("--cause")
    p = with_world("health", cmd_health, "narrator: heal (+5) or hurt (-5) a character")
    p.add_argument("character")
    p.add_argument("delta", type=int)
    p.add_argument("--cause")
    p = with_world("give", cmd_give, "narrator: create an item for a character or a place")
    p.add_argument("to", help="character id or place id")
    p.add_argument("kind", help="item kind, e.g. weapon, food, key")
    p.add_argument("name", help="item name (use quotes for several words)")
    p.add_argument("--price", type=int, default=0)
    p.add_argument("--damage", help="weapon damage, e.g. 2-8")
    p = with_world("take", cmd_take, "narrator: make an item vanish")
    p.add_argument("item", type=int, help="item number")
    p.add_argument("--reason")
    p = with_world("money", cmd_money, "narrator: give (+50) or take (-50) money")
    p.add_argument("character")
    p.add_argument("amount", type=int)
    p.add_argument("--bank", action="store_true", help="use the bank account, not cash")
    p.add_argument("--reason")
    p = with_world("move", cmd_move, "narrator: teleport a character to a place")
    p.add_argument("character")
    p.add_argument("location")
    p = with_world("stat", cmd_stat, "narrator: set a stat (1-10)")
    p.add_argument("character")
    p.add_argument("stat", choices=STATS)
    p.add_argument("value", type=int)
    p = with_world("body", cmd_body, "narrator: change height and figure")
    p.add_argument("character")
    p.add_argument("--height", dest="height_cm", type=int, help="height in cm (1 to 50000)")
    p.add_argument("--muscles", type=int, help="0-100")
    p.add_argument("--fatness", type=int, help="0-100")
    p.add_argument("--build", help="e.g. slender, athletic, broad")
    p = with_world("relation", cmd_relation, "narrator: set how one character feels about another")
    p.add_argument("from_id")
    p.add_argument("to_id")
    for scale, (low, high) in RELATION_SCALES.items():
        p.add_argument(f"--{scale}", type=int, help=f"{low}..{high}")
    p.add_argument("--knows-name", action="store_true")
    p.add_argument("--forget-name", action="store_true")
    p = with_world("ability", cmd_ability, "narrator: grant or remove an ability")
    p.add_argument("character")
    p.add_argument("kind", help="e.g. divine_will, immortality, omniscience, magic:fire")
    p.add_argument("--remove", action="store_true")
    p = with_world("controller", cmd_controller, "narrator: hand a character to the player or AI")
    p.add_argument("character")
    p.add_argument("controller", choices=CONTROLLERS)
    p = with_world("fact", cmd_fact, "narrator: add, change or end a fact")
    p.add_argument("action", choices=["add", "change", "end"])
    p.add_argument("values", nargs="+", help="add: subject predicate object; "
                   "change: id new_object; end: id")
    p.add_argument("--status", choices=FACT_STATUSES, default="truth")
    p.add_argument("--canon", action="store_true")
    p.add_argument("--multiple", action="store_true",
                   help="this property can have several values")
    p = with_world("teach", cmd_teach, "narrator: let a character learn a fact")
    p.add_argument("character")
    p.add_argument("fact", type=int)
    p.add_argument("--disbelieve", action="store_true", help="knows it but does not believe it")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (RuleError, SchemaError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        # Вывод оборвали (например, `| head`): это не ошибка.
        sys.stderr.close()
    return 0


def create_empty(args) -> None:
    """`new --template empty`: пустой мир без мест и персонажей."""
    path = world_path(args)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    with World.create(
        path,
        args.name or args.world,
        setting=args.setting or "fantasy",
        seed=seed,
        rule_mode=args.rules or "narrative",
        scenario_type=args.scenario or "standard",
        travel=args.travel or "map",
    ) as world:
        out(f"Created empty world '{world.info.name}' in {path}. Seed: {seed}.")


if __name__ == "__main__":
    sys.exit(main())

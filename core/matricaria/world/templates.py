"""Стартовые миры из файлов TOML.

Шаблон описывает места, персонажей, предметы, отношения и факты.
Мир собирается обычными методами `World` с основанием `author`,
поэтому всё созданное проверено кодом и записано в журнал.
"""

import tomllib
from pathlib import Path

from . import World
from .errors import NotFoundError, RuleError

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def template_names() -> list[str]:
    """Имена встроенных шаблонов (без `.toml`)."""
    return sorted(path.stem for path in TEMPLATE_DIR.glob("*.toml"))


def read_template(name_or_path: str | Path) -> dict:
    """Читает встроенный шаблон по имени или любой файл TOML по пути."""
    path = Path(name_or_path)
    if not path.suffix:
        path = TEMPLATE_DIR / f"{name_or_path}.toml"
    if not path.is_file():
        raise NotFoundError(
            f"No world template '{name_or_path}'; built-in: {', '.join(template_names())}"
        )
    with path.open("rb") as file:
        try:
            return tomllib.load(file)
        except tomllib.TOMLDecodeError as error:
            raise RuleError(f"Template {path.name} is broken: {error}") from error


def create_from_template(
    path: str | Path,
    template: dict,
    *,
    seed: int,
    name: str | None = None,
    rule_mode: str | None = None,
    scenario_type: str | None = None,
    travel: str | None = None,
) -> World:
    """Создаёт новый мир по шаблону. Параметры, переданные явно, важнее шаблона."""
    meta = template.get("world", {})
    options = {
        "setting": meta.get("setting", "fantasy"),
        "rule_mode": rule_mode or meta.get("rule_mode", "narrative"),
        "scenario_type": scenario_type or meta.get("scenario_type", "standard"),
        "travel": travel or meta.get("travel", "map"),
    }
    world = World.create(path, name or meta.get("name", "New world"), seed=seed, **options)
    try:
        fill_world(world, template)
    except Exception:
        world.close()
        Path(path).unlink(missing_ok=True)
        raise
    return world


def fill_world(world: World, template: dict) -> None:
    """Добавляет в мир всё из шаблона. Ошибка в шаблоне называет запись."""
    for entry in template.get("locations", []):
        _with_context(
            "location", entry,
            lambda e: world.add_location(
                e["id"], e["name"], e["kind"],
                parent_id=e.get("parent"), x=e.get("x"), y=e.get("y"),
            ),
        )
    for entry in template.get("characters", []):
        _with_context("character", entry, lambda e: _add_character(world, e))
    for entry in template.get("items", []):
        _with_context("item", entry, lambda e: _add_item(world, e))
    for entry in template.get("relations", []):
        _with_context(
            "relation", entry,
            lambda e: world.set_relation(
                e["from"], e["to"],
                knows_name=e.get("knows_name"),
                **{k: v for k, v in e.items() if k not in ("from", "to", "knows_name")},
            ),
        )
    for entry in template.get("facts", []):
        _with_context("fact", entry, lambda e: _add_fact(world, e))


def _with_context(kind: str, entry: dict, action) -> None:
    label = entry.get("id") or entry.get("name") or entry.get("subject") or entry.get("from")
    try:
        action(entry)
    except KeyError as error:
        raise RuleError(f"Template {kind} '{label}' has no field {error}") from error
    except RuleError as error:
        raise RuleError(f"Template {kind} '{label}': {error}") from error


def _add_character(world: World, entry: dict) -> None:
    world.add_character(
        entry["id"],
        entry["name"],
        role=entry.get("role", ""),
        profession=entry.get("profession", ""),
        controller=entry.get("controller", "ai"),
        location_id=entry.get("location"),
        home_id=entry.get("home"),
        work_id=entry.get("work"),
        stats=entry.get("stats"),
        body=entry.get("body"),
        personality=entry.get("personality"),
        cash=entry.get("cash", 0),
        bank=entry.get("bank", 0),
    )
    for ability in entry.get("abilities", []):
        if isinstance(ability, str):
            ability = {"kind": ability}
        world.grant_ability(entry["id"], ability["kind"], ability.get("params"))


def _add_item(world: World, entry: dict) -> None:
    damage = entry.get("damage")
    item = world.create_item(
        entry["kind"],
        entry["name"],
        owner_id=entry.get("owner"),
        location_id=entry.get("location"),
        base_price=entry.get("price", 0),
        damage=tuple(damage) if damage else None,
    )
    if entry.get("equipped"):
        world.equip(item.id, entry["equipped"], basis="author")


def _add_fact(world: World, entry: dict) -> None:
    fact = world.add_fact(
        entry["subject"],
        entry["predicate"],
        entry["object"],
        status=entry.get("status", "truth"),
        canon=entry.get("canon", False),
        multiple=entry.get("multiple", False),
        source=entry.get("source", "template"),
        basis="author",
    )
    for character_id in entry.get("known_by", []):
        world.learn_fact(character_id, fact.id, source="template", basis="author")
    for character_id in entry.get("believed_by", []):
        world.learn_fact(character_id, fact.id, source="rumor", basis="author")
    for character_id in entry.get("disbelieved_by", []):
        world.learn_fact(
            character_id, fact.id, believes=False, source="rumor", basis="author"
        )

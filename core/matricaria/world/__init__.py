"""Ядро мира: база SQLite, в которой живёт правда о мире.

Пример:

    from matricaria.world import World

    with World.create("saves/demo/world.db", "Demo", seed=42) as world:
        world.add_location("square", "Village square", "square")
        world.add_character("hero", "Ash", controller="player", location_id="square")

Любое изменение проверяется кодом и записывается в журнал событий.
"""

from .characters import CharactersMixin
from .calendar import format_date
from .constants import format_time
from .errors import NotFoundError, RuleError, SchemaError
from .facts import FactsMixin
from .items import ItemsMixin
from .locations import LocationsMixin
from .models import (
    Character,
    Event,
    Fact,
    Item,
    Knowledge,
    Location,
    NpcState,
    Relation,
    Snapshot,
    WorldInfo,
)
from .relations import RelationsMixin
from .settings import SettingsMixin
from .simulation import CLOCK, SimulationMixin, TimeReport
from .snapshots import SnapshotsMixin
from .schema import SCHEMA_VERSION


class World(
    CharactersMixin,
    LocationsMixin,
    ItemsMixin,
    RelationsMixin,
    FactsMixin,
    SettingsMixin,
    SimulationMixin,
    SnapshotsMixin,
):
    """Открытый мир. Создать: `World.create(...)`, открыть: `World.open(path)`."""


__all__ = [
    "CLOCK",
    "SCHEMA_VERSION",
    "Character",
    "Event",
    "Fact",
    "Item",
    "Knowledge",
    "Location",
    "NotFoundError",
    "NpcState",
    "Relation",
    "RuleError",
    "SchemaError",
    "Snapshot",
    "TimeReport",
    "World",
    "WorldInfo",
    "format_date",
    "format_time",
]

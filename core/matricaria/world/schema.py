"""Схема базы мира (SQLite) и её версия.

Версия схемы хранится в самой базе (`PRAGMA user_version`).
Старое сохранение обновляется до новой схемы миграцией — шагом из `MIGRATIONS`.
Версии: 1 — ядро мира (0.3), 2 — дом, работа и состояние жителей (0.4).
"""

import sqlite3

from .constants import (
    BASES,
    CONTROLLERS,
    EQUIP_STATES,
    FACT_STATUSES,
    HEIGHT_MAX_CM,
    HEIGHT_MIN_CM,
    RELATION_SCALES,
    RULE_MODES,
    SCENARIO_TYPES,
    SETTINGS,
    STAT_MAX,
    STAT_MIN,
    TRAVEL_MODES,
)
from .errors import SchemaError

SCHEMA_VERSION = 2


def _one_of(values: tuple[str, ...]) -> str:
    """Список для проверки `IN (...)` в SQL."""
    return ", ".join(f"'{value}'" for value in values)


def _stat(name: str) -> str:
    return f"{name} INTEGER NOT NULL CHECK ({name} BETWEEN {STAT_MIN} AND {STAT_MAX})"


def _scale(name: str) -> str:
    low, high = RELATION_SCALES[name]
    return f"{name} INTEGER NOT NULL DEFAULT 0 CHECK ({name} BETWEEN {low} AND {high})"


def _need(name: str) -> str:
    return f"{name} REAL NOT NULL CHECK ({name} BETWEEN 0 AND 100)"


# Состояние жителя для симуляции (0.4): чем занят, когда решит снова,
# потребности 0–100, была ли рядом компания в начале занятия
# и заработок, который ещё не выплачен.
NPC_STATE = f"""
CREATE TABLE npc_state (
    character_id TEXT    PRIMARY KEY REFERENCES character(id),
    activity     TEXT    NOT NULL DEFAULT 'idle',
    level        TEXT    NOT NULL DEFAULT 'town',
    next_at      INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    {_need("food")},
    {_need("rest")},
    {_need("social")},
    {_need("safety")},
    company      INTEGER NOT NULL DEFAULT 0 CHECK (company IN (0, 1)),
    owed         INTEGER NOT NULL DEFAULT 0 CHECK (owed >= 0),
    shift_day    INTEGER
);
"""

SCHEMA = f"""
-- Параметры мира: ровно одна строка.
CREATE TABLE world (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    name          TEXT    NOT NULL,
    setting       TEXT    NOT NULL CHECK (setting IN ({_one_of(SETTINGS)})),
    seed          INTEGER NOT NULL,
    time          INTEGER NOT NULL DEFAULT 0 CHECK (time >= 0),
    rule_mode     TEXT    NOT NULL CHECK (rule_mode IN ({_one_of(RULE_MODES)})),
    scenario_type TEXT    NOT NULL CHECK (scenario_type IN ({_one_of(SCENARIO_TYPES)})),
    travel        TEXT    NOT NULL CHECK (travel IN ({_one_of(TRAVEL_MODES)}))
);

-- Места. discovered_* заполнены, если место появилось по ходу игры (D27).
CREATE TABLE location (
    id            TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    parent_id     TEXT    REFERENCES location(id),
    x             INTEGER,
    y             INTEGER,
    discovered_at INTEGER,
    discovered_by TEXT    REFERENCES character(id)
);

-- Герои и NPC. Деньги: наличные и на счёте (D41).
CREATE TABLE character (
    id          TEXT    PRIMARY KEY,
    name        TEXT    NOT NULL,
    role        TEXT    NOT NULL DEFAULT '',
    profession  TEXT    NOT NULL DEFAULT '',
    personality TEXT    NOT NULL DEFAULT '{{}}',
    controller  TEXT    NOT NULL CHECK (controller IN ({_one_of(CONTROLLERS)})),
    location_id TEXT    REFERENCES location(id),
    home_id     TEXT    REFERENCES location(id),
    work_id     TEXT    REFERENCES location(id),
    sprite      TEXT,
    portrait    TEXT,
    cash        INTEGER NOT NULL DEFAULT 0 CHECK (cash >= 0),
    bank        INTEGER NOT NULL DEFAULT 0 CHECK (bank >= 0)
);

-- Характеристики и состояние.
CREATE TABLE stats (
    character_id TEXT    PRIMARY KEY REFERENCES character(id),
    {_stat("strength")},
    {_stat("agility")},
    {_stat("endurance")},
    {_stat("intellect")},
    {_stat("charisma")},
    max_health   INTEGER NOT NULL CHECK (max_health >= 1),
    health       INTEGER NOT NULL CHECK (health BETWEEN 0 AND max_health),
    alive        INTEGER NOT NULL DEFAULT 1 CHECK (alive IN (0, 1)),
    conditions   TEXT    NOT NULL DEFAULT '[]',
    -- Тело (D38): рост в сантиметрах, мускулы и полнота 0–100, телосложение.
    height_cm    INTEGER NOT NULL CHECK (height_cm BETWEEN {HEIGHT_MIN_CM} AND {HEIGHT_MAX_CM}),
    muscles      INTEGER NOT NULL CHECK (muscles BETWEEN 0 AND 100),
    fatness      INTEGER NOT NULL CHECK (fatness BETWEEN 0 AND 100),
    build        TEXT    NOT NULL DEFAULT ''
);

-- Отношения from_id к to_id: пять шкал (D28) и знает ли имя.
CREATE TABLE relation (
    from_id    TEXT    NOT NULL REFERENCES character(id),
    to_id      TEXT    NOT NULL REFERENCES character(id),
    {_scale("liking")},
    {_scale("trust")},
    {_scale("fear")},
    {_scale("respect")},
    {_scale("love")},
    knows_name INTEGER NOT NULL DEFAULT 0 CHECK (knows_name IN (0, 1)),
    PRIMARY KEY (from_id, to_id),
    CHECK (from_id <> to_id)
);

-- Способности персонажей (божественная воля, бессмертие, магия…).
CREATE TABLE ability (
    id           INTEGER PRIMARY KEY,
    character_id TEXT    NOT NULL REFERENCES character(id),
    kind         TEXT    NOT NULL,
    params       TEXT    NOT NULL DEFAULT '{{}}',
    UNIQUE (character_id, kind)
);

-- Предметы: у владельца или лежат в месте, но не то и другое сразу.
CREATE TABLE item (
    id          INTEGER PRIMARY KEY,
    kind        TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    owner_id    TEXT    REFERENCES character(id),
    location_id TEXT    REFERENCES location(id),
    base_price  INTEGER NOT NULL DEFAULT 0 CHECK (base_price >= 0),
    equipped    TEXT    CHECK (equipped IN ({_one_of(EQUIP_STATES)})),
    damage_min  INTEGER CHECK (damage_min >= 0),
    damage_max  INTEGER CHECK (damage_max >= damage_min),
    CHECK ((owner_id IS NULL) <> (location_id IS NULL)),
    CHECK (equipped IS NULL OR owner_id IS NOT NULL)
);

-- Факты. until и replaced_by заполнены, когда факт перестал быть верным.
CREATE TABLE fact (
    id          INTEGER PRIMARY KEY,
    subject     TEXT    NOT NULL,
    predicate   TEXT    NOT NULL,
    object      TEXT    NOT NULL,
    status      TEXT    NOT NULL CHECK (status IN ({_one_of(FACT_STATUSES)})),
    canon       INTEGER NOT NULL DEFAULT 0 CHECK (canon IN (0, 1)),
    since       INTEGER NOT NULL,
    until       INTEGER,
    source      TEXT    NOT NULL DEFAULT '',
    replaced_by INTEGER REFERENCES fact(id)
);
CREATE INDEX fact_subject ON fact (subject, predicate);

-- Кто какой факт знает и верит ли ему.
CREATE TABLE knowledge (
    character_id TEXT    NOT NULL REFERENCES character(id),
    fact_id      INTEGER NOT NULL REFERENCES fact(id),
    believes     INTEGER NOT NULL DEFAULT 1 CHECK (believes IN (0, 1)),
    source       TEXT    NOT NULL DEFAULT '',
    learned_at   INTEGER NOT NULL,
    PRIMARY KEY (character_id, fact_id)
);

-- Журнал событий: только дополняется (D7).
CREATE TABLE event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    time         INTEGER NOT NULL,
    kind         TEXT    NOT NULL,
    actor_id     TEXT,
    participants TEXT    NOT NULL DEFAULT '[]',
    data         TEXT    NOT NULL DEFAULT '{{}}',
    dice         TEXT,
    basis        TEXT    NOT NULL CHECK (basis IN ({_one_of(BASES)}))
);

-- Защита журнала самой базой: даже ошибка в коде не изменит прошлое.
CREATE TRIGGER event_no_update BEFORE UPDATE ON event
BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;
CREATE TRIGGER event_no_delete BEFORE DELETE ON event
BEGIN SELECT RAISE(ABORT, 'event log is append-only'); END;

{NPC_STATE}
-- Снимки для отката: время, последнее событие, файл копии базы.
CREATE TABLE snapshot (
    id            INTEGER PRIMARY KEY,
    time          INTEGER NOT NULL,
    last_event_id INTEGER,
    label         TEXT    NOT NULL DEFAULT '',
    file          TEXT    NOT NULL
);
"""


# Миграции: версия → SQL, который обновляет базу этой версии до следующей.
MIGRATIONS = {
    # 0.3 → 0.4: дом и работа жителя, состояние для симуляции.
    # Старым жителям дом и работа — там, где они стоят сейчас.
    1: f"""
ALTER TABLE character ADD COLUMN home_id TEXT REFERENCES location(id);
ALTER TABLE character ADD COLUMN work_id TEXT REFERENCES location(id);
UPDATE character SET home_id = location_id, work_id = location_id WHERE controller = 'ai';
{NPC_STATE}
""",
}


def create_schema(conn: sqlite3.Connection) -> None:
    """Создаёт все таблицы в пустой базе и записывает версию схемы."""
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def check_schema(conn: sqlite3.Connection) -> None:
    """Проверяет, что это мир Matricaria и программа умеет его открыть.

    Старая схема подходит: её обновит `upgrade_schema`.
    """
    version = schema_version(conn)
    if version == 0:
        raise SchemaError("This file is not a Matricaria world")
    if version > SCHEMA_VERSION:
        raise SchemaError(
            f"This world was saved by a newer version of Matricaria (schema {version})"
        )
    if version not in MIGRATIONS and version != SCHEMA_VERSION:
        raise SchemaError(f"Unsupported world schema version {version}")


def upgrade_schema(conn: sqlite3.Connection) -> int | None:
    """Обновляет базу до текущей схемы. Возвращает старую версию или None.

    Вызывается внутри транзакции: при ошибке база остаётся как была.
    """
    old = version = schema_version(conn)
    if version == SCHEMA_VERSION:
        return None
    while version < SCHEMA_VERSION:
        for statement in MIGRATIONS[version].split(";"):
            if statement.strip():
                conn.execute(statement)
        version += 1
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return old

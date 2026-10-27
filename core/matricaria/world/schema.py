"""Схема базы мира (SQLite) и её версия.

Версия схемы хранится в самой базе (`PRAGMA user_version`).
Когда в следующих версиях игры появятся новые таблицы, сюда добавится
миграция — шаг, который обновляет старое сохранение до новой схемы.
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

SCHEMA_VERSION = 1


def _one_of(values: tuple[str, ...]) -> str:
    """Список для проверки `IN (...)` в SQL."""
    return ", ".join(f"'{value}'" for value in values)


def _stat(name: str) -> str:
    return f"{name} INTEGER NOT NULL CHECK ({name} BETWEEN {STAT_MIN} AND {STAT_MAX})"


def _scale(name: str) -> str:
    low, high = RELATION_SCALES[name]
    return f"{name} INTEGER NOT NULL DEFAULT 0 CHECK ({name} BETWEEN {low} AND {high})"


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

-- Снимки для отката: время, последнее событие, файл копии базы.
CREATE TABLE snapshot (
    id            INTEGER PRIMARY KEY,
    time          INTEGER NOT NULL,
    last_event_id INTEGER,
    label         TEXT    NOT NULL DEFAULT '',
    file          TEXT    NOT NULL
);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    """Создаёт все таблицы в пустой базе и записывает версию схемы."""
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def check_schema(conn: sqlite3.Connection) -> None:
    """Проверяет, что база создана этой версией программы."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        raise SchemaError("This file is not a Matricaria world")
    if version > SCHEMA_VERSION:
        raise SchemaError(
            f"This world was saved by a newer version of Matricaria (schema {version})"
        )
    if version < SCHEMA_VERSION:
        # Миграций пока нет: первая версия схемы.
        raise SchemaError(f"Unsupported world schema version {version}")

"""Допустимые значения полей мира: режимы, статусы, шкалы, характеристики.

Здесь собраны все «словари» ядра, чтобы проверки и схема базы
брали значения из одного места.
"""

# Сеттинг мира: фэнтези и современность равноправны (D27).
SETTINGS = ("fantasy", "modern")
# Режимы правил: строгий, повествовательный (по умолчанию), свободный (D22).
RULE_MODES = ("strict", "narrative", "free")
DEFAULT_RULE_MODE = "narrative"
# Тип сценария: обычный или «Уютная история» (D30).
SCENARIO_TYPES = ("standard", "cozy")
# Передвижение: по карте или сценами, как в визуальной новелле (D30).
TRAVEL_MODES = ("map", "scenes")

# Кто управляет персонажем: игрок или ИИ (D26).
CONTROLLERS = ("player", "ai")

# Основание у каждого события (D22): по правилам, способностью, волей автора.
BASES = ("rules", "ability", "author")

# Статусы факта (docs/04-database.md).
FACT_STATUSES = ("truth", "belief", "rumor", "lie")

# Пять характеристик от 1 до 10 (docs/02-game-design.md).
STATS = ("strength", "agility", "endurance", "intellect", "charisma")
STAT_MIN = 1
STAT_MAX = 10
DEFAULT_STAT = 5

# Известные состояния персонажа; список открытый, можно добавлять свои.
CONDITIONS = ("wounded", "stunned", "unconscious")

# Пять шкал отношений и их пределы (D28).
RELATION_SCALES = {
    "liking": (-100, 100),
    "trust": (-100, 100),
    "fear": (-100, 100),
    "respect": (-100, 100),
    "love": (0, 100),
}

# Отметка у предмета: в руках или надето (docs/02-game-design.md).
EQUIP_STATES = ("held", "worn")

# Счета персонажа: наличные и деньги на счёте (D41).
ACCOUNTS = ("cash", "bank")

# Способности с особым смыслом для ядра (docs/02-game-design.md).
DIVINE_WILL = "divine_will"
IMMORTALITY = "immortality"
OMNISCIENCE = "omniscience"

MINUTES_PER_DAY = 24 * 60


def default_max_health(endurance: int) -> int:
    """Запас здоровья по выносливости: от 12 (выносливость 1) до 30 (10)."""
    return 10 + 2 * endurance


def format_time(minutes: int) -> str:
    """Игровое время в минутах от начала → «Day 3, 14:20» (день считается с 1)."""
    day, rest = divmod(minutes, MINUTES_PER_DAY)
    return f"Day {day + 1}, {rest // 60:02d}:{rest % 60:02d}"

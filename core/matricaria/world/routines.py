"""Распорядок жителей: сон, работа и свободное время по профессии (0.4).

Правила лежат в `routines/<сеттинг>.toml`. Здесь они читаются и
превращаются в простые вопросы: что по распорядку у жителя в эту минуту
и когда распорядок сменится.
"""

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .calendar import DAYS_PER_WEEK, WEEKDAYS, weekday_of_day
from .constants import ACCOUNTS, MINUTES_PER_DAY
from .errors import RuleError

ROUTINE_DIR = Path(__file__).resolve().parent / "routines"

SLEEP, WORK, FREE = "sleep", "work", "free"


def _minutes(text: str, where: str) -> int:
    try:
        hours, minutes = (int(part) for part in str(text).split(":"))
    except ValueError:
        raise RuleError(f"{where}: time must look like 07:30, got '{text}'") from None
    if not (0 <= hours <= 24 and 0 <= minutes < 60) or hours * 60 + minutes > MINUTES_PER_DAY:
        raise RuleError(f"{where}: no such time '{text}'")
    return hours * 60 + minutes


def _span(value, where: str) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise RuleError(f"{where}: expected [\"start\", \"end\"]")
    return _minutes(value[0], where), _minutes(value[1], where)


def _inside(minute: int, span: tuple[int, int]) -> bool:
    start, end = span
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end  # через полночь


@dataclass(frozen=True)
class Routine:
    """Распорядок одной профессии."""

    sleep: tuple[int, int]
    work: tuple[int, int] | None
    days_off: frozenset[str]
    eat_out: float
    sociable: float
    wage: int
    takings: tuple[int, int] | None
    payday: str  # день, когда выплачивают зарплату за неделю

    def works_on(self, day: int) -> bool:
        return self.work is not None and weekday_of_day(day) not in self.days_off

    def block_at(self, time: int) -> str:
        """Что по распорядку в эту минуту: сон, работа или свободное время."""
        day, minute = divmod(time, MINUTES_PER_DAY)
        if _inside(minute, self.sleep):
            return SLEEP
        if self.works_on(day) and _inside(minute, self.work):
            return WORK
        return FREE

    def next_change(self, time: int) -> int:
        """Ближайшая минута после `time`, когда распорядок может смениться."""
        day = time // MINUTES_PER_DAY
        marks = [0, *self.sleep, *(self.work or ())]
        return min(
            d * MINUTES_PER_DAY + mark
            for d in (day, day + 1)
            for mark in marks
            if d * MINUTES_PER_DAY + mark > time
        )

    def shift_end(self, day: int) -> int:
        """Минута, когда кончается рабочая смена дня `day`."""
        return day * MINUTES_PER_DAY + self.work[1]


@dataclass(frozen=True)
class Rules:
    """Правила жизни для одного сеттинга."""

    setting: str
    food: dict[str, int]  # вид места → цена еды
    social: tuple[str, ...]
    wages_to: str
    takings_to: str
    card: bool
    routines: dict[str, Routine]
    default: Routine

    def routine(self, profession: str) -> Routine:
        return self.routines.get(profession, self.default)


def _routine(values: dict, where: str, payday: str) -> Routine:
    work = _span(values["work"], where) if values.get("work") else None
    if work is not None and work[0] >= work[1]:
        raise RuleError(f"{where}: work must start and end on the same day")
    days_off = frozenset(values.get("days_off", []))
    unknown = days_off - set(WEEKDAYS)
    if unknown:
        raise RuleError(f"{where}: unknown days {', '.join(sorted(unknown))}")
    takings = values.get("takings")
    if takings is not None:
        if len(takings) != 2 or not 0 <= takings[0] <= takings[1]:
            raise RuleError(f"{where}: takings must be [from, to]")
        takings = (int(takings[0]), int(takings[1]))
    return Routine(
        sleep=_span(values.get("sleep", ["22:00", "07:00"]), where),
        work=work,
        days_off=days_off,
        eat_out=float(values.get("eat_out", 0.4)),
        sociable=float(values.get("sociable", 0.3)),
        wage=int(values.get("wage", 0)),
        takings=takings,
        payday=_payday(payday, days_off),
    )


def _payday(payday: str, days_off: frozenset[str]) -> str:
    """Если в день выплаты выходной, платят в последний рабочий день перед ним."""
    index = WEEKDAYS.index(payday)
    for back in range(DAYS_PER_WEEK):
        day = WEEKDAYS[(index - back) % DAYS_PER_WEEK]
        if day not in days_off:
            return day
    return payday


@cache
def load_rules(setting: str) -> Rules:
    path = ROUTINE_DIR / f"{setting}.toml"
    if not path.is_file():
        raise RuleError(f"No routine rules for setting '{setting}'")
    with path.open("rb") as file:
        try:
            data = tomllib.load(file)
        except tomllib.TOMLDecodeError as error:
            raise RuleError(f"Routine file {path.name} is broken: {error}") from error
    money = data.get("money", {})
    places = data.get("places", {})
    for key in ("wages_to", "takings_to"):
        if money.get(key, "cash") not in ACCOUNTS:
            raise RuleError(f"{path.name}: {key} must be cash or bank")
    payday = money.get("payday", "fri")
    if payday not in WEEKDAYS:
        raise RuleError(f"{path.name}: unknown payday '{payday}'")
    defaults = data.get("defaults", {})
    return Rules(
        setting=setting,
        food={kind: int(price) for kind, price in places.get("food", {}).items()},
        social=tuple(places.get("social", [])),
        wages_to=money.get("wages_to", "cash"),
        takings_to=money.get("takings_to", "cash"),
        card=bool(money.get("card", False)),
        routines={
            name: _routine({**defaults, **values}, f"{path.name}: {name}", payday)
            for name, values in data.get("professions", {}).items()
        },
        default=_routine(defaults, f"{path.name}: defaults", payday),
    )

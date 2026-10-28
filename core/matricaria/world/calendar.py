"""Календарь мира (D50): 12 месяцев по 30 дней, год — 360 дней.

Мир начинается в понедельник, в первый день весны, в 00:00.
Месяцы называются по временам года: ранняя, середина и поздняя весна и т.д.
Так календарь подходит и фэнтези, и современности.
"""

from dataclasses import dataclass

from .constants import MINUTES_PER_DAY

DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 30
MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = DAYS_PER_MONTH * MONTHS_PER_YEAR

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SEASONS = ("spring", "summer", "autumn", "winter")
MONTH_PARTS = ("Early", "Mid", "Late")


@dataclass(frozen=True)
class Date:
    """Дата и время по игровым минутам. Год, месяц и день считаются с 1."""

    year: int
    month: int
    day: int
    weekday: int  # 0 — понедельник
    hour: int
    minute: int

    @property
    def season(self) -> str:
        return SEASONS[(self.month - 1) // 3]

    @property
    def month_name(self) -> str:
        part = MONTH_PARTS[(self.month - 1) % 3]
        return f"{part} {self.season.capitalize()}"


def date_of(minutes: int) -> Date:
    days, rest = divmod(minutes, MINUTES_PER_DAY)
    year, day_of_year = divmod(days, DAYS_PER_YEAR)
    month, day = divmod(day_of_year, DAYS_PER_MONTH)
    return Date(
        year=year + 1,
        month=month + 1,
        day=day + 1,
        weekday=days % DAYS_PER_WEEK,
        hour=rest // 60,
        minute=rest % 60,
    )


def format_date(minutes: int) -> str:
    """Игровое время → «Monday, Early Spring 1, Year 1, 06:30»."""
    d = date_of(minutes)
    return (f"{WEEKDAY_NAMES[d.weekday]}, {d.month_name} {d.day}, Year {d.year}, "
            f"{d.hour:02d}:{d.minute:02d}")


def weekday_of_day(day_index: int) -> str:
    """День от начала мира (с 0) → «mon»…«sun»."""
    return WEEKDAYS[day_index % DAYS_PER_WEEK]

"""Обхваты тела и размер бюстгальтера (идея И1, D58).

Ядро хранит обхваты в сантиметрах. Дюймы — только способ показа,
его выбирает игрок. Размер бюстгальтера не хранится, а считается
из обхватов, поэтому цифры не противоречат друг другу.
"""

CM_PER_INCH = 2.54
UNITS = ("cm", "in")

# Американские чашки: разница груди и обхвата под грудью в дюймах → буква.
# 0 — AA, 1 — A, … 5 — DD, 6 — DDD, дальше G, H, I… до Z.
CUPS = ("AA", "A", "B", "C", "D", "DD", "DDD") + tuple("GHIJKLMNOPQRSTUVWXYZ")


def bra_size(bust_cm: int | None, underbust_cm: int | None) -> str | None:
    """Размер по американской системе, например «34C».

    Число (обхват пояса) — обхват под грудью в дюймах, округлённый до чётного
    вверх; буква — на сколько дюймов грудь больше пояса. Если букв не хватает,
    размер «вне таблицы». Без обоих обхватов размера нет.
    """
    if bust_cm is None or underbust_cm is None:
        return None
    band = round(underbust_cm / CM_PER_INCH)
    band += band % 2
    difference = round(bust_cm / CM_PER_INCH - band)
    if difference >= len(CUPS):
        return f"{band}, cup off the chart"
    return f"{band}{CUPS[max(0, difference)]}"


def format_length(cm: int, units: str = "cm") -> str:
    """Длина для игрока: «92 cm», «36 in»; большое — в метрах, км, футах, милях."""
    if units == "in":
        inches = cm / CM_PER_INCH
        if inches < 120:
            return f"{inches:.1f} in".replace(".0 in", " in")
        if inches < 63_360:
            return f"{inches / 12:,.0f} ft"
        return f"{inches / 63_360:,.1f} mi"
    if cm < 1000:
        return f"{cm} cm"
    if cm < 100_000:
        return f"{cm / 100:,.1f} m".replace(".0 m", " m")
    return f"{cm / 100_000:,.1f} km".replace(".0 km", " km")

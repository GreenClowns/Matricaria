"""Симуляция мира (0.4, docs/08-simulation.md): жители живут без игрока.

Каждый житель (персонаж под управлением ИИ) сам решает, чем заняться:
спит, работает, ест, идёт к людям или отдыхает дома. Решение зависит
от распорядка профессии (`routines/*.toml`), потребностей и случайности
по seed мира (D51). Житель решает не каждую минуту, а в нужный момент:
когда кончится занятие, сменится распорядок или он проголодается.

Подробность зависит от того, где житель (D52):
- `near` — там же, где герой: решения с точностью до минуты;
- `town` — в том же поселении: с точностью до часа;
- `far` — в другом месте мира: итоги за день, без походов в гости;
- `summary` — пропуск больше месяца: итоги за неделю для всех.

Всё, что меняет мир (ходьба, платежи, заработок), идёт через обычные
методы `World` с основанием `rules` и пишется в журнал. Потребности и
занятие — служебное состояние симуляции (`npc_state`), оно меняется без
отдельных событий (D53).
"""

import heapq
import math
from dataclasses import dataclass, field

from .base import WorldBase
from .calendar import DAYS_PER_WEEK, weekday_of_day
from .chance import rng
from .constants import MINUTES_PER_DAY
from .errors import RuleError
from .models import Character, NpcState
from .routines import FREE, SLEEP, WORK, Routine, load_rules

# Причина хода часов в окне: такие шаги не пишутся в журнал (D53).
CLOCK = "clock"
# Пропуск длиннее месяца считается итогами по неделям.
SUMMARY_AFTER = 30 * MINUTES_PER_DAY

LEVELS = ("near", "town", "far", "summary")
RANK = {level: index for index, level in enumerate(LEVELS)}

NEEDS = ("food", "rest", "social", "safety")
FRESH = {"food": 80.0, "rest": 80.0, "social": 60.0, "safety": 100.0}
# После итогового шага житель «как обычно»: сыт, отдохнул.
NORMAL = {"food": 70.0, "rest": 70.0, "social": 60.0}

HUNGRY = 35  # ниже — идёт есть
LONELY = 40  # ниже — в свободное время ищет компанию
TIRED = 25  # ниже — в свободное время идёт домой отдыхать
SHORT_BREAK = 45  # свободное время короче — житель никуда не идёт
MEAL_MINUTES = 30
MEAL_FOOD = 60

# Как меняются еда и отдых за час в разных занятиях.
FOOD_PER_HOUR = {"sleep": -2.5}
FOOD_AWAKE = -6.0
REST_PER_HOUR = {"sleep": 14.0, "work": -6.0, "rest": 2.0}
REST_AWAKE = -4.0
SOCIAL_WITH_COMPANY = 15.0
SOCIAL_ALONE = -3.0
SAFETY_RECOVERY = 10.0

ACTIVITY_OF_BLOCK = {SLEEP: "sleep", WORK: "work", FREE: "rest"}


@dataclass(frozen=True)
class TimeReport:
    """Что случилось за пропуск времени."""

    start: int
    end: int
    first_event_id: int  # события пропуска — с номерами больше этого
    last_event_id: int
    counts: dict[str, int] = field(default_factory=dict)  # вид события → сколько
    money: dict[str, int] = field(default_factory=dict)  # кто сколько заработал (−потратил)

    @property
    def events(self) -> int:
        return self.last_event_id - self.first_event_id


class SimulationMixin(WorldBase):
    # --- Чтение --------------------------------------------------------

    def npc_state(self, character_id: str) -> NpcState | None:
        """Чем занят житель и его потребности. У героя и до первой симуляции — None."""
        row = self._conn.execute(
            "SELECT * FROM npc_state WHERE character_id = ?", (character_id,)
        ).fetchone()
        return NpcState.from_row(row) if row else None

    # --- Ход времени ---------------------------------------------------

    def advance_time(self, minutes: int, *, basis: str = "rules", reason: str = "") -> int:
        """Переносит время вперёд, мир живёт. Возвращает новое время."""
        return self.skip_time(minutes, basis=basis, reason=reason).end

    def skip_time(self, minutes: int, *, basis: str = "rules", reason: str = "") -> TimeReport:
        """Пропуск времени: жители живут по распорядку, всё пишется в журнал.

        Назад время идёт только откатом к снимку. Ход часов в окне
        (`reason="clock"`) не пишет событие `time_advanced` на каждую минуту.
        """
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
            raise RuleError("Time can only move forward by a positive number of minutes")
        with self._change():
            self._check_basis(basis, None, action="Moving time")
            start = self.time
            first = self.last_event_id()
            money_before = self._money()
            _Life(self, start + minutes, summary=minutes > SUMMARY_AFTER).run()
            if reason != CLOCK:
                self._record(
                    "time_advanced",
                    basis=basis,
                    data={"from": start, "to": start + minutes, "minutes": minutes,
                          "reason": reason, "events": self.last_event_id() - first},
                )
            counts = dict(self._conn.execute(
                "SELECT kind, COUNT(*) FROM event WHERE id > ? AND kind <> 'time_advanced'"
                " GROUP BY kind ORDER BY kind",
                (first,),
            ).fetchall())
            money_after = self._money()
            return TimeReport(
                start=start,
                end=start + minutes,
                first_event_id=first,
                last_event_id=self.last_event_id(),
                counts=counts,
                money={cid: money_after[cid] - money_before.get(cid, 0)
                       for cid in money_after
                       if money_after[cid] != money_before.get(cid, 0)},
            )

    def _money(self) -> dict[str, int]:
        return dict(self._conn.execute("SELECT id, cash + bank FROM character").fetchall())

    def _set_time(self, time: int) -> None:
        self._conn.execute("UPDATE world SET time = ?", (time,))


class _Life:
    """Один пропуск времени: очередь решений жителей по времени."""

    def __init__(self, world: SimulationMixin, until: int, *, summary: bool) -> None:
        self.world = world
        self.conn = world._conn
        self.until = until
        self.summary = summary
        info = world.info
        self.seed = info.seed
        self.rules = load_rules(info.setting)
        self.locations = {loc.id: loc for loc in world.locations()}
        players = world.players()
        self.hero_place = players[0].location_id if players else None

    # --- Очередь -------------------------------------------------------

    def run(self) -> None:
        start = self.world.time
        self._create_missing_states(start)
        queue: list[tuple[int, int, str]] = []
        rows = self.conn.execute(
            "SELECT n.*, c.location_id, s.alive FROM npc_state n"
            " JOIN character c ON c.id = n.character_id"
            " JOIN stats s ON s.character_id = n.character_id"
            " WHERE c.controller = 'ai' ORDER BY c.rowid"
        ).fetchall()
        for order, row in enumerate(rows):
            if not row["alive"]:
                continue
            next_at = row["next_at"]
            # Герой рядом — житель решает заново с новой подробностью.
            if next_at < start or RANK[self.level_for(row["location_id"])] < RANK[row["level"]]:
                next_at = start
            heapq.heappush(queue, (next_at, order, row["character_id"]))
        while queue and queue[0][0] <= self.until:
            time, order, character_id = heapq.heappop(queue)
            self.world._set_time(time)
            next_at = self.step(character_id, time)
            if next_at is not None:
                heapq.heappush(queue, (next_at, order, character_id))
        self.world._set_time(self.until)

    def _create_missing_states(self, time: int) -> None:
        self.conn.execute(
            "INSERT INTO npc_state (character_id, next_at, updated_at, food, rest, social, safety)"
            " SELECT id, ?, ?, ?, ?, ?, ? FROM character WHERE controller = 'ai'"
            " AND id NOT IN (SELECT character_id FROM npc_state)",
            (time, time, *(FRESH[need] for need in NEEDS)),
        )

    def step(self, character_id: str, time: int) -> int | None:
        """Решение жителя в минуту `time`. Возвращает время следующего решения."""
        c = self.world.character(character_id)
        if not c.alive or c.controller != "ai":
            return None
        state = dict(self.conn.execute(
            "SELECT * FROM npc_state WHERE character_id = ?", (character_id,)
        ).fetchone())
        if not c.conscious:
            self.update_needs(c, state, time)
            state["next_at"] = time + 60
            self.save(state)
            return state["next_at"]
        routine = self.rules.routine(c.profession)
        level = self.level_for(c.location_id)
        if level in ("far", "summary"):
            next_at = self.coarse(c, state, time, routine, level)
        else:
            next_at = self.fine(c, state, time, routine)
        state["next_at"] = next_at
        self.save(state)
        return next_at

    def save(self, state: dict) -> None:
        columns = [key for key in state if key != "character_id"]
        self.conn.execute(
            f"UPDATE npc_state SET {', '.join(f'{key} = ?' for key in columns)}"
            " WHERE character_id = ?",
            (*(state[key] for key in columns), state["character_id"]),
        )

    # --- Где житель ----------------------------------------------------

    def root(self, location_id: str | None) -> str | None:
        while location_id is not None and self.locations[location_id].parent_id is not None:
            location_id = self.locations[location_id].parent_id
        return location_id

    def level_for(self, location_id: str | None) -> str:
        if self.summary:
            return "summary"
        if self.hero_place is None or location_id is None:
            return "town"
        if location_id == self.hero_place:
            return "near"
        if self.root(location_id) == self.root(self.hero_place):
            return "town"
        return "far"

    def nearby(self, c: Character, kinds) -> list[str]:
        """Места этих видов в том же поселении, что и житель, по порядку."""
        root = self.root(c.location_id)
        return [loc.id for loc in self.locations.values()
                if loc.kind in kinds and self.root(loc.id) == root]

    def has_company(self, c: Character, activity: str) -> bool:
        """Есть ли рядом с кем поговорить. На работе в трактире или кафе — всегда:
        там посетители, которых мир не считает поимённо."""
        if c.location_id is None:
            return False
        kind = self.locations[c.location_id].kind
        if activity == "work" and (kind in self.rules.food or kind in self.rules.social):
            return True
        rows = self.conn.execute(
            "SELECT s.conditions FROM character c JOIN stats s ON s.character_id = c.id"
            " WHERE c.location_id = ? AND c.id <> ? AND s.alive = 1",
            (c.location_id, c.id),
        ).fetchall()
        return any("unconscious" not in row["conditions"] for row in rows)

    def seller(self, place: str, time: int) -> Character | None:
        """Хозяин, который сейчас работает в этом месте. Без него место закрыто."""
        rows = self.conn.execute(
            "SELECT c.id FROM character c JOIN stats s ON s.character_id = c.id"
            " WHERE c.work_id = ? AND c.location_id = ? AND c.controller = 'ai'"
            " AND s.alive = 1 ORDER BY c.rowid",
            (place, place),
        ).fetchall()
        for row in rows:
            owner = self.world.character(row["id"])
            if owner.conscious and self.rules.routine(owner.profession).block_at(time) == WORK:
                return owner
        return None

    def go(self, c: Character, target: str | None) -> None:
        if target is not None and target != c.location_id:
            self.world.move_character(c.id, target, basis="rules")

    # --- Потребности ---------------------------------------------------

    def update_needs(self, c: Character, state: dict, time: int) -> None:
        hours = (time - state["updated_at"]) / 60
        activity = state["activity"]
        state["food"] += FOOD_PER_HOUR.get(activity, FOOD_AWAKE) * hours
        state["rest"] += REST_PER_HOUR.get(activity, REST_AWAKE) * hours
        if activity != "sleep":
            # Компания в начале и в конце занятия — по половине времени.
            share = (state["company"] + self.has_company(c, activity)) / 2
            rate = SOCIAL_ALONE + (SOCIAL_WITH_COMPANY - SOCIAL_ALONE) * share
            state["social"] += rate * hours
        state["safety"] += SAFETY_RECOVERY * hours
        for need in NEEDS:
            state[need] = max(0.0, min(100.0, state[need]))
        state["updated_at"] = time

    @staticmethod
    def minutes_to_hungry(state: dict, activity: str) -> int:
        rate = -FOOD_PER_HOUR.get(activity, FOOD_AWAKE)
        return max(15, math.ceil((state["food"] - HUNGRY) / rate * 60))

    # --- Подробный шаг: рядом с героем и в его поселении ---------------------

    def fine(self, c: Character, state: dict, time: int, routine: Routine) -> int:
        self.update_needs(c, state, time)
        block = routine.block_at(time)
        day = time // MINUTES_PER_DAY
        if state["shift_day"] is not None and (block != WORK or day != state["shift_day"]):
            self.income(c, state, routine, [state["shift_day"]])
            state["shift_day"] = None
        until = routine.next_change(time)
        r = rng(self.seed, "decide", c.id, time)
        if block == SLEEP:
            activity, target = "sleep", c.home_id
        elif state["food"] < HUNGRY and state["activity"] != "eat":
            activity, target = "eat", None
            until = self.meal(c, state, time, routine, r)
        elif block == WORK and c.work_id is not None:
            activity, target = "work", c.work_id
            state["shift_day"] = day
            until = min(until, time + self.minutes_to_hungry(state, activity))
        elif until - time < SHORT_BREAK:
            activity, target = "rest", None  # скоро снова дела: остаётся, где есть
        else:
            places = [p for p in self.nearby(c, self.rules.social)
                      if self.locations[p].kind not in self.rules.food or self.seller(p, time)]
            wants_company = state["social"] < LONELY or r.random() < routine.sociable
            if places and state["rest"] >= TIRED and wants_company:
                activity, target = "socialize", r.choice(places)
                length = r.randint(60, 150)
            else:
                activity, target = "rest", c.home_id
                length = r.randint(60, 180)
            until = min(until, time + length, time + self.minutes_to_hungry(state, activity))
        self.go(c, target)
        c = self.world.character(c.id)
        state["activity"] = activity
        state["company"] = int(self.has_company(c, activity))
        # Точность следующего решения — по месту, куда житель пришёл.
        level = state["level"] = self.level_for(c.location_id)
        if level == "near":
            until += r.randint(0, 10)
        else:
            until = math.ceil(until / 60) * 60
        if level not in ("near", "town"):
            until = math.ceil(until / MINUTES_PER_DAY) * MINUTES_PER_DAY  # ушёл далеко
        return until if until > time else time + (1 if level == "near" else 60)

    def meal(self, c: Character, state: dict, time: int, routine: Routine, r) -> int:
        """Поесть: там, где кормят (за деньги, если это не свой трактир), или дома даром."""
        price_of = self.rules.food
        here = c.location_id
        place = None
        if here is not None and self.locations[here].kind in price_of and self.seller(here, time):
            place = here
        elif r.random() < routine.eat_out:
            options = [p for p in self.nearby(c, price_of)
                       if self.seller(p, time) and self.can_pay(c, price_of[self.locations[p].kind])]
            if options:
                place = r.choice(options)
        if place is not None:
            seller = self.seller(place, time)
            self.go(c, place)
            if seller.id != c.id and not self.pay_meal(c, seller, place):
                place = None
        if place is None:
            self.go(self.world.character(c.id), c.home_id)
        state["food"] = min(100.0, state["food"] + MEAL_FOOD)
        return time + MEAL_MINUTES

    def can_pay(self, c: Character, price: int) -> bool:
        return c.cash >= price or (self.rules.card and c.bank >= price)

    def pay_meal(self, c: Character, seller: Character, place: str) -> bool:
        price = self.rules.food[self.locations[place].kind]
        name = self.locations[place].name
        if c.cash >= price:
            account = "cash"
        elif self.rules.card and c.bank >= price:
            account = "bank"
        else:
            # Денег нет — придётся есть дома. Об этом узнает журнал (и сплетники).
            self.world._record(
                "could_not_afford",
                basis="rules",
                actor_id=c.id,
                participants=[c.id, place, seller.id],
                data={"what": "meal", "price": price, "place": place},
            )
            return False
        self.world.pay(c.id, seller.id, price, account=account, reason=f"meal at {name}")
        return True

    # --- Заработок -----------------------------------------------------

    def income(self, c: Character, state: dict, routine: Routine, days: list[int]) -> None:
        """Выручка и зарплата за рабочие дни `days`. Выручка дня — по seed, в любом режиме."""
        if not days:
            return
        takings = 0
        payday = False
        for day in days:
            if routine.takings is not None:
                takings += rng(self.seed, "takings", c.id, day).randint(*routine.takings)
            if routine.wage:
                state["owed"] += routine.wage
                payday = payday or weekday_of_day(day) == routine.payday
        work = self.locations[c.work_id].name if c.work_id else "work"
        if takings:
            note = f"takings at {work}" + (f" for {len(days)} days" if len(days) > 1 else "")
            self.world.earn_money(c.id, takings, account=self.rules.takings_to,
                                  source="takings", note=note)
        if payday and state["owed"]:
            self.world.earn_money(c.id, state["owed"], account=self.rules.wages_to,
                                  source="wage", note=f"weekly wage ({c.profession})")
            state["owed"] = 0

    # --- Итоговый шаг: далеко от героя или долгий пропуск --------------------

    def living_costs(self, c: Character, routine: Routine, days: range) -> None:
        """Еда вне дома за прошедшие дни одной тратой: в итогах житель ест там же,
        где обычно, но к хозяину поимённо не ходит (его выручку считает `income`)."""
        home = self.world.character(c.id)
        places = [p for p in self.nearby(home, self.rules.food) if self.has_owner(p)]
        if not places or not days or home.work_id in places:
            return  # кормить негде, или житель сам хозяин трактира
        prices = [self.rules.food[self.locations[p].kind] for p in places]
        meals = sum(
            sum(1 for _ in range(2) if r.random() < routine.eat_out)
            for r in (rng(self.seed, "meals", c.id, day) for day in days)
        )
        cost = meals * min(prices)
        if not cost:
            return
        cash = min(cost, home.cash)
        if cash:
            self.world.spend_money(c.id, cash, note=f"{cash // min(prices)} meals out")
        rest = cost - cash
        if rest and self.rules.card and home.bank:
            paid = min(rest, home.bank)
            self.world.spend_money(c.id, paid, account="bank", note="meals out by card")

    def has_owner(self, place: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM character c JOIN stats s ON s.character_id = c.id"
            " WHERE c.work_id = ? AND c.controller = 'ai' AND s.alive = 1",
            (place,),
        ).fetchone() is not None

    def coarse(self, c: Character, state: dict, time: int, routine: Routine, level: str) -> int:
        """Итоги с прошлого решения: заработок за отработанные дни и где житель сейчас.

        В итоговом шаге жители не ходят в гости и едят дома (D52).
        """
        done = None
        if state["shift_day"] is not None and routine.work is not None \
                and routine.shift_end(state["shift_day"]) <= time:
            done = state["shift_day"]
            state["shift_day"] = None
        since = state["updated_at"]
        days = [] if done is None else [done]
        days += [
            day
            for day in range(since // MINUTES_PER_DAY - 1, time // MINUTES_PER_DAY + 1)
            if day != done and routine.works_on(day)
            and since < routine.shift_end(day) <= time
        ]
        self.income(c, state, routine, days)
        self.living_costs(c, routine, range(since // MINUTES_PER_DAY, time // MINUTES_PER_DAY))
        state.update(NORMAL)
        state["updated_at"] = time
        block = routine.block_at(time)
        if block == WORK and c.work_id is None:
            block = FREE
        target = c.work_id if block == WORK else c.home_id
        self.go(c, target)
        state["activity"] = ACTIVITY_OF_BLOCK[block]
        state["company"] = 0
        state["level"] = level
        if level == "summary":
            week = DAYS_PER_WEEK * MINUTES_PER_DAY
            return (time // week + 1) * week
        if target is not None and RANK[self.level_for(target)] < RANK[level]:
            state["level"] = self.level_for(target)
            return time + 60  # пришёл туда, где подробнее
        return (time // MINUTES_PER_DAY + 1) * MINUTES_PER_DAY

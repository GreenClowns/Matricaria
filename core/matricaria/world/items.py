"""Предметы и деньги. Всё критичное проверяет код (D17): ИИ не выдаст того, чего нет."""

from .base import WorldBase, _require_choice
from .constants import ACCOUNTS, EQUIP_STATES
from .errors import NotFoundError, RuleError
from .models import Item


class ItemsMixin(WorldBase):
    # --- Предметы: чтение ----------------------------------------------

    def item(self, item_id: int) -> Item:
        return Item.from_row(self._item_row(item_id))

    def items(
        self, *, owner_id: str | None = None, location_id: str | None = None
    ) -> list[Item]:
        """Предметы персонажа, предметы, лежащие в месте, или все."""
        if owner_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM item WHERE owner_id = ? ORDER BY id", (owner_id,)
            )
        elif location_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM item WHERE location_id = ? ORDER BY id", (location_id,)
            )
        else:
            rows = self._conn.execute("SELECT * FROM item ORDER BY id")
        return [Item.from_row(row) for row in rows]

    def _item_row(self, item_id: int):
        row = self._conn.execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No item #{item_id}")
        return row

    # --- Предметы: изменения -------------------------------------------

    def create_item(
        self,
        kind: str,
        name: str,
        *,
        owner_id: str | None = None,
        location_id: str | None = None,
        base_price: int = 0,
        damage: tuple[int, int] | None = None,
        basis: str = "author",
        actor_id: str | None = None,
    ) -> Item:
        """Создаёт предмет у владельца или в месте.

        Из ничего предметы появляются только волей автора или чудом.
        """
        if not kind.strip() or not name.strip():
            raise RuleError("Item kind and name cannot be empty")
        if (owner_id is None) == (location_id is None):
            raise RuleError("An item needs either an owner or a location")
        if base_price < 0:
            raise RuleError("Price cannot be negative")
        damage_min = damage_max = None
        if damage is not None:
            damage_min, damage_max = damage
            if not 0 <= damage_min <= damage_max:
                raise RuleError(f"Bad damage range {damage_min}-{damage_max}")
        with self._change():
            self._check_basis(
                basis, actor_id, action="Creating an item from nothing", rules_allow=False
            )
            if owner_id is not None:
                self._character_row(owner_id)
            else:
                self._location_row(location_id)
            cursor = self._conn.execute(
                "INSERT INTO item (kind, name, owner_id, location_id, base_price,"
                " damage_min, damage_max) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, name, owner_id, location_id, base_price, damage_min, damage_max),
            )
            item_id = cursor.lastrowid
            self._record(
                "item_created",
                basis=basis,
                actor_id=actor_id,
                participants=[p for p in (owner_id, location_id) if p],
                data={
                    "item_id": item_id,
                    "kind": kind,
                    "name": name,
                    "owner_id": owner_id,
                    "location_id": location_id,
                    "base_price": base_price,
                    "damage": list(damage) if damage else None,
                },
            )
        return self.item(item_id)

    def give_item(
        self,
        item_id: int,
        to_id: str,
        *,
        basis: str = "rules",
        actor_id: str | None = None,
    ) -> None:
        """Владелец отдаёт предмет другому персонажу в том же месте.

        Волей автора или способностью предмет можно отдать кому угодно и откуда угодно.
        """
        with self._change():
            item = self._item_row(item_id)
            if basis == "rules":
                actor_id = actor_id or item["owner_id"]
            self._check_basis(basis, actor_id, action="Giving an item")
            receiver = self._character_row(to_id)
            if item["owner_id"] == to_id:
                raise RuleError(f"{receiver['name']} already has {item['name']}")
            if basis == "rules":
                if item["owner_id"] is None or item["owner_id"] != actor_id:
                    raise RuleError(f"Only the owner can give away {item['name']}")
                giver = self._character_row(actor_id)
                if not receiver["alive"]:
                    raise RuleError(f"{receiver['name']} is dead")
                if giver["location_id"] != receiver["location_id"]:
                    raise RuleError(f"{receiver['name']} is not here")
            self._conn.execute(
                "UPDATE item SET owner_id = ?, location_id = NULL, equipped = NULL WHERE id = ?",
                (to_id, item_id),
            )
            self._record(
                "item_given",
                basis=basis,
                actor_id=actor_id,
                participants=[p for p in (item["owner_id"], to_id, item["location_id"]) if p],
                data={
                    "item_id": item_id,
                    "name": item["name"],
                    "from_owner": item["owner_id"],
                    "from_location": item["location_id"],
                    "to": to_id,
                },
            )

    def pick_up(self, item_id: int, character_id: str, *, basis: str = "rules") -> None:
        """Персонаж поднимает предмет, который лежит там же, где он."""
        with self._change():
            item = self._item_row(item_id)
            self._check_basis(basis, character_id, action="Picking up")
            row = self._character_row(character_id)
            if item["location_id"] is None:
                raise RuleError(f"{item['name']} belongs to someone")
            if item["location_id"] != row["location_id"]:
                raise RuleError(f"{item['name']} is not here")
            self._conn.execute(
                "UPDATE item SET owner_id = ?, location_id = NULL WHERE id = ?",
                (character_id, item_id),
            )
            self._record(
                "item_picked_up",
                basis=basis,
                actor_id=character_id,
                participants=[character_id, item["location_id"]],
                data={"item_id": item_id, "name": item["name"]},
            )

    def drop_item(self, item_id: int, character_id: str, *, basis: str = "rules") -> None:
        """Владелец кладёт предмет там, где стоит."""
        with self._change():
            item = self._item_row(item_id)
            self._check_basis(basis, character_id, action="Dropping")
            row = self._character_row(character_id)
            if item["owner_id"] != character_id:
                raise RuleError(f"{row['name']} does not have {item['name']}")
            if row["location_id"] is None:
                raise RuleError(f"{row['name']} is nowhere to drop it")
            self._conn.execute(
                "UPDATE item SET owner_id = NULL, location_id = ?, equipped = NULL WHERE id = ?",
                (row["location_id"], item_id),
            )
            self._record(
                "item_dropped",
                basis=basis,
                actor_id=character_id,
                participants=[character_id, row["location_id"]],
                data={"item_id": item_id, "name": item["name"]},
            )

    def place_item(
        self,
        item_id: int,
        location_id: str,
        *,
        basis: str = "author",
        actor_id: str | None = None,
    ) -> None:
        """Переносит предмет в место без участия владельца: волей автора или чудом."""
        with self._change():
            item = self._item_row(item_id)
            self._check_basis(basis, actor_id, action="Moving an item", rules_allow=False)
            self._location_row(location_id)
            self._conn.execute(
                "UPDATE item SET owner_id = NULL, location_id = ?, equipped = NULL WHERE id = ?",
                (location_id, item_id),
            )
            self._record(
                "item_placed",
                basis=basis,
                actor_id=actor_id,
                participants=[p for p in (item["owner_id"], item["location_id"], location_id) if p],
                data={
                    "item_id": item_id,
                    "name": item["name"],
                    "from_owner": item["owner_id"],
                    "from_location": item["location_id"],
                    "to": location_id,
                },
            )

    def equip(
        self, item_id: int, state: str | None, *, basis: str = "rules"
    ) -> None:
        """Берёт предмет в руки (`held`), надевает (`worn`) или убирает (`None`)."""
        if state is not None:
            _require_choice("equip state", state, EQUIP_STATES)
        with self._change():
            item = self._item_row(item_id)
            if item["owner_id"] is None:
                raise RuleError(f"Nobody has {item['name']}")
            self._check_basis(basis, item["owner_id"], action="Equipping")
            if item["equipped"] == state:
                raise RuleError(f"{item['name']} is already {state or 'put away'}")
            self._conn.execute("UPDATE item SET equipped = ? WHERE id = ?", (state, item_id))
            self._record(
                "item_equipped",
                basis=basis,
                actor_id=item["owner_id"],
                participants=[item["owner_id"]],
                data={"item_id": item_id, "name": item["name"], "from": item["equipped"],
                      "to": state},
            )

    # --- Деньги --------------------------------------------------------

    @staticmethod
    def _check_amount(amount: int) -> None:
        if not isinstance(amount, int) or amount <= 0:
            raise RuleError("Amount must be a positive whole number")

    def _balance(self, character_id: str, account: str) -> int:
        return self._conn.execute(
            f"SELECT {account} FROM character WHERE id = ?", (character_id,)
        ).fetchone()[0]

    def _add_money(self, character_id: str, account: str, amount: int) -> None:
        self._conn.execute(
            f"UPDATE character SET {account} = {account} + ? WHERE id = ?",
            (amount, character_id),
        )

    def pay(
        self,
        from_id: str,
        to_id: str,
        amount: int,
        *,
        account: str = "cash",
        basis: str = "rules",
        reason: str = "",
    ) -> None:
        """Платёж. Наличные — только из рук в руки в одном месте, перевод со счёта — куда угодно."""
        self._check_amount(amount)
        _require_choice("account", account, ACCOUNTS)
        with self._change():
            self._check_basis(basis, from_id, action="Paying")
            payer = self._character_row(from_id)
            payee = self._character_row(to_id)
            if from_id == to_id:
                raise RuleError("Cannot pay yourself")
            if (
                basis == "rules"
                and account == "cash"
                and payer["location_id"] != payee["location_id"]
            ):
                raise RuleError(f"{payee['name']} is not here to take cash")
            if payer[account] < amount:
                raise RuleError(
                    f"{payer['name']} has only {payer[account]} ({account}), {amount} needed"
                )
            self._add_money(from_id, account, -amount)
            self._add_money(to_id, account, amount)
            self._record(
                "money_paid",
                basis=basis,
                actor_id=from_id,
                participants=[from_id, to_id],
                data={"amount": amount, "account": account, "reason": reason},
            )

    def deposit(self, character_id: str, amount: int, *, basis: str = "rules") -> None:
        """Наличные → на счёт."""
        self._move_between_accounts(character_id, amount, "cash", "bank", basis)

    def withdraw(self, character_id: str, amount: int, *, basis: str = "rules") -> None:
        """Со счёта → в наличные."""
        self._move_between_accounts(character_id, amount, "bank", "cash", basis)

    def _move_between_accounts(
        self, character_id: str, amount: int, source: str, target: str, basis: str
    ) -> None:
        self._check_amount(amount)
        with self._change():
            self._check_basis(basis, character_id, action="Moving money")
            row = self._character_row(character_id)
            if row[source] < amount:
                raise RuleError(f"{row['name']} has only {row[source]} ({source})")
            self._add_money(character_id, source, -amount)
            self._add_money(character_id, target, amount)
            self._record(
                "money_moved",
                basis=basis,
                actor_id=character_id,
                participants=[character_id],
                data={"amount": amount, "from": source, "to": target},
            )

    def grant_money(
        self,
        character_id: str,
        amount: int,
        *,
        account: str = "cash",
        basis: str = "author",
        actor_id: str | None = None,
        reason: str = "",
    ) -> None:
        """Выдаёт (`amount` > 0) или забирает (< 0) деньги волей автора или чудом.

        Больше, чем есть, забрать нельзя: деньги не уходят в минус.
        """
        if not isinstance(amount, int) or amount == 0:
            raise RuleError("Amount must be a non-zero whole number")
        _require_choice("account", account, ACCOUNTS)
        with self._change():
            self._check_basis(
                basis, actor_id, action="Creating money from nothing", rules_allow=False
            )
            row = self._character_row(character_id)
            if row[account] + amount < 0:
                raise RuleError(f"{row['name']} has only {row[account]} ({account})")
            self._add_money(character_id, account, amount)
            self._record(
                "money_granted",
                basis=basis,
                actor_id=actor_id,
                participants=[character_id],
                data={"amount": amount, "account": account, "reason": reason},
            )

    def earn_money(
        self,
        character_id: str,
        amount: int,
        *,
        account: str = "cash",
        source: str,
        note: str = "",
        basis: str = "rules",
    ) -> None:
        """Заработок по правилам: зарплата или выручка от покупателей (0.4).

        Деньги приходят «со стороны» (казна деревни, город, прохожие),
        поэтому платит не персонаж мира. Заработать может только живой.
        """
        self._check_amount(amount)
        _require_choice("account", account, ACCOUNTS)
        if source not in ("wage", "takings"):
            raise RuleError(f"Unknown income '{source}'; expected wage or takings")
        with self._change():
            self._check_basis(basis, character_id, action="Earning money")
            self._add_money(character_id, account, amount)
            self._record(
                "money_earned",
                basis=basis,
                actor_id=character_id,
                participants=[character_id],
                data={"amount": amount, "account": account, "source": source, "note": note},
            )

    def spend_money(
        self,
        character_id: str,
        amount: int,
        *,
        account: str = "cash",
        note: str = "",
        basis: str = "rules",
    ) -> None:
        """Траты «на сторону» по правилам: еда и мелочи в итогах симуляции (0.4).

        Деньги уходят из мира, а не к персонажу. Больше, чем есть, не потратить.
        """
        self._check_amount(amount)
        _require_choice("account", account, ACCOUNTS)
        with self._change():
            self._check_basis(basis, character_id, action="Spending money")
            row = self._character_row(character_id)
            if row[account] < amount:
                raise RuleError(f"{row['name']} has only {row[account]} ({account}), {amount} needed")
            self._add_money(character_id, account, -amount)
            self._record(
                "money_spent",
                basis=basis,
                actor_id=character_id,
                participants=[character_id],
                data={"amount": amount, "account": account, "note": note},
            )

    def remove_item(
        self,
        item_id: int,
        *,
        basis: str = "author",
        actor_id: str | None = None,
        reason: str = "",
    ) -> None:
        """Предмет исчезает из мира: волей автора или чудом. Запись о нём остаётся в журнале."""
        with self._change():
            item = self._item_row(item_id)
            self._check_basis(basis, actor_id, action="Making an item vanish", rules_allow=False)
            self._conn.execute("DELETE FROM item WHERE id = ?", (item_id,))
            self._record(
                "item_removed",
                basis=basis,
                actor_id=actor_id,
                participants=[p for p in (item["owner_id"], item["location_id"]) if p],
                data={
                    "item_id": item_id,
                    "name": item["name"],
                    "owner_id": item["owner_id"],
                    "location_id": item["location_id"],
                    "reason": reason,
                },
            )

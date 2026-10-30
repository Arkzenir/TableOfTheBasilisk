"""Lookup tables in play (§2.2 Randomizer service, §2.3 `randomizers.tables`, §7.1).

A pack's tables are rolled by a chargen `table` step, and in play by
`roll_table`: random encounters, oracles, weather. The roll goes through the
engine's logged randomizer, so it is on the roll counter like dice and deck
draws, and the entry is recorded as `table_rolled`. Entries are text for the
GM or a player to narrate; mechanical consequences are consequence tables
(§2.6), so a lookup table carries no effects.

The GM may roll any table. A player may roll a table the pack marks
`players_roll: true`.
"""

from __future__ import annotations

from .command import EngineError, _suggest, atomic, gm_call


def player_tables(pack) -> list[str]:
    return [t["id"] for t in pack.catalogue("randomizers.tables") if t.get("players_roll") is True]


def lint_tables(pack) -> list[str]:
    """Problems with in-play table settings, for pack lint (§2.10)."""
    return [f"table {t.get('id')}: players_roll is true or false, not {t.get('players_roll')!r}"
            for t in pack.catalogue("randomizers.tables")
            if "players_roll" in t and not isinstance(t["players_roll"], bool)]


class TableCommands:
    """`roll_table`. Mixed into `Engine`."""

    def _table_entry(self, table: dict, value: int) -> dict:
        return next(e for e in table["entries"] if e["range"][0] <= value <= e["range"][1])

    @atomic
    @gm_call(lambda e, a: sorted(t["id"] for t in e.pack.catalogue("randomizers.tables")))
    def roll_table(self, table_id: str, by: str | None = None) -> dict:
        """Roll a lookup table in play; returns the value and the entry's text."""
        by = by or self.gm_seat
        tables = self.pack.by_id("randomizers.tables")
        gm = self._role(by) == "gm"
        allowed = list(tables) if gm else player_tables(self.pack)
        if table_id not in allowed:
            raise EngineError(_suggest("table you can roll", table_id, allowed))
        if not gm and by not in self.seats:
            raise EngineError(_suggest("seat", by, self.seats))
        self._require_settled()
        table = tables[table_id]
        result, roll_seq = self._roll(table["roll"], {}, None, f"table:{table_id}", actor=by)
        entry = self._table_entry(table, result.total)
        self._emit("table_rolled", {"table": table_id, "value": result.total, "text": entry.get("text", ""),
                                    "by": by, "purpose": "play"}, actor=by, caused_by=roll_seq)
        return {"table": table_id, "value": result.total, "text": entry.get("text", "")}

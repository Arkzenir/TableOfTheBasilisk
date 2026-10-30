"""Meta-currencies (§2.3 `gm.meta_currencies`, §2.4 meta-currency).

Each currency has a holder: `each_player` (one on every player character),
`party` (one pool the player characters share), or `gm` (one pool the GM's
side shares). Mixed into `Engine`.
"""

from __future__ import annotations

from .command import EngineError


class CurrencyCommands:
    """Who holds which currency, and where a change to it lands."""

    def _pool_of(self, ent: dict) -> str:
        """The shared pool an entity draws on: `gm` for the GM's side, else `party`."""
        return "gm" if self._role(ent["controller"]) == "gm" else "party"

    def _pool_value(self, holder: str, currency_id: str) -> int:
        """A shared pool's value: its `start` until the first change creates
        `state.currencies.<holder>`."""
        cdef = self.pack.by_id("gm.meta_currencies")[currency_id]
        return (self.state.get("currencies") or {}).get(holder, {}).get(currency_id, int(cdef.get("start", 0)))

    def _currencies(self, ent: dict) -> dict[str, int]:
        """What the entity holds or can spend (§2.3 `holder`): its own currencies,
        plus its side's shared pools: the party's for a player character, the
        GM's for a GM-side entity."""
        out = dict(ent.get("currencies", {}))
        pool = self._pool_of(ent)
        if pool == "party" and ent["kind"] != "pc":
            return out
        for c in self.pack.catalogue("gm.meta_currencies"):
            if c.get("holder") == pool:
                out[c["id"]] = self._pool_value(pool, c["id"])
        return out

    def _currency_path(self, ent: dict, currency_id: str) -> list[str]:
        """Where a change to this entity's currency lands."""
        holder = self.pack.by_id("gm.meta_currencies")[currency_id].get("holder", "each_player")
        if holder == "party" and (ent["kind"] != "pc" or self._pool_of(ent) != "party"):
            raise EngineError(f"{currency_id} belongs to the party, and {ent['id']} is not a player character")
        if holder == "gm" and self._pool_of(ent) != "gm":
            raise EngineError(f"{currency_id} belongs to the GM's side, and {ent['id']} is not GM-controlled; "
                              "an effect feeds it with target: gm")
        if holder in ("party", "gm"):
            return ["currencies", holder, currency_id]
        return ["entities", ent["id"], "currencies", currency_id]

    def currency(self, entity_id: str, currency_id: str) -> int:
        """How much of a currency the entity can spend now (own or shared)."""
        return self._currencies(self._entity(entity_id)).get(currency_id, 0)

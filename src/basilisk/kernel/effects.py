"""The closed set of effect primitives (§2.6).

Packs compose these in data. The engine turns each into concrete state
changes, emitted as `effect_applied` events whose payload carries the exact
changes, so the reducer that folds events into state stays trivial and
pack-agnostic.
"""

from __future__ import annotations

import copy
from typing import Any

from . import dice
from .command import EngineError, _suggest, atomic
from .determinism import STANDARD, STRICT

MAX_TRIGGER_DEPTH = 5

# primitive -> required parameters ("target" is implied for entity primitives)
PRIMITIVES: dict[str, tuple[str, ...]] = {
    "modify_resource": ("target", "resource", "amount"),
    "set_resource": ("target", "resource", "value"),
    "mark_track": ("target", "track", "amount"),
    "clear_track": ("target", "track"),
    "add_condition": ("target", "condition"),
    "remove_condition": ("target", "condition"),
    "add_tag": ("target", "tag"),
    "remove_tag": ("target", "tag"),
    "move": ("target", "to"),
    "transfer_item": ("from", "to", "item"),
    "create_item": ("target", "item"),
    "destroy_item": ("target", "item"),
    "advance_clock": ("clock", "amount"),
    "earn_currency": ("target", "currency", "amount"),
    "spend_currency": ("target", "currency", "amount"),
    "trigger_procedure": ("procedure",),
    "request_gm_ruling": ("table",),
}

# Defined by the architecture but not yet implemented by this kernel build.
RESERVED = {"trigger_procedure"}

# Symbolic targets an effect may name; anything else must be an entity id.
TARGET_SYMBOLS = {"actor", "target", "self"}


def references(effect: dict) -> dict[str, str]:
    """Catalogue references made by an effect: {kind: id}."""
    refs = {}
    for key, kind in (
        ("resource", "resource"), ("track", "track"), ("condition", "condition"),
        ("currency", "currency"), ("table", "consequence_table"), ("clock", "clock"),
    ):
        if key in effect:
            refs[kind] = effect[key]
    return refs


# ====================================================================== commands

class EffectCommands:
    """Effect application (§2.6) and ruling slots (§2.6, §2.13). Mixed into
    `Engine`; uses its state, `_emit`, `_roll`, `_draw`, and seat roles."""

    # ------------------------------------------------------------ effects (§2.6)

    def _amount(self, value: Any, variables: dict, cause: int | None) -> int:
        if isinstance(value, bool):
            raise EngineError("amounts must be integers")
        if isinstance(value, int):
            return value
        if dice.has_dice(str(value)):
            result, _ = self._roll(str(value), variables, cause, "effect")
            return result.total
        return dice.evaluate(str(value), variables).total

    def _apply_effect(self, effect: dict, ids: dict, cause: int | None, variables: dict) -> None:
        prim = effect["primitive"]
        if prim not in PRIMITIVES or prim in RESERVED:
            raise EngineError(f"primitive {prim!r} is not available")
        if prim == "request_gm_ruling":
            self._ruling(effect["table"], ids, cause)
            return

        def resolve_target(key: str = "target") -> str:
            sym = effect.get(key)
            eid = ids.get(sym) if sym in ("actor", "target", "self") else sym
            if not eid:
                raise EngineError(f"{prim}: no {key} for {sym!r}")
            self._entity(eid)
            return eid

        changes: list[dict] = []
        params: dict[str, Any] = {k: v for k, v in effect.items() if k != "primitive"}
        triggers: list[tuple[list, str]] = []
        target_id = None

        if prim in ("modify_resource", "set_resource"):
            target_id = resolve_target()
            ent = self.state["entities"][target_id]
            rdef = self.pack.by_id("entity_model.resources")[effect["resource"]]
            old = ent["resources"][effect["resource"]]
            lo, hi = int(rdef.get("min", 0)), self._max(ent, rdef)
            if prim == "modify_resource":
                amt = self._amount(effect["amount"], variables, cause)
                params["amount"] = amt
                new = max(lo, min(hi, old + amt))
            else:
                new = max(lo, min(hi, self._amount(effect["value"], variables, cause)))
                params["value"] = new
            params.update({"old": old, "new": new})
            changes.append({"path": ["entities", target_id, "resources", effect["resource"]], "value": new})
            if new == lo and old > lo:
                triggers.append((rdef.get("on_zero") or [], target_id))
        elif prim in ("mark_track", "clear_track"):
            target_id = resolve_target()
            ent = self.state["entities"][target_id]
            tdef = self.pack.by_id("entity_model.tracks")[effect["track"]]
            old = ent["tracks"][effect["track"]]
            if prim == "mark_track":
                amt = self._amount(effect["amount"], variables, cause)
                params["amount"] = amt
                new = max(0, min(int(tdef["boxes"]), old + amt))
            else:
                new = 0
            params.update({"old": old, "new": new})
            changes.append({"path": ["entities", target_id, "tracks", effect["track"]], "value": new})
            if new >= int(tdef["boxes"]) > old:
                triggers.append((tdef.get("on_fill") or [], target_id))
        elif prim == "add_condition":
            target_id = resolve_target()
            if effect["condition"] not in self.state["entities"][target_id]["conditions"]:
                changes.append({"path": ["entities", target_id, "conditions", effect["condition"]],
                                "value": {"since_scene": self.state["scene"]["index"]}})
        elif prim == "remove_condition":
            target_id = resolve_target()
            if effect["condition"] in self.state["entities"][target_id]["conditions"]:
                changes.append({"path": ["entities", target_id, "conditions", effect["condition"]], "delete": True})
        elif prim in ("add_tag", "remove_tag"):
            target_id = resolve_target()
            tags = set(self.state["entities"][target_id]["tags"])
            (tags.add if prim == "add_tag" else tags.discard)(effect["tag"])
            changes.append({"path": ["entities", target_id, "tags"], "value": sorted(tags)})
        elif prim == "move":
            target_id = resolve_target()
            to = ids.get("target") if effect["to"] == "$target" else effect["to"]
            if not to:
                raise EngineError("move: no destination")
            self._check_move(target_id, to)
            params["to"] = to
            changes += self._move_changes(target_id, to)
        elif prim in ("create_item", "destroy_item"):
            target_id = resolve_target()
            inv = list(self.state["entities"][target_id]["inventory"])
            if prim == "create_item":
                inv.append(effect["item"])
            elif effect["item"] in inv:
                inv.remove(effect["item"])
            else:
                raise EngineError(f"{target_id} has no {effect['item']!r}")
            changes.append({"path": ["entities", target_id, "inventory"], "value": inv})
        elif prim == "transfer_item":
            src, dst = resolve_target("from"), resolve_target("to")
            inv_src = list(self.state["entities"][src]["inventory"])
            if effect["item"] not in inv_src:
                raise EngineError(f"{src} has no {effect['item']!r}")
            inv_src.remove(effect["item"])
            inv_dst = list(self.state["entities"][dst]["inventory"]) + [effect["item"]]
            changes += [{"path": ["entities", src, "inventory"], "value": inv_src},
                        {"path": ["entities", dst, "inventory"], "value": inv_dst}]
            params.update({"from": src, "to": dst})
        elif prim == "advance_clock":
            clock = self.state["clocks"].get(effect["clock"])
            if clock is None:
                raise EngineError(_suggest("clock", effect["clock"], self.state["clocks"]))
            amt = self._amount(effect["amount"], variables, cause)
            new = max(0, min(clock["total"], clock["filled"] + amt))
            params.update({"amount": amt, "old": clock["filled"], "new": new})
            changes.append({"path": ["clocks", effect["clock"], "filled"], "value": new})
        elif prim in ("earn_currency", "spend_currency"):
            target_id = resolve_target()
            ent = self.state["entities"][target_id]
            cdef = self.pack.by_id("gm.meta_currencies")[effect["currency"]]
            old = ent["currencies"].get(effect["currency"], 0)
            amt = self._amount(effect["amount"], variables, cause)
            if prim == "spend_currency":
                if amt > old:
                    raise EngineError(f"{target_id} has only {old} {effect['currency']}")
                new = old - amt
            else:
                new = min(int(cdef.get("max", 10**6)), old + amt)
            params.update({"amount": amt, "old": old, "new": new})
            changes.append({"path": ["entities", target_id, "currencies", effect["currency"]], "value": new})

        if target_id:
            params["target"] = target_id
        seq = self._emit("effect_applied", {"primitive": prim, "target": target_id, "params": params,
                                            "changes": changes}, caused_by=cause)
        for effects, owner in triggers:
            self._depth += 1
            try:
                if self._depth > MAX_TRIGGER_DEPTH:
                    raise EngineError("trigger depth exceeded; check the pack for trigger loops")
                for e in effects:
                    self._apply_effect(e, {"actor": owner, "target": owner, "self": owner}, seq, variables)
            finally:
                self._depth -= 1

    # ------------------------------------------------------------ rulings (§2.6, §2.13)

    def _ruling(self, table_id: str, ids: dict, cause: int | None) -> None:
        table = self.pack.by_id("gm.consequence_tables")[table_id]
        mode = self.mode("ruling_slots", self.gm_seat)
        slot = f"r{self.store.head(self.campaign_id)[0] + 1}"
        self._emit("gm_ruling_requested", {
            "slot": slot, "table": table_id, "mode": "engine_draw" if mode == STRICT else "gm_select",
            "ids": {k: v for k, v in ids.items()}, "entries": [e["id"] for e in table["entries"]],
        }, caused_by=cause)
        if mode == STANDARD:
            return
        lethality = int(self.state["campaign"].get("gm_lethality", 50))
        weights = []
        for e in table["entries"]:
            base, severity = int(e.get("weight", 1)), int(e.get("severity", 2))
            weights.append(max(1, base * (100 + (severity - 2) * (lethality - 50))))
        counter, draw = self._draw()
        value = draw(0, 1, sum(weights))
        roll_seq = self._emit("roll_made", {"counter": counter, "purpose": f"ruling:{table_id}", "expression": "weighted",
                                            "weights": weights, "total": value, "groups": [], "variables": {}},
                              caused_by=cause)
        acc = 0
        for entry, w in zip(table["entries"], weights):
            acc += w
            if value <= acc:
                break
        filled = self._emit("gm_ruling_filled", {"slot": slot, "entry": entry["id"], "by": "engine"},
                            caused_by=roll_seq)
        for e in entry.get("effects") or []:
            self._apply_effect(e, ids, filled, {})

    def open_rulings(self) -> dict:
        return copy.deepcopy(self.state["open_rulings"])

    @atomic
    def fill_ruling(self, slot: str, entry_id: str, by: str | None = None) -> None:
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM fills rulings")
        open_ = self.state["open_rulings"]
        if slot not in open_:
            raise EngineError(_suggest("open ruling", slot, open_))
        info = open_[slot]
        table = self.pack.by_id("gm.consequence_tables")[info["table"]]
        entries = {e["id"]: e for e in table["entries"]}
        if entry_id not in entries:
            raise EngineError(_suggest("consequence", entry_id, entries))
        self._judge(by, "ruling_slots", STANDARD, entry_id, list(entries), None)
        filled = self._emit("gm_ruling_filled", {"slot": slot, "entry": entry_id, "by": by}, actor=by)
        for e in entries[entry_id].get("effects") or []:
            self._apply_effect(e, info["ids"], filled, {})

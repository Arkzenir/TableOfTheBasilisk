"""The closed set of effect primitives (§2.6).

Packs compose these in data. The engine turns each into concrete state
changes, emitted as `effect_applied` events whose payload carries the exact
changes, so the reducer that folds events into state stays trivial and
pack-agnostic.
"""

from __future__ import annotations

import copy
from typing import Any

from . import dice, expr
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

# primitive -> optional parameters; anything else on an effect is a lint error.
OPTIONAL_PARAMS: dict[str, set[str]] = {
    "remove_condition": {"levels"},  # lower a stacked condition by some levels
    "trigger_procedure": {"target", "stat", "against", "difficulty", "outcome_effects"},
}

# Defined by the architecture but not yet implemented by this kernel build: none.
RESERVED: set[str] = set()

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
        if prim == "trigger_procedure":
            self._triggered_procedure(effect, ids, cause)
            return

        def resolve_target(key: str = "target") -> str:
            sym = effect.get(key)
            eid = ids.get(sym) if sym in ("actor", "target", "self") else sym
            if not eid:
                raise EngineError(f"{prim}: no {key} for {sym!r}")
            self._entity(eid)
            return eid

        changes: list[dict] = []
        provoked: list[str] = []
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
            cid = effect["condition"]
            held = self.state["entities"][target_id]["conditions"].get(cid)
            cdef = self.pack.by_id("entity_model.conditions").get(cid, {})
            stacks = cdef.get("stacking", "none") == "intensity"
            if held is None:
                value = {"since_scene": self.state["scene"]["index"]}
                if stacks:  # stacking conditions carry a level; others keep their old shape
                    value["level"] = 1
                changes.append({"path": ["entities", target_id, "conditions", cid], "value": value})
            elif stacks and held.get("level", 1) < int(cdef.get("max_level", 3)):
                changes.append({"path": ["entities", target_id, "conditions", cid, "level"],
                                "value": held.get("level", 1) + 1})
                params["level"] = held.get("level", 1) + 1
        elif prim == "remove_condition":
            target_id = resolve_target()
            cid = effect["condition"]
            held = self.state["entities"][target_id]["conditions"].get(cid)
            levels = effect.get("levels")
            if held is not None:
                if levels and held.get("level", 1) > int(levels):  # lower a stacked condition by some levels
                    changes.append({"path": ["entities", target_id, "conditions", cid, "level"],
                                    "value": held["level"] - int(levels)})
                    params["level"] = held["level"] - int(levels)
                else:
                    changes.append({"path": ["entities", target_id, "conditions", cid], "delete": True})
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
            provoked = self._provokers(target_id, to)
            changes += self._move_changes(target_id, to)
        elif prim in ("create_item", "destroy_item"):
            target_id = resolve_target()
            inv = list(self.state["entities"][target_id]["inventory"])
            if prim == "create_item":
                self._check_carry(target_id, effect["item"])
                inv.append(effect["item"])
            elif effect["item"] in inv:
                inv.remove(effect["item"])
            else:
                raise EngineError(f"{target_id} has no {effect['item']!r}")
            changes.append({"path": ["entities", target_id, "inventory"], "value": inv})
        elif prim == "transfer_item":
            src, dst = resolve_target("from"), resolve_target("to")
            if src == dst:  # writing both inventories would duplicate the item
                raise EngineError(f"transfer_item: {src} cannot give {effect['item']!r} to itself")
            inv_src = list(self.state["entities"][src]["inventory"])
            if effect["item"] not in inv_src:
                raise EngineError(f"{src} has no {effect['item']!r}")
            inv_src.remove(effect["item"])
            self._check_carry(dst, effect["item"])
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
            cdef = self.pack.by_id("gm.meta_currencies")[effect["currency"]]
            if effect.get("target") == "gm":  # the GM's pool, fed by anyone's effect (§2.3)
                if cdef.get("holder") != "gm":
                    raise EngineError(f"{prim}: target gm needs a GM-held currency; {effect['currency']} is held "
                                      f"by {cdef.get('holder', 'each_player')}")
                old, path = self._pool_value("gm", effect["currency"]), ["currencies", "gm", effect["currency"]]
                holder = "the GM"
            else:
                target_id = resolve_target()
                ent = self.state["entities"][target_id]
                old = self._currencies(ent).get(effect["currency"], 0)
                path = self._currency_path(ent, effect["currency"])
                holder = target_id
            # a rolled amount below zero counts as zero: earning never takes and spending never gives (D-053)
            amt = max(0, self._amount(effect["amount"], variables, cause))
            if prim == "spend_currency":
                if amt > old:
                    raise EngineError(f"{holder} has only {old} {effect['currency']}")
                new = old - amt
            else:
                new = max(old, min(int(cdef.get("max", 10**6)), old + amt))  # never lowered by a max below it
            params.update({"amount": amt, "old": old, "new": new})
            changes.append({"path": path, "value": new})

        if target_id:
            params["target"] = target_id
        seq = self._emit("effect_applied", {"primitive": prim, "target": target_id, "params": params,
                                            "changes": changes}, caused_by=cause)
        if prim == "advance_clock":
            self._clock_moved(effect["clock"], params["old"], params["new"], seq)
        if prim == "move" and provoked:  # a reaction may answer it (§2.4)
            self._emit("move_provoked", {"mover": target_id, "by": provoked, "to": params["to"]}, caused_by=seq)
        for effects, owner in triggers:
            self._depth += 1
            try:
                if self._depth > MAX_TRIGGER_DEPTH:
                    raise EngineError("trigger depth exceeded; check the pack for trigger loops")
                for e in effects:
                    self._apply_effect(e, {"actor": owner, "target": owner, "self": owner}, seq, variables)
            finally:
                self._depth -= 1

    def _inventory_model(self) -> str:
        return str((self.pack.get("entity_model.inventory") or {}).get("model", "abstract"))

    def carried(self, ent: dict) -> int:
        """Total weight an entity carries (weight model; 0 otherwise)."""
        items = self.pack.by_id("entity_model.items")
        return sum(int(items.get(i, {}).get("weight", 0)) for i in ent["inventory"])

    def capacity(self, ent: dict) -> int | None:
        """The entity's carry limit from `inventory.limit_expr`, or None without one."""
        spec = self.pack.get("entity_model.inventory") or {}
        if self._inventory_model() != "weight" or not spec.get("limit_expr"):
            return None
        own = self._derived(ent)
        return expr.evaluate(spec["limit_expr"], {**own, "actor": own}, self.rounding)

    def _check_carry(self, holder: str, item: str) -> None:
        """Weight inventory (§2.3): the item must be a known one, and the holder
        must be able to carry it. Refusals are atomic."""
        if self._inventory_model() != "weight":
            return
        items = self.pack.by_id("entity_model.items")
        if item not in items:
            raise EngineError(_suggest("item", item, items))
        ent = self.state["entities"][holder]
        limit = self.capacity(ent)
        after = self.carried(ent) + int(items[item].get("weight", 0))
        if limit is not None and after > limit:
            raise EngineError(f"{holder} cannot carry {item}: that would be {after} of {limit}")

    def _triggered_procedure(self, effect: dict, ids: dict, cause: int | None) -> None:
        """`trigger_procedure` (§2.6): a rule that makes someone roll, then applies
        the effects the pack lists for that outcome. Who rolls is `target`
        (default the actor); `against` names the other side, for derived or
        opposed difficulties. A difficulty is fixed by the pack: an expression,
        or a ladder rung, so no model chooses it and nothing is a judgement input."""
        procs = self.pack.by_id("resolution.procedures")
        if effect["procedure"] not in procs:
            raise EngineError(_suggest("procedure", effect["procedure"], procs))

        def who(sym):
            eid = ids.get(sym) if sym in ("actor", "target", "self") else sym
            if eid:
                self._entity(eid)
            return eid

        roller = who(effect.get("target", "actor"))
        if not roller:
            raise EngineError("trigger_procedure: nobody to roll")
        other = who(effect.get("against", "target" if effect.get("target", "actor") != "target" else "actor"))
        other = None if other == roller else other
        spec = effect.get("difficulty")
        if isinstance(spec, dict) and "ladder" in spec:
            rungs = {r["id"]: r for r in self.pack.by_id("resolution.difficulty_ladders")[spec["ladder"]]["rungs"]}
            spec = {"derived": str(int(rungs[spec["rung"]]["value"]))}
        params = {k: v for k, v in effect.items() if k not in ("primitive", "outcome_effects")}
        params["target"] = roller
        seq = self._emit("effect_applied", {"primitive": "trigger_procedure", "target": roller, "params": params,
                                            "changes": []}, caused_by=cause)
        self._depth += 1
        try:
            if self._depth > MAX_TRIGGER_DEPTH:
                raise EngineError("trigger depth exceeded; check the pack for procedures that trigger each other")
            ents = self.state["entities"]
            outcome, _, proc_seq = self._run_procedure(procs[effect["procedure"]], ents[roller],
                                                       ents.get(other) if other else None, effect.get("stat"),
                                                       spec, {}, seq)
            nested = {"actor": roller, "target": other, "self": roller}
            for e in (effect.get("outcome_effects") or {}).get(outcome, []):
                self._apply_effect(e, nested, proc_seq, {})
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

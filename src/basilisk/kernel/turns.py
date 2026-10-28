"""Encounter turn order and action economy (§2.4, BUILD_PLAN P0.4).

The pack's `turn_structure.encounter` picks one ordering strategy and one
economy; the kernel runs them.

Orders:
- `spotlight` — no turns. Anyone may act; the GM moves the table on with
  `next_round`, which refreshes every budget.
- `initiative` — each participant rolls the pack's `initiative.roll` (stat
  variables in braces) at the start of the encounter, or every round with
  `each_round: true`. Highest first; ties break by entity id.
- `sides` — the players' side and the GM's side alternate (`first` says who
  opens). Any member of the side in play may act.
- `handoff` — "popcorn": whoever finishes picks who goes next among those who
  have not gone this round; the last of a round picks who opens the next.
- `fixed` — the order the GM gives at the start, every round.
- `deck` — a fresh seeded shuffle of the participants every round, drawn one
  card at a time through the logged randomizer.

Economies:
- `none` — no limit.
- `slots` — typed slots per turn, `slots: [{id, count}]`; an action uses its
  `slot` or the first one.
- `points` — a budget per turn, `points: n`; an action costs its `points`, or 1.

A budget refreshes when its owner's turn starts, so an off-turn `reaction`
spends from the budget that the owner's next turn restores. Off-turn actions
other than reactions are refused. Nothing applies until the GM starts an
encounter, and `state["encounter"]` exists only while one runs, so older logs
fold unchanged.
"""

from __future__ import annotations

import copy
from . import dice
from .command import EngineError, _suggest, atomic, gm_call

EVENT_TYPES = frozenset({"encounter_started", "round_started", "turn_started", "economy_spent", "encounter_ended"})
ORDERS = ("spotlight", "initiative", "sides", "handoff", "fixed", "deck")
ECONOMIES = ("none", "slots", "points")
SIDES = ("players", "gm")


def structure(pack) -> dict:
    return dict((pack.get("turn_structure") or {}).get("encounter") or {"order": "spotlight", "economy": "none"})


def lint_turns(pack) -> list[str]:
    """Problems in a pack's turn structure, for pack lint (§2.10)."""
    ts, out = structure(pack), []
    order, economy = ts.get("order"), ts.get("economy", "none")
    if order not in ORDERS:
        out.append(_suggest("turn order", order, ORDERS))
    if economy not in ECONOMIES:
        out.append(_suggest("action economy", economy, ECONOMIES))
    if order == "initiative":
        roll = (ts.get("initiative") or {}).get("roll")
        if not roll:
            out.append("initiative order needs initiative.roll, e.g. \"1d20 + {some_stat}\"")
        else:
            stats = {s["id"] for s in pack.catalogue("entity_model.stats")} | \
                    {d["id"] for d in pack.catalogue("entity_model.derived")}
            try:
                unknown = dice.variables_used(roll) - stats
            except dice.DiceError as e:
                out.append(f"initiative.roll: {e}")
                unknown = set()
            for name in sorted(unknown):
                out.append("initiative.roll: " + _suggest("stat", name, stats))
    if order == "sides" and ts.get("first", "players") not in SIDES:
        out.append(f"sides.first must be one of {', '.join(SIDES)}")
    slot_ids = [s.get("id") for s in ts.get("slots") or []]
    if economy == "slots":
        if not slot_ids:
            out.append("slots economy needs slots: [{id, count}]")
        for s in ts.get("slots") or []:
            if isinstance(s.get("count"), bool) or not isinstance(s.get("count"), int) or s["count"] < 1:
                out.append(f"slot {s.get('id')}: count must be a positive integer")
        if len(slot_ids) != len(set(slot_ids)):
            out.append("duplicate slot ids")
    if economy == "points":
        pts = ts.get("points")
        if isinstance(pts, bool) or not isinstance(pts, int) or pts < 1:
            out.append("points economy needs points: a positive integer")
    for action in pack.catalogue("actions"):
        if "slot" in action and action["slot"] not in slot_ids:
            out.append(f"action {action['id']}: " + _suggest("slot", action["slot"], slot_ids))
        if "points" in action and (isinstance(action["points"], bool) or not isinstance(action["points"], int)
                                   or action["points"] < 0):
            out.append(f"action {action['id']}: points must be a non-negative integer")
    return out


# ====================================================================== reducer

def apply_event(state: dict, ev: dict) -> None:
    """Fold one turn event. Called from `engine.apply_event`."""
    t, p = ev["type"], ev.get("payload") or {}
    if t == "encounter_started":
        state["encounter"] = {"order": p["order"], "economy": p["economy"], "participants": list(p["participants"]),
                              "round": 0, "sequence": [], "index": -1, "current": None, "acted": [], "budgets": {}}
        return
    enc = state["encounter"]
    if t == "round_started":
        enc.update({"round": p["round"], "sequence": list(p["sequence"]), "index": -1, "current": None, "acted": []})
        enc["budgets"].update(copy.deepcopy(p.get("budgets") or {}))
    elif t == "turn_started":
        enc["index"], enc["current"] = p["index"], p["actor"]
        enc["acted"].append(p["actor"])
        enc["budgets"].update(copy.deepcopy(p.get("budgets") or {}))
    elif t == "economy_spent":
        enc["budgets"].setdefault(p["entity"], {})[p["key"]] = p["remaining"]
    elif t == "encounter_ended":
        state.pop("encounter", None)


# ====================================================================== commands

class TurnCommands:
    """Turn controller commands and queries. Mixed into `Engine`."""

    def _enc(self) -> dict | None:
        return self.state.get("encounter")

    def _side_of(self, entity_id: str) -> str:
        return "gm" if self._role(self.state["entities"][entity_id]["controller"]) == "gm" else "players"

    def _members(self, actor: str) -> list[str]:
        """The entities whose turn it is: one entity, or every member of a side."""
        enc = self._enc()
        if actor in SIDES:
            return [e for e in enc["participants"] if self._side_of(e) == actor]
        return [actor]

    def _full_budget(self) -> dict:
        ts = structure(self.pack)
        if ts.get("economy") == "slots":
            return {s["id"]: int(s["count"]) for s in ts.get("slots") or []}
        if ts.get("economy") == "points":
            return {"points": int(ts["points"])}
        return {}

    def _sequence(self, round_no: int, cause: int) -> list[str]:
        """The order for a round, by strategy. Rolls and draws are logged."""
        enc, ts = self._enc(), structure(self.pack)
        people = list(enc["participants"])
        order = enc["order"]
        if order == "fixed":
            return people
        if order == "sides":
            first = ts.get("first", "players")
            return [first, "gm" if first == "players" else "players"]
        if order == "initiative":
            spec = ts.get("initiative") or {}
            if round_no > 1 and not spec.get("each_round"):
                return list(enc["sequence"])
            totals = {}
            for eid in sorted(people):
                result, _ = self._roll(spec["roll"], self._derived(self.state["entities"][eid]), cause,
                                       f"initiative:{eid}")
                totals[eid] = result.total
            return sorted(people, key=lambda e: (-totals[e], e))
        if order == "deck":
            remaining, drawn = sorted(people), []
            while remaining:
                counter, draw = self._draw()
                value = draw(0, 1, len(remaining))
                self._emit("roll_made", {"counter": counter, "purpose": f"turn_deck:round{round_no}",
                                         "expression": "weighted", "weights": [1] * len(remaining),
                                         "total": value, "groups": [], "variables": {}}, caused_by=cause)
                drawn.append(remaining.pop(value - 1))
            return drawn
        return []  # spotlight and handoff have no precomputed order

    def _start_round(self, round_no: int, cause: int, actor: str) -> int:
        enc = self._enc()
        sequence = self._sequence(round_no, cause)
        budgets = {e: self._full_budget() for e in enc["participants"]} if enc["order"] == "spotlight" else {}
        return self._emit("round_started", {"round": round_no, "sequence": sequence, "budgets": budgets},
                          actor=actor, caused_by=cause)

    def _start_turn(self, index: int, who: str, actor: str, cause: int | None) -> None:
        budgets = {e: self._full_budget() for e in self._members(who)}
        self._emit("turn_started", {"round": self._enc()["round"], "index": index, "actor": who,
                                    "budgets": budgets}, actor=actor, caused_by=cause)

    @atomic
    @gm_call()
    def start_encounter(self, participants: list[str] | None = None, first: str | None = None,
                        by: str | None = None) -> dict:
        """Start encounter mode in the current encounter scene (§2.4). With no
        participants, everyone in the scene takes part (everyone, in a scene
        without positions). `participants` gives the order for `fixed`;
        `first` picks the opener for `handoff`."""
        by = by or self.gm_seat
        self.snapshot()  # §5.6: a snapshot before any encounter (rolled back if this is refused)
        if self._role(by) != "gm":
            raise EngineError("only the GM starts an encounter")
        if not self.state["scene"]["encounter"]:
            raise EngineError("the current scene is not an encounter scene; set one with encounter=True")
        if self._enc() is not None:
            raise EngineError("an encounter is already running; end it first")
        ts = structure(self.pack)
        if participants is None:
            spatial = self._spatial()
            participants = [e for e in sorted(self.state["entities"]) if spatial is None or self._in_scene(e)]
        for eid in participants:
            self._entity(eid)
        if not participants or len(set(participants)) != len(participants):
            raise EngineError("participants must be a non-empty list without repeats")
        if first is not None and ts["order"] != "handoff":
            raise EngineError(f"first applies to handoff order; this pack uses {ts['order']}")
        if first is not None and first not in participants:
            raise EngineError(_suggest("participant", first, participants))
        seq = self._emit("encounter_started", {"order": ts["order"], "economy": ts.get("economy", "none"),
                                               "participants": list(participants)}, actor=by)
        self._start_round(1, seq, by)
        order = ts["order"]
        if order == "handoff":
            opener = first or participants[0]
            if first is not None:
                self._judge(by, "turn_handoff", None, opener, list(participants), seq)
            self._start_turn(0, opener, by, seq)
        elif order != "spotlight":
            self._start_turn(0, self._enc()["sequence"][0], by, seq)
        return self.current_turn()

    @atomic
    @gm_call()
    def end_turn(self, by: str | None = None, next: str | None = None) -> dict:
        """End the current turn and start the next (a new round when the order
        runs out). Under `handoff`, `next` names who goes next."""
        enc = self._enc()
        if enc is None:
            raise EngineError("no encounter is running")
        if enc["order"] == "spotlight":
            raise EngineError("spotlight order has no turns; the GM uses next_round")
        by = by or self.gm_seat
        current = enc["current"]
        allowed = {self.state["entities"][e]["controller"] for e in self._members(current)}
        if self._role(by) != "gm" and by not in allowed:
            raise EngineError(f"it is {current}'s turn; only its controller or the GM can end it")
        if enc["order"] == "handoff":
            return self._handoff(current, by, next)
        if next is not None:
            raise EngineError(f"next applies to handoff order; this encounter uses {enc['order']}")
        index = enc["index"] + 1
        cause = None
        if index >= len(enc["sequence"]):
            cause = self._start_round(enc["round"] + 1, None, by)
            index = 0
        self._start_turn(index, self._enc()["sequence"][index], by, cause)
        return self.current_turn()

    def _handoff(self, current: str, by: str, nxt: str | None) -> dict:
        enc = self._enc()
        waiting = [e for e in enc["participants"] if e not in enc["acted"]]
        new_round = not waiting
        options = [e for e in enc["participants"] if e != current] if new_round else waiting
        if not options:  # a lone participant goes again
            options = [current]
        if nxt is None:
            raise EngineError(f"handoff: name who goes next: {', '.join(options)}")
        if nxt not in options:
            raise EngineError(_suggest("next participant", nxt, options))
        mover = self.state["entities"][current]["controller"] if self._role(by) != "gm" else by
        cause = self._start_round(enc["round"] + 1, None, by) if new_round else None
        self._judge(mover, "turn_handoff", None, nxt, options, cause)
        self._start_turn(len(self._enc()["acted"]), nxt, by, cause)
        return self.current_turn()

    @atomic
    @gm_call()
    def next_round(self, by: str | None = None) -> dict:
        """Spotlight order: start a new round, refreshing every budget."""
        enc = self._enc()
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM starts a new round")
        if enc is None:
            raise EngineError("no encounter is running")
        if enc["order"] != "spotlight":
            raise EngineError(f"{enc['order']} order advances with end_turn")
        self._start_round(enc["round"] + 1, None, by)
        return self.current_turn()

    @atomic
    @gm_call()
    def end_encounter(self, by: str | None = None) -> None:
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM ends an encounter")
        if self._enc() is None:
            raise EngineError("no encounter is running")
        self._emit("encounter_ended", {"round": self._enc()["round"]}, actor=by)

    def current_turn(self) -> dict | None:
        """Whose turn it is, for the scheduler's Stage 1 bid (§4.1): the order,
        the round, the entity or side in play, the seats that may act, and the
        budgets left. None outside an encounter."""
        enc = self._enc()
        if enc is None:
            return None
        current = enc["current"]
        members = self._members(current) if current else []
        seats = sorted({self.state["entities"][e]["controller"] for e in members})
        up_next = None
        if enc["order"] not in ("spotlight", "handoff") and enc["sequence"]:
            nxt = enc["index"] + 1
            if nxt < len(enc["sequence"]):
                up_next = enc["sequence"][nxt]
            elif not self._reorders_each_round():  # the next round opens in the same order
                up_next = enc["sequence"][0]
        return {"order": enc["order"], "economy": enc["economy"], "round": enc["round"], "actor": current,
                "kind": None if current is None else ("side" if current in SIDES else "entity"),
                "seats": seats, "up_next": up_next,
                "budgets": {e: dict(enc["budgets"].get(e, {})) for e in (members or enc["participants"])}}

    def _reorders_each_round(self) -> bool:
        ts = structure(self.pack)
        return ts["order"] == "deck" or (ts["order"] == "initiative" and bool((ts.get("initiative") or {}).get("each_round")))

    # ------------------------------------------------------------ action gate (used by commit_action)

    def _economy_cost(self, action: dict) -> tuple[str, int] | None:
        ts = structure(self.pack)
        if ts.get("economy") == "slots":
            return action.get("slot") or ts["slots"][0]["id"], 1
        if ts.get("economy") == "points":
            return "points", int(action.get("points", 1))
        return None

    def _turn_problem(self, entity_id: str, action: dict) -> str | None:
        """Why the entity cannot take this action now under the running
        encounter, or None. Free play and spotlight-without-economy never block."""
        enc = self._enc()
        if enc is None:
            return None
        if entity_id not in enc["participants"]:
            return f"{entity_id} is not taking part in this encounter"
        if enc["order"] != "spotlight" and action.get("trigger") != "reaction" \
                and entity_id not in self._members(enc["current"]):
            return f"it is {enc['current']}'s turn, not {entity_id}'s; only reactions are allowed out of turn"
        cost = self._economy_cost(action)
        if cost is not None:
            key, amount = cost
            left = enc["budgets"].get(entity_id, {}).get(key, 0)
            if left < amount:
                return f"{entity_id} has {left} {key} left this turn; {action['id']} needs {amount}"
        return None

    def _spend_turn_economy(self, entity_id: str, action: dict, cause: int) -> None:
        enc = self._enc()
        cost = self._economy_cost(action) if enc is not None else None
        if cost is None or cost[1] == 0:
            return
        key, amount = cost
        left = enc["budgets"][entity_id][key]
        self._emit("economy_spent", {"entity": entity_id, "key": key, "amount": amount, "remaining": left - amount},
                   caused_by=cause)

"""The rules engine (§2, §5).

Commands validate input, compute results with the seeded randomizer, and emit
events. State changes only by folding events through `apply_event`, which is
pack-agnostic: every `effect_applied` event carries the exact state changes.
Replaying the log therefore reproduces state byte-for-byte without re-running
any rules.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from . import KERNEL_VERSION, canon, dice, expr, spatial
from .canon import CanonCommands
from .canonical import hash_obj
from .command import EngineError, _suggest, atomic
from .determinism import STANDARD, STRICT, apply_change, expand, setting_for, unsupported_strict
from .effects import PRIMITIVES, RESERVED
from .events import EventStore
from .packlint import readiness
from .packs import ResolvedPack
from .rng import Randomizer
from .spatial import SpatialCommands

MAX_TRIGGER_DEPTH = 5


# ====================================================================== reducer

def empty_state() -> dict:
    return {
        "campaign": {},
        "determinism": {"effective": {}, "pending": None, "last_change_scene": None},
        "roll_counter": 0,
        "session": 0,
        "scene": {"id": None, "index": 0, "flags": {}, "encounter": False},
        "entities": {},
        "clocks": {},
        "open_rulings": {},
        "chargen_taken": {},
        "actions_taken": 0,
    }


def _set_path(state: dict, path: list, value: Any, delete: bool = False) -> None:
    node = state
    for key in path[:-1]:
        node = node.setdefault(key, {})
    if delete:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = copy.deepcopy(value)


_PASSIVE = {
    "chargen_started", "judgement_input", "procedure_resolved", "table_rolled",
    "gm_resolution", "campaign_forked",
}

# Every event type the reducer accepts. Adding a type means: handle it in
# apply_event, document it in docs/dev/EVENTS.md (a test enforces both), and
# bump KERNEL_VERSION if existing logs would fold differently.
EVENT_TYPES = frozenset({
    "campaign_started", "determinism_settings_recorded", "determinism_change_requested",
    "determinism_changed", "session_started", "session_ended", "scene_set", "roll_made",
    "effect_applied", "character_created", "entity_spawned", "clock_created",
    "action_committed", "gm_ruling_requested", "gm_ruling_filled",
}) | canon.EVENT_TYPES | spatial.EVENT_TYPES | _PASSIVE


def apply_event(state: dict, ev: dict) -> None:
    t, p = ev["type"], ev.get("payload") or {}
    if t == "campaign_started":
        state["campaign"] = copy.deepcopy(p)
    elif t == "determinism_settings_recorded":
        state["determinism"]["effective"] = copy.deepcopy(p["settings"])
    elif t == "determinism_change_requested":
        state["determinism"]["pending"] = {"to": copy.deepcopy(p["to"]), "request_seq": ev["seq"]}
    elif t == "determinism_changed":
        state["determinism"]["effective"] = copy.deepcopy(p["to"])
        state["determinism"]["pending"] = None
        state["determinism"]["last_change_scene"] = p["scene_index"]
    elif t == "session_started":
        state["session"] = p["number"]
    elif t == "session_ended":
        pass
    elif t == "scene_set":
        state["scene"] = {"id": p["scene_id"], "index": p["index"], "flags": dict(p.get("flags") or {}),
                          "encounter": bool(p.get("encounter"))}
        layout = spatial.scene_spatial(p)
        if layout is not None:  # absent for non-spatial scenes, so older logs fold unchanged
            state["scene"]["spatial"] = layout
    elif t == "roll_made":
        state["roll_counter"] = p["counter"] + 1
    elif t == "effect_applied":
        for change in p["changes"]:
            _set_path(state, change["path"], change.get("value"), change.get("delete", False))
    elif t in ("character_created", "entity_spawned"):
        ent = p["entity"]
        state["entities"][ent["id"]] = copy.deepcopy(ent)
        for step, option in (p.get("unique_choices") or {}).items():
            state["chargen_taken"].setdefault(step, []).append(option)
    elif t == "clock_created":
        state["clocks"][p["clock_id"]] = {"label": p["label"], "filled": 0, "total": p["total"], "visible": p["visible"]}
    elif t == "action_committed":
        state["actions_taken"] += 1
    elif t == "gm_ruling_requested":
        if p["mode"] == "gm_select":
            state["open_rulings"][p["slot"]] = copy.deepcopy(p)
    elif t == "gm_ruling_filled":
        state["open_rulings"].pop(p["slot"], None)
    elif t in canon.EVENT_TYPES:
        canon.apply_event(state, ev)
    elif t in spatial.EVENT_TYPES:
        spatial.apply_event(state, ev)
    elif t in _PASSIVE:
        pass
    else:
        raise EngineError(f"unknown event type {t!r} at seq {ev.get('seq')}")


def fold(events: Iterable[dict], state: dict | None = None) -> dict:
    state = state if state is not None else empty_state()
    for ev in events:
        apply_event(state, ev)
    return state


# ====================================================================== engine

class Engine(CanonCommands, SpatialCommands):
    def __init__(self, pack: ResolvedPack, seed: str, store: EventStore | None = None,
                 campaign_id: str = "campaign", clock: Callable[[], str | None] | None = None):
        if pack.data["meta"].get("abstract"):
            raise EngineError(f"pack {pack.id} is abstract and cannot be played")
        self.pack = pack
        self.rng = Randomizer(seed)
        self.store = store or EventStore(":memory:")
        self.campaign_id = campaign_id
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.state = empty_state()
        self.readiness = readiness(pack)
        self.rounding = pack.get("presentation.rounding", "floor")
        self._depth = 0
        self._atomic_depth = 0

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def start_campaign(cls, pack: ResolvedPack, seed: str, config: dict, store: EventStore | None = None,
                       campaign_id: str = "campaign", clock=None) -> "Engine":
        eng = cls(pack, seed, store, campaign_id, clock)
        if eng.store.head(campaign_id)[0]:
            raise EngineError(f"campaign {campaign_id!r} already exists in this store")
        seats = dict(config.get("seats") or {})
        if list(seats.values()).count("gm") > 1:
            raise EngineError("at most one GM seat")
        bad = {s: r for s, r in seats.items() if r not in ("gm", "player")}
        if bad:
            raise EngineError(f"seat roles must be gm or player: {bad}")
        effective = expand(config.get("determinism"))
        unsupported = unsupported_strict(effective, eng.readiness)
        if unsupported:
            raise EngineError(f"pack {pack.id} cannot support strict for: {', '.join(unsupported)}")
        eng._emit("campaign_started", {
            "campaign_id": campaign_id,
            "pack_id": pack.id,
            "pack_hash": pack.hash,
            "kernel_version": KERNEL_VERSION,
            "seed_commitment": eng.rng.commitment(),
            "seats": seats,
            "gm_lethality": int((config.get("gm_traits") or {}).get("lethality", 50)),
        }, actor="engine")
        eng._emit("determinism_settings_recorded", {"settings": effective}, actor="engine")
        return eng

    @classmethod
    def load(cls, pack: ResolvedPack, seed: str, store: EventStore, campaign_id: str, clock=None) -> "Engine":
        eng = cls(pack, seed, store, campaign_id, clock)
        events = list(store.read(campaign_id))
        if not events:
            raise EngineError(f"no campaign {campaign_id!r}")
        first = events[0]["payload"]
        if first.get("pack_hash") != pack.hash:
            raise EngineError(f"pack hash mismatch: campaign pinned {first.get('pack_hash')}, loaded {pack.hash}")
        if first.get("kernel_version") != KERNEL_VERSION:
            raise EngineError(f"kernel mismatch: campaign pinned {first.get('kernel_version')}, running {KERNEL_VERSION}")
        if first.get("seed_commitment") != eng.rng.commitment():
            raise EngineError("seed does not match the campaign's seed commitment")
        eng.state = fold(events)
        return eng

    def state_hash(self) -> str:
        return hash_obj(self.state)

    def snapshot(self) -> str:
        seq, _ = self.store.head(self.campaign_id)
        return self.store.write_snapshot(self.campaign_id, seq, self.state, self.pack.hash, KERNEL_VERSION)

    # ------------------------------------------------------------ plumbing

    def _emit(self, type_: str, payload: dict, actor: str = "engine", caused_by: int | None = None) -> int:
        session = self.state.get("session") or 0
        stored = self.store.append({
            "campaign_id": self.campaign_id,
            "ts": self.clock(),
            "session_id": f"s{session}" if session else None,
            "scene_id": self.state["scene"]["id"],
            "actor": actor,
            "type": type_,
            "payload": payload,
            "caused_by": caused_by,
        })
        apply_event(self.state, stored)
        return stored["seq"]

    @property
    def seats(self) -> dict[str, str]:
        return self.state["campaign"].get("seats", {})

    @property
    def gm_seat(self) -> str:
        return next((s for s, r in self.seats.items() if r == "gm"), "gm")

    def _role(self, seat: str) -> str:
        if seat in ("gm", self.gm_seat) or self.seats.get(seat) == "gm":
            return "gm"
        return "players"

    def mode(self, control: str, seat: str) -> str:
        eff = self.state["determinism"]["effective"]
        return setting_for(eff, self._role(seat), control, seat)

    def _judge(self, seat: str, control: str, setting: str | None, choice: Any, options: Any, cause: int | None) -> None:
        self._emit("judgement_input", {
            "seat": seat, "control": control, "setting": setting, "choice": choice, "options": options,
        }, actor=seat, caused_by=cause)

    def _entity(self, entity_id: str) -> dict:
        ents = self.state["entities"]
        if entity_id not in ents:
            raise EngineError(_suggest("entity", entity_id, ents))
        return ents[entity_id]

    def _draw(self) -> tuple[int, Callable[[int, int, int], int]]:
        counter = self.state["roll_counter"]
        return counter, (lambda sub, lo, hi: self.rng.integer(counter, sub, lo, hi))

    def _roll(self, src: str, variables: dict[str, int], cause: int | None, purpose: str, actor: str = "engine") -> tuple[dice.RollResult, int]:
        grammar = self.pack.get("randomizers.dice_grammar", {}) or {}
        counter, draw = self._draw()
        result = dice.evaluate(src, variables, draw, max_dice=int(grammar.get("max_dice", 20)))
        seq = self._emit("roll_made", {"counter": counter, "purpose": purpose, **result.to_payload()},
                         actor=actor, caused_by=cause)
        return result, seq

    # ------------------------------------------------------------ views

    def _derived(self, ent: dict) -> dict[str, int]:
        base = dict(ent["stats"])
        for d in self.pack.catalogue("entity_model.derived"):
            base[d["id"]] = expr.evaluate(d["expr"], {**base, "actor": base}, self.rounding)
        return base

    def _max(self, ent: dict, resource: dict) -> int:
        own = self._derived(ent)
        return expr.evaluate(resource["max"], {**own, "actor": own}, self.rounding)

    def view(self, ent: dict | None) -> dict:
        if ent is None:
            return expr.Lenient()
        out = self._derived(ent)
        out.update(ent["resources"])
        out.update(ent["tracks"])
        out.update(ent.get("currencies", {}))
        out["conditions"] = expr.Lenient({c: 1 for c in ent["conditions"]})
        out["tags"] = expr.Lenient({t: 1 for t in ent["tags"]})
        return out

    def _ctx(self, actor: dict | None, target: dict | None, extra: dict | None = None) -> dict:
        scene = expr.Lenient(self.state["scene"]["flags"])
        scene["encounter"] = int(self.state["scene"]["encounter"])
        ctx = {"actor": self.view(actor), "target": self.view(target), "scene": scene}
        ctx.update(extra or {})
        return ctx

    # ------------------------------------------------------------ boundaries

    def _boundary(self, cause: int | None = None) -> None:
        pending = self.state["determinism"]["pending"]
        if pending:
            self._emit("determinism_changed", {
                "from": self.state["determinism"]["effective"], "to": pending["to"],
                "request_seq": pending["request_seq"], "scene_index": self.state["scene"]["index"],
            }, actor="engine", caused_by=pending["request_seq"])

    def _expire(self, durations: set[str]) -> None:
        conds = self.pack.by_id("entity_model.conditions")
        for eid in sorted(self.state["entities"]):
            ent = self.state["entities"][eid]
            for cid in sorted(ent["conditions"]):
                if conds.get(cid, {}).get("duration", "until_removed") in durations:
                    self._emit("effect_applied", {
                        "primitive": "remove_condition", "target": eid, "params": {"condition": cid, "reason": "duration"},
                        "changes": [{"path": ["entities", eid, "conditions", cid], "delete": True}],
                    })

    @atomic
    def start_session(self, by: str | None = None) -> int:
        self._boundary()
        return self._emit("session_started", {"number": self.state["session"] + 1}, actor=by or self.gm_seat)

    @atomic
    def end_session(self, by: str | None = None) -> int:
        self._expire({"scene", "session"})
        return self._emit("session_ended", {"number": self.state["session"]}, actor=by or self.gm_seat)

    @atomic
    def set_scene(self, scene_id: str, flags: dict | None = None, encounter: bool = False, by: str | None = None,
                  regions: list[dict] | None = None, placements: dict[str, str] | None = None) -> int:
        """Open a scene (§8.2). With `regions` the scene is spatial (§1.4) and
        `placements` puts entities in its regions."""
        if not self.state["session"]:
            raise EngineError("start a session before setting a scene")
        if placements and regions is None:
            raise EngineError("placements need regions: a scene without regions has no positions")
        layout = self._spatial_spec(regions) if regions is not None else None
        by = by or self.gm_seat
        self._expire({"scene"})
        flags = {k: int(v) for k, v in (flags or {}).items()}
        index = self.state["scene"]["index"] + 1
        payload = {"scene_id": scene_id, "index": index, "flags": flags, "encounter": bool(encounter)}
        if layout is not None:
            payload["spatial"] = layout
        self._emit("scene_set", payload, actor=by)
        for eid, region in self._placement_effects(placements):
            self._place(eid, region, by)
        self._boundary()
        return index

    # ------------------------------------------------------------ settings changes (§2.13.3)

    @atomic
    def request_determinism_change(self, by: str = "operator", role: str | None = None, preset: str | None = None,
                                   overrides: dict | None = None, seat: str | None = None,
                                   seat_overrides: dict | None = None) -> int:
        det = self.state["determinism"]
        if det["pending"]:
            raise EngineError("a determinism change is already queued for the next scene boundary")
        min_gap = int(det["effective"].get("min_scenes_between_changes", 1))
        last = det["last_change_scene"]
        next_boundary = self.state["scene"]["index"] + 1
        if last is not None and next_boundary - last < min_gap:
            raise EngineError(f"cooldown: changes must be at least {min_gap} scene(s) apart")
        new = apply_change(det["effective"], role, preset, overrides, seat, seat_overrides)
        unsupported = unsupported_strict(new, self.readiness)
        if unsupported:
            raise EngineError(f"pack {self.pack.id} cannot support strict for: {', '.join(unsupported)}")
        if new == det["effective"]:
            raise EngineError("requested settings are identical to the current ones")
        return self._emit("determinism_change_requested", {"from": det["effective"], "to": new}, actor=by)

    # ------------------------------------------------------------ entities

    def _new_entity(self, entity_id: str, name: str, kind: str, controller: str, stats: dict[str, int]) -> dict:
        ent = {
            "id": entity_id, "name": name, "kind": kind, "controller": controller,
            "stats": {}, "resources": {}, "tracks": {}, "conditions": {}, "tags": [],
            "inventory": [], "zone": None, "currencies": {}, "details": [],
        }
        for s in self.pack.catalogue("entity_model.stats"):
            value = int(stats.get(s["id"], s.get("default", 0)))
            lo, hi = s.get("range", [value, value])
            ent["stats"][s["id"]] = max(lo, min(hi, value))
        unknown = set(stats) - set(ent["stats"])
        if unknown:
            raise EngineError(_suggest("stat", sorted(unknown)[0], ent["stats"]))
        for r in self.pack.catalogue("entity_model.resources"):
            ent["resources"][r["id"]] = self._max(ent, r)
        for t in self.pack.catalogue("entity_model.tracks"):
            ent["tracks"][t["id"]] = 0
        for c in self.pack.catalogue("gm.meta_currencies"):
            holder = c.get("holder", "each_player")
            if (holder == "each_player" and kind == "pc") or (holder == "gm" and kind == "npc"):
                ent["currencies"][c["id"]] = int(c.get("start", 0))
        return ent

    @atomic
    def create_character(self, agent_id: str, name: str, choices: dict[str, str] | None = None,
                         entity_id: str | None = None) -> str:
        if self.seats.get(agent_id) != "player":
            raise EngineError(f"{agent_id!r} is not a player seat")
        entity_id = entity_id or agent_id
        if entity_id in self.state["entities"]:
            raise EngineError(f"entity {entity_id!r} already exists")
        choices = dict(choices or {})
        start = self._emit("chargen_started", {"agent": agent_id, "entity": entity_id}, actor=agent_id)
        stats: dict[str, int] = {}
        tags: list[str] = []
        details: list[str] = []
        unique: dict[str, str] = {}
        tables = self.pack.by_id("randomizers.tables")
        for step in self.pack.get("chargen.steps") or []:
            kind = step["kind"]
            if kind == "roll":
                for target in step["targets"]:
                    result, _ = self._roll(step["roll"], {}, start, f"chargen:{step['id']}:{target}", actor="engine")
                    stats[target] = result.total
            elif kind == "choice":
                options = {o["id"]: o for o in step.get("options") or []}
                taken = set(self.state["chargen_taken"].get(step["id"], [])) if step.get("unique_per_table") else set()
                available = [o for o in options if o not in taken]
                pick = choices.get(step["id"])
                if pick not in options:
                    raise EngineError(_suggest(f"option for {step['id']}", pick, available))
                if pick in taken:
                    raise EngineError(f"{pick!r} is already taken at this table ({step['id']} is unique per table)")
                self._judge(agent_id, "chargen_choice", None, pick, available, start)
                stats.update(options[pick].get("stats") or {})
                tags += options[pick].get("tags") or []
                if step.get("unique_per_table"):
                    unique[step["id"]] = pick
            elif kind == "table":
                table = tables[step["table"]]
                result, roll_seq = self._roll(table["roll"], {}, start, f"chargen:{step['id']}", actor="engine")
                entry = next(e for e in table["entries"] if e["range"][0] <= result.total <= e["range"][1])
                self._emit("table_rolled", {"table": table["id"], "value": result.total, "text": entry.get("text", "")},
                           caused_by=roll_seq)
                details.append(entry.get("text", ""))
        ent = self._new_entity(entity_id, name, "pc", agent_id, stats)
        ent["tags"] = sorted(set(tags))
        ent["details"] = details
        self._emit("character_created", {"entity": ent, "unique_choices": unique, "choices": choices},
                   actor=agent_id, caused_by=start)
        return entity_id

    @atomic
    def spawn_entity(self, entity_id: str, name: str, stats: dict[str, int] | None = None,
                     zone: str | None = None, by: str | None = None) -> str:
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM can spawn entities")
        if entity_id in self.state["entities"]:
            raise EngineError(f"entity {entity_id!r} already exists")
        if zone is not None:
            self._check_region(zone)
        ent = self._new_entity(entity_id, name, "npc", "gm", stats or {})
        ent["zone"] = zone
        self._emit("entity_spawned", {"entity": ent}, actor=by)
        return entity_id

    @atomic
    def create_clock(self, clock_id: str, label: str, total: int, visible: bool = True, by: str | None = None) -> None:
        if clock_id in self.state["clocks"]:
            raise EngineError(f"clock {clock_id!r} exists")
        self._emit("clock_created", {"clock_id": clock_id, "label": label, "total": int(total), "visible": bool(visible)},
                   actor=by or self.gm_seat)

    @atomic
    def advance_clock(self, clock_id: str, amount: int, by: str | None = None) -> None:
        if amount not in (1, 2, 3):
            raise EngineError("clock advances are 1, 2 or 3")
        self._apply_effect({"primitive": "advance_clock", "clock": clock_id, "amount": amount},
                           {"actor": None, "target": None, "self": None}, None, {})

    # ------------------------------------------------------------ actions

    def _requires_ok(self, action: dict, ent: dict, target: dict | None) -> bool:
        if "requires" not in action:
            return True
        return bool(expr.evaluate(action["requires"], self._ctx(ent, target), self.rounding))

    def _eligible(self, action: dict, ent: dict, target: dict | None) -> bool:
        if "eligibility" not in action:
            return True
        return bool(expr.evaluate(action["eligibility"], self._ctx(ent, target), self.rounding))

    def _mode_ok(self, action: dict) -> bool:
        mode = "encounter" if self.state["scene"]["encounter"] else "free"
        return mode in (action.get("modes") or ["free", "encounter"])

    def _affordable(self, action: dict, ent: dict) -> bool:
        cost = action.get("cost")
        if not cost:
            return True
        need = cost.get("amount", min(cost.get("amounts") or [cost.get("range", [0])[0]]))
        return ent["currencies"].get(cost["currency"], 0) >= need

    def enumerate_actions(self, entity_id: str, target_id: str | None = None) -> list[str]:
        ent = self._entity(entity_id)
        target = self.state["entities"].get(target_id) if target_id else None
        out = []
        for a in self.pack.catalogue("actions"):
            if not self._mode_ok(a) or not self._affordable(a, ent):
                continue
            if not self._requires_ok(a, ent, target):
                continue
            if a.get("trigger") == "fiction" and not self._eligible(a, ent, target):
                continue
            out.append(a["id"])
        return out

    @atomic
    def commit_action(self, entity_id: str, action_id: str, *, by: str | None = None, target: str | None = None,
                      spend: int | None = None, gm: dict | None = None) -> dict:
        ent = self._entity(entity_id)
        by = by or ent["controller"]
        if by != ent["controller"] and self._role(by) != "gm":
            raise EngineError(f"{by!r} does not control {entity_id!r}")
        actions = self.pack.by_id("actions")
        if action_id not in actions:
            raise EngineError(_suggest("action", action_id, actions))
        action = actions[action_id]
        if not self._mode_ok(action):
            raise EngineError(f"{action_id} is not available in this mode")
        target_ent = None
        target_kind = action.get("target", "none")
        if target_kind == "entity":
            if not target:
                raise EngineError(f"{action_id} needs a target entity")
            target_ent = self._entity(target)
            if not self.visible(by, target):
                seen = [e for e in self.state["entities"] if e != entity_id and self.visible(by, e)]
                raise EngineError(_suggest("entity", target, seen))
        elif target_kind == "zone":
            if not target:
                raise EngineError(f"{action_id} needs a target zone")
            self._check_region(target)
        elif target:
            raise EngineError(f"{action_id} takes no target")
        if not self._requires_ok(action, ent, target_ent):
            raise EngineError(f"{action_id}: requirements not met for {entity_id}")
        options = self.enumerate_actions(entity_id, target if target_kind == "entity" else None)
        eligible = self._eligible(action, ent, target_ent)
        trigger_mode = None
        if action.get("trigger") == "fiction":
            trigger_mode = self.mode("fiction_triggers", by)
            if trigger_mode == STRICT and not eligible:
                raise EngineError(f"{action_id} is not among the eligible moves: {', '.join(options) or 'none'}")

        cost = action.get("cost") or {}
        amount = None
        spend_mode = None
        if cost:
            if "amount" in cost:
                amount = int(cost["amount"])
            else:
                spend_mode = self.mode("spend_amounts", by)
                if spend is None:
                    raise EngineError(f"{action_id} needs a spend amount")
                if spend_mode == STRICT and spend not in cost["amounts"]:
                    raise EngineError(f"spend must be one of {cost['amounts']}")
                lo, hi = cost.get("range") or [min(cost["amounts"]), max(cost["amounts"])]
                if spend_mode == STANDARD and not (lo <= spend <= hi):
                    raise EngineError(f"spend must be between {lo} and {hi}")
                amount = int(spend)
            if ent["currencies"].get(cost["currency"], 0) < amount:
                raise EngineError(f"{entity_id} cannot afford {amount} {cost['currency']}")

        seq = self._emit("action_committed", {
            "entity": entity_id, "by": by, "action": action_id, "target": target, "spend": amount,
            "trigger": action.get("trigger", "declared"), "eligible": eligible,
        }, actor=by)
        self._judge(by, "action_selection", trigger_mode, action_id, options, seq)
        if spend_mode:
            self._judge(by, "spend_amounts", spend_mode, amount, cost.get("amounts") or cost.get("range"), seq)
        if amount:
            self._apply_effect({"primitive": "spend_currency", "target": "actor", "currency": cost["currency"],
                                "amount": amount}, {"actor": entity_id, "target": target, "self": entity_id}, seq, {})

        proc = self.pack.by_id("resolution.procedures")[action["procedure"]]
        outcome, rank, proc_seq = self._run_procedure(
            proc, ent, target_ent, action.get("stat"), action.get("difficulty"), gm or {}, seq)
        variables = {"spent": amount or 0}
        for e in (action.get("outcome_effects") or {}).get(outcome, []):
            self._apply_effect(e, {"actor": entity_id, "target": target, "self": entity_id}, proc_seq, variables)
        return {"seq": seq, "outcome": outcome, "rank": rank}

    @atomic
    def resolve_unmodelled(self, entity_id: str, procedure_id: str, *, stat: str | None = None,
                           difficulty: Any = None, tags: list[str] | None = None, outcome: str | None = None,
                           by: str | None = None) -> dict:
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM resolves unmodelled actions")
        procs = self.pack.by_id("resolution.procedures")
        if procedure_id not in procs:
            raise EngineError(_suggest("procedure", procedure_id, procs))
        ent = self._entity(entity_id)
        mode = self.mode("unmodelled_actions", by)
        if outcome is not None and mode == STRICT:
            raise EngineError("under strict settings the GM maps the action onto a procedure; the engine rolls")
        seq = self._emit("gm_resolution", {"entity": entity_id, "procedure": procedure_id, "stat": stat,
                                           "direct_outcome": outcome}, actor=by)
        self._judge(by, "unmodelled_actions", mode, {"procedure": procedure_id, "stat": stat, "outcome": outcome},
                    sorted(procs), seq)
        ladder = (self.pack.catalogue("resolution.difficulty_ladders") or [{}])[0].get("id")
        out, rank, _ = self._run_procedure(procs[procedure_id], ent, None, stat,
                                           {"ladder": ladder} if ladder else None,
                                           {"difficulty": difficulty, "tags": tags or []}, seq, direct_outcome=outcome)
        return {"seq": seq, "outcome": out, "rank": rank}

    # ------------------------------------------------------------ resolution (§2.5)

    def _run_procedure(self, proc: dict, ent: dict, target: dict | None, stat: str | None,
                       difficulty_spec: dict | None, gm_inputs: dict, cause: int,
                       direct_outcome: str | None = None) -> tuple[str, int, int]:
        steps = {k: v for step in proc.get("steps") or [] for k, v in step.items()}
        interp = steps["interpret"]
        scale = self.pack.by_id("resolution.outcome_scales")[interp["scale"]]["ordered"]
        gm_seat = self.gm_seat
        modifiers: list[dict] = []
        difficulty: dict | None = None
        total = None
        roll_seq = None

        if interp.get("automatic"):
            outcome = scale[-1]
        elif direct_outcome is not None:
            if direct_outcome not in scale:
                raise EngineError(_suggest("outcome", direct_outcome, scale))
            outcome = direct_outcome
        else:
            sources = (steps.get("modifiers") or {}).get("from", [])
            if "stat" in sources and stat:
                value = self._derived(ent)[stat]
                modifiers.append({"source": stat, "kind": "stat", "value": value, "origin": "state"})
            if "conditions" in sources:
                conds = self.pack.by_id("entity_model.conditions")
                for cid in sorted(ent["conditions"]):
                    if conds.get(cid, {}).get("modifier"):
                        modifiers.append({"source": cid, "kind": "condition",
                                          "value": int(conds[cid]["modifier"]), "origin": "state"})
            if "tags" in sources:
                modifiers += self._situational(ent, target, gm_inputs, cause)

            if "difficulty" in (proc.get("inputs") or []):
                difficulty = self._difficulty(difficulty_spec, ent, target, gm_inputs.get("difficulty"), cause)

            mod = sum(m["value"] for m in modifiers)
            result, roll_seq = self._roll(steps["roll"], {"mod": mod}, cause, f"procedure:{proc['id']}")
            total = result.total
            if "bands" in interp:
                idx = len(interp["bands"]) - 1
                for i, (lo, hi) in enumerate(interp["bands"]):
                    if total <= hi:
                        idx = i
                        break
                outcome = scale[max(0, idx)]
            else:
                against = difficulty["value"] if difficulty else 0
                ok = total >= against if interp["compare"] == ">=" else total <= against
                outcome = scale[1] if ok else scale[0]

        rank = scale.index(outcome)
        seq = self._emit("procedure_resolved", {
            "procedure": proc["id"], "entity": ent["id"], "scale": interp["scale"], "outcome": outcome,
            "rank": rank, "ranks": len(scale), "total": total, "difficulty": difficulty,
            "modifiers": modifiers, "roll_seq": roll_seq, "direct": direct_outcome is not None,
        }, caused_by=cause)
        return outcome, rank, seq

    def _situational(self, ent: dict, target: dict | None, gm_inputs: dict, cause: int) -> list[dict]:
        tags = self.pack.by_id("resolution.situational_tags")
        ctx = self._ctx(ent, target)
        out = []
        for tid, tag in tags.items():
            if "derive" in tag and expr.evaluate(tag["derive"], ctx, self.rounding):
                out.append({"source": tid, "kind": "tag", "value": int(tag["value"]), "origin": "auto"})
        chosen = list(gm_inputs.get("tags") or [])
        cap = int(self.pack.get("resolution.tags_cap_per_roll", 2))
        if len(chosen) > cap:
            raise EngineError(f"at most {cap} situational tags per roll")
        mode = self.mode("situational_modifiers", self.gm_seat)
        for tid in chosen:
            if tid not in tags:
                raise EngineError(_suggest("situational tag", tid, [t for t in tags if "derive" not in tags[t]]))
            if "derive" in tags[tid]:
                raise EngineError(f"{tid} is derived from state and cannot be added by hand")
            out.append({"source": tid, "kind": "tag", "value": int(tags[tid]["value"]), "origin": "gm"})
        free = gm_inputs.get("free_modifier")
        if free:
            if mode == STRICT:
                raise EngineError("free modifiers are not available under strict settings; choose tags instead")
            bound = int(self.pack.get("resolution.free_modifier_max", 2))
            if not (-bound <= int(free) <= bound):
                raise EngineError(f"free modifier must be within ±{bound}")
            out.append({"source": "free_modifier", "kind": "free", "value": int(free), "origin": "gm"})
        if chosen or free:
            self._judge(self.gm_seat, "situational_modifiers", mode, {"tags": chosen, "free": free or 0},
                        [t for t in tags if "derive" not in tags[t]], cause)
        return out

    def _difficulty(self, spec: dict | None, ent: dict, target: dict | None, supplied: Any, cause: int) -> dict:
        if not spec:
            raise EngineError("this procedure needs a difficulty but the action declares none")
        if "derived" in spec:
            value = expr.evaluate(spec["derived"], self._ctx(ent, target), self.rounding)
            return {"value": value, "origin": "derived", "rung": None}
        ladder = self.pack.by_id("resolution.difficulty_ladders")[spec["ladder"]]
        rungs = {r["id"]: r for r in ladder["rungs"]}
        mode = self.mode("difficulty", self.gm_seat)
        if supplied is None:
            raise EngineError(f"the GM must choose a difficulty: {', '.join(rungs)}")
        if isinstance(supplied, str):
            if supplied not in rungs:
                raise EngineError(_suggest("difficulty rung", supplied, rungs))
            self._judge(self.gm_seat, "difficulty", mode, supplied, list(rungs), cause)
            return {"value": int(rungs[supplied]["value"]), "origin": "gm-rung", "rung": supplied}
        if isinstance(supplied, bool) or not isinstance(supplied, int):
            raise EngineError("difficulty must be a rung id or an integer")
        if mode == STRICT:
            raise EngineError(f"under strict settings difficulty is a rung: {', '.join(rungs)}")
        lo, hi = ladder.get("range") or [min(r["value"] for r in rungs.values()), max(r["value"] for r in rungs.values())]
        if not (lo <= supplied <= hi):
            raise EngineError(f"difficulty must be between {lo} and {hi}")
        self._judge(self.gm_seat, "difficulty", mode, supplied, [lo, hi], cause)
        return {"value": supplied, "origin": "gm-value", "rung": None}

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
            changes.append({"path": ["entities", target_id, "zone"], "value": to})
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

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

from . import KERNEL_VERSION, canon, clocks, decks, dice, expr, fudging, hooks, progression, rules, spatial, timekeeping, turns
from .canon import CanonCommands
from .canonical import hash_obj
from .clocks import ClockCommands
from .decks import DeckCommands
from .command import EngineError, _suggest, atomic, gm_call
from .determinism import STANDARD, STRICT, apply_change, expand, setting_for, unsupported_strict
from .effects import EffectCommands
from .events import EventStore
from .fudging import FudgeCommands
from .packlint import readiness
from .packs import ResolvedPack
from .progression import ProgressionCommands
from .resolution import ResolutionCommands
from .sheets import SheetCommands
from .rng import Randomizer
from .rules import RulesCommands
from .spatial import SpatialCommands
from .terms import TermCommands
from .timekeeping import TimeCommands
from .tactics import TacticalCommands
from .turns import TurnCommands


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


_PASSIVE = rules.EVENT_TYPES | spatial.PASSIVE_EVENTS | {"hook_ran"} | {
    "chargen_started", "judgement_input", "procedure_resolved", "table_rolled",
    "gm_resolution", "campaign_forked",
}

# Every event type the reducer accepts. Adding a type means: handle it in
# apply_event, document it in docs/dev/EVENTS.md (a test enforces both), and
# bump KERNEL_VERSION if existing logs would fold differently.
EVENT_TYPES = frozenset({
    "campaign_started", "determinism_settings_recorded", "determinism_change_requested",
    "determinism_changed", "session_started", "session_ended", "scene_set", "scene_closed", "roll_made",
    "effect_applied", "character_created", "entity_spawned", "clock_created",
    "action_committed", "gm_ruling_requested", "gm_ruling_filled",
}) | canon.EVENT_TYPES | spatial.EVENT_TYPES | turns.EVENT_TYPES | decks.EVENT_TYPES | fudging.EVENT_TYPES \
    | clocks.EVENT_TYPES | timekeeping.EVENT_TYPES | progression.EVENT_TYPES | _PASSIVE


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
    elif t == "scene_closed":
        state["scene"]["closed"] = True  # only logs with the marker carry the flag
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
        state["clocks"][p["clock_id"]] = clocks.created_clock(p)
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
    elif t in turns.EVENT_TYPES:
        turns.apply_event(state, ev)
    elif t in decks.EVENT_TYPES:
        decks.apply_event(state, ev)
    elif t in fudging.EVENT_TYPES:
        fudging.apply_event(state, ev)
    elif t in clocks.EVENT_TYPES:
        clocks.apply_event(state, ev)
    elif t in timekeeping.EVENT_TYPES:
        timekeeping.apply_event(state, ev)
    elif t in progression.EVENT_TYPES:
        progression.apply_event(state, ev)
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

class Engine(ResolutionCommands, EffectCommands, CanonCommands, SpatialCommands, TacticalCommands,
             TurnCommands, DeckCommands, FudgeCommands, SheetCommands, ClockCommands, RulesCommands,
             TermCommands, TimeCommands, ProgressionCommands):
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
            "gm_fudging": int((config.get("gm_traits") or {}).get("fudging", 50)),
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
        result = dice.evaluate(src, variables, draw, max_dice=int(grammar.get("max_dice", 20)),
                               step_sizes=grammar.get("step_sizes"))
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

    @staticmethod
    def _plain(value):
        """A plain copy for pack code: dicts, lists, and scalars only."""
        if isinstance(value, dict):
            return {str(k): Engine._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [Engine._plain(v) for v in value]
        return value

    def _hooks_at(self, point: str) -> list[dict]:
        return [h for h in self.pack.get("hooks") or [] if isinstance(h, dict) and h.get("point") == point]

    def _call_hook(self, name: str, point: str, view: dict, params: dict, cause: int | None, rolls: bool = True):
        """Run one pack hook under the §2.7 contract and log it. Draws use one
        roll counter and are logged as a `roll_made` (expression `hook`)."""
        hook = next((h for h in self.pack.get("hooks") or [] if h.get("name") == name), None)
        if hook is None or hook["point"] != point:
            raise EngineError(f"no {point} hook named {name!r} in pack {self.pack.id}")
        counter, draw = self._draw()
        try:
            result, draws = hooks.run(hook, view, params, draw if rolls else None)
        except hooks.HookError as e:
            raise EngineError(str(e)) from None
        roll_seq = None
        if draws:
            roll_seq = self._emit("roll_made", {"counter": counter, "purpose": f"hook:{name}", "expression": "hook",
                                                "draws": draws, "total": sum(d[2] for d in draws), "groups": [],
                                                "variables": {}}, caused_by=cause)
        self._emit("hook_ran", {"hook": name, "point": point, "result": self._plain(result), "roll_seq": roll_seq},
                   caused_by=cause)
        return result

    # ------------------------------------------------------------ currencies (§2.3, §2.4)

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

    def view(self, ent: dict | None) -> dict:
        if ent is None:  # no entity: every field reads 0, nested ones too (target.region.cover.x)
            return expr.Lenient({"conditions": expr.Lenient(), "tags": expr.Lenient(),
                                 "region": expr.Lenient({"elevation": 0, "terrain": expr.Lenient(),
                                                         "cover": expr.Lenient()})})
        out = self._derived(ent)
        out.update(ent["resources"])
        out.update(ent["tracks"])
        out.update(self._currencies(ent))
        out["conditions"] = expr.Lenient({c: int(v.get("level", 1)) for c, v in ent["conditions"].items()})
        out["tags"] = expr.Lenient({t: 1 for t in ent["tags"]})
        out["region"] = self._region_view(ent["id"], None)  # cover, terrain, elevation where it stands
        if self._inventory_model() == "weight":  # an encumbrance tag can read these
            out["carried"] = self.carried(ent)
            out["capacity"] = self.capacity(ent) if self.capacity(ent) is not None else 0
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
        self._time_between_sessions()  # in-world time passes off-air, if the pack says how much
        self._advance_off_air()  # axiom 15: world changes are canon before play resumes
        self._boundary()
        seq = self._emit("session_started", {"number": self.state["session"] + 1}, actor=by or self.gm_seat)
        self._reshuffle_at("session")
        return seq

    def _close_scene(self, by: str, reason: str) -> None:
        """Mark the end of the open scene (§5.7), after the events that close it."""
        scene = self.state["scene"]
        if scene["id"] is not None and not scene.get("closed"):
            self._emit("scene_closed", {"scene_id": scene["id"], "index": scene["index"], "reason": reason}, actor=by)

    def _close_encounter(self, by: str) -> None:
        if self.state.get("encounter") is not None:  # an encounter never outlives its scene
            self._emit("encounter_ended", {"round": self.state["encounter"]["round"]}, actor=by)

    @atomic
    def end_session(self, by: str | None = None) -> int:
        self._require_settled()
        self._close_encounter(by or self.gm_seat)
        self._expire({"scene", "session"})
        self._close_scene(by or self.gm_seat, "session_ended")
        self._progress_on_session_end()
        return self._emit("session_ended", {"number": self.state["session"]}, actor=by or self.gm_seat)

    @atomic
    @gm_call()
    def set_scene(self, scene_id: str, flags: dict | None = None, encounter: bool = False, by: str | None = None,
                  regions: list[dict] | None = None, placements: dict[str, str] | None = None,
                  participants: list[str] | None = None, ranges: list[dict] | None = None) -> int:
        """Open a scene (§8.2). With `regions` it is a zone scene and `placements`
        puts entities in its regions; with `participants` it is a range-band scene
        and `ranges` sets bands between pairs (§1.4)."""
        if not self.state["session"]:
            raise EngineError("start a session before setting a scene")
        self._require_settled()
        if placements and regions is None:
            raise EngineError("placements need regions: a scene without regions has no positions")
        if ranges and participants is None:
            raise EngineError("ranges need participants: a band scene measures between its participants")
        spatial_scene = regions is not None or participants is not None
        layout = self._spatial_spec(regions, participants, ranges) if spatial_scene else None
        by = by or self.gm_seat
        self._close_encounter(by)
        self._expire({"scene"})
        self._close_scene(by, "next_scene")
        flags = {k: int(v) for k, v in (flags or {}).items()}
        index = self.state["scene"]["index"] + 1
        payload = {"scene_id": scene_id, "index": index, "flags": flags, "encounter": bool(encounter)}
        if layout is not None:
            payload["spatial"] = layout
        self._emit("scene_set", payload, actor=by)
        self._reshuffle_at("scene")
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
            if c.get("holder", "each_player") == "each_player" and kind == "pc":  # pools are shared (§2.3)
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
            elif kind == "assign":  # place a fixed array of values onto stats (§1.5)
                pick = choices.get(step["id"])
                values, targets = list(step["values"]), list(step["targets"])
                if not isinstance(pick, dict) or sorted(pick) != sorted(targets):
                    raise EngineError(f"{step['id']}: assign each of {', '.join(targets)} one of the values "
                                      f"{values}, as {{stat: value}}")
                if sorted(pick.values()) != sorted(values):
                    raise EngineError(f"{step['id']}: the values must be exactly {sorted(values)}, each used once; "
                                      f"got {sorted(pick.values())}")
                self._judge(agent_id, "chargen_assign", None, {t: pick[t] for t in targets}, values, start)
                stats.update({t: int(pick[t]) for t in targets})
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
        for hook in self._hooks_at("sheet.validate"):  # cross-field constraints (§2.7)
            problems = self._call_hook(hook["name"], "sheet.validate", self._sheet_view(ent), {}, start, rolls=False)
            if problems:
                raise EngineError(f"{entity_id}'s sheet breaks {hook['name']}: {'; '.join(map(str, problems))}")
        self._emit("character_created", {"entity": ent, "unique_choices": unique, "choices": choices},
                   actor=agent_id, caused_by=start)
        return entity_id

    @atomic
    @gm_call()
    def spawn_entity(self, entity_id: str, name: str, stats: dict[str, int] | None = None,
                     zone: str | None = None, by: str | None = None) -> str:
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM can spawn entities")
        if entity_id in self.state["entities"]:
            raise EngineError(f"entity {entity_id!r} already exists")
        if zone is not None:
            self._check_position(zone)
        relative = zone is not None and (self._spatial() or {}).get("mode") == "bands"
        ent = self._new_entity(entity_id, name, "npc", "gm", stats or {})
        ent["zone"] = None if relative else zone
        self._emit("entity_spawned", {"entity": ent}, actor=by)
        if relative:  # a band position is relative to others: join the scene there
            self._place(entity_id, zone, by)
        return entity_id

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
        return self._currencies(ent).get(cost["currency"], 0) >= need

    def available_actions(self, entity_id: str, target_id: str | None = None) -> list[str]:
        """Ids of the actions the entity could commit now, in catalogue order. The
        ranked, annotated view for agents is `enumerate_action_candidates` (§1.4.2)."""
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
            if self._turn_problem(entity_id, a) is not None:
                continue
            if self._roll_refusal(self.pack.by_id("resolution.procedures")[a["procedure"]], ent, target):
                continue  # the GM never rolls (§2.4)
            out.append(a["id"])
        return out

    @atomic
    def commit_action(self, entity_id: str, action_id: str, *, by: str | None = None, target: str | None = None,
                      spend: int | None = None, gm: dict | None = None) -> dict:
        self._require_settled()
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
            self._check_position(target, observer=by)
        elif target:
            raise EngineError(f"{action_id} takes no target")
        if not self._requires_ok(action, ent, target_ent):
            raise EngineError(f"{action_id}: requirements not met for {entity_id}")
        problem = self._turn_problem(entity_id, action)
        if problem:
            raise EngineError(problem)
        options = self.available_actions(entity_id, target if target_kind == "entity" else None)
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
            if self._currencies(ent).get(cost["currency"], 0) < amount:
                raise EngineError(f"{entity_id} cannot afford {amount} {cost['currency']}")

        seq = self._emit("action_committed", {
            "entity": entity_id, "by": by, "action": action_id, "target": target, "spend": amount,
            "trigger": action.get("trigger", "declared"), "eligible": eligible,
        }, actor=by)
        self._judge(by, "action_selection", trigger_mode, action_id, options, seq)
        self._spend_turn_economy(entity_id, action, seq)
        if spend_mode:
            self._judge(by, "spend_amounts", spend_mode, amount, cost.get("amounts") or cost.get("range"), seq)
        if amount:
            self._apply_effect({"primitive": "spend_currency", "target": "actor", "currency": cost["currency"],
                                "amount": amount}, {"actor": entity_id, "target": target, "self": entity_id}, seq, {})

        proc = self.pack.by_id("resolution.procedures")[action["procedure"]]
        ids = {"actor": entity_id, "target": target, "self": entity_id}
        variables = {"spent": amount or 0}
        outcome, rank, proc_seq = self._run_procedure(
            proc, ent, target_ent, action.get("stat"), action.get("difficulty"), gm or {}, seq,
            continuation={"kind": "action", "action": action_id, "ids": ids, "variables": variables})
        if outcome is None:  # the GM peeked (§5.5): resolution waits for peek_roll
            return {"seq": seq, "pending": self.pending_peek()}
        self._apply_outcome(action_id, outcome, ids, variables, proc_seq)
        return {"seq": seq, "outcome": outcome, "rank": rank}

    def _apply_outcome(self, action_id: str, outcome: str, ids: dict, variables: dict, cause: int) -> None:
        action = self.pack.by_id("actions")[action_id]
        for e in (action.get("outcome_effects") or {}).get(outcome, []):
            self._apply_effect(e, ids, cause, variables)

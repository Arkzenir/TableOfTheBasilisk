"""Scripted-actor harness (BUILD_PLAN P0.12).

Plays campaigns through the engine with hardcoded choices instead of models.
Every choice is derived from engine enumerations and a turn counter, never
from randomness, so the same script and seed always produce the same log.

Three entry points:
  * smoke_script(pack)  - a generic campaign that works for any pack
  * run_script(script)  - execute a script (from YAML or smoke_script)
  * verify(...)         - hash chain, replay, seed commitment, roll re-derivation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..kernel import dice
from ..kernel.canonical import hash_obj
from ..kernel.determinism import STANDARD, STRICT
from ..kernel.engine import Engine, EngineError, fold
from ..kernel.events import EventStore
from ..kernel.packs import ResolvedPack, resolve
from ..kernel.rng import Randomizer
from ..kernel.spatial import declared_backends

PLAYERS = ["ash", "bram", "cyra", "dov"]
NAMES = {"ash": "Ash", "bram": "Bram", "cyra": "Cyra", "dov": "Dov", "gm": "The GM"}
NPCS = [("npc_warden", "The Warden"), ("npc_shade", "A Shade")]
# A three-region line for smoke scenes on packs that permit zone scenes: zone_0 - zone_1 - zone_2.
SMOKE_REGIONS = [{"id": "zone_0", "label": "Near side", "adjacency": ["zone_1"]},
                 {"id": "zone_1", "label": "Middle", "adjacency": ["zone_2"]},
                 {"id": "zone_2", "label": "Far side"}]


def logical_clock():
    return None  # timestamps are wall-clock in production; None keeps harness logs byte-identical


@dataclass
class RunReport:
    campaign_id: str
    pack: str
    pack_hash: str
    events: int
    state_hash: str
    head_hash: str
    actions_taken: dict[str, int] = field(default_factory=dict)
    actions_never_taken: list[str] = field(default_factory=list)
    settings_changes: int = 0
    rejected: list[str] = field(default_factory=list)

    def summary(self) -> str:
        cov = len(self.actions_taken)
        total = cov + len(self.actions_never_taken)
        lines = [
            f"campaign      {self.campaign_id}",
            f"pack          {self.pack} ({self.pack_hash[:12]})",
            f"events        {self.events}",
            f"state hash    {self.state_hash[:16]}",
            f"log head      {self.head_hash[:16]}",
            f"actions       {cov}/{total} covered " + ", ".join(f"{k}x{v}" for k, v in sorted(self.actions_taken.items())),
            f"settings      {self.settings_changes} mid-campaign change(s)",
        ]
        if self.actions_never_taken:
            lines.append(f"NOT COVERED   {', '.join(self.actions_never_taken)}")
        if self.rejected:
            lines.append(f"rejected      {len(self.rejected)} command(s) (expected: engine refusals are atomic)")
        return "\n".join(lines)


# ---------------------------------------------------------------- generic smoke script

def smoke_script(pack: ResolvedPack, seed: str = "smoke-seed", sessions: int = 3, scenes_per_session: int = 2,
                 campaign_id: str | None = None, determinism: dict | None = None) -> dict:
    """A pack-agnostic campaign description. Concrete choices are made at run time
    from engine enumerations (see `_play_turn`), so it works for any pack."""
    return {
        "campaign_id": campaign_id or f"smoke-{pack.id}",
        "pack": f"{pack.id}@{pack.version}",
        "seed": seed,
        "config": {
            "seats": {"gm": "gm", **{p: "player" for p in PLAYERS}},
            "determinism": determinism or {"players": {"preset": STRICT}, "gm": {"preset": STANDARD}},
            "gm_traits": {"lethality": 50},
        },
        "smoke": {"sessions": sessions, "scenes_per_session": scenes_per_session, "toggle_gm": True},
        "steps": [],
    }


def _gm_inputs(engine: Engine, action: dict, turn: int) -> dict:
    pack = engine.pack
    gm: dict[str, Any] = {}
    procs = pack.by_id("resolution.procedures")
    proc = procs.get(action["procedure"], {})
    if "difficulty" in (proc.get("inputs") or []) and isinstance(action.get("difficulty"), dict) \
            and "ladder" in action["difficulty"]:
        ladder = pack.by_id("resolution.difficulty_ladders")[action["difficulty"]["ladder"]]
        rungs = ladder["rungs"]
        if engine.mode("difficulty", engine.gm_seat) == STANDARD and turn % 3 == 0:
            lo, hi = ladder.get("range", [rungs[0]["value"], rungs[-1]["value"]])
            gm["difficulty"] = (lo + hi) // 2
        else:
            gm["difficulty"] = rungs[turn % len(rungs)]["id"]
    choosable = [t["id"] for t in pack.catalogue("resolution.situational_tags") if "derive" not in t]
    if choosable and turn % 2 == 0:
        gm["tags"] = [choosable[turn % len(choosable)]]
    if engine.mode("situational_modifiers", engine.gm_seat) == STANDARD and turn % 4 == 0:
        gm["free_modifier"] = 1
    return gm


def _pick_target(engine: Engine, actor: str, action: dict, turn: int) -> str | None:
    kind = action.get("target", "none")
    if kind == "zone":
        reachable = engine.reachable(actor)
        return reachable[turn % len(reachable)] if reachable else f"zone_{turn % 3}"
    if kind != "entity":
        return None
    by = engine.state["entities"][actor]["controller"]
    others = sorted(e for e in engine.state["entities"] if e != actor and engine.visible(by, e))
    return others[turn % len(others)] if others else None


def _spend(engine: Engine, action: dict, actor: str) -> int | None:
    cost = action.get("cost") or {}
    if "amounts" not in cost:
        return None
    have = engine.state["entities"][actor]["currencies"].get(cost["currency"], 0)
    if engine.mode("spend_amounts", actor) == STRICT:
        affordable = [a for a in cost["amounts"] if a <= have]
        return affordable[-1] if affordable else None
    lo, hi = cost.get("range", [min(cost["amounts"]), max(cost["amounts"])])
    return min(hi, have) if have >= lo else None


def _play_turn(engine: Engine, actor: str, turn: int, report: RunReport, force: str | None = None) -> None:
    actions = engine.pack.by_id("actions")
    options = engine.available_actions(actor)
    if force:
        if force not in options:
            return
        choice = force
    else:
        if not options:
            return
        choice = options[turn % len(options)]
    action = actions[choice]
    target = _pick_target(engine, actor, action, turn)
    spend = _spend(engine, action, actor)
    if action.get("cost") and "amounts" in action["cost"] and spend is None:
        return
    try:
        engine.commit_action(actor, choice, target=target, spend=spend, gm=_gm_inputs(engine, action, turn))
        report.actions_taken[choice] = report.actions_taken.get(choice, 0) + 1
    except EngineError as e:
        report.rejected.append(f"{actor}:{choice}: {e}")
    for slot, info in sorted(engine.open_rulings().items()):
        entries = info["entries"]
        engine.fill_ruling(slot, entries[turn % len(entries)])


def _play_encounter(engine: Engine, players: list[str], turn: int, report: RunReport) -> int:
    """One round of encounter mode under the pack's turn structure (§2.4):
    whoever is in play acts until their budget or options run out, then the
    turn passes. NPC turns pass without acting."""
    info = engine.start_encounter()
    participants = engine.state["encounter"]["participants"]
    if info["order"] == "spotlight":
        for p in players:
            _play_turn(engine, p, turn, report)
            turn += 1
        engine.next_round()
    else:
        for _ in range(len(participants) if info["order"] != "sides" else 2):
            current = engine.current_turn()
            members = [current["actor"]] if current["kind"] == "entity" else \
                [e for e in participants if engine.state["entities"][e]["controller"] in players]
            for member in members:
                if member in players:
                    for _ in range(3):  # a few actions, bounded by the economy
                        before = engine.store.head(engine.campaign_id)
                        _play_turn(engine, member, turn, report)
                        turn += 1
                        if engine.store.head(engine.campaign_id) == before:
                            break
            nxt = None
            if info["order"] == "handoff":
                acted = engine.state["encounter"]["acted"]
                waiting = [e for e in participants if e not in acted] or [e for e in participants if e != current["actor"]]
                nxt = (waiting or [current["actor"]])[0]
            engine.end_turn(next=nxt)
    engine.end_encounter()
    return turn


def _run_smoke(engine: Engine, script: dict, report: RunReport) -> None:
    smoke = script["smoke"]
    seats = script["config"]["seats"]
    players = [s for s, r in seats.items() if r == "player"]
    for n, p in enumerate(players):
        choices = {}
        for step in engine.pack.get("chargen.steps") or []:
            if step["kind"] == "choice":
                taken = set(engine.state["chargen_taken"].get(step["id"], []))
                opts = [o["id"] for o in step["options"] if o["id"] not in taken]
                choices[step["id"]] = opts[0]
            elif step["kind"] == "assign":  # each player rotates the array differently
                values = list(step["values"])
                shift = n % len(values)
                choices[step["id"]] = dict(zip(step["targets"], values[shift:] + values[:shift]))
        engine.create_character(p, NAMES.get(p, p), choices)
    for npc_id, name in NPCS:
        engine.spawn_entity(npc_id, name)
    engine.create_clock("pressure", "Something is coming", 6, visible=False, schedule={"every": 1, "amount": 1},
                        stages=[{"at": 3, "record": {"type": "event", "name": "The lights go out on the quay",
                                                     "body": "Something has reached the harbour.", "knowledge": "revealed"}},
                                {"at": 6, "record": {"type": "event", "name": "The thing arrives",
                                                     "body": "What was coming is here.", "knowledge": "revealed"}}])

    backends = declared_backends(engine.pack)
    placements = {**{p: "zone_1" for p in players}, "npc_warden": "zone_0", "npc_shade": "zone_2"}

    def open_scene(scene_id: str, flags: dict, encounter: bool) -> None:
        if "zone_graph" in backends:
            engine.set_scene(scene_id, flags=flags, encounter=encounter, regions=SMOKE_REGIONS, placements=placements)
        elif "range_bands" in backends:
            bands = [b["id"] for b in engine.pack.get("spatial.bands")]
            everyone = sorted(engine.state["entities"])
            ranges = [{"between": [p, "npc_warden"], "band": bands[0]} for p in players[:1]]
            engine.set_scene(scene_id, flags=flags, encounter=encounter, participants=everyone, ranges=ranges)
        else:
            engine.set_scene(scene_id, flags=flags, encounter=encounter)
            return
        if encounter and players:
            # one seat loses sight of the shade: per-observer visibility (§8.2)
            engine.set_visibility("npc_shade", [p for p in players if p != players[0]])

    turn = 0
    for s in range(smoke["sessions"]):
        engine.start_session()
        for sc in range(smoke["scenes_per_session"]):
            encounter = sc % 2 == 1
            flags = {"dim": int(sc == 0), "storm": int(s % 2 == 0), "danger": 1}
            if smoke.get("toggle_gm") and sc == 0 and s >= 1:
                current = engine.state["determinism"]["effective"]["gm"]
                flip = STRICT if STANDARD in current.values() else STANDARD
                engine.request_determinism_change(by="operator", role="gm", preset=flip)
                report.settings_changes += 1
            open_scene(f"s{s + 1}_scene{sc + 1}", flags, encounter)
            action_ids = sorted(engine.pack.by_id("actions"))  # a player looks a rule up (§2.11)
            engine.query_rules(players[sc % len(players)], action_ids[(s + sc) % len(action_ids)])
            if encounter:
                turn = _play_encounter(engine, players, turn, report)
            else:
                for p in players:
                    _play_turn(engine, p, turn, report)
                    turn += 1
            for deck in engine.pack.catalogue("randomizers.decks"):  # one draw per deck per scene
                engine.draw_card(deck["id"], to=players[sc % len(players)] if sc % 2 else None)
            engine.advance_clock("pressure", 1)
        engine.end_session()

    # coverage sweep: take every action the pack defines at least once (P0.12)
    engine.start_session()
    for encounter in (False, True):
        open_scene(f"sweep_{int(encounter)}", {"danger": 1, "dim": 0, "storm": 0}, encounter)
        for action_id in engine.pack.by_id("actions"):
            if action_id in report.actions_taken:
                continue
            for p in players:
                _play_turn(engine, p, turn, report, force=action_id)
                turn += 1
                if action_id in report.actions_taken:
                    break
    engine.end_session()


def _run_steps(engine: Engine, steps: list[dict], report: RunReport) -> None:
    for i, step in enumerate(steps):
        step = dict(step)
        do = step.pop("do")
        try:
            if do == "create_character":
                engine.create_character(step["agent"], step.get("name", step["agent"]), step.get("choices"))
            elif do == "spawn_entity":
                engine.spawn_entity(step["entity"], step.get("name", step["entity"]), step.get("stats"), step.get("zone"))
            elif do == "create_clock":
                engine.create_clock(step["clock"], step.get("label", step["clock"]), step["total"], step.get("visible", True),
                                    schedule=step.get("schedule"), stages=step.get("stages"))
            elif do == "pause_clock":
                engine.pause_clock(step["clock"], step.get("paused", True))
            elif do == "advance_clock":
                engine.advance_clock(step["clock"], step.get("amount", 1))
            elif do == "start_session":
                engine.start_session()
            elif do == "end_session":
                engine.end_session()
            elif do == "set_scene":
                engine.set_scene(step["scene"], step.get("flags"), step.get("encounter", False),
                                 regions=step.get("regions"), placements=step.get("placements"),
                                 participants=step.get("participants"), ranges=step.get("ranges"))
            elif do == "place_entity":
                engine.place_entity(step["entity"], step.get("position") or step["region"])
            elif do == "set_visibility":
                engine.set_visibility(step["entity"], step.get("visible_to"))
            elif do == "start_encounter":
                engine.start_encounter(step.get("participants"), step.get("first"))
            elif do == "end_turn":
                engine.end_turn(step.get("by"), step.get("next"))
            elif do == "next_round":
                engine.next_round()
            elif do == "end_encounter":
                engine.end_encounter()
            elif do == "write_canon":
                engine.write_canon(step["record"])
            elif do == "query_rules":
                engine.query_rules(step.get("seat", "gm"), step["query"])
            elif do == "peek_roll":
                engine.peek_roll(step["decision"])
            elif do == "draw_card":
                engine.draw_card(step["deck"], step.get("by"), step.get("to"))
            elif do == "reshuffle_deck":
                engine.reshuffle_deck(step["deck"])
            elif do == "discard_card":
                engine.discard_card(step["deck"], step["card"], step["holder"], step.get("by"))
            elif do == "commit_action":
                engine.commit_action(step["actor"], step["action"], target=step.get("target"),
                                     spend=step.get("spend"), gm=step.get("gm"))
                if engine.pending_peek() and step.get("then"):  # a scripted GM settles its own peek
                    engine.peek_roll(step["then"])
                report.actions_taken[step["action"]] = report.actions_taken.get(step["action"], 0) + 1
            elif do == "fill_ruling":
                for slot, info in sorted(engine.open_rulings().items()):
                    choose = step.get("choose", "first")
                    entry = info["entries"][0] if choose == "first" else choose
                    engine.fill_ruling(slot, entry)
            elif do == "request_change":
                engine.request_determinism_change(by=step.get("by", "operator"), role=step.get("role"),
                                                  preset=step.get("preset"), overrides=step.get("overrides"))
                report.settings_changes += 1
            elif do == "snapshot":
                engine.snapshot()
            else:
                raise EngineError(f"unknown step {do!r}")
        except EngineError as e:
            if step.get("expect_error"):
                report.rejected.append(f"step {i} ({do}): {e}")
                continue
            raise EngineError(f"step {i} ({do}) failed: {e}") from None


def run_script(script: dict, packs_dir: str | Path, store: EventStore | None = None) -> tuple[Engine, RunReport]:
    pack = resolve(script["pack"], packs_dir, allow_abstract=False)
    store = store or EventStore(":memory:")
    engine = Engine.start_campaign(pack, script["seed"], script["config"], store=store,
                                   campaign_id=script["campaign_id"], clock=logical_clock)
    report = RunReport(script["campaign_id"], pack.id, pack.hash, 0, "", "")
    if script.get("smoke"):
        _run_smoke(engine, script, report)
    _run_steps(engine, script.get("steps") or [], report)
    engine.snapshot()
    report.actions_never_taken = sorted(set(pack.by_id("actions")) - set(report.actions_taken))
    seq, head = store.head(script["campaign_id"])
    report.events, report.head_hash, report.state_hash = seq, head, engine.state_hash()
    return engine, report


def load_script(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------- verification

def verify(store: EventStore, campaign_id: str, pack: ResolvedPack | None = None,
           seed: str | None = None, expected_state_hash: str | None = None) -> list[str]:
    """Hash chain, fold, snapshot consistency, pinning, and (with the seed) every roll."""
    problems = store.verify_chain(campaign_id)
    events = list(store.read(campaign_id))
    if not events:
        return problems + [f"no events for {campaign_id}"]
    try:
        state = fold(events)
    except EngineError as e:
        return problems + [f"fold failed: {e}"]
    if expected_state_hash and hash_obj(state) != expected_state_hash:
        problems.append("replayed state differs from live state")
    snap = store.latest_snapshot(campaign_id)
    if snap:
        partial = fold(store.read(campaign_id, upto=snap["seq"]))
        if hash_obj(partial) != snap["state_hash"]:
            problems.append(f"snapshot at seq {snap['seq']} does not match the log")
        tail = fold(store.read(campaign_id, after=snap["seq"]), state=snap["state"])
        if hash_obj(tail) != hash_obj(state):
            problems.append("snapshot + tail does not equal a full fold")
    first = events[0]["payload"]
    if pack is not None and first.get("pack_hash") != pack.hash:
        problems.append(f"pinned pack hash {first.get('pack_hash', '')[:12]} != {pack.hash[:12]}")
    if seed is not None:
        rng = Randomizer(seed)
        if rng.commitment() != first.get("seed_commitment"):
            problems.append("seed does not match the published commitment")
        else:
            for ev in events:
                if ev["type"] == "deck_shuffled":
                    p = ev["payload"]
                    if rng.shuffle(p["counter"], p["cards"]) != p["order"]:
                        problems.append(f"seq {ev['seq']}: deck shuffle does not re-derive from the seed")
                    continue
                if ev["type"] != "roll_made":
                    continue
                p = ev["payload"]
                counter = p["counter"]
                if p.get("expression") == "weighted":
                    if rng.integer(counter, 0, 1, sum(p["weights"])) != p["total"]:
                        problems.append(f"seq {ev['seq']}: weighted draw does not re-derive")
                    continue
                again = dice.evaluate(p["expression"], p.get("variables") or {},
                                      lambda sub, lo, hi, c=counter: rng.integer(c, sub, lo, hi), max_dice=10**6)
                if again.total != p["total"] or again.groups != p["groups"]:
                    problems.append(f"seq {ev['seq']}: roll does not re-derive from the seed")
    return problems


def determinism_check(script: dict, packs_dir: str | Path) -> list[str]:
    """Run the same script twice; the logs must be byte-identical (P0 gate)."""
    _, a = run_script(script, packs_dir)
    _, b = run_script(script, packs_dir)
    problems = []
    if a.head_hash != b.head_hash:
        problems.append("two runs of the same script produced different event logs")
    if a.state_hash != b.state_hash:
        problems.append("two runs of the same script produced different final states")
    return problems

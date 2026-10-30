"""The encounter roster changes while it runs: join_encounter and
leave_encounter (T0.39; ARCHITECTURE §2.4, §5.7, §7.1; D-056)."""

import shutil

import pytest
import yaml

from basilisk.harness.scripted import verify
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import generate
from basilisk.kernel.determinism import expand

SEED = "roster-seed"
_PACKS: dict = {}
ORDERS = {
    "initiative": {"order": "initiative", "economy": "none", "initiative": {"roll": "1d20 + {grace}"}},
    "initiative_each_round": {"order": "initiative", "economy": "none",
                              "initiative": {"roll": "1d20 + {grace}", "each_round": True}},
    "fixed": {"order": "fixed", "economy": "none"},
    "deck": {"order": "deck", "economy": "none"},
    "sides": {"order": "sides", "economy": "none", "first": "players"},
    "handoff": {"order": "handoff", "economy": "none"},
    "spotlight": {"order": "spotlight", "economy": "points", "points": 2},
}


@pytest.fixture
def variant(packs_dir, tmp_path_factory):
    def make(name: str):
        if name not in _PACKS:
            dst = tmp_path_factory.mktemp("roster") / "packs"
            shutil.copytree(packs_dir, dst)
            path = dst / "lanternlight" / "pack.yaml"
            data = yaml.safe_load(path.read_text())
            data["turn_structure"] = {"encounter": ORDERS[name]}
            for action in data["actions"]:
                action.pop("slot", None)
            path.write_text(yaml.safe_dump(data, sort_keys=False))
            _PACKS[name] = resolve("lanternlight", dst)
        return _PACKS[name]
    return make


def table(pack, participants=None):
    eng = Engine.start_campaign(pack, SEED, {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("fight", encounter=True)
    eng.start_encounter(participants=participants)
    return eng


def enc(eng):
    return eng.state["encounter"]


def replays(eng):
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()
    assert verify(eng.store, eng.campaign_id, eng.pack, SEED) == []


def turns_over(eng, n):
    seen = []
    for _ in range(n):
        seen.append(enc(eng)["current"])
        eng.end_turn()
    return seen


# ---------------------------------------------------------------- joining

def test_a_late_arrival_takes_part_once_joined(variant):
    eng = table(variant("fixed"), participants=["ash", "bram", "foe"])
    eng.spawn_entity("wolf", "Wolf")
    with pytest.raises(EngineError, match="not taking part"):
        eng.commit_action("wolf", "recall", gm={"difficulty": "easy"})
    eng.join_encounter("wolf")
    assert enc(eng)["participants"] == ["ash", "bram", "foe", "wolf"]
    assert turns_over(eng, 5) == ["ash", "bram", "foe", "wolf", "ash"]
    replays(eng)


def test_fixed_order_joins_after_the_named_participant(variant):
    eng = table(variant("fixed"), participants=["ash", "bram", "foe"])
    eng.end_turn()  # bram is up
    eng.spawn_entity("wolf", "Wolf")
    eng.join_encounter("wolf", after="ash")  # its slot is already past this round
    assert enc(eng)["sequence"] == ["ash", "wolf", "bram", "foe"] and enc(eng)["current"] == "bram"
    assert turns_over(eng, 4) == ["bram", "foe", "ash", "wolf"]
    eng.spawn_entity("bat", "Bat")
    with pytest.raises(EngineError, match="No participant to follow 'nobody'"):
        eng.join_encounter("bat", after="nobody")
    replays(eng)


@pytest.mark.parametrize("name", ["initiative", "initiative_each_round"])
def test_initiative_rolls_on_joining_and_slots_in_by_total(variant, name):
    eng = table(variant(name))
    eng.spawn_entity("wolf", "Wolf")
    before = list(enc(eng)["sequence"])
    eng.join_encounter("wolf")
    rolls = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "roll_made"]
    totals = {r["purpose"].split(":", 1)[1]: r["total"] for r in rolls if r["purpose"].startswith("initiative:")}
    after = enc(eng)["sequence"]
    assert [e for e in after if e != "wolf"] == before  # nobody else moves
    assert after == sorted(after, key=lambda e: (-totals[e], e))
    joined = [e for e in eng.store.read(eng.campaign_id) if e["type"] == "participant_joined"][-1]
    assert joined["caused_by"] == [e for e in eng.store.read(eng.campaign_id)
                                   if e["type"] == "roll_made"][-1]["seq"]  # the logged roll placed it
    seen = turns_over(eng, 8)
    assert "wolf" in seen
    replays(eng)


def test_deck_order_shuffles_a_joiner_in_next_round(variant):
    eng = table(variant("deck"))
    eng.spawn_entity("wolf", "Wolf")
    eng.join_encounter("wolf")
    assert "wolf" not in enc(eng)["sequence"]
    turns_over(eng, 3)  # the first round ends
    assert "wolf" in enc(eng)["sequence"]
    replays(eng)


def test_spotlight_gives_a_joiner_a_full_budget_at_once(variant):
    eng = table(variant("spotlight"))
    eng.spawn_entity("wolf", "Wolf")
    eng.join_encounter("wolf")
    assert enc(eng)["budgets"]["wolf"] == {"points": 2}
    eng.commit_action("wolf", "recall", gm={"difficulty": "easy"})
    replays(eng)


def test_handoff_can_hand_the_turn_to_a_joiner(variant):
    eng = table(variant("handoff"))
    eng.spawn_entity("wolf", "Wolf")
    eng.join_encounter("wolf")
    eng.end_turn(next="wolf")
    assert enc(eng)["current"] == "wolf"
    replays(eng)


@pytest.mark.parametrize("call, fragment", [
    (lambda e: e.join_encounter("ash"), "already taking part"),
    (lambda e: e.join_encounter("nobody"), "No entity 'nobody'"),
    (lambda e: e.join_encounter("wolf", after="ash"), "after applies to fixed order"),
    (lambda e: e.join_encounter("wolf", by="ash"), "only the GM"),
    (lambda e: e.leave_encounter("wolf", "defeated"), "No participant 'wolf'"),
    (lambda e: e.leave_encounter("foe", "bored"), "No reason 'bored'"),
    (lambda e: e.leave_encounter("foe", "fled", by="bram"), "only the GM"),
])
def test_roster_changes_are_checked_and_atomic(variant, call, fragment):
    eng = table(variant("initiative"))
    eng.spawn_entity("wolf", "Wolf")
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    with pytest.raises(EngineError, match=fragment):
        call(eng)
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before


def test_joining_needs_a_running_encounter_and_a_place_in_the_scene(variant, lantern):
    eng = table(variant("fixed"))
    eng.end_encounter()
    with pytest.raises(EngineError, match="no encounter is running"):
        eng.join_encounter("foe")
    zones = Engine.start_campaign(lantern, SEED, {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    zones.create_character("ash", "Ash", {"background": "soldier"})
    zones.start_session()
    regions = [{"id": "near", "label": "Near", "adjacency": ["far"]}, {"id": "far", "label": "Far", "adjacency": []}]
    zones.set_scene("fight", encounter=True, regions=regions, placements={"ash": "near"})
    zones.start_encounter()
    zones.spawn_entity("wolf", "Wolf")  # in state, not in the scene
    with pytest.raises(EngineError, match="not in the scene: place it first"):
        zones.join_encounter("wolf")
    zones.place_entity("wolf", "far")
    zones.join_encounter("wolf")
    replays(zones)


# ---------------------------------------------------------------- leaving

@pytest.mark.parametrize("name", ["fixed", "initiative", "deck"])
def test_the_current_participant_leaving_passes_the_turn(variant, name):
    eng = table(variant(name))
    order = list(enc(eng)["sequence"])
    leaver, nxt = order[0], order[1]
    eng.leave_encounter(leaver, "defeated")
    assert enc(eng)["current"] == nxt and leaver not in enc(eng)["participants"]
    assert leaver not in enc(eng)["budgets"]
    with pytest.raises(EngineError, match="not taking part"):
        eng.commit_action(leaver, "recall", gm={"difficulty": "easy"})
    seen = turns_over(eng, 4)
    assert leaver not in seen
    replays(eng)


def test_the_last_in_a_round_leaving_starts_the_next_round(variant):
    eng = table(variant("fixed"), participants=["ash", "bram", "foe"])
    eng.end_turn()
    eng.end_turn()  # foe's turn, last of round 1
    eng.leave_encounter("foe", "fled")
    assert enc(eng)["round"] == 2 and enc(eng)["current"] == "ash"
    replays(eng)


def test_someone_leaving_before_the_current_turn_keeps_it(variant):
    eng = table(variant("fixed"), participants=["ash", "bram", "foe"])
    eng.end_turn()  # bram's turn
    eng.leave_encounter("ash", "removed")
    assert enc(eng)["current"] == "bram" and enc(eng)["sequence"] == ["bram", "foe"]
    assert turns_over(eng, 3) == ["bram", "foe", "bram"]
    replays(eng)


def test_a_side_with_nobody_left_is_skipped(variant):
    eng = table(variant("sides"))
    assert enc(eng)["current"] == "players"
    eng.end_turn()  # the GM's side
    eng.leave_encounter("foe", "defeated")  # its last member: the turn passes
    assert enc(eng)["current"] == "players" and enc(eng)["round"] == 2
    eng.end_turn()  # the GM's side is empty, so the players go again
    assert enc(eng)["current"] == "players" and enc(eng)["round"] == 3
    replays(eng)


def test_under_handoff_the_gm_names_who_goes_after_a_leaver(variant):
    eng = table(variant("handoff"))
    current = enc(eng)["current"]
    eng.leave_encounter(current, "fled")
    assert enc(eng)["current"] is None and eng.current_turn()["actor"] is None
    with pytest.raises(EngineError, match="only its controller or the GM"):
        eng.end_turn(by="ash", next="bram")
    rest = [e for e in enc(eng)["participants"]]
    eng.end_turn(next=rest[0])
    assert enc(eng)["current"] == rest[0]
    replays(eng)


def test_an_empty_encounter_waits_for_the_gm(variant):
    eng = table(variant("fixed"), participants=["foe"])
    eng.leave_encounter("foe", "defeated")
    assert enc(eng)["participants"] == [] and enc(eng)["current"] is None
    with pytest.raises(EngineError, match="nobody is left in the encounter"):
        eng.end_turn()
    eng.join_encounter("foe")  # a leaver can come back
    eng.end_turn()
    assert enc(eng)["current"] == "foe"
    eng.end_encounter()
    replays(eng)


# ---------------------------------------------------------------- the GM's tools and the log

def test_the_gm_has_the_roster_tools_and_players_do_not(variant):
    fixed = generate(variant("fixed"), expand({}), "gm")
    assert fixed["join_encounter"] == {"entity_id": fixed["join_encounter"]["entity_id"],
                                       "after": fixed["join_encounter"]["after"]}
    assert fixed["leave_encounter"]["reason"] == {"enum": ["defeated", "fled", "removed"]}
    assert "after" not in generate(variant("initiative"), expand({}), "gm")["join_encounter"]
    players = generate(variant("fixed"), expand({}), "players")
    assert "join_encounter" not in players and "leave_encounter" not in players


def test_roster_changes_are_logged_gm_judgements(variant):
    eng = table(variant("fixed"))
    eng.spawn_entity("wolf", "Wolf")
    eng.join_encounter("wolf")
    eng.leave_encounter("wolf", "fled")
    judged = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "judgement_input"]
    assert {"control": "join_encounter", "choice": {"entity_id": "wolf"}}.items() <= judged[-2].items()
    assert {"control": "leave_encounter", "choice": {"entity_id": "wolf", "reason": "fled"},
            "options": ["defeated", "fled", "removed"]}.items() <= judged[-1].items()
    left = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "participant_left"][-1]
    assert left["reason"] == "fled" and left["entity"] == "wolf"


def test_a_snapshot_resume_keeps_the_roster(variant):
    eng = table(variant("initiative"))
    eng.spawn_entity("wolf", "Wolf")
    eng.join_encounter("wolf")
    eng.leave_encounter("foe", "defeated")
    eng.snapshot()
    eng.end_turn()
    again = Engine.load(eng.pack, SEED, eng.store, eng.campaign_id, clock=lambda: None)
    assert again.state_hash() == eng.state_hash()
    assert again.state["encounter"]["participants"] == eng.state["encounter"]["participants"]

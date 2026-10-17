"""Encounter turn order and action economy (T0.6; ARCHITECTURE §2.4)."""

import shutil

import pytest
import yaml

from basilisk.harness.scripted import verify
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import generate

SEED = "turns-seed"
_PACKS: dict = {}


@pytest.fixture
def variant(packs_dir, tmp_path_factory):
    """Lanternlight with a different `turn_structure` (and optional action edits)."""
    def make(structure: dict, actions: dict | None = None):
        key = repr((structure, actions))
        if key not in _PACKS:
            dst = tmp_path_factory.mktemp("turns") / "packs"
            shutil.copytree(packs_dir, dst)
            path = dst / "lanternlight" / "pack.yaml"
            data = yaml.safe_load(path.read_text())
            data["turn_structure"] = {"encounter": structure}
            for action in data["actions"]:
                action.pop("slot", None)
                action.update((actions or {}).get(action["id"], {}))
            path.write_text(yaml.safe_dump(data, sort_keys=False))
            _PACKS[key] = resolve("lanternlight", dst)
        return _PACKS[key]
    return make


def table(pack):
    eng = Engine.start_campaign(pack, SEED, {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("fight", encounter=True)
    return eng


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


def actors_over(eng, turns):
    seen = [eng.current_turn()["actor"]]
    for _ in range(turns - 1):
        seen.append(eng.end_turn()["actor"])
    return seen


# ---------------------------------------------------------------- orders

def test_initiative_rolls_once_and_cycles(lantern):
    eng = table(lantern)  # Lanternlight: initiative 1d20 + grace, slots
    first = eng.start_encounter()
    rolls = {e["payload"]["purpose"]: e["payload"]["total"] for e in eng.store.read(eng.campaign_id)
             if e["type"] == "roll_made" and e["payload"]["purpose"].startswith("initiative:")}
    totals = {k.split(":")[1]: v for k, v in rolls.items()}
    expected = sorted(totals, key=lambda e: (-totals[e], e))
    assert eng.state["encounter"]["sequence"] == expected and first["actor"] == expected[0]
    assert actors_over(eng, 7) == expected * 2 + expected[:1]
    assert eng.current_turn()["round"] == 3
    assert len(rolls) == 3 and len([e for e in eng.store.read(eng.campaign_id) if e["type"] == "roll_made"
                                    and e["payload"]["purpose"].startswith("initiative:")]) == 3  # rolled once


def test_initiative_can_reroll_each_round(variant):
    pack = variant({"order": "initiative", "initiative": {"roll": "1d20 + {grace}", "each_round": True},
                    "economy": "none"})
    eng = table(pack)
    eng.start_encounter()
    actors_over(eng, 4)  # into round 2
    purposes = [e["payload"]["purpose"] for e in eng.store.read(eng.campaign_id) if e["type"] == "roll_made"]
    assert len([p for p in purposes if p.startswith("initiative:")]) == 6


def test_fixed_keeps_the_given_order(variant):
    eng = table(variant({"order": "fixed", "economy": "none"}))
    eng.start_encounter(["foe", "bram", "ash"])
    assert actors_over(eng, 6) == ["foe", "bram", "ash"] * 2
    assert eng.current_turn()["up_next"] == "foe"


def test_sides_alternate_and_any_member_acts(variant):
    eng = table(variant({"order": "sides", "first": "gm", "economy": "none"}))
    info = eng.start_encounter()
    assert info["actor"] == "gm" and info["kind"] == "side" and info["seats"] == ["gm"]
    with pytest.raises(EngineError, match="it is gm's turn"):
        eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    info = eng.end_turn()
    assert info["actor"] == "players" and info["seats"] == ["ash", "bram"]
    eng.commit_action("bram", "recall", gm={"difficulty": "easy"})
    eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    assert eng.end_turn()["actor"] == "gm" and eng.current_turn()["round"] == 2


def test_handoff_passes_to_someone_who_has_not_gone(variant):
    eng = table(variant({"order": "handoff", "economy": "none"}))
    eng.start_encounter(first="bram")
    with pytest.raises(EngineError, match="name who goes next"):
        eng.end_turn()
    with pytest.raises(EngineError, match="No next participant 'bram'"):
        eng.end_turn(next="bram")  # already went
    assert eng.end_turn(by="bram", next="foe")["actor"] == "foe"
    assert eng.end_turn(next="ash")["actor"] == "ash"
    info = eng.end_turn(by="ash", next="foe")  # the last of the round opens the next, anyone but itself
    assert info["actor"] == "foe" and info["round"] == 2
    picks = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "judgement_input"
             and e["payload"]["control"] == "turn_handoff"]
    assert [p["choice"] for p in picks] == ["bram", "foe", "ash", "foe"]
    assert picks[1]["options"] == ["ash", "foe"] and picks[3]["options"] == ["bram", "foe"]


def test_deck_reshuffles_every_round_from_the_seed(variant, packs_dir):
    pack = variant({"order": "deck", "economy": "none"})
    eng = table(pack)
    eng.start_encounter()
    first = list(eng.state["encounter"]["sequence"])
    assert sorted(first) == ["ash", "bram", "foe"]
    actors_over(eng, 4)
    draws = [e for e in eng.store.read(eng.campaign_id) if e["type"] == "roll_made"
             and e["payload"]["purpose"].startswith("turn_deck:")]
    assert len(draws) == 6 and {d["payload"]["purpose"] for d in draws} == {"turn_deck:round1", "turn_deck:round2"}
    assert verify(eng.store, eng.campaign_id, pack, SEED) == []  # every draw re-derives from the seed
    again = table(pack)
    again.start_encounter()
    assert again.state["encounter"]["sequence"] == first  # same seed, same deck


def test_spotlight_has_no_turns(tide):
    eng = Engine.start_campaign(tide, SEED, {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.start_session()
    eng.set_scene("storm", encounter=True, flags={"danger": 1})
    info = eng.start_encounter()
    assert info["actor"] is None and info["seats"] == []
    with pytest.raises(EngineError, match="no turns"):
        eng.end_turn()
    eng.commit_action("ash", "defy_danger")
    assert eng.next_round()["round"] == 2


# ---------------------------------------------------------------- economy

def test_out_of_turn_actions_are_refused_atomically(lantern):
    eng = table(lantern)
    info = eng.start_encounter()
    idle = next(e for e in ("ash", "bram") if e != info["actor"])
    before = frozen(eng)
    with pytest.raises(EngineError, match="only reactions are allowed out of turn"):
        eng.commit_action(idle, "recall", gm={"difficulty": "easy"})
    assert frozen(eng) == before
    assert eng.available_actions(idle) == []


def test_slots_limit_each_turn_and_refresh_on_the_next(lantern):
    eng = table(lantern)
    eng.start_encounter(["ash", "foe"])
    while eng.current_turn()["actor"] != "ash":
        eng.end_turn()
    eng.commit_action("ash", "climb", target="ledge", gm={"difficulty": "easy"})
    assert eng.current_turn()["budgets"]["ash"] == {"action": 0, "minor": 1}
    assert "climb" not in eng.available_actions("ash") and "recall" in eng.available_actions("ash")
    before = frozen(eng)
    with pytest.raises(EngineError, match="0 action left"):
        eng.commit_action("ash", "climb", target="ledge", gm={"difficulty": "easy"})
    assert frozen(eng) == before
    eng.commit_action("ash", "recall", gm={"difficulty": "easy"})  # the minor slot
    eng.end_turn()
    eng.end_turn()
    assert eng.current_turn()["budgets"]["ash"] == {"action": 1, "minor": 1}


def test_points_budget(variant):
    pack = variant({"order": "fixed", "economy": "points", "points": 3},
                   {"climb": {"points": 2}, "recall": {"points": 1}})
    eng = table(pack)
    eng.start_encounter(["ash", "bram"])
    eng.commit_action("ash", "climb", target="ledge", gm={"difficulty": "easy"})
    with pytest.raises(EngineError, match="1 points left"):
        eng.commit_action("ash", "climb", target="ledge", gm={"difficulty": "easy"})
    eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    spent = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "economy_spent"]
    assert [(p["amount"], p["remaining"]) for p in spent] == [(2, 1), (1, 0)]


def test_reactions_spend_from_the_budget_the_next_turn_restores(variant):
    pack = variant({"order": "fixed", "economy": "slots", "slots": [{"id": "act", "count": 1}, {"id": "react", "count": 1}]},
                   {"recall": {"trigger": "reaction", "slot": "react"}})
    eng = table(pack)
    eng.start_encounter(["ash", "bram"])
    eng.end_turn()  # bram's turn; ash's budget stays from its own turn
    eng.commit_action("ash", "recall", gm={"difficulty": "easy"})  # off-turn reaction
    with pytest.raises(EngineError, match="0 react left"):
        eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    eng.end_turn()
    assert eng.current_turn()["budgets"]["ash"]["react"] == 1


# ---------------------------------------------------------------- lifecycle

def test_encounters_need_an_encounter_scene_and_the_gm(lantern):
    eng = table(lantern)
    with pytest.raises(EngineError, match="only the GM"):
        eng.start_encounter(by="ash")
    eng.set_scene("calm")
    with pytest.raises(EngineError, match="not an encounter scene"):
        eng.start_encounter()
    eng.set_scene("fight2", encounter=True)
    eng.start_encounter(["ash"])
    with pytest.raises(EngineError, match="already running"):
        eng.start_encounter()
    with pytest.raises(EngineError, match="not taking part"):
        eng.commit_action("bram", "recall", gm={"difficulty": "easy"})
    eng.end_encounter()
    with pytest.raises(EngineError, match="first applies to handoff"):
        eng.start_encounter(first="ash")


def test_encounters_end_at_scene_and_session_boundaries(lantern):
    eng = table(lantern)
    eng.start_encounter()
    eng.set_scene("after")
    assert "encounter" not in eng.state
    eng.set_scene("fight2", encounter=True)
    eng.start_encounter()
    eng.end_session()
    ended = [e for e in eng.store.read(eng.campaign_id) if e["type"] == "encounter_ended"]
    assert len(ended) == 2 and eng.current_turn() is None


def test_replay_and_older_logs(lantern):
    eng = table(lantern)
    assert "encounter" not in eng.state  # nothing changes until an encounter starts: no kernel bump
    eng.start_encounter()
    actor = eng.current_turn()["actor"]
    if actor in ("ash", "bram"):
        eng.commit_action(actor, "recall", gm={"difficulty": "easy"})
    actors_over(eng, 4)
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


# ---------------------------------------------------------------- packs and tools

@pytest.mark.parametrize("structure, fragment", [
    ({"order": "queue", "economy": "none"}, "No turn order 'queue'"),
    ({"order": "fixed", "economy": "coins"}, "No action economy 'coins'"),
    ({"order": "initiative", "economy": "none"}, "needs initiative.roll"),
    ({"order": "initiative", "initiative": {"roll": "1d20 + {speed}"}, "economy": "none"}, "No stat 'speed'"),
    ({"order": "fixed", "economy": "slots"}, "needs slots"),
    ({"order": "fixed", "economy": "points"}, "needs points"),
    ({"order": "sides", "first": "both", "economy": "none"}, "sides.first"),
])
def test_bad_turn_structures_fail_lint(variant, structure, fragment):
    found = [f.message for f in errors(lint(variant(structure))) if f.code == "turn-structure"]
    assert any(fragment in m for m in found), found


def test_unknown_slot_on_an_action_fails_lint(variant):
    pack = variant({"order": "fixed", "economy": "slots", "slots": [{"id": "act", "count": 1}]}, {"recall": {"slot": "minor"}})
    assert any("No slot 'minor'" in f.message for f in errors(lint(pack)))


def test_turn_tools_follow_the_order(lantern, tide, variant):
    eff = table(lantern).state["determinism"]["effective"]
    lgm, lpl = generate(lantern, eff, "gm"), generate(lantern, eff, "players")
    assert lpl["end_turn"] == {} and "start_encounter" not in lpl and "next_round" not in lgm
    assert {"start_encounter", "end_encounter", "end_turn"} <= set(lgm)
    tgm, tpl = generate(tide, eff, "gm"), generate(tide, eff, "players")
    assert "end_turn" not in tpl and "next_round" in tgm
    handoff = variant({"order": "handoff", "economy": "none"})
    hpl, hgm = generate(handoff, eff, "players"), generate(handoff, eff, "gm")
    assert hpl["end_turn"] == {"next": {"type": "string", "format": "id"}} and "first" in hgm["start_encounter"]

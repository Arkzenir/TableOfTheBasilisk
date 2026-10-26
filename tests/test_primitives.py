"""Every effect primitive, triggered procedures, and the last toggle and schema lines
(T0.23; ARCHITECTURE §2.6, §2.13.3; BUILD_PLAN P0.4, P0.5)."""

import shutil
import textwrap

import pytest
import yaml

from basilisk.kernel import hooks
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.determinism import expand
from basilisk.kernel.effects import PRIMITIVES, RESERVED
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import generate

IDS = {"actor": "ash", "target": "foe", "self": "ash"}


def lantern_table(pack, seed="prim-seed", determinism=None):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player", "bram": "player"},
                                             "determinism": determinism or {}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.spawn_entity("foe", "Foe")
    eng.create_clock("dread", "Dread", 4)
    eng.start_session()
    eng.set_scene("hall", encounter=True, regions=[{"id": "a", "adjacency": ["b"]}, {"id": "b"}],
                  placements={"ash": "a", "foe": "a", "bram": "b"})
    return eng


def replays(eng):
    return hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


# ---------------------------------------------------------------- "every primitive emits events and replays exactly"

EFFECTS = [
    {"primitive": "modify_resource", "target": "target", "resource": "vigor", "amount": -3},
    {"primitive": "set_resource", "target": "target", "resource": "vigor", "value": 5},
    {"primitive": "mark_track", "target": "actor", "track": "fatigue", "amount": 2},
    {"primitive": "clear_track", "target": "actor", "track": "fatigue"},
    {"primitive": "add_condition", "target": "actor", "condition": "shaken"},
    {"primitive": "remove_condition", "target": "actor", "condition": "shaken"},
    {"primitive": "add_tag", "target": "actor", "tag": "marked"},
    {"primitive": "remove_tag", "target": "actor", "tag": "marked"},
    {"primitive": "move", "target": "actor", "to": "b"},
    {"primitive": "create_item", "target": "actor", "item": "lantern"},
    {"primitive": "transfer_item", "from": "actor", "to": "target", "item": "lantern"},
    {"primitive": "destroy_item", "target": "target", "item": "lantern"},
    {"primitive": "advance_clock", "clock": "dread", "amount": 2},
    {"primitive": "earn_currency", "target": "actor", "currency": "luck", "amount": 1},
    {"primitive": "spend_currency", "target": "actor", "currency": "luck", "amount": 1},
    {"primitive": "trigger_procedure", "procedure": "check", "target": "actor", "stat": "might",
     "difficulty": {"ladder": "ladder", "rung": "easy"},
     "outcome_effects": {"pass": [{"primitive": "add_tag", "target": "actor", "tag": "steeled"}],
                         "fail": [{"primitive": "add_tag", "target": "actor", "tag": "shaken_up"}]}},
]


def test_every_primitive_is_covered_here():
    assert not RESERVED
    tested = {e["primitive"] for e in EFFECTS} | {"request_gm_ruling"}  # the ruling is tested below, on Tidewrack
    assert tested == set(PRIMITIVES)


@pytest.mark.parametrize("effect", EFFECTS, ids=[e["primitive"] for e in EFFECTS])
def test_each_primitive_emits_events_and_replays(lantern, effect):
    eng = lantern_table(lantern)
    for earlier in EFFECTS[:EFFECTS.index(effect)]:  # each runs on the state its predecessors leave
        eng._apply_effect(earlier, IDS, None, {})
    before = eng.store.head(eng.campaign_id)[0]
    eng._apply_effect(effect, IDS, None, {})
    new = list(eng.store.read(eng.campaign_id, after=before))
    applied = [e for e in new if e["type"] == "effect_applied" and e["payload"]["primitive"] == effect["primitive"]]
    assert applied, effect["primitive"]
    assert replays(eng)


def test_request_gm_ruling_emits_events_and_replays(tide):
    eng = Engine.start_campaign(tide, "rul", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.start_session()
    eng._apply_effect({"primitive": "request_gm_ruling", "table": "hard_moves"}, {"actor": "ash", "target": None,
                                                                                 "self": "ash"}, None, {})
    assert [e for e in eng.store.read(eng.campaign_id) if e["type"] == "gm_ruling_requested"]
    assert replays(eng)


def test_primitive_effects_are_exact(lantern):
    eng = lantern_table(lantern)
    for effect in EFFECTS[:12]:
        eng._apply_effect(effect, IDS, None, {})
    ash, foe = eng.state["entities"]["ash"], eng.state["entities"]["foe"]
    assert foe["resources"]["vigor"] == 5 and ash["tracks"]["fatigue"] == 0 and ash["zone"] == "b"
    assert ash["inventory"] == [] and foe["inventory"] == [] and "marked" not in ash["tags"]


# ---------------------------------------------------------------- trigger_procedure as pack data

@pytest.fixture(scope="module")
def last_stand(packs_dir, tmp_path_factory):
    """Lanternlight where dropping to 0 Vigor makes you roll Heart: pass and you
    stay up with 1 Vigor, fail and you go down (a triggered procedure)."""
    dst = tmp_path_factory.mktemp("trig") / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["entity_model"]["resources"][0]["on_zero"] = [{
        "primitive": "trigger_procedure", "procedure": "check", "target": "self", "stat": "heart",
        "difficulty": {"ladder": "ladder", "rung": "moderate"},
        "outcome_effects": {"pass": [{"primitive": "set_resource", "target": "actor", "resource": "vigor", "value": 1}],
                            "fail": [{"primitive": "add_condition", "target": "actor", "condition": "down"}]}}]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pack = resolve("lanternlight", dst)
    assert errors(lint(pack)) == [], [str(f) for f in errors(lint(pack))]
    return pack


def test_a_triggered_procedure_rolls_and_applies_its_outcome(last_stand):
    outcomes = set()
    for i in range(30):
        eng = lantern_table(last_stand, f"stand-{i}")
        eng._apply_effect({"primitive": "modify_resource", "target": "target", "resource": "vigor", "amount": -99},
                          IDS, None, {})
        resolved = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "procedure_resolved"]
        assert resolved[-1]["procedure"] == "check" and resolved[-1]["entity"] == "foe"
        assert resolved[-1]["difficulty"] == {"value": 12, "origin": "derived", "rung": None}  # fixed by the pack
        foe = eng.state["entities"]["foe"]
        if resolved[-1]["outcome"] == "pass":
            assert foe["resources"]["vigor"] == 1 and "down" not in foe["conditions"]
        else:
            assert "down" in foe["conditions"]
        outcomes.add(resolved[-1]["outcome"])
        assert not [e for e in eng.store.read(eng.campaign_id) if e["type"] == "judgement_input"
                    and e["payload"]["control"] == "difficulty"]  # no model chose anything
        assert replays(eng)
    assert outcomes == {"pass", "fail"}


@pytest.mark.parametrize("bad, fragment", [
    ({"procedure": "dance"}, "unknown procedure 'dance'"),
    ({"difficulty": None}, "needs a difficulty fixed by the pack"),
    ({"difficulty": {"ladder": "ladder", "rung": "impossible"}}, "unknown ladder rung"),
    ({"outcome_effects": {"triumph": []}}, "outcome 'triumph' is not on check's scale"),
    ({"outcome_effects": {"pass": [{"primitive": "teleport"}]}}, "unknown primitive 'teleport'"),
])
def test_bad_triggered_procedures_fail_lint(packs_dir, tmp_path, bad, fragment):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    effect = {"primitive": "trigger_procedure", "procedure": "check", "target": "self", "stat": "heart",
              "difficulty": {"ladder": "ladder", "rung": "moderate"}, "outcome_effects": {}}
    effect.update(bad)
    if effect["difficulty"] is None:
        del effect["difficulty"]
    data["entity_model"]["resources"][0]["on_zero"] = [effect]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f.message for f in errors(lint(resolve("lanternlight", dst)))]
    assert any(fragment in m for m in found), found


# ---------------------------------------------------------------- the toggle test's mid-encounter case (§2.13.3)

def test_a_change_requested_mid_encounter_waits_for_the_scene_boundary(lantern):
    eng = lantern_table(lantern)  # GM standard
    eng.start_encounter()
    eng.request_determinism_change(by="operator", role="gm", preset="strict")
    while eng.current_turn()["actor"] not in ("ash", "bram"):
        eng.end_turn()
    actor = eng.current_turn()["actor"]
    eng.commit_action(actor, "recall", gm={"difficulty": 13})  # still standard: a free value is allowed
    assert eng.state["determinism"]["pending"] is not None and eng.state.get("encounter")
    eng.set_scene("after", encounter=True)
    kinds = [e["type"] for e in eng.store.read(eng.campaign_id)][-4:]
    assert "encounter_ended" in kinds and "determinism_changed" in kinds
    assert kinds.index("encounter_ended") < kinds.index("determinism_changed")  # the encounter finished first
    with pytest.raises(EngineError, match="rung"):
        eng.commit_action("ash", "recall", gm={"difficulty": 13})
    assert replays(eng)


# ---------------------------------------------------------------- P0.5: only the affected seat's schema changes

@pytest.mark.parametrize("pack_id", ["lanternlight", "tidewrack"])
def test_a_seat_override_changes_only_that_seat(pack_id, packs_dir):
    pack = resolve(pack_id, packs_dir)
    base = expand({})
    override = expand({"seat_overrides": {"ash": {"spend_amounts": "standard"}}})
    has_spends = any("amounts" in (a.get("cost") or {}) for a in pack.catalogue("actions"))
    assert (generate(pack, override, "players", seat="ash") != generate(pack, base, "players", seat="ash")) == has_spends
    assert generate(pack, override, "players", seat="bram") == generate(pack, base, "players", seat="bram")
    assert generate(pack, override, "gm") == generate(pack, base, "gm")


# ---------------------------------------------------------------- hook memory limits (Appendix C)

def _hook(source):
    return {"name": "m", "point": "sheet.validate", "source": textwrap.dedent(source)}


@pytest.mark.parametrize("source, fragment", [
    ("def hook(view, params, rng):\n    x = 'a' * 1000000\n    return []\n", "repeating a sequence"),
    ("def hook(view, params, rng):\n    x = [0]\n    x *= 1000000\n    return []\n", "repeating a sequence"),
    ("def hook(view, params, rng):\n    return list(range(10000000))\n", "range of 10000000 items"),
    ("def hook(view, params, rng):\n    return [list(range(90000)) for i in range(40)]\n", "MB of memory"),
])
def test_hooks_cannot_exhaust_memory(source, fragment):
    assert hooks.check_source("m", source) == []  # each passes the static check: the runtime stops it
    with pytest.raises(hooks.HookError, match=fragment):
        hooks.run(_hook(source), {}, {}, None)


def test_ordinary_multiplication_still_works():
    out, _ = hooks.run(_hook("def hook(view, params, rng):\n    n = 6\n    n *= 7\n    return [n * 2, 'ab' * 3]\n"),
                       {}, {}, None)
    assert out == [84, "ababab"]

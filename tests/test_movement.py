"""Pack movement, provoke, and cover rules (T0.20; ARCHITECTURE §1.4, §2.3; BUILD_PLAN P0.10)."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import generate

LINE = [{"id": "a", "adjacency": ["b"]}, {"id": "b", "adjacency": ["c"], "cover": "partial"},
        {"id": "c", "adjacency": ["d"]}, {"id": "d"}]
_CACHE: dict = {}


@pytest.fixture
def variant(packs_dir, tmp_path_factory):
    def make(pack_id="lanternlight", **spatial):
        key = repr((pack_id, sorted(spatial.items())))
        if key not in _CACHE:
            dst = tmp_path_factory.mktemp("move") / "packs"
            shutil.copytree(packs_dir, dst)
            path = dst / pack_id / "pack.yaml"
            data = yaml.safe_load(path.read_text())
            extra = dict(spatial)
            profile = extra.pop("tactical_profile", None)
            data.setdefault("spatial", {}).update(extra)
            if profile:  # extend the pack's own profile rather than replace it
                own = data["spatial"]["tactical_profile"]
                own["categories"] += profile.get("categories", [])
                own["weights"].update(profile.get("weights", {}))
                own["annotation_templates"] += profile.get("annotation_templates", [])
            if pack_id == "lanternlight":
                data["resolution"]["situational_tags"].append(
                    {"id": "behind_cover", "value": -2, "derive": "target.region.cover.partial == 1"})
                data["presentation"]["rule_cards"]["behind_cover"] = {
                    "title": "Behind cover", "summary": "-2 to hit someone in partial cover.", "category": "tag",
                    "icon_id": "wall"}
            path.write_text(yaml.safe_dump(data, sort_keys=False))
            pack = resolve(pack_id, dst)
            assert errors(lint(pack)) == [], [str(f) for f in errors(lint(pack))]
            _CACHE[key] = pack
        return _CACHE[key]
    return make


def zone_table(pack, seed="move-seed", where=None):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "smuggler"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("line", encounter=True, regions=LINE, placements=where or {"ash": "a", "foe": "a"})
    return eng


def passing_seed(pack, target):
    for i in range(200):
        eng = zone_table(pack, f"s{i}")
        if eng.commit_action("ash", "climb", target=target, gm={"difficulty": "easy"})["outcome"] == "pass":
            return f"s{i}"
    raise AssertionError("no passing seed")


def events(eng, kind):
    return [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


# ---------------------------------------------------------------- movement allowance

def test_one_step_by_default(variant):
    pack = variant(terrain=[{"id": "mire"}], cover=[{"id": "partial"}])
    eng = zone_table(pack)
    assert eng.reachable("ash") == ["b"]


def test_a_pack_can_allow_longer_moves(variant):
    pack = variant(movement={"steps_per_move": 2}, cover=[{"id": "partial"}])
    eng = zone_table(pack)
    assert eng.reachable("ash") == ["b", "c"]
    assert {c["id"] for c in eng.enumerate_moves("ash", 100)} == {"b", "c"}
    seed = passing_seed(pack, "c")
    eng = zone_table(pack, seed)
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    with pytest.raises(EngineError, match="more than 2 steps"):
        eng.commit_action("ash", "climb", target="d", gm={"difficulty": "easy"})
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before
    eng.commit_action("ash", "climb", target="c", gm={"difficulty": "easy"})
    assert eng.state["entities"]["ash"]["zone"] == "c"


def test_bands_honour_the_allowance_too(variant):
    pack = variant("tidewrack", movement={"steps_per_move": 2})
    eng = Engine.start_campaign(pack, "b", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("deck", participants=["ash", "foe"])  # far
    assert set(eng.reachable("ash")) == {"near:foe", "close:foe"}


# ---------------------------------------------------------------- provokes

def test_leaving_a_threat_provokes_it(variant):
    pack = variant(provokes={"when": "actor.conditions.down == 0"}, cover=[{"id": "partial"}])
    seed = passing_seed(pack, "b")
    eng = zone_table(pack, seed)
    eng.commit_action("ash", "climb", target="b", gm={"difficulty": "easy"})
    assert events(eng, "move_provoked") == [{"mover": "ash", "by": ["foe"], "to": "b"}]
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()  # passive: replays


def test_the_when_rule_filters_provokers(variant):
    pack = variant(provokes={"when": "actor.conditions.down == 0"}, cover=[{"id": "partial"}])
    seed = passing_seed(pack, "b")
    eng = zone_table(pack, seed)
    eng._apply_effect({"primitive": "add_condition", "target": "foe", "condition": "down"},
                      {"actor": None, "target": None, "self": None}, None, {})  # a downed foe cannot react
    eng.commit_action("ash", "climb", target="b", gm={"difficulty": "easy"})
    assert events(eng, "move_provoked") == []


def test_no_provokes_without_the_rule(variant):
    pack = variant(cover=[{"id": "partial"}])
    seed = passing_seed(pack, "b")
    eng = zone_table(pack, seed)
    eng.commit_action("ash", "climb", target="b", gm={"difficulty": "easy"})
    assert events(eng, "move_provoked") == []


def test_backing_out_of_the_closest_band_provokes(variant):
    pack = variant("tidewrack", provokes={})
    eng = Engine.start_campaign(pack, "b", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("deck", participants=["ash", "foe"], ranges=[{"between": ["ash", "foe"], "band": "close"}])
    assert eng._provokers("ash", "near:foe") == ["foe"]
    assert eng._provokers("ash", "close:foe") == []


def test_candidates_see_provokes_only_from_visible_threats(variant):
    pack = variant(provokes={}, cover=[{"id": "partial"}], tactical_profile={
        "categories": [{"id": "provoking", "order": 1}], "weights": {"provokes": -5},
        "annotation_templates": [{"id": "prov", "applies_to": "move", "category": "provoking",
                                  "when": "provokes > 0", "text": "provokes {provokers}"}]})
    eng = zone_table(pack)
    [move] = eng.enumerate_moves("ash", 100)
    assert move["annotations"] == [{"category": "provoking", "text": "provokes foe"}]
    eng.set_visibility("foe", [])
    assert eng.enumerate_moves("ash", 100)[0]["annotations"] == []  # a hidden threat is never hinted at


# ---------------------------------------------------------------- cover in expressions

def test_derived_tags_can_read_cover(variant):
    pack = variant(cover=[{"id": "partial"}])
    eng = zone_table(pack, where={"ash": "a", "foe": "b"})
    eng.commit_action("ash", "strike", target="foe")
    proc = events(eng, "procedure_resolved")[-1]
    assert {"source": "behind_cover", "kind": "tag", "value": -2, "origin": "auto"} in proc["modifiers"]
    eng2 = zone_table(pack, where={"ash": "a", "foe": "a"})
    eng2.commit_action("ash", "strike", target="foe")
    assert all(m["source"] != "behind_cover" for m in events(eng2, "procedure_resolved")[-1]["modifiers"])


@pytest.mark.parametrize("spatial, fragment", [
    ({"movement": {"steps_per_move": 0}}, "steps_per_move must be"),
    ({"provokes": {"when": "import os"}}, "provokes.when"),
])
def test_bad_movement_rules_fail_lint(packs_dir, tmp_path, spatial, fragment):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["spatial"].update(spatial)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert any(fragment in f.message for f in errors(lint(resolve("lanternlight", dst))))

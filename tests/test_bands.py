"""RangeBands (T0.5; ARCHITECTURE §1.4, §8.2): relative bands between entities."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import free_values, generate

PEOPLE = ["ash", "bram", "foe", "imp"]


def table(pack, seed="test-seed"):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    choice = {s["id"]: s["options"][0]["id"] for s in pack.get("chargen.steps") or [] if s["kind"] == "choice"}
    eng.create_character("ash", "Ash", choice)
    other = dict(choice)
    for s in pack.get("chargen.steps") or []:
        if s["kind"] == "choice" and s.get("unique_per_table"):
            other[s["id"]] = s["options"][1]["id"]
    eng.create_character("bram", "Bram", other)
    eng.spawn_entity("foe", "Foe")
    eng.spawn_entity("imp", "Imp")
    eng.start_session()
    return eng


def banded(pack, seed="test-seed", ranges=(("ash", "foe", "near"),)):
    eng = table(pack, seed)
    eng.set_scene("deck", encounter=True, participants=PEOPLE,
                  ranges=[{"between": [a, b], "band": band} for a, b, band in ranges])
    return eng


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


@pytest.fixture(scope="module")
def lantern_bands(packs_dir, tmp_path_factory):
    """Lanternlight, unchanged except that it permits range_bands instead of
    zone_graph: the same pack data runs under the other backend."""
    dst = tmp_path_factory.mktemp("bands") / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["spatial"]["backends"] = ["range_bands"]
    data["spatial"]["bands"] = [{"id": "close", "label": "Close"}, {"id": "near", "label": "Near"},
                                {"id": "far", "label": "Far"}]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pack = resolve("lanternlight", dst)
    assert errors(lint(pack)) == []
    return pack


# ---------------------------------------------------------------- scene layout

def test_every_pair_has_a_band_and_unset_pairs_start_far(tide):
    eng = banded(tide)
    sp = eng.state["scene"]["spatial"]
    assert sp["mode"] == "bands" and sp["bands"] == ["close", "near", "far"]  # from the pack, closest first
    assert sp["participants"] == sorted(PEOPLE)
    assert len(sp["ranges"]) == 6 and sp["ranges"]["ash|foe"] == "near"
    assert {band for key, band in sp["ranges"].items() if key != "ash|foe"} == {"far"}
    assert eng.distance("ash", "foe") == 1 and eng.distance("ash", "imp") == 2


@pytest.mark.parametrize("kwargs, message", [
    ({"participants": []}, "non-empty"),
    ({"participants": ["ash", "ghost"]}, "No entity 'ghost'"),
    ({"participants": ["ash", "ash"]}, "twice"),
    ({"participants": PEOPLE, "ranges": [{"between": ["ash", "ash"], "band": "near"}]}, "between"),
    ({"participants": PEOPLE, "ranges": [{"between": ["ash", "foe"], "band": "touching"}]}, "No band 'touching'"),
    ({"participants": ["ash", "bram"], "ranges": [{"between": ["ash", "foe"], "band": "near"}]}, "No participant 'foe'"),
    ({"ranges": [{"between": ["ash", "foe"], "band": "near"}]}, "ranges need participants"),
    ({"participants": PEOPLE, "placements": {"ash": "near"}}, "placements need regions"),
    ({"participants": PEOPLE, "regions": [{"id": "a"}]}, "not both"),
    ({"regions": [{"id": "a"}]}, "does not permit zone_graph"),
])
def test_bad_band_scenes_are_refused_atomically(tide, kwargs, message):
    eng = table(tide)
    before = frozen(eng)
    with pytest.raises(EngineError, match=message):
        eng.set_scene("bad", **kwargs)
    assert frozen(eng) == before


def test_a_pack_must_declare_its_bands(packs_dir, tmp_path):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "tidewrack" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["spatial"]["bands"] = [{"id": "close", "label": "Close"}]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f.message for f in errors(lint(resolve("tidewrack", dst))) if f.code == "spatial"]
    assert any("at least two bands" in m for m in found)


# ---------------------------------------------------------------- moves (§1.4.1)

def passing_seed(pack):
    for i in range(200):
        eng = banded(pack, f"seed-{i}")
        if eng.commit_action("ash", "climb", target="close:foe", gm={"difficulty": "easy"})["outcome"] == "pass":
            return f"seed-{i}"
    raise AssertionError("no passing seed in range")


def test_moves_shift_one_band_and_illegal_ones_leave_no_trace(lantern_bands):
    seed = passing_seed(lantern_bands)
    eng = banded(lantern_bands, seed, ranges=(("ash", "foe", "far"),))
    before = frozen(eng)
    with pytest.raises(EngineError, match="more than one band"):  # far -> close skips near
        eng.commit_action("ash", "climb", target="close:foe", gm={"difficulty": "easy"})
    assert frozen(eng) == before
    with pytest.raises(EngineError, match="No position 'close:ghost'"):
        eng.commit_action("ash", "climb", target="close:ghost", gm={"difficulty": "easy"})
    eng.place_entity("ash", "near:foe")  # same roll counter as the probe: this climb passes
    eng.commit_action("ash", "climb", target="close:foe", gm={"difficulty": "easy"})
    sp = eng.state["scene"]["spatial"]
    assert sp["ranges"]["ash|foe"] == "close" and sp["ranges"]["ash|imp"] == "far"  # only that pair moved
    assert "near:foe" in eng.reachable("ash") and "close:foe" not in eng.reachable("ash")


def test_moves_are_never_measured_from_hidden_entities(lantern_bands):
    eng = banded(lantern_bands)
    eng.set_visibility("foe", ["bram"])
    assert not any(p.endswith(":foe") for p in eng.reachable("ash"))
    assert any(p.endswith(":foe") for p in eng.reachable("bram"))
    with pytest.raises(EngineError, match="No position 'close:foe'"):
        eng.commit_action("ash", "climb", target="close:foe", gm={"difficulty": "easy"})


def test_outsiders_cannot_move_and_newcomers_join_far(lantern_bands):
    eng = table(lantern_bands)
    eng.set_scene("deck", participants=["ash", "foe"])
    with pytest.raises(EngineError, match="not placed in this scene"):
        eng._check_move("bram", "near:foe")  # the move effect's own check, without a roll
    eng.place_entity("bram", "near:ash")
    sp = eng.state["scene"]["spatial"]
    assert sp["participants"] == ["ash", "bram", "foe"]
    assert sp["ranges"]["ash|bram"] == "near" and sp["ranges"]["bram|foe"] == "far"
    eng.spawn_entity("gull", "Gull", zone="close:foe")
    assert eng.state["entities"]["gull"]["zone"] is None  # bands are relative: no zone label
    assert eng.state["scene"]["spatial"]["ranges"]["foe|gull"] == "close"
    with pytest.raises(EngineError, match="not from yourself"):
        eng.place_entity("ash", "near:ash")


# ---------------------------------------------------------------- views and candidates

def test_scene_view_shows_only_visible_pairs(tide):
    eng = banded(tide)
    eng.set_visibility("foe", ["bram"])
    ash, bram = eng.scene_view("ash"), eng.scene_view("bram")
    assert ash["mode"] == "bands" and "regions" not in ash and ash["bands"] == ["close", "near", "far"]
    assert [t["entity_id"] for t in ash["tokens"]] == ["ash", "bram", "imp"]
    assert all("foe" not in r["between"] for r in ash["ranges"])
    assert {"between": ["ash", "foe"], "band": "near"} in bram["ranges"]


def test_candidates_use_the_same_surface(tide):
    eng = banded(tide)
    moves = eng.enumerate_moves("ash", 100)
    assert moves[0]["id"] == "close:foe" and moves[0]["label"] == "close Foe"
    assert set(moves[0]) == {"id", "position_id", "label", "annotations"}
    assert {c["action_id"] for c in eng.enumerate_action_candidates("ash", 100)} <= set(eng.available_actions("ash"))


def test_tool_surface_matches_zone_packs(lantern, tide):
    def tools(pack):
        eff = table(pack).state["determinism"]["effective"]
        return generate(pack, eff, "gm"), generate(pack, eff, "players")
    (lgm, lpl), (tgm, tpl) = tools(lantern), tools(tide)
    tactical = {"look", "enumerate_moves", "enumerate_actions", "preview"}
    assert tactical <= set(lpl) and tactical <= set(tpl)
    assert {"place_entity", "set_visibility"} <= set(lgm) & set(tgm)
    assert lgm["place_entity"] == tgm["place_entity"]
    assert set(tgm["set_scene"]) == {"scene_id", "participants", "ranges"}
    assert tgm["set_scene"]["ranges"]["items"]["band"] == {"enum": ["close", "far", "near"]}
    assert not free_values(tgm["set_scene"])


def test_replay_is_byte_identical(lantern_bands):
    eng = banded(lantern_bands)
    eng.set_visibility("foe", ["bram"])
    eng.place_entity("imp", "close:bram")
    eng.commit_action("ash", "climb", target="near:bram", gm={"difficulty": "easy"})
    eng.set_scene("after")
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()

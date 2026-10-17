"""ZoneGraph and per-observer visibility (T0.3; ARCHITECTURE §1.4, §8.2)."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import free_values, generate

REGIONS = [
    {"id": "stair", "label": "Stair", "adjacency": ["floor"]},
    {"id": "floor", "label": "Floor", "adjacency": ["gallery", "vault"]},
    {"id": "gallery", "label": "Gallery"},
    {"id": "vault", "label": "Vault"},
]


def campaign(pack, seed="test-seed"):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    return eng


def zoned(pack, seed="test-seed"):
    eng = campaign(pack, seed)
    eng.set_scene("undercroft", regions=REGIONS, placements={"ash": "floor", "bram": "stair", "foe": "vault"})
    return eng


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


def passing_seed(pack):
    """A seed whose next climb roll passes, so the move effect actually runs.
    Rejected commands roll back the roll counter, so the same roll is replayed."""
    for i in range(200):
        eng = zoned(pack, f"seed-{i}")
        probe = eng.commit_action("ash", "climb", target="gallery", gm={"difficulty": "easy"})
        if probe["outcome"] == "pass":
            return f"seed-{i}"
    raise AssertionError("no passing seed in range")


# ---------------------------------------------------------------- scene schema (§8.2)

def test_regions_are_normalised_into_the_scene(lantern):
    eng = zoned(lantern)
    sp = eng.state["scene"]["spatial"]
    assert sp["mode"] == "zone"
    by_id = {r["id"]: r for r in sp["regions"]}
    assert [r["id"] for r in sp["regions"]] == sorted(by_id)
    assert by_id["floor"]["adjacency"] == ["gallery", "stair", "vault"]  # undirected, sorted
    assert by_id["vault"]["adjacency"] == ["floor"]
    assert by_id["gallery"] == {"id": "gallery", "label": "Gallery", "adjacency": ["floor"],
                                "terrain": None, "elevation": 0, "cover": None}
    assert eng.state["entities"]["foe"]["zone"] == "vault"
    assert eng.distance("stair", "vault") == 2 and eng.reachable("ash") == ["gallery", "stair", "vault"]


@pytest.mark.parametrize("regions, message", [
    ([], "non-empty"),
    ([{"id": "a", "adjacency": ["b"]}], "region adjacent to a"),
    ([{"id": "a", "adjacency": ["a"]}], "itself"),
    ([{"id": "a"}, {"id": "a"}], "twice"),
    ([{"id": "Bad Id"}], "lowercase"),
    ([{"id": "a", "colour": "red"}], "unknown region field"),
    ([{"id": "a", "terrain": "mire"}], "terrain for region a"),
    ([{"id": "a", "elevation": "high"}], "elevation"),
])
def test_bad_regions_are_refused_atomically(lantern, regions, message):
    eng = campaign(lantern)
    before = frozen(eng)
    with pytest.raises(EngineError, match=message):
        eng.set_scene("bad", regions=regions)
    assert frozen(eng) == before


def test_placements_need_regions_and_known_ids(lantern):
    eng = campaign(lantern)
    with pytest.raises(EngineError, match="placements need regions"):
        eng.set_scene("plain", placements={"ash": "floor"})
    with pytest.raises(EngineError, match="No region 'attic'"):
        eng.set_scene("z", regions=REGIONS, placements={"ash": "attic"})
    with pytest.raises(EngineError, match="No entity 'ghost'"):
        eng.set_scene("z", regions=REGIONS, placements={"ghost": "floor"})


def test_pack_terrain_values_are_enforced(packs_dir, tmp_path):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["spatial"].update({"backends": ["zone_graph"], "terrain": [{"id": "mire"}], "cover": [{"id": "partial"}]})
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pack = resolve("lanternlight", dst)
    assert errors(lint(pack)) == []
    eng = campaign(pack)
    eng.set_scene("bog", regions=[{"id": "a", "terrain": "mire", "cover": "partial", "elevation": -1}])
    assert eng.state["scene"]["spatial"]["regions"][0]["terrain"] == "mire"
    gm = generate(pack, eng.state["determinism"]["effective"], "gm")
    assert gm["set_scene"]["regions"]["items"]["terrain"] == {"enum": ["mire"]}
    assert not free_values(gm["set_scene"])  # elevation, a free number, is not offered to models


# ---------------------------------------------------------------- moves (§1.4.1)

def test_moves_follow_adjacency_and_illegal_moves_leave_no_trace(lantern):
    seed = passing_seed(lantern)
    eng = zoned(lantern, seed)
    before = frozen(eng)
    with pytest.raises(EngineError, match="No region 'attic'"):
        eng.commit_action("ash", "climb", target="attic", gm={"difficulty": "easy"})
    assert frozen(eng) == before
    eng.place_entity("ash", "stair")  # same roll counter as the probe: this climb would pass
    before = frozen(eng)
    with pytest.raises(EngineError, match="gallery is not adjacent to stair"):
        eng.commit_action("ash", "climb", target="gallery", gm={"difficulty": "easy"})
    assert frozen(eng) == before
    eng.place_entity("ash", "floor")
    eng.commit_action("ash", "climb", target="gallery", gm={"difficulty": "easy"})
    assert eng.state["entities"]["ash"]["zone"] == "gallery"


def test_an_entity_outside_the_scene_cannot_move(lantern):
    seed = passing_seed(lantern)
    eng = campaign(lantern, seed)
    eng.set_scene("undercroft", regions=REGIONS)  # nobody placed
    with pytest.raises(EngineError, match="not placed in this scene"):
        eng.commit_action("ash", "climb", target="gallery", gm={"difficulty": "easy"})


def test_scenes_without_regions_keep_plain_zone_labels(lantern):
    eng = campaign(lantern)
    eng.set_scene("one")
    assert "spatial" not in eng.state["scene"]  # older logs fold unchanged: no kernel bump
    eng.commit_action("ash", "climb", target="anywhere", gm={"difficulty": "easy"})
    assert eng.scene_view("ash") == {"scene_id": "one", "mode": None, "regions": [], "tokens": []}


def test_gm_placement_and_spawn_are_checked(lantern):
    eng = zoned(lantern)
    with pytest.raises(EngineError, match="only the GM"):
        eng.place_entity("ash", "vault", by="ash")
    with pytest.raises(EngineError, match="No region"):
        eng.spawn_entity("rat", "Rat", zone="attic")
    eng.spawn_entity("rat", "Rat", zone="gallery")
    assert eng.state["entities"]["rat"]["zone"] == "gallery"


# ---------------------------------------------------------------- visibility (§8.2)

def test_visibility_is_per_observer(lantern):
    eng = zoned(lantern)
    eng.set_visibility("foe", ["bram"])
    tokens = lambda seat: [t["entity_id"] for t in eng.scene_view(seat)["tokens"]]  # noqa: E731
    assert tokens("gm") == ["ash", "bram", "foe"]
    assert tokens("bram") == ["ash", "bram", "foe"]
    assert tokens("ash") == ["ash", "bram"]  # the foe does not exist for Ash
    with pytest.raises(EngineError, match="No entity 'foe'"):
        eng.commit_action("ash", "strike", target="foe")
    eng.set_visibility("foe", None)
    assert tokens("ash") == ["ash", "bram", "foe"]


def test_visibility_resets_each_scene_and_is_gm_only(lantern):
    eng = zoned(lantern)
    with pytest.raises(EngineError, match="only the GM"):
        eng.set_visibility("foe", [], by="ash")
    with pytest.raises(EngineError, match="No seat"):
        eng.set_visibility("foe", ["nobody"])
    eng.set_visibility("foe", [])
    assert not eng.visible("ash", "foe") and not eng.visible("bram", "foe") and eng.visible("gm", "foe")
    assert eng.visible("ash", "ash")  # a seat always sees what it controls
    eng.set_scene("next", regions=REGIONS, placements={"foe": "vault"})
    assert eng.visible("ash", "foe")


# ---------------------------------------------------------------- replay, packs, schemas

def test_replay_is_byte_identical(lantern):
    eng = zoned(lantern)
    eng.set_visibility("foe", ["bram"])
    eng.commit_action("ash", "climb", target="gallery", gm={"difficulty": "easy"})
    eng.set_scene("after")
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_pack_without_spatial_refuses_regions_and_tools(packs_dir, tmp_path):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["spatial"] = "none"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pack = resolve("lanternlight", dst)
    assert errors(lint(pack)) == []
    eng = campaign(pack)
    with pytest.raises(EngineError, match="permitted backends: none"):
        eng.set_scene("z", regions=REGIONS)
    eff = eng.state["determinism"]["effective"]
    gm, players = generate(pack, eff, "gm"), generate(pack, eff, "players")
    assert not {"look", "place_entity", "set_visibility"} & (set(gm) | set(players))
    assert set(gm["set_scene"]) == {"scene_id"}


def test_unknown_backend_fails_lint(packs_dir, tmp_path):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["spatial"]["backends"] = ["hex_map"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f for f in errors(lint(resolve("lanternlight", dst))) if f.code == "spatial"]
    assert found and "available: zone_graph" in found[0].message


def test_spatial_tools_in_schema(lantern, tide):
    for pack in (lantern, tide):
        eff = campaign(lantern).state["determinism"]["effective"]
        gm, players = generate(pack, eff, "gm"), generate(pack, eff, "players")
        assert "look" in players and "look" in gm
        assert {"place_entity", "set_visibility"} <= set(gm)
        assert not {"place_entity", "set_visibility"} & set(players)
        assert not free_values(gm["set_scene"]) and not free_values(gm["set_visibility"])

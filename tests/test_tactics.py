"""Candidate generator and mastery tiering (T0.4; ARCHITECTURE §1.4.2, §1.4.3)."""

import random
import shutil

import pytest
import yaml

from basilisk.kernel import spatial, tactics
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve

SEATS = {"gm": "gm", "ash": "player", "bram": "player"}


def table(pack, seed="t"):
    eng = Engine.start_campaign(pack, seed, {"seats": SEATS}, clock=lambda: None)
    choice = {s["id"]: s["options"][0]["id"] for s in pack.get("chargen.steps") or [] if s["kind"] == "choice"}
    eng.create_character("ash", "Ash", choice)
    other = {k: v for k, v in choice.items()}
    for s in pack.get("chargen.steps") or []:
        if s["kind"] == "choice" and s.get("unique_per_table"):
            other[s["id"]] = s["options"][1]["id"]
    eng.create_character("bram", "Bram", other)
    eng.spawn_entity("foe", "Foe")
    eng.spawn_entity("imp", "Imp")
    eng.start_session()
    return eng


# a - b - d,  a - c - d;  b is high ground
DIAMOND = [{"id": "a", "adjacency": ["b", "c"]}, {"id": "b", "adjacency": ["d"], "elevation": 1},
           {"id": "c", "adjacency": ["d"]}, {"id": "d"}]


def diamond(pack, **placements):
    eng = table(pack)
    where = {"ash": "a", "bram": "b", "foe": "c", "imp": "d", **placements}
    eng.set_scene("x", encounter=True, regions=DIAMOND, placements=where)
    return eng


def banded(pack, ranges=None):
    """A range-band scene: everyone present; Ash close to Bram, near the foe."""
    eng = table(pack)
    pairs = ranges or [(("ash", "bram"), "close"), (("ash", "foe"), "near")]
    eng.set_scene("x", encounter=True, participants=["ash", "bram", "foe", "imp"],
                  ranges=[{"between": list(pair), "band": band} for pair, band in pairs])
    return eng


def scene_for(pack):
    return diamond(pack) if "zone_graph" in spatial.declared_backends(pack) else banded(pack)


def ids(cands):
    return [c["id"] for c in cands]


# ---------------------------------------------------------------- tiers (§1.4.3)

def test_tier_counts_follow_the_kernel_settings():
    counts = [tactics.tier_of(m)[1] for m in range(101)]
    assert counts == sorted(counts) and max(counts) == tactics.CANDIDATE_CAP
    assert {tactics.tier_of(m)[1] for m in range(0, 34)} == {4, 5}
    assert {tactics.tier_of(m)[1] for m in range(34, 67)} == {7, 8}
    assert {tactics.tier_of(m)[1] for m in range(67, 101)} == {10, 11, 12}
    for bad in (-1, 101, "50", True):
        with pytest.raises(EngineError, match="mastery"):
            tactics.tier_of(bad)


def test_lower_tiers_are_strict_information_subsets(lantern):
    eng = diamond(lantern)
    for kind in ("moves", "actions"):
        get = (lambda m: eng.enumerate_moves("ash", m)) if kind == "moves" else \
              (lambda m: eng.enumerate_action_candidates("ash", m))
        outputs = [get(m) for m in range(0, 101, 5)]
        for low, high in zip(outputs, outputs[1:]):
            assert ids(low) == ids(high)[:len(low)], kind
            by_id = {c["id"]: c for c in high}
            for c in low:
                assert all(a in by_id[c["id"]]["annotations"] for a in c["annotations"]), kind
        assert all(not c["annotations"] for c in get(0))  # bare at the lowest tier
    low, mid, high = (eng.enumerate_moves("ash", m) for m in (0, 50, 100))
    info = lambda out: sum(len(c["annotations"]) for c in out)  # noqa: E731
    assert info(low) < info(mid) < info(high)  # strictly more on this state
    order = {c["id"]: c["order"] for c in tactics.profile(lantern)["categories"]}
    assert all(order[a["category"]] == 1 for c in mid for a in c["annotations"])


def test_candidate_cap_holds(lantern):
    eng = table(lantern)
    hub = [{"id": "hub", "adjacency": [f"r{i:02d}" for i in range(20)]}] + [{"id": f"r{i:02d}"} for i in range(20)]
    eng.set_scene("wide", encounter=True, regions=hub, placements={"ash": "hub"})
    for i in range(10):
        eng.spawn_entity(f"npc{i}", f"N{i}", zone=f"r{i:02d}")
    for m in (0, 33, 34, 66, 67, 100):
        _, count = tactics.tier_of(m)
        assert len(eng.enumerate_moves("ash", m)) == count <= tactics.CANDIDATE_CAP
        assert len(eng.enumerate_action_candidates("ash", m)) == count


# ---------------------------------------------------------------- scoring (§1.4.2)

def test_pack_weights_rank_moves(lantern, tide):
    eng = diamond(lantern)
    moves = eng.enumerate_moves("ash", 100)
    assert ids(moves) == ["c", "b"]  # Lanternlight weights meeting a threat (3) over an ally (1)
    assert {"category": "engagement", "text": "meets foe head on"} in moves[0]["annotations"]
    assert {"category": "footing", "text": "higher than where you stand"} in moves[1]["annotations"]
    acts = eng.enumerate_action_candidates("ash", 100)
    assert ids(acts)[:2] == ["strike@foe", "strike@imp"]  # factors: strike a threat first
    tide_moves = {c["id"]: c for c in banded(tide).enumerate_moves("ash", 100)}
    # same kernel features under another backend, in the pack's own words
    assert ids(banded(tide).enumerate_moves("ash", 100))[0] == "close:foe"
    assert tide_moves["close:foe"]["annotations"] == [{"category": "pressure", "text": "into the thick of it with foe"}]
    assert "region_id" not in tide_moves["close:foe"] and tide_moves["close:foe"]["position_id"] == "close:foe"


def test_zone_actions_describe_the_destination(lantern):
    eng = diamond(lantern)
    climbs = {c["target"]: c for c in eng.enumerate_action_candidates("ash", 100) if c["action_id"] == "climb"}
    assert climbs["b"]["annotations"] == [{"category": "footing", "text": "a climb up to b"}]
    assert climbs["c"]["annotations"] == []
    from_b = eng.enumerate_action_candidates("ash", 100, position_id="b")
    assert {c["target"] for c in from_b if c["action_id"] == "climb"} == {"a", "d"}
    with pytest.raises(EngineError, match="No position 'd'"):
        eng.enumerate_action_candidates("ash", 100, position_id="d")


def test_hidden_entities_never_shape_candidates(lantern):
    hidden = diamond(lantern)
    hidden.set_visibility("foe", ["bram"])
    absent = table(lantern)
    absent.set_scene("x", encounter=True, regions=DIAMOND, placements={"ash": "a", "bram": "b", "imp": "d"})
    for m in (0, 50, 100):
        assert hidden.enumerate_moves("ash", m) == absent.enumerate_moves("ash", m)
        assert hidden.enumerate_action_candidates("ash", m) == absent.enumerate_action_candidates("ash", m)
    assert "foe" not in hidden.preview("ash", "strike", 100)["targets"]
    assert "foe" in hidden.preview("bram", "strike", 100)["targets"]


# ---------------------------------------------------------------- preview

def test_preview_reports_without_rolling_or_leaking(lantern):
    eng = diamond(lantern)
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    pv = eng.preview("ash", "strike", 100, target="foe")
    assert pv["difficulty"] == {"kind": "derived"}  # never the target's value
    assert pv["targets"] == ["bram", "foe", "imp"] and pv["available"]
    assert set(pv["outcomes"]) == {"pass", "fail"}
    climb = eng.preview("ash", "climb", 0, target="b")
    assert climb["difficulty"]["kind"] == "ladder" and climb["annotations"] == []
    assert eng.preview("ash", "climb", 100, target="b")["annotations"] == [{"category": "footing", "text": "a climb up to b"}]
    with pytest.raises(EngineError, match="No target 'd'"):
        eng.preview("ash", "climb", 100, target="d")
    with pytest.raises(EngineError, match="No action"):
        eng.preview("ash", "fly", 100)
    eng.enumerate_moves("ash", 100)
    eng.enumerate_action_candidates("ash", 100)
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before  # read-only


def _no_numbers(obj, path="$"):
    if isinstance(obj, bool) or isinstance(obj, (int, float)):
        raise AssertionError(f"number at {path}: candidates carry ids and text only")
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in {"x", "y", "coord", "coords", "coordinates", "position"}, path
            _no_numbers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_numbers(v, f"{path}[{i}]")


# ---------------------------------------------------------------- legality at volume

def _zone_scene(eng, rng, n):
    names = [f"z{i}" for i in range(rng.randint(2, 9))]
    regions = [{"id": z, "adjacency": [o for o in names[i + 1:] if rng.random() < 0.35]} for i, z in enumerate(names)]
    placements = {e: rng.choice(names) for e in ("ash", "bram", "foe", "imp")}
    eng.set_scene(f"v{n}", encounter=bool(n % 2), regions=regions, placements=placements)


def _band_scene(eng, rng, n):
    bands = [b["id"] for b in eng.pack.get("spatial.bands")]
    people = ["ash", "bram", "foe", "imp"]
    ranges = [{"between": [a, b], "band": rng.choice(bands)} for i, a in enumerate(people) for b in people[i + 1:]]
    eng.set_scene(f"v{n}", encounter=bool(n % 2), participants=people, ranges=ranges)


@pytest.mark.parametrize("backend", ["zone_graph", "range_bands"])
def test_ten_thousand_enumerations_are_all_legal(lantern, tide, backend):
    """Gate P0: zero illegal candidates across 10,000 enumerations, per backend."""
    assert set(spatial.BACKENDS) == {"zone_graph", "range_bands"}  # add a case here as backends land
    pack, build = (lantern, _zone_scene) if backend == "zone_graph" else (tide, _band_scene)
    rng = random.Random(7)
    enumerations = scene = 0
    eng = table(pack, "volume")
    impl = spatial.BACKENDS[backend]
    while enumerations < 10_000:
        scene += 1
        build(eng, rng, scene)
        for e in ("foe", "imp"):
            if rng.random() < 0.3:
                eng.set_visibility(e, [rng.choice(["ash", "bram"])])
        sp = eng.state["scene"]["spatial"]
        for actor in ("ash", "bram", "foe", "imp"):
            seer = eng.state["entities"][actor]["controller"]
            among = {e for e in eng.state["entities"] if eng.visible(seer, e)}
            for m in (0, 20, 40, 60, 80, 100):
                moves = eng.enumerate_moves(actor, m)
                acts = eng.enumerate_action_candidates(actor, m)
                enumerations += 2
                _no_numbers(moves)
                _no_numbers(acts)
                assert len(moves) <= tactics.CANDIDATE_CAP and len(acts) <= tactics.CANDIDATE_CAP
                for c in moves:
                    impl.check_move(sp, eng.state["entities"], actor, c["position_id"], among)  # raises if illegal
                    if ":" in c["position_id"]:  # never measured from someone the seat cannot see
                        assert c["position_id"].split(":", 1)[1] in among
                available = eng.available_actions(actor)
                for c in acts:
                    assert c["action_id"] in available
                    if c["target"] is not None:
                        kind = pack.by_id("actions")[c["action_id"]]["target"]
                        if kind == "entity":
                            assert eng.visible(seer, c["target"]) and eng._in_scene(c["target"])
                        else:
                            assert c["target"] in eng.reachable(actor)
    assert enumerations >= 10_000


def test_enumerated_actions_are_accepted_by_the_engine(lantern, tide):
    """Commit a sample of candidates for real: the engine must accept every one."""
    for pack in (lantern, tide):
        count = len(scene_for(pack).enumerate_action_candidates("ash", 100))
        for i in range(count):
            eng = scene_for(pack)  # a fresh table per candidate: each one is legal on this state
            cand = eng.enumerate_action_candidates("ash", 100)[i]
            action = pack.by_id("actions")[cand["action_id"]]
            gm = {"difficulty": "easy"} if "ladder" in (action.get("difficulty") or {}) else {}
            spend = min((action.get("cost") or {}).get("amounts") or [0]) or None
            head = eng.store.head(eng.campaign_id)
            eng.commit_action("ash", cand["action_id"], target=cand["target"], gm=gm, spend=spend)
            assert eng.store.head(eng.campaign_id) != head


# ---------------------------------------------------------------- pack lint

@pytest.mark.parametrize("edit, code_fragment", [
    (lambda p: p["weights"].update({"bravery": 2}), "No tactical feature 'bravery'"),
    (lambda p: p["categories"].append({"id": "odd", "order": 3}), "order must be 1"),
    (lambda p: p["annotation_templates"][0].update({"category": "nope"}), "No category 'nope'"),
    (lambda p: p["annotation_templates"][0].update({"text": "near {secret_stuff}"}), "may use only"),
    (lambda p: p["factors"][1].update({"actions": ["fly"]}), "No action 'fly'"),
    (lambda p: p["factors"][0].update({"when": "import os"}), "factors high_ground"),
])
def test_bad_tactical_profiles_fail_lint(packs_dir, tmp_path, edit, code_fragment):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    edit(data["spatial"]["tactical_profile"])
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f.message for f in errors(lint(resolve("lanternlight", dst))) if f.code == "tactical-profile"]
    assert any(code_fragment in m for m in found), found

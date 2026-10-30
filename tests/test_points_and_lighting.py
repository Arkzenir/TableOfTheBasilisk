"""Point-buy chargen and lighting per region (T0.42; ARCHITECTURE §1.5, §2.3,
§8.2; D-059)."""

import random
import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.determinism import expand
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.entities import allocate_points, point_cost
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import free_values, generate

SEED = "points-seed"
POINTS = {"id": "buy", "kind": "points", "targets": ["might", "grace", "wits", "heart"],
          "pool": 6, "range": [-1, 3], "cost": 1}


def _variant(packs_dir, tmp_path, fn, pid="lanternlight"):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / pid / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve(pid, dst)


def with_points(step):
    """Lanternlight with its rolled stats replaced by a point-buy step."""
    def edit(d):
        d["chargen"]["steps"] = [step] + [s for s in d["chargen"]["steps"] if s["kind"] != "roll"]
    return edit


def table(pack, seats=None):
    return Engine.start_campaign(pack, SEED, {"seats": seats or {"gm": "gm", "ash": "player"}}, clock=lambda: None)


# ---------------------------------------------------------------- point-buy (§1.5)

def test_a_points_step_spends_the_pool_and_logs_the_allocation(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, with_points(POINTS))
    assert errors(lint(pack)) == []
    eng = table(pack)
    pick = {"might": 3, "grace": 1, "wits": 0, "heart": -1}  # costs 4 + 2 + 1 + 0 = 7: one too many
    with pytest.raises(EngineError, match="that costs 7 points; spend exactly 6"):
        eng.create_character("ash", "Ash", {"buy": pick, "background": "scholar"})
    pick["grace"] = 0
    eng.create_character("ash", "Ash", {"buy": pick, "background": "scholar"})
    assert {k: eng.state["entities"]["ash"]["stats"][k] for k in ("might", "grace", "heart")} == \
        {"might": 3, "grace": 0, "heart": -1}  # the scholar background then sets Wits
    judged = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "judgement_input"
              and e["payload"]["control"] == "chargen_points"]
    assert judged[0]["choice"] == pick and judged[0]["options"] == {"pool": 6, "range": [-1, 3], "cost": 1,
                                                                    "exact": True}
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


@pytest.mark.parametrize("pick, fragment", [
    ({"might": 3, "grace": 1}, "give each of might, grace, wits, heart"),
    ({"might": 4, "grace": 0, "wits": 0, "heart": -1}, "might must be an integer from -1 to 3"),
    ({"might": "3", "grace": 0, "wits": 0, "heart": -1}, "might must be an integer"),
    ("all in might", "give each of"),
])
def test_a_bad_allocation_is_refused_atomically(packs_dir, tmp_path, pick, fragment):
    eng = table(_variant(packs_dir, tmp_path, with_points(POINTS)))
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    with pytest.raises(EngineError, match=fragment):
        eng.create_character("ash", "Ash", {"buy": pick, "background": "scholar"})
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before


def test_a_cost_table_and_an_inexact_pool(packs_dir, tmp_path):
    step = {**POINTS, "cost": [0, 1, 2, 4, 7], "pool": 8, "exact": False}  # one cost per value, -1 to 3
    pack = _variant(packs_dir, tmp_path, with_points(step))
    assert errors(lint(pack)) == []
    eng = table(pack)
    with pytest.raises(EngineError, match="that costs 9 points; spend at most 8"):
        eng.create_character("ash", "Ash", {"buy": {"might": 3, "grace": 1, "wits": -1, "heart": -1},
                                            "background": "scholar"})
    eng.create_character("ash", "Ash", {"buy": {"might": 3, "grace": -1, "wits": -1, "heart": -1},
                                        "background": "scholar"})  # 7 of 8 is allowed
    assert point_cost(step, 2) == 4


def test_a_thousand_point_buy_characters_are_all_valid(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, with_points(POINTS))
    rng = random.Random(7)
    for n in range(1000):
        order = list(POINTS["targets"])
        rng.shuffle(order)
        alloc = allocate_points(POINTS, order)
        assert sum(point_cost(POINTS, v) for v in alloc.values()) == POINTS["pool"]
        if n < 25:  # a sample through the engine: every one is accepted and schema-valid
            eng = table(pack)
            eng.create_character("ash", "Ash", {"buy": alloc, "background": "scholar"})
            assert eng.sheet_problems("ash") == []


@pytest.mark.parametrize("step, fragment", [
    ({**POINTS, "pool": 99}, "a pool of 99 cannot be spent within the range"),
    ({**POINTS, "range": [-3, 3]}, "goes outside might's range -1..3"),
    ({**POINTS, "range": [3, 1]}, "range must be [min, max]"),
    ({**POINTS, "cost": 0}, "cost must be a positive integer"),
    ({**POINTS, "cost": [0, 1]}, "the cost list needs one entry per value from -1 to 3 (5), not 2"),
    ({**POINTS, "cost": [3, 1, 2, 3, 4]}, "never fall as the value rises"),
    ({**POINTS, "targets": ["mana"]}, "No stat 'mana'"),
    ({**POINTS, "exact": "yes"}, "exact is true or false"),
    ({**POINTS, "cost": [0, 2, 4, 6, 8], "pool": 7}, "no allocation spends the pool of 7 exactly"),
])
def test_bad_points_steps_fail_lint(packs_dir, tmp_path, step, fragment):
    found = [f.message for f in errors(lint(_variant(packs_dir, tmp_path, with_points(step))))]
    assert any(fragment in m for m in found), found


# ---------------------------------------------------------------- lighting per region (§8.2)

REGIONS = [{"id": "door", "label": "Doorway", "adjacency": ["hall"], "lighting": "bright"},
           {"id": "hall", "label": "Hall", "adjacency": ["corner"]},
           {"id": "corner", "label": "Dark corner", "adjacency": [], "lighting": "dim"}]


def lit_table(lantern):
    eng = table(lantern, {"gm": "gm", "ash": "player", "bram": "player"})
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.start_session()
    eng.set_scene("crypt", regions=REGIONS, placements={"ash": "door", "bram": "corner"})
    return eng


def test_light_is_read_where_each_entity_stands(lantern):
    eng = lit_table(lantern)
    regions = {r["id"]: r for r in eng.state["scene"]["spatial"]["regions"]}
    assert regions["corner"]["lighting"] == "dim" and "lighting" not in regions["hall"]  # only when set
    assert eng.view(eng.state["entities"]["bram"])["region"]["lighting"]["dim"] == 1
    assert eng.view(eng.state["entities"]["ash"])["region"]["lighting"]["dim"] == 0
    situational = {m["source"] for m in eng._situational(eng.state["entities"]["bram"], None, {}, None)}
    assert "dim_light" in situational  # derived from the region, not the scene
    assert "dim_light" not in {m["source"] for m in eng._situational(eng.state["entities"]["ash"], None, {}, None)}
    view = eng.tactical_view("ash")
    assert {o["id"]: o.get("lighting") for o in view["others"]}["bram"] == "dim"
    assert view["self"]["lighting"] == "bright"
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_lighting_values_come_from_the_pack(lantern):
    eng = table(lantern)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.start_session()
    with pytest.raises(EngineError, match="No lighting for region a 'gloom'"):
        eng.set_scene("x", regions=[{"id": "a", "label": "A", "lighting": "gloom"}])
    gm = generate(lantern, expand({"gm": {"preset": "strict"}}), "gm")
    assert gm["set_scene"]["regions"]["items"]["lighting"] == {"enum": ["bright", "dark", "dim"]}
    assert not free_values(gm["set_scene"])


def test_a_scene_without_lighting_folds_as_before(lantern):
    eng = table(lantern)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.start_session()
    eng.set_scene("plain", regions=[{"id": "a", "label": "A"}], placements={"ash": "a"})
    assert "lighting" not in eng.state["scene"]["spatial"]["regions"][0]
    assert eng.view(eng.state["entities"]["ash"])["region"]["lighting"]["dim"] == 0


# ---------------------------------------------------------------- point-buy in a shipped pack (D-060)

def test_the_shipped_point_buy_pack_builds_characters_from_a_pool(packs_dir):
    pack = resolve("lanternlight_pointbuy", packs_dir)
    step = next(s for s in pack.get("chargen.steps") if s["id"] == "stats")
    assert step["kind"] == "points" and step["pool"] == 5
    assert [s["id"] for s in pack.get("chargen.steps")][:2] == ["stats", "background"]  # spend, then background
    assert errors(lint(pack)) == []
    eng = table(pack, {"gm": "gm", "ash": "player"})
    pick = {"might": 2, "grace": 0, "wits": -1, "heart": -1}  # 4 + 1 + 0 + 0 = 5
    eng.create_character("ash", "Ash", {"stats": pick, "background": "scholar"})
    stats = eng.state["entities"]["ash"]["stats"]
    assert {k: stats[k] for k in ("might", "grace", "heart")} == {"might": 2, "grace": 0, "heart": -1}
    with pytest.raises(EngineError, match="that costs 4 points; spend exactly 5"):
        eng2 = table(pack, {"gm": "gm", "ash": "player"})
        eng2.create_character("ash", "Ash", {"stats": {"might": 2, "grace": -1, "wits": -1, "heart": -1},
                                             "background": "scholar"})
    assert not any(e["type"] == "roll_made" and "chargen:stats" in e["payload"]["purpose"]
                   for e in eng.store.read(eng.campaign_id))  # nothing is rolled for stats any more

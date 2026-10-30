"""Props, entity templates, and the tactical view (T0.41; ARCHITECTURE §2.3,
§5.2, §7.1, §8.2; D-058)."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.determinism import expand
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import free_values, generate

SEED = "props-seed"
REGIONS = [{"id": "near", "label": "Near", "adjacency": ["mid"], "cover": None},
           {"id": "mid", "label": "Middle", "adjacency": ["far"]},
           {"id": "far", "label": "Far", "adjacency": []}]


def _variant(packs_dir, tmp_path, fn, pid="lanternlight"):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / pid / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve(pid, dst)


def table(pack, seats=None):
    eng = Engine.start_campaign(pack, SEED, {"seats": seats or {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    if "bram" in eng.seats:
        eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.start_session()
    return eng


def replays(eng):
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


# ---------------------------------------------------------------- templates (§2.3, §1.3.2)

def test_a_template_is_a_stat_block_by_id(lantern):
    eng = table(lantern)
    eng.set_scene("hall")
    eng.spawn_entity("guard1", "Guard", template="watch_guard")
    guard = eng.state["entities"]["guard1"]
    assert guard["kind"] == "npc" and guard["stats"]["might"] == 2 and guard["stats"]["grace"] == 1
    assert guard["inventory"] == ["lantern", "rope"] and guard["tags"] == ["watch"]
    assert guard["resources"]["vigor"] == 12  # 8 + might * 2, from the template's stats
    eng.spawn_entity("guard2", "Hurt Guard", template="watch_guard", resources={"vigor": 3},
                     conditions=["shaken"])  # the spec's fields override the template's
    hurt = eng.state["entities"]["guard2"]
    assert hurt["resources"]["vigor"] == 3 and "shaken" in hurt["conditions"] and hurt["tags"] == ["watch"]
    replays(eng)


@pytest.mark.parametrize("kwargs, fragment", [
    ({"template": "dragon"}, "No template 'dragon'"),
    ({"resources": {"vigor": 99}}, "resource vigor starts from 0 to 8"),
    ({"resources": {"mana": 1}}, "No resource 'mana'"),
    ({"items": ["anvil"]}, "No item 'anvil'"),
    ({"items": ["crowbar"] * 3}, "would start carrying 12 of 10"),
    ({"conditions": ["cursed"]}, "No condition 'cursed'"),
    ({"tags": ["Bad Tag"]}, "tag"),
    ({"kind": "monster"}, "No kind 'monster'"),
    ({"interactable": "no"}, "interactable is true or false"),
])
def test_a_bad_spawn_spec_is_refused_atomically(lantern, kwargs, fragment):
    eng = table(lantern)
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    with pytest.raises(EngineError, match=fragment):
        eng.spawn_entity("thing", "Thing", **kwargs)
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before


def test_the_gm_spawns_by_template_and_kind_never_by_number(lantern, tide):
    for pack, templates in ((lantern, ["rope_bridge", "watch_guard"]), (tide, ["broken_mast", "reef_raider"])):
        for preset in ("strict", "standard"):
            tool = generate(pack, expand({"gm": {"preset": preset}}), "gm")["spawn_entity"]
            assert tool["template"] == {"enum": templates} and tool["kind"] == {"enum": ["npc", "prop"]}
            assert "stats" not in tool and "resources" not in tool
        assert not free_values(generate(pack, expand({"gm": {"preset": "strict"}}), "gm"))


@pytest.mark.parametrize("template, fragment", [
    ({"id": "t", "label": "T", "stats": {"might": 9}}, "stat might must be an integer from -1 to 3"),
    ({"id": "t", "label": "T", "stats": {"mana": 1}}, "No stat 'mana'"),
    ({"id": "t", "label": "T", "resources": {"vigor": 20}}, "resource vigor must be an integer from 0 to 8"),
    ({"id": "t", "label": "T", "items": ["anvil"]}, "No item 'anvil'"),
    ({"id": "t", "label": "T", "items": ["crowbar", "crowbar", "crowbar"]}, "more than its carry limit 10"),
    ({"id": "t", "label": "T", "conditions": ["cursed"]}, "No condition 'cursed'"),
    ({"id": "t", "label": "T", "kind": "monster"}, "kind must be npc or prop"),
    ({"id": "t"}, "needs a label"),
    ({"id": "t", "label": "T", "hp": 3}, "unknown key 'hp'"),
])
def test_bad_templates_fail_lint(packs_dir, tmp_path, template, fragment):
    pack = _variant(packs_dir, tmp_path, lambda d: d["entity_model"]["templates"].append(template))
    found = [f.message for f in errors(lint(pack))]
    assert any(fragment in m for m in found), found


# ---------------------------------------------------------------- props (§5.2, §8.2)

def test_a_prop_never_takes_a_turn_unless_joined(lantern):
    eng = table(lantern)
    eng.spawn_entity("foe", "Foe")
    eng.spawn_entity("bridge", "The Rope Bridge", template="rope_bridge")
    assert eng.state["entities"]["bridge"]["kind"] == "prop"
    eng.set_scene("gorge", encounter=True)
    eng.start_encounter()
    assert "bridge" not in eng.state["encounter"]["participants"]
    eng.join_encounter("bridge")  # an animated statue, say
    assert "bridge" in eng.state["encounter"]["participants"]
    replays(eng)


def test_a_prop_never_rolls_on_either_side(lantern):
    eng = table(lantern)
    eng.set_scene("gorge")
    eng.spawn_entity("bridge", "The Rope Bridge", template="rope_bridge")
    with pytest.raises(EngineError, match="bridge is a prop and cannot roll the other side of opposed"):
        eng.resolve_unmodelled("ash", "opposed", stat="might", target="bridge")
    with pytest.raises(EngineError, match="bridge is a prop and never rolls"):
        eng.resolve_unmodelled("bridge", "check", difficulty="easy")
    result = eng.commit_action("ash", "strike", target="bridge")  # a derived difficulty: the prop does not roll
    assert result["outcome"] in ("pass", "fail")
    assert "recall" not in eng.available_actions("bridge")
    replays(eng)


def test_scenery_cannot_be_targeted(lantern):
    eng = table(lantern)
    eng.set_scene("hall", regions=REGIONS, placements={"ash": "near", "bram": "near"})
    eng.spawn_entity("wall", "The Wall", kind="prop", interactable=False, zone="near")
    assert eng.state["entities"]["wall"]["interactable"] is False
    with pytest.raises(EngineError, match="wall is scenery: nothing can target it"):
        eng.commit_action("ash", "strike", target="wall")
    targets = {c["target"] for c in eng.enumerate_action_candidates("ash", 100)}
    assert "wall" not in targets and "bram" in targets
    eng.spawn_entity("crate", "Crate", kind="prop", zone="near")
    assert "interactable" not in eng.state["entities"]["crate"]  # written only when false
    replays(eng)


# ---------------------------------------------------------------- the tactical view (§7.1)

def test_the_tactical_view_shows_what_the_seat_sees(lantern):
    eng = table(lantern)
    regions = [dict(r) for r in REGIONS]
    regions[1]["cover"] = None
    eng.set_scene("hall", encounter=True, regions=regions,
                  placements={"ash": "near", "bram": "mid"})
    eng.spawn_entity("foe", "Foe", zone="far")
    eng.spawn_entity("lurker", "Lurker", zone="far")
    eng.set_visibility("lurker", ["bram"])  # ash cannot see it
    eng.start_encounter()
    view = eng.tactical_view("ash")
    assert view["mode"] == "zone" and view["self"]["id"] == "ash" and view["self"]["position"] == "near"
    assert view["self"]["reach"] == eng.reachable("ash")
    others = {o["id"]: o for o in view["others"]}
    assert set(others) == {"bram", "foe"}  # the lurker is not there at all
    assert others["bram"]["steps"] == 1 and others["foe"]["steps"] == 2 and others["foe"]["position"] == "far"
    assert view["turn"] == eng.current_turn("ash")
    assert "lurker" in {o["id"] for o in eng.tactical_view("bram")["others"]}
    gm = eng.tactical_view("gm")
    assert gm["self"] is None and {o["id"] for o in gm["others"]} == {"ash", "bram", "foe", "lurker"}
    assert eng.tactical_view("gm", "foe")["self"]["id"] == "foe"
    with pytest.raises(EngineError, match="own entity only"):
        eng.tactical_view("ash", "bram")
    with pytest.raises(EngineError, match="No entity 'lurker'"):
        eng.tactical_view("ash", "lurker")


def test_the_tactical_view_names_bands_in_a_band_scene(tide):
    eng = Engine.start_campaign(tide, SEED, {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.spawn_entity("raider", "Raider", template="reef_raider")
    eng.start_session()
    bands = [b["id"] for b in tide.get("spatial.bands")]
    eng.set_scene("deck", encounter=True, participants=["ash", "raider"],
                  ranges=[{"between": ["ash", "raider"], "band": bands[1]}])
    row = eng.tactical_view("ash")["others"][0]
    assert row["id"] == "raider" and row["band"] == bands[1] and row["steps"] == 1


def test_the_tool_is_there_only_with_a_spatial_backend(lantern, packs_dir, tmp_path):
    assert generate(lantern, expand({}), "players")["get_tactical_view"] == {}
    assert "entity_id" in generate(lantern, expand({}), "gm")["get_tactical_view"]
    flat = _variant(packs_dir, tmp_path, lambda d: d.update(spatial={"backends": "none"}))
    assert "get_tactical_view" not in generate(flat, expand({}), "players")

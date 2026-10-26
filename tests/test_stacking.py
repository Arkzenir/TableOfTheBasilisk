"""Condition stacking (T0.25; ARCHITECTURE §2.3, §2.4)."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve

IDS = {"actor": "ash", "target": "ash", "self": "ash"}


@pytest.fixture(scope="module")
def stacked(packs_dir, tmp_path_factory):
    """Lanternlight where Shaken stacks: each time it lands it worsens, to -3."""
    dst = tmp_path_factory.mktemp("stack") / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    for c in data["entity_model"]["conditions"]:
        if c["id"] == "shaken":
            c.update({"stacking": "intensity", "max_level": 3})
    data["resolution"]["situational_tags"].append({"id": "badly_shaken", "value": -1,
                                                   "derive": "actor.conditions.shaken >= 2"})
    data["presentation"]["rule_cards"]["badly_shaken"] = {"title": "Badly shaken", "summary": "-1 more at 2+ Shaken.",
                                                          "category": "tag", "icon_id": "shaken"}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pack = resolve("lanternlight", dst)
    assert errors(lint(pack)) == []
    return pack


def table(pack):
    eng = Engine.start_campaign(pack, "stack", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.start_session()
    eng.set_scene("s")
    return eng


def apply(eng, prim, **kw):
    eng._apply_effect({"primitive": prim, "target": "actor", "condition": "shaken", **kw}, IDS, None, {})


def level(eng):
    return (eng.state["entities"]["ash"]["conditions"].get("shaken") or {}).get("level")


def test_intensity_rises_to_its_cap(stacked):
    eng = table(stacked)
    for expected in (1, 2, 3, 3):
        apply(eng, "add_condition")
        assert level(eng) == expected
    assert eng.view(eng.state["entities"]["ash"])["conditions"]["shaken"] == 3
    assert {f["id"]: f["value"] for f in eng.full_sheet("ash")["fields"]}["shaken"] == 3
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_modifiers_scale_with_the_level(stacked):
    eng = table(stacked)
    apply(eng, "add_condition")
    apply(eng, "add_condition")
    eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    mods = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "procedure_resolved"][-1]["modifiers"]
    assert {"source": "shaken", "kind": "condition", "value": -2, "origin": "state"} in mods
    assert any(m["source"] == "badly_shaken" for m in mods)  # expressions read the level


def test_removal_by_levels_and_entirely(stacked):
    eng = table(stacked)
    for _ in range(3):
        apply(eng, "add_condition")
    apply(eng, "remove_condition", levels=2)
    assert level(eng) == 1
    apply(eng, "remove_condition", levels=2)  # more levels than it has: it is gone
    assert level(eng) is None and "shaken" not in eng.state["entities"]["ash"]["conditions"]
    apply(eng, "add_condition")
    apply(eng, "add_condition")
    apply(eng, "remove_condition")  # no levels named: removed entirely
    assert "shaken" not in eng.state["entities"]["ash"]["conditions"]


def test_expiry_ends_every_level(stacked):
    eng = table(stacked)
    apply(eng, "add_condition")
    apply(eng, "add_condition")
    eng.set_scene("next")  # Shaken lasts a scene
    assert "shaken" not in eng.state["entities"]["ash"]["conditions"]


def test_non_stacking_conditions_keep_their_shape(lantern):
    eng = table(lantern)
    apply(eng, "add_condition")
    apply(eng, "add_condition")
    assert eng.state["entities"]["ash"]["conditions"]["shaken"] == {"since_scene": 1}  # no level key: older logs fold the same


@pytest.mark.parametrize("change, fragment", [
    ({"stacking": "cumulative"}, "stacking must be none or intensity"),
    ({"stacking": "intensity", "max_level": 1}, "max_level must be"),
])
def test_bad_stacking_fails_lint(packs_dir, tmp_path, change, fragment):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["entity_model"]["conditions"][0].update(change)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert any(fragment in f.message for f in errors(lint(resolve("lanternlight", dst))))

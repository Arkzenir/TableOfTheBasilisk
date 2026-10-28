"""Starting equipment and currencies from chargen choices (§1.5), and the GM
substituting a fiction-triggered move (§2.13.1) (T0.35; BUILD_PLAN P0.4, P0.8)."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.determinism import expand
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import free_values, generate


def _variant(packs_dir, tmp_path, pid, fn):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / pid / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve(pid, dst)


def _options(d):
    return next(s for s in d["chargen"]["steps"] if s["id"] == "background")["options"]


# ---------------------------------------------------------------- starting equipment (§1.5)

@pytest.fixture
def outfitted(packs_dir, tmp_path):
    def kit(d):
        _options(d)[0].update({"items": ["rope", "ration"], "currencies": {"luck": 1}})  # soldier
    return _variant(packs_dir, tmp_path, "lanternlight", kit)


def test_a_choice_grants_equipment_and_currency(outfitted):
    assert errors(lint(outfitted)) == []
    eng = Engine.start_campaign(outfitted, "kit", {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    ash, bram = eng.state["entities"]["ash"], eng.state["entities"]["bram"]
    assert ash["inventory"] == ["rope", "ration"] and bram["inventory"] == []
    assert eng.currency("ash", "luck") == 2 and eng.currency("bram", "luck") == 1  # start 1, plus 1
    assert eng.sheet_problems("ash") == []
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_starting_equipment_must_fit(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, "lanternlight",
                    lambda d: _options(d)[0].__setitem__("items", ["crowbar"] * 6))  # 24 > 10 + might * 2
    eng = Engine.start_campaign(pack, "heavy", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    before = eng.store.head(eng.campaign_id)
    with pytest.raises(EngineError, match="more equipment than the character can carry"):
        eng.create_character("ash", "Ash", {"background": "soldier"})
    assert eng.store.head(eng.campaign_id) == before


@pytest.mark.parametrize("grant, fragment", [
    ({"items": ["anvil"]}, "No item 'anvil'"),
    ({"currencies": {"doom": 1}}, "'doom' is unknown"),
    ({"currencies": {"luck": 0}}, "currency luck amount must be a positive integer"),
])
def test_bad_grants_fail_lint(packs_dir, tmp_path, grant, fragment):
    found = [f.message for f in errors(lint(_variant(packs_dir, tmp_path, "lanternlight",
                                                      lambda d: _options(d)[0].update(grant))))]
    assert any(fragment in m for m in found), found


def test_a_shared_currency_is_not_a_starting_grant(packs_dir, tmp_path):
    def pool(d):
        d["gm"]["meta_currencies"].append({"id": "resolve", "holder": "party", "start": 1})
        _options(d)[0]["currencies"] = {"resolve": 1}
    found = [f.message for f in errors(lint(_variant(packs_dir, tmp_path, "lanternlight", pool)))]
    assert any("a starting currency must be one each player holds; 'resolve' is held by party" in m
               for m in found), found


# ---------------------------------------------------------------- the GM substitutes a move (§2.13.1)

def tide_table(pack, gm_preset="standard"):
    eng = Engine.start_campaign(pack, "subst", {"seats": {"gm": "gm", "ash": "player"},
                                                "determinism": {"gm": {"preset": gm_preset}}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.start_session()
    eng.set_scene("deck")
    return eng


def test_a_standard_gm_substitutes_any_legal_move(tide):
    eng = tide_table(tide)
    assert not eng._eligible(tide.by_id("actions")["defy_danger"], eng.state["entities"]["ash"], None)  # here
    result = eng.commit_action("ash", "read_the_waters", gm={"substitute": "defy_danger"})
    events = list(eng.store.read(eng.campaign_id))
    committed = [e["payload"] for e in events if e["type"] == "action_committed"][-1]
    assert committed["action"] == "defy_danger" and committed["declared"] == "read_the_waters"
    judged = [e["payload"] for e in events if e["type"] == "judgement_input"]
    assert {"seat": "ash", "control": "action_selection", "choice": "read_the_waters"}.items() <= judged[-2].items()
    assert judged[-1]["seat"] == "gm" and judged[-1]["control"] == "fiction_triggers"
    assert judged[-1]["setting"] == "standard"
    assert judged[-1]["choice"] == {"declared": "read_the_waters", "substitute": "defy_danger"}
    resolved = [e["payload"] for e in events if e["type"] == "procedure_resolved"][-1]
    assert resolved["outcome"] == result["outcome"]
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_a_strict_gm_substitutes_only_an_eligible_move(tide):
    eng = tide_table(tide, gm_preset="strict")
    before = eng.store.head(eng.campaign_id)
    with pytest.raises(EngineError, match="under strict settings the GM substitutes an eligible move"):
        eng.commit_action("ash", "read_the_waters", gm={"substitute": "defy_danger"})
    assert eng.store.head(eng.campaign_id) == before


@pytest.mark.parametrize("declared, substitute, fragment", [
    ("mend", "defy_danger", "only a fiction-triggered move can be substituted; mend is declared"),
    ("read_the_waters", "mend", "No fiction-triggered move to substitute 'mend'"),
    ("read_the_waters", "read_the_waters", "No fiction-triggered move to substitute 'read_the_waters'"),
])
def test_bad_substitutions_are_refused(tide, declared, substitute, fragment):
    eng = tide_table(tide)
    with pytest.raises(EngineError, match=fragment):
        eng.commit_action("ash", declared, gm={"substitute": substitute})


def test_the_gm_tool_offers_substitution_as_an_enum(lantern, tide):
    for preset in ("strict", "standard"):
        eff = expand({"gm": {"preset": preset}})
        rule = generate(tide, eff, "gm")["rule_on_action"]
        assert rule["substitute"] == {"enum": ["defy_danger", "face_down", "read_the_waters"]}
        assert not free_values({"rule_on_action": {"substitute": rule["substitute"]}})
    assert "substitute" not in generate(lantern, expand({}), "gm")["rule_on_action"]  # no fiction moves
    assert "substitute" not in generate(tide, expand({}), "players").get("rule_on_action", {})

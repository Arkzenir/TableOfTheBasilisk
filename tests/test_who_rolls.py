"""Who rolls: where the pack's GM never rolls, no GM-side entity does (T0.31;
ARCHITECTURE §2.3 `gm.gm_rolls`, §2.4 "Who rolls"; BUILD_PLAN P0.4)."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve


def tide_table(pack, seed="who-rolls"):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.create_character("bram", "Bram", {"playbook": "reaver"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("deck")
    return eng


def _edited(packs_dir, tmp_path, fn, pid="tidewrack"):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / pid / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve(pid, dst)


def test_the_gm_side_cannot_roll_where_the_gm_never_rolls(tide):
    assert tide.get("gm.gm_rolls") is False
    eng = tide_table(tide)
    before = eng.store.head(eng.campaign_id)
    with pytest.raises(EngineError, match="the GM never rolls in tidewrack: foe is GM-controlled"):
        eng.commit_action("foe", "defy_danger", by="gm")
    with pytest.raises(EngineError, match="cannot roll banded_roll"):
        eng.resolve_unmodelled("foe", "banded_roll", stat="iron")
    assert eng.store.head(eng.campaign_id) == before  # refused atomically
    assert eng.commit_action("ash", "read_the_waters")["outcome"]  # the players still roll
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_rolling_actions_are_never_offered_to_the_gm_side(tide):
    eng = tide_table(tide)
    procs = tide.by_id("resolution.procedures")
    rolling = {a["id"] for a in tide.catalogue("actions") if procs[a["procedure"]]["id"] != "automatic"}
    assert not rolling & set(eng.available_actions("foe"))
    assert rolling & set(eng.available_actions("ash"))


def test_a_gm_who_rolls_still_rolls_for_npcs(lantern):
    eng = Engine.start_campaign(lantern, "rolls", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("hall")
    assert eng.resolve_unmodelled("foe", "check", stat="might", difficulty="easy")["outcome"]


@pytest.fixture
def contested(packs_dir, tmp_path):
    """Tidewrack with an opposed action: both sides roll."""
    def add(d):
        d["actions"].append({"id": "contest", "target": "entity", "stat": "iron", "procedure": "opposed",
                             "outcome_effects": {}})
    return _edited(packs_dir, tmp_path, add)


def test_an_opposed_check_cannot_make_the_gm_side_roll(contested):
    eng = tide_table(contested)
    with pytest.raises(EngineError, match="foe is GM-controlled, so it cannot roll opposed"):
        eng.commit_action("ash", "contest", target="foe")
    assert "contest" not in eng.available_actions("ash", "foe")
    assert "contest" in eng.available_actions("ash", "bram")
    assert eng.commit_action("ash", "contest", target="bram")["outcome"]  # two players may contest


def test_a_trigger_any_entity_can_reach_must_not_roll(packs_dir, tmp_path):
    def trigger(d):
        d["entity_model"]["tracks"][0]["on_fill"].append(
            {"primitive": "trigger_procedure", "procedure": "banded_roll", "target": "self", "stat": "iron",
             "outcome_effects": {}})
    found = [f.message for f in errors(lint(_edited(packs_dir, tmp_path, trigger)))]
    assert any("the GM never rolls (gm.gm_rolls: false)" in m for m in found), found

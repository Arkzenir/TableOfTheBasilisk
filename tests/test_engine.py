import pytest

from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.canonical import hash_obj
from conftest import new_campaign


def setup_lantern(eng):
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("one", flags={"dim": 1})
    return eng


def test_unique_per_table_and_chargen(lantern):
    eng = new_campaign(lantern)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    with pytest.raises(EngineError, match="already taken"):
        eng.create_character("bram", "Bram", {"background": "soldier"})
    assert eng.state["entities"]["ash"]["stats"]["might"] == 2
    assert eng.state["entities"]["ash"]["resources"]["vigor"] == 12


def test_rejected_commands_leave_no_trace(lantern):
    eng = setup_lantern(new_campaign(lantern))
    head, state = eng.store.head(eng.campaign_id), hash_obj(eng.state)
    with pytest.raises(EngineError):
        eng.commit_action("ash", "climb", target="wall", gm={"difficulty": "impossible"})
    assert eng.store.head(eng.campaign_id) == head and hash_obj(eng.state) == state


def test_strict_gm_rejects_free_numbers(lantern):
    eng = setup_lantern(new_campaign(lantern, {"gm": {"preset": "strict"}}))
    with pytest.raises(EngineError, match="rung"):
        eng.commit_action("ash", "climb", target="wall", gm={"difficulty": 14})
    with pytest.raises(EngineError, match="free modifiers"):
        eng.commit_action("ash", "climb", target="wall", gm={"difficulty": "hard", "free_modifier": 1})
    eng.commit_action("ash", "climb", target="wall", gm={"difficulty": "hard"})


def test_standard_gm_bounds(lantern):
    eng = setup_lantern(new_campaign(lantern))  # GM standard by default
    with pytest.raises(EngineError, match="between"):
        eng.commit_action("ash", "climb", target="wall", gm={"difficulty": 99})
    eng.commit_action("ash", "climb", target="wall", gm={"difficulty": 14, "free_modifier": 1})
    judged = [e for e in eng.store.read(eng.campaign_id) if e["type"] == "judgement_input"]
    assert {j["payload"]["control"] for j in judged} >= {"action_selection", "difficulty", "situational_modifiers"}


def test_derived_tags_are_automatic_and_not_hand_addable(lantern):
    eng = setup_lantern(new_campaign(lantern))
    with pytest.raises(EngineError, match="derived from state"):
        eng.commit_action("ash", "recall", gm={"difficulty": "easy", "tags": ["dim_light"]})
    eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    proc = [e for e in eng.store.read(eng.campaign_id) if e["type"] == "procedure_resolved"][-1]
    assert {"source": "dim_light", "kind": "tag", "value": -1, "origin": "auto"} in proc["payload"]["modifiers"]


def test_triggers_fire(lantern):
    eng = setup_lantern(new_campaign(lantern))
    eng._apply_effect({"primitive": "mark_track", "target": "actor", "track": "fatigue", "amount": 3},
                      {"actor": "ash", "target": None, "self": "ash"}, None, {})
    assert "exhausted" in eng.state["entities"]["ash"]["conditions"]


def test_rulings_strict_draw_vs_standard_slot(tide):
    def run(preset):
        eng = new_campaign(tide, {"gm": {"preset": preset}})
        eng.create_character("ash", "Ash", {"playbook": "warden"})
        eng.start_session()
        eng.set_scene("deck", flags={"danger": 1})
        for _ in range(12):
            eng.commit_action("ash", "defy_danger")
            for slot, info in eng.open_rulings().items():
                eng.fill_ruling(slot, info["entries"][0])
        return eng
    strict = run("strict")
    types = [e["type"] for e in strict.store.read(strict.campaign_id)]
    assert "gm_ruling_filled" in types and not strict.open_rulings()
    assert all(e["payload"]["by"] == "engine" for e in strict.store.read(strict.campaign_id) if e["type"] == "gm_ruling_filled")
    std = run("standard")
    fills = [e for e in std.store.read(std.campaign_id) if e["type"] == "gm_ruling_filled"]
    assert fills and all(f["payload"]["by"] == "gm" for f in fills)


def test_fiction_trigger_strict_vs_standard(tide):
    eng = new_campaign(tide, {"players": {"preset": "strict"}})
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.start_session()
    eng.set_scene("calm", flags={"danger": 0})
    with pytest.raises(EngineError, match="not among the eligible"):
        eng.commit_action("ash", "defy_danger")
    eng2 = new_campaign(tide, {"players": {"preset": "standard"}})
    eng2.create_character("ash", "Ash", {"playbook": "warden"})
    eng2.start_session()
    eng2.set_scene("calm", flags={"danger": 0})
    eng2.commit_action("ash", "defy_danger")  # declared; would be a GM ruling at the table


def test_settings_change_applies_only_at_scene_boundary(lantern):
    eng = setup_lantern(new_campaign(lantern))
    assert eng.mode("difficulty", "gm") == "standard"
    eng.request_determinism_change(role="gm", preset="strict")
    with pytest.raises(EngineError, match="already queued"):
        eng.request_determinism_change(role="players", preset="standard")
    eng.commit_action("ash", "climb", target="wall", gm={"difficulty": 14})  # still standard mid-scene
    eng.set_scene("two")
    assert eng.mode("difficulty", "gm") == "strict"
    with pytest.raises(EngineError):
        eng.commit_action("ash", "climb", target="wall", gm={"difficulty": 14})
    types = [e["type"] for e in eng.store.read(eng.campaign_id)]
    assert types.index("determinism_changed") > types.index("scene_set")


def test_cooldown(lantern):
    eng = setup_lantern(new_campaign(lantern, {"min_scenes_between_changes": 2}))
    eng.request_determinism_change(role="gm", preset="strict")
    eng.set_scene("two")
    with pytest.raises(EngineError, match="cooldown"):
        eng.request_determinism_change(role="gm", preset="standard")
    eng.set_scene("three")
    eng.request_determinism_change(role="gm", preset="standard")


def test_open_ruling_keeps_its_starting_mode(tide):
    eng = new_campaign(tide)  # GM standard: rulings open as GM choices
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.start_session()
    eng.set_scene("deck", flags={"danger": 1})
    while not eng.open_rulings():
        eng.commit_action("ash", "defy_danger")
    eng.request_determinism_change(role="gm", preset="strict")
    eng.set_scene("next", flags={"danger": 1})
    slot, info = next(iter(eng.open_rulings().items()))
    eng.fill_ruling(slot, info["entries"][0])  # still fillable by the GM after the switch


def test_pinning_refuses_mismatch(lantern, tide):
    eng = setup_lantern(new_campaign(lantern))
    with pytest.raises(EngineError, match="pack hash"):
        Engine.load(tide, "test-seed", eng.store, eng.campaign_id)
    with pytest.raises(EngineError, match="seed"):
        Engine.load(lantern, "wrong-seed", eng.store, eng.campaign_id)
    again = Engine.load(lantern, "test-seed", eng.store, eng.campaign_id)
    assert again.state_hash() == eng.state_hash()


def test_replay_matches_live_state(lantern):
    eng = setup_lantern(new_campaign(lantern))
    for _ in range(5):
        eng.commit_action("ash", "strike", target="foe")
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_unsupported_strict_refused(packs_dir, tmp_path):
    import shutil
    import yaml
    from basilisk.kernel.packs import resolve
    pd = tmp_path / "packs"
    shutil.copytree(packs_dir, pd)
    path = pd / "tidewrack" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    del data["actions"][0]["eligibility"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pack = resolve("tidewrack", pd)
    with pytest.raises(EngineError, match="cannot support strict"):
        new_campaign(pack, {"players": {"preset": "strict"}})
    new_campaign(pack, {"players": {"preset": "standard"}})

"""Every GM call is logged as a judgement_input (D-044; ARCHITECTURE §2.13)."""

import pytest

from basilisk.kernel.determinism import expand
from basilisk.kernel.engine import Engine, EngineError
from basilisk.kernel.tools import generate

# Tools that change nothing: table talk (P1) and reads.
READS = {"post_to_table", "pass", "read_sheet", "read_party_sheets", "query_canon", "query_rules",
         "enumerate_actions", "look", "enumerate_moves", "preview"}
# Tools whose command already logs each choice under its own control (§2.13).
JUDGED = {"commit_action": "action_selection", "rule_on_action": "difficulty", "fill_ruling": "ruling_slots",
          "resolve_unmodelled": "unmodelled_actions", "peek_roll": "fudging", "take_advance": "advance"}


def table(pack, choices):
    eng = Engine.start_campaign(pack, "gm", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", choices)
    eng.start_session()
    eng.set_scene("s", flags={"danger": 1})
    return eng


def judged(eng):
    return [e for e in eng.store.read(eng.campaign_id) if e["type"] == "judgement_input"]


@pytest.mark.parametrize("which", ["lantern", "tide"])
def test_every_gm_tool_is_logged(request, which):
    pack = request.getfixturevalue(which)
    from basilisk.kernel import engine as engine_module
    for preset in ("strict", "standard"):
        tools = generate(pack, expand({"gm": {"preset": preset}}), "gm", "gm")
        for name in sorted(set(tools) - READS):
            if name in JUDGED:
                continue
            command = getattr(engine_module.Engine, name, None)
            assert command is not None, f"GM tool {name} has no engine command"
            assert getattr(command, "gm_call", False), f"GM tool {name} is not logged as a GM call"


def test_a_gm_call_records_its_arguments_and_options(lantern):
    eng = table(lantern, {"background": "soldier"})
    eng.create_clock("doom", "Doom", 6)
    eng.advance_clock("doom", 2)
    last = judged(eng)[-1]["payload"]
    assert last == {"seat": "gm", "control": "advance_clock", "setting": None,
                    "choice": {"clock_id": "doom", "amount": 2}, "options": [1, 2, 3]}
    cause = judged(eng)[-1]["caused_by"]
    assert next(e for e in eng.store.read(eng.campaign_id) if e["seq"] == cause)["type"] == "effect_applied"
    eng.advance_time("watch", 1)
    assert judged(eng)[-1]["payload"]["options"] == ["watch", "day", "moon"]
    eng.spawn_entity("foe", "Foe")
    assert judged(eng)[-1]["payload"]["choice"]["entity_id"] == "foe"


def test_engine_and_refused_calls_log_nothing(lantern):
    eng = table(lantern, {"background": "soldier"})
    before = len(judged(eng))
    eng.write_canon({"type": "npc", "name": "Varro", "body": "A tithe-keeper.", "knowledge": "revealed",
                     "origin": "prepped"}, by="engine")
    assert len(judged(eng)) == before  # the engine is not a model
    head = eng.store.head(eng.campaign_id)
    with pytest.raises(EngineError):
        eng.advance_clock("nothing", 1)
    assert eng.store.head(eng.campaign_id) == head  # refused: no events, no judgement
    with pytest.raises(EngineError):
        eng.pause_clock("nothing", by="ash")
    assert eng.store.head(eng.campaign_id) == head


def test_a_players_turn_end_is_not_a_gm_call(lantern):
    eng = table(lantern, {"background": "soldier"})
    eng.set_scene("fight", encounter=True)
    eng.start_encounter()
    while eng.current_turn()["actor"] != "ash":
        eng.end_turn()
    before = [p["payload"]["control"] for p in judged(eng)]
    assert "start_encounter" in before  # the GM's call
    eng.end_turn(by="ash")
    assert [p["payload"]["control"] for p in judged(eng)] == before
    eng.end_turn()  # the GM ending a turn is logged
    assert judged(eng)[-1]["payload"]["control"] == "end_turn"

"""Clocks and off-air advancement (T0.11; ARCHITECTURE §7.6.1, §7.6.2 axiom 15)."""

import pytest

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold


def table(pack):
    eng = Engine.start_campaign(pack, "clock-seed", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    return eng


def stage(at, name, knowledge="revealed", **extra):
    return {"at": at, "record": {"type": "event", "name": name, "body": f"{name}.", "knowledge": knowledge, **extra}}


def faction_clock(eng, every=1, amount=1, total=4):
    eng.create_clock("tithe", "The Tithe Guild tightens its grip", total, visible=False,
                     schedule={"every": every, "amount": amount},
                     stages=[stage(2, "The guild seizes the lower docks"), stage(4, "The guild owns the harbour")])


def sessions(eng, n):
    for _ in range(n):
        eng.start_session()
        eng.end_session()


def events(eng, kind):
    return [e for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


def test_clocks_advance_between_sessions_and_write_canon(lantern):
    """BUILD_PLAN P0.11: no party interference; canon for each world change."""
    eng = table(lantern)
    faction_clock(eng)
    fills = []
    for _ in range(5):
        eng.start_session()
        fills.append(eng.state["clocks"]["tithe"]["filled"])
        eng.end_session()
    assert fills == [0, 1, 2, 3, 4]  # nothing before the first session; one segment per gap after
    reached = [e["payload"] for e in events(eng, "clock_stage_reached")]
    assert [r["at"] for r in reached] == [2, 4]
    for r in reached:
        rec = eng.state["canon"][r["record"]]
        assert rec["origin"] == "prepped" and rec["type"] == "event"
    names = [eng.state["canon"][r["record"]]["name"] for r in reached]
    assert names == ["The guild seizes the lower docks", "The guild owns the harbour"]
    advances = [e for e in events(eng, "effect_applied") if e["payload"]["params"].get("reason") == "off_air"]
    assert len(advances) == 4


def test_world_changes_are_canon_before_play_resumes(lantern):
    eng = table(lantern)
    faction_clock(eng, amount=2)
    sessions(eng, 1)
    eng.start_session()
    log = list(eng.store.read(eng.campaign_id))
    started = max(e["seq"] for e in log if e["type"] == "session_started")
    written = [e for e in log if e["type"] == "canon_written"]
    assert written and all(e["seq"] < started for e in written)
    reached = events(eng, "clock_stage_reached")[0]
    effect = next(e for e in log if e["seq"] == next(c for c in log if c["seq"] == reached["caused_by"])["caused_by"])
    assert effect["payload"]["params"]["reason"] == "off_air"  # stage <- canon <- off-air advance


def test_every_n_sessions(lantern):
    eng = table(lantern)
    faction_clock(eng, every=2)
    fills = []
    for _ in range(6):
        eng.start_session()
        fills.append(eng.state["clocks"]["tithe"]["filled"])
        eng.end_session()
    assert fills == [0, 0, 1, 1, 2, 2]


def test_a_clock_created_mid_campaign_counts_from_its_session(lantern):
    eng = table(lantern)
    sessions(eng, 2)
    eng.start_session()
    faction_clock(eng)
    eng.end_session()
    eng.start_session()
    assert eng.state["clocks"]["tithe"]["filled"] == 1 and eng.state["clocks"]["tithe"]["created_session"] == 3


def test_interference_pauses_a_clock(lantern):
    eng = table(lantern)
    faction_clock(eng)
    sessions(eng, 2)
    with pytest.raises(EngineError, match="only the GM"):
        eng.pause_clock("tithe", by="ash")
    eng.pause_clock("tithe")
    sessions(eng, 2)
    assert eng.state["clocks"]["tithe"]["filled"] == 1
    eng.pause_clock("tithe", False)
    sessions(eng, 1)
    assert eng.state["clocks"]["tithe"]["filled"] == 2
    eng.create_clock("plain", "No schedule", 4)
    with pytest.raises(EngineError, match="no schedule"):
        eng.pause_clock("plain")


def test_stages_fire_however_the_clock_moves_and_only_once(lantern):
    eng = table(lantern)
    eng.create_clock("storm", "The storm builds", 4, stages=[stage(2, "The sea wall cracks")])
    eng.start_session()
    eng.advance_clock("storm", 2)  # in play, by the GM
    assert len(events(eng, "clock_stage_reached")) == 1
    eng._apply_effect({"primitive": "advance_clock", "clock": "storm", "amount": -2},
                      {"actor": None, "target": None, "self": None}, None, {})  # the party pushes it back
    eng.advance_clock("storm", 3)
    assert len(events(eng, "clock_stage_reached")) == 1  # a world change happens once


@pytest.mark.parametrize("kwargs, message", [
    ({"schedule": {"every": 0}}, "every must be"),
    ({"schedule": {"every": 1, "amount": 5}}, "amount must be"),
    ({"schedule": {"every": 1, "when": "dawn"}}, "every \\(sessions\\)"),
    ({"stages": [{"at": 9, "record": {}}]}, "segment from 1 to 4"),
    ({"stages": [stage(2, "A"), stage(2, "B")]}, "two stages at segment 2"),
    ({"stages": [{"at": 1, "record": {"type": "event", "name": "No body", "knowledge": "revealed"}}]}, "missing body"),
    ({"stages": [stage(1, "A hidden plot", knowledge="secret")]}, "discovery path"),
    ({"stages": [stage(1, "Made up", origin="improvised")]}, "origin prepped"),
])
def test_bad_schedules_and_stages_are_refused_atomically(lantern, kwargs, message):
    eng = table(lantern)
    before = frozen(eng)
    with pytest.raises(EngineError, match=message):
        eng.create_clock("bad", "Bad", 4, **kwargs)
    assert frozen(eng) == before


def test_secret_stages_with_discovery_paths(lantern):
    eng = table(lantern)
    eng.create_clock("plot", "The quiet plot", 2, schedule={"every": 1, "amount": 2},
                     stages=[stage(2, "The warden is bought", knowledge="secret", discovery_paths=["ash"])])
    sessions(eng, 1)
    eng.start_session()
    [rec] = [r for r in eng.state["canon"].values()]
    assert rec["knowledge"] == "secret"
    assert eng.query_canon("ash", "warden is bought")["records"] == []  # players never see it
    assert len(eng.query_canon("gm", "warden is bought")["records"]) == 1


def test_plain_clocks_fold_unchanged_and_replay(lantern):
    eng = table(lantern)
    eng.create_clock("plain", "No schedule", 4)
    assert eng.state["clocks"]["plain"] == {"label": "No schedule", "filled": 0, "total": 4, "visible": True}
    faction_clock(eng)
    sessions(eng, 4)
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()

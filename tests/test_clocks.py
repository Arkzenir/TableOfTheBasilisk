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


# ---------------------------------------------------------------- limits: the pack's, kernel defaults (T0.39, D-056)

def _with_clocks(packs_dir, tmp_path, block):
    import shutil

    import yaml

    from basilisk.kernel.packs import resolve
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["clocks"] = block
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve("lanternlight", dst)


def test_kernel_defaults_bound_clocks_when_the_pack_says_nothing(lantern):
    from basilisk.kernel.clocks import DEFAULT_LIMITS, limits
    assert limits(lantern) == DEFAULT_LIMITS
    eng = table(lantern)
    eng.start_session()
    for call, fragment in [
        (lambda: eng.create_clock("huge", "Huge", 101), "from 1 to 100 segments"),
        (lambda: eng.create_clock("none", "None", 0), "from 1 to 100 segments"),
        (lambda: eng.create_clock("slow", "Slow", 4, schedule={"every": 13, "amount": 1}), "every must be an integer from 1 to 12"),
        (lambda: eng.create_clock("big", "Big", 4, schedule={"every": 1, "amount": 4}), "amount must be an integer from 1 to 3"),
    ]:
        with pytest.raises(EngineError, match=fragment):
            call()
    eng.create_clock("doom", "Doom", 100)
    with pytest.raises(EngineError, match="a clock advances 1 to 3 segments at a time"):
        eng.advance_clock("doom", 4)


def test_a_pack_sets_its_own_clock_limits(packs_dir, tmp_path):
    from basilisk.kernel.determinism import expand
    from basilisk.kernel.packlint import errors, lint
    from basilisk.kernel.tools import generate
    pack = _with_clocks(packs_dir, tmp_path, {"segments": [4, 12], "advance": [1, 5], "every_sessions": [2, 4]})
    assert errors(lint(pack)) == []
    eng = table(pack)
    eng.start_session()
    with pytest.raises(EngineError, match="from 4 to 12 segments"):
        eng.create_clock("tiny", "Tiny", 3)
    with pytest.raises(EngineError, match="every must be an integer from 2 to 4"):
        eng.create_clock("fast", "Fast", 8, schedule={"every": 1, "amount": 5})
    eng.create_clock("doom", "Doom", 12, schedule={"every": 2, "amount": 5})
    eng.advance_clock("doom", 5)
    assert eng.state["clocks"]["doom"]["filled"] == 5
    assert generate(pack, expand({}), "gm")["advance_clock"]["amount"] == {"enum": [1, 2, 3, 4, 5]}
    judged = [e["payload"] for e in events(eng, "judgement_input") if e["payload"]["control"] == "advance_clock"]
    assert judged[-1]["options"] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("block, fragment", [
    ({"segments": [0, 8]}, "clocks.segments must be [min, max]"),
    ({"advance": [3, 1]}, "clocks.advance must be [min, max]"),
    ({"every_units": 5}, "clocks.every_units must be [min, max]"),
    ({"advance": [1, True]}, "clocks.advance must be [min, max]"),
    ({"segmnts": [1, 8]}, "No clock limit 'segmnts'"),
])
def test_bad_clock_limits_fail_lint(packs_dir, tmp_path, block, fragment):
    from basilisk.kernel.packlint import errors, lint
    found = [f.message for f in errors(lint(_with_clocks(packs_dir, tmp_path, block)))]
    assert any(fragment in m for m in found), found

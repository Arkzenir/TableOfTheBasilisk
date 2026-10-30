"""Watches and calendar (T0.21; ARCHITECTURE §2.2; BUILD_PLAN P0.11)."""

import shutil

import pytest
import yaml

from basilisk.kernel import timekeeping
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import PackError, resolve
from basilisk.kernel.tools import free_values, generate


def table(pack, seed="time-seed"):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    return eng


def events(eng, kind):
    return [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


def test_time_carries_into_larger_units(lantern):
    eng = table(lantern)  # 4 watches to a day, 28 days to a moon
    assert "time" not in eng.state and eng.current_time()["text"] == "Moon 1, Day 1, Watch 1"
    eng.advance_time("watch", 3)
    assert eng.current_time()["units"] == {"watch": 4, "day": 1, "moon": 1}
    eng.advance_time("watch", 1)
    assert eng.current_time()["units"] == {"watch": 1, "day": 2, "moon": 1}
    for days in (12, 12, 3):  # a GM call moves at most 12 of a unit by default (D-057)
        eng.advance_time("day", days)
    assert eng.current_time()["units"] == {"watch": 1, "day": 1, "moon": 2}
    assert eng.elapsed() == 4 + 27 * 4
    assert [(e["unit"], e["amount"], e["from"], e["to"]) for e in events(eng, "time_advanced")] == [
        ("watch", 3, 0, 3), ("watch", 1, 3, 4), ("day", 12, 4, 52), ("day", 12, 52, 100), ("day", 3, 100, 112)]
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_breakdown_is_mixed_radix(lantern):
    assert timekeeping.breakdown(lantern, 9) == {"watch": 2, "day": 3, "moon": 1}
    assert timekeeping.unit_size(lantern, "moon") == 112


def test_time_passes_between_sessions(lantern):
    eng = table(lantern)
    eng.start_session()
    assert eng.elapsed() == 0  # nothing has been played yet
    eng.end_session()
    eng.start_session()
    off_air = events(eng, "time_advanced")
    assert off_air == [{"unit": "day", "amount": 1, "from": 0, "to": 4, "reason": "off_air"}]


def test_clocks_can_run_on_in_world_time(lantern):
    eng = table(lantern)
    eng.advance_time("watch", 2)  # the clock starts counting from now
    eng.create_clock("tide", "The flood tide", 6, schedule={"every": 2, "amount": 1, "unit": "watch"},
                     stages=[{"at": 2, "record": {"type": "event", "name": "The lower quay floods",
                                                  "body": "Water over the stones.", "knowledge": "revealed"}}])
    eng.advance_time("watch", 1)
    assert eng.state["clocks"]["tide"]["filled"] == 0
    eng.advance_time("watch", 1)
    assert eng.state["clocks"]["tide"]["filled"] == 1
    eng.advance_time("day", 1)  # four watches: two more intervals
    assert eng.state["clocks"]["tide"]["filled"] == 3
    assert [e["at"] for e in events(eng, "clock_stage_reached")] == [2]  # its canon was written on the way
    eng.start_session()
    eng.end_session()
    eng.start_session()  # off-air: a day passes, so two intervals, not a session tick
    assert eng.state["clocks"]["tide"]["filled"] == 5
    eng.pause_clock("tide")
    eng.advance_time("day", 2)
    assert eng.state["clocks"]["tide"]["filled"] == 5


def test_refusals(lantern, tide):
    eng = table(lantern)
    with pytest.raises(EngineError, match="only the GM"):
        eng.advance_time("watch", 1, by="ash")
    with pytest.raises(EngineError, match="No time unit 'hour'"):
        eng.advance_time("hour", 1)
    with pytest.raises(EngineError, match="1 to 12 watch"):
        eng.advance_time("watch", 0)
    with pytest.raises(EngineError, match="1 to 12 watch"):
        eng.advance_time("watch", 13)
    with pytest.raises(EngineError, match="No time unit 'hour'"):
        eng.create_clock("c", "C", 4, schedule={"every": 1, "unit": "hour"})
    t = Engine.start_campaign(tide, "t", {"seats": {"gm": "gm"}}, clock=lambda: None)
    with pytest.raises(EngineError, match="keeps no calendar"):
        t.advance_time("day", 1)
    assert t.current_time() is None


@pytest.mark.parametrize("time, fragment", [
    ({"units": [{"id": "watch", "label": "Watch", "per": 1}, {"id": "day", "label": "Day"}]}, "per must be"),
    ({"units": [{"id": "watch", "per": 4}, {"id": "day", "label": "Day"}]}, "needs a label"),
    ({"units": [{"id": "watch", "label": "Watch"}], "between_sessions": {"unit": "year"}}, "No time unit 'year'"),
])
def test_bad_calendars_fail_lint(packs_dir, tmp_path, time, fragment):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["time"] = time
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f.message for f in errors(lint(resolve("lanternlight", dst))) if f.code == "time"]
    assert any(fragment in m for m in found), found


def test_a_duplicate_time_unit_is_refused_by_name(packs_dir, tmp_path):
    """Caught before lint since T0.31: the loader refuses an id declared twice in one pack."""
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["time"] = {"units": [{"id": "watch", "label": "Watch", "per": 4}, {"id": "watch", "label": "Day"}]}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(PackError, match="declares an id twice in one catalogue: time.units: watch"):
        resolve("lanternlight", dst)


def test_time_tool(lantern, tide):
    eff = table(lantern).state["determinism"]["effective"]
    gm = generate(lantern, eff, "gm")
    assert gm["advance_time"]["unit"] == {"enum": ["day", "moon", "watch"]} and not free_values(gm["advance_time"])
    assert "advance_time" not in generate(lantern, eff, "players")
    assert "advance_time" not in generate(tide, eff, "gm")

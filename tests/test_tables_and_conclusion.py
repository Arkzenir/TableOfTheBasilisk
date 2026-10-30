"""Lookup tables in play, per-unit time limits, and concluding a campaign
(T0.40; ARCHITECTURE §2.3, §5.5, §7.1; D-057)."""

import shutil

import pytest
import yaml

from basilisk.harness.scripted import verify
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.determinism import expand
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.events import EventStoreError
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import generate

SEED = "tables-seed"


def _variant(packs_dir, tmp_path, fn, pid="lanternlight"):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / pid / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve(pid, dst)


def table(pack):
    eng = Engine.start_campaign(pack, SEED, {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.start_session()
    eng.set_scene("hall")
    return eng


def events(eng, kind):
    return [e for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


# ---------------------------------------------------------------- lookup tables in play

def test_the_gm_rolls_a_lookup_table_on_the_seeded_stream(lantern):
    eng = table(lantern)
    tdef = lantern.by_id("randomizers.tables")["detail_table"]
    result = eng.roll_table("detail_table")
    rolled = events(eng, "table_rolled")[-1]
    roll = events(eng, "roll_made")[-1]
    assert rolled["caused_by"] == roll["seq"] and roll["payload"]["purpose"] == "table:detail_table"
    assert rolled["payload"] == {"table": "detail_table", "value": result["value"], "text": result["text"],
                                 "by": "gm", "purpose": "play"}
    entry = next(e for e in tdef["entries"] if e["range"][0] <= result["value"] <= e["range"][1])
    assert result["text"] == entry["text"]
    judged = events(eng, "judgement_input")[-1]["payload"]
    assert judged["control"] == "roll_table" and judged["choice"] == {"table_id": "detail_table"}
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()
    assert verify(eng.store, eng.campaign_id, lantern, SEED) == []  # the roll re-derives from the seed


def test_players_roll_only_tables_the_pack_opens_to_them(lantern, packs_dir, tmp_path):
    eng = table(lantern)
    with pytest.raises(EngineError, match="No table you can roll 'detail_table'"):
        eng.roll_table("detail_table", by="ash")
    assert "roll_table" not in generate(lantern, expand({}), "players")
    assert generate(lantern, expand({}), "gm")["roll_table"] == {"table_id": {"enum": ["detail_table"]}}
    opened = _variant(packs_dir, tmp_path, lambda d: d.setdefault("randomizers", {}).setdefault("tables", []).append(
        {"id": "omen", "roll": "1d2", "players_roll": True,
         "entries": [{"range": [1, 1], "text": "a crow"}, {"range": [2, 2], "text": "a candle gutters"}]}))
    assert errors(lint(opened)) == []
    eng = table(opened)
    assert eng.roll_table("omen", by="ash")["text"] in ("a crow", "a candle gutters")
    assert generate(opened, expand({}), "players")["roll_table"] == {"table_id": {"enum": ["omen"]}}
    with pytest.raises(EngineError, match="No table you can roll"):
        eng.roll_table("detail_table", by="ash")


def test_players_roll_must_be_a_boolean(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, lambda d: d.setdefault("randomizers", {}).setdefault("tables", []).append(
        {"id": "omen", "roll": "1d2", "players_roll": "yes",
         "entries": [{"range": [1, 2], "text": "a crow"}]}))
    assert any("players_roll is true or false" in f.message for f in errors(lint(pack)))


# ---------------------------------------------------------------- time-advance limits per unit

def test_each_time_unit_sets_how_far_one_call_moves(packs_dir, tmp_path):
    def limits(d):
        d["time"]["units"][1]["advance"] = [1, 28]  # days: up to a moon
    pack = _variant(packs_dir, tmp_path, limits)
    assert errors(lint(pack)) == []
    eng = table(pack)
    eng.advance_time("day", 28)
    with pytest.raises(EngineError, match="advance time by 1 to 12 watch"):
        eng.advance_time("watch", 13)  # the default holds for units that say nothing
    assert generate(pack, expand({}), "gm")["advance_time"]["amount"] == {"enum": list(range(1, 29))}


@pytest.mark.parametrize("value", [[0, 4], [5, 2], [1, 10_000], 7, [1, True]])
def test_bad_time_advance_limits_fail_lint(packs_dir, tmp_path, value):
    pack = _variant(packs_dir, tmp_path, lambda d: d["time"]["units"][0].update(advance=value))
    assert any("advance must be [min, max]" in f.message for f in errors(lint(pack)))


# ---------------------------------------------------------------- concluding a campaign (§5.5)

def test_concluding_reveals_the_seed_and_ends_play(lantern):
    eng = table(lantern)
    with pytest.raises(EngineError, match="still open"):
        eng.conclude_campaign(SEED)
    eng.end_session()
    with pytest.raises(EngineError, match="does not match the campaign's seed commitment"):
        eng.conclude_campaign("a-guess")
    with pytest.raises(EngineError, match="only the operator"):
        eng.conclude_campaign(SEED, by="gm")
    seq = eng.conclude_campaign(SEED)
    assert events(eng, "campaign_concluded")[-1]["payload"] == {"seed": SEED}
    assert eng.state["campaign"]["concluded"] is True
    head = eng.store.head(eng.campaign_id)
    for call in (eng.start_session, lambda: eng.spawn_entity("late", "Late"), lambda: eng.conclude_campaign(SEED)):
        with pytest.raises(EngineError, match="has concluded"):
            call()
    assert eng.store.head(eng.campaign_id) == head
    assert eng.read_sheet("ash")  # reads still work
    assert verify(eng.store, eng.campaign_id, lantern) == []  # no seed passed: the log carries it
    with pytest.raises(EventStoreError, match="has concluded by seq"):
        eng.store.fork(eng.campaign_id, seq, "after_the_end")
    eng.store.fork(eng.campaign_id, seq - 1, "before_the_end")
    branch = Engine.load(lantern, SEED, eng.store, "before_the_end", clock=lambda: None)
    branch.start_session()  # a fork before the conclusion plays on (debugging only, P6)
    reloaded = Engine.load(lantern, SEED, eng.store, eng.campaign_id, clock=lambda: None)
    assert reloaded.state_hash() == eng.state_hash()
    with pytest.raises(EngineError, match="has concluded"):
        reloaded.start_session()


def test_a_revealed_seed_that_does_not_rederive_is_caught(lantern):
    eng = table(lantern)
    eng.end_session()
    eng.conclude_campaign(SEED)
    assert verify(eng.store, eng.campaign_id, lantern, "someone-elses-seed") == [
        "seed does not match the published commitment"]

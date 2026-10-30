"""Seats, session lifecycle, GM authority, and the fixes from the fourth Phase 0
audit (T0.38; §3.1, §5.4, §2.6, §2.13, §5.6, BUILD_PLAN P0.1, P0.4, P0.12)."""

import shutil
import socket
import subprocess
import sys

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.events import EventStore, EventStoreError
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve, scaffold
from basilisk.harness.scripted import run_script, smoke_script


def lantern_table(pack, seats=None):
    eng = Engine.start_campaign(pack, "audit-seed", {"seats": seats or {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.start_session()
    eng.set_scene("hall")
    return eng


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


def _variant(packs_dir, tmp_path, pid, fn):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / pid / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve(pid, dst)


# ---------------------------------------------------------------- seats and campaign config (§3.1)

@pytest.mark.parametrize("config, fragment", [
    ({"seats": {f"p{i}": "player" for i in range(5)}}, "at most 4 player seats"),
    ({"seats": {"engine": "player"}}, "the engine's own names"),
    ({"seats": {"operator": "gm"}}, "the engine's own names"),
    ({"seats": {"gm": "player", "boss": "gm"}}, "a seat called gm must be the GM's seat"),
    ({"seats": {"Ash Smith": "player"}}, "seat ids are lowercase"),
    ({"seats": {1: "player"}}, "seat ids are lowercase"),
    ({"seats": {"ash": "wizard"}}, "roles are gm or player"),
    ({"seats": {"a": "gm", "b": "gm"}}, "at most one GM seat"),
    ({"seats": ["ash"]}, "seats is a mapping"),
    ({"gm_traits": {"lethality": "high"}}, "gm_traits.lethality must be an integer from 0 to 100"),
    ({"gm_traits": {"fudging": 900}}, "gm_traits.fudging must be an integer from 0 to 100"),
    ({"determinism": "strict"}, "determinism is a mapping"),
])
def test_bad_campaign_config_is_refused_with_a_named_error(lantern, config, fragment):
    with pytest.raises(EngineError, match=fragment):
        Engine.start_campaign(lantern, "s", config)


def test_four_players_and_a_gm_is_the_full_table(lantern):
    seats = {"gm": "gm", **{f"p{i}": "player" for i in range(4)}}
    assert Engine.start_campaign(lantern, "s", {"seats": seats}).seats == seats


# ---------------------------------------------------------------- session lifecycle

def test_sessions_open_and_close_in_turn(lantern):
    eng = Engine.start_campaign(lantern, "s", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    with pytest.raises(EngineError, match="no session is open"):
        eng.end_session()
    with pytest.raises(EngineError, match="start a session before setting a scene"):
        eng.set_scene("hall")
    eng.start_session()
    with pytest.raises(EngineError, match="session 1 is still open"):
        eng.start_session()
    eng.end_session()
    before = frozen(eng)
    with pytest.raises(EngineError, match="no session is open"):
        eng.end_session()  # would award session-end progression a second time
    with pytest.raises(EngineError, match="start a session before setting a scene"):
        eng.set_scene("after_hours")
    assert frozen(eng) == before
    eng.start_session(by="operator")  # the operator runs the show (§9.3)
    assert eng.state["session"] == 2


# ---------------------------------------------------------------- mutation authority (§5.4)

@pytest.mark.parametrize("call", [
    lambda e: e.create_clock("mine", "Mine", 4, by="ash"),
    lambda e: e.advance_clock("doom", 1, by="ash"),
    lambda e: e.set_scene("elsewhere", by="ash"),
    lambda e: e.end_session(by="ash"),
])
def test_gm_commands_refuse_a_player_seat(lantern, call):
    eng = lantern_table(lantern)
    eng.create_clock("doom", "Doom", 6)
    before = frozen(eng)
    with pytest.raises(EngineError, match="only the GM"):
        call(eng)
    assert frozen(eng) == before


# ---------------------------------------------------------------- effects (§2.6)

def test_an_item_cannot_be_given_to_its_holder(lantern):
    eng = lantern_table(lantern)
    ids = {"actor": "ash", "target": "ash", "self": "ash"}
    eng._apply_effect({"primitive": "create_item", "target": "actor", "item": "rope"}, ids, None, {})
    with pytest.raises(EngineError, match="cannot give 'rope' to itself"):
        eng._apply_effect({"primitive": "transfer_item", "from": "actor", "to": "self", "item": "rope"}, ids, None, {})
    assert eng.state["entities"]["ash"]["inventory"] == ["rope"]


@pytest.mark.parametrize("primitive", ["earn_currency", "spend_currency"])
def test_a_rolled_amount_below_zero_moves_no_currency(lantern, primitive):
    eng = lantern_table(lantern)
    ids = {"actor": "ash", "target": None, "self": "ash"}
    eng._apply_effect({"primitive": primitive, "target": "actor", "currency": "luck", "amount": "1d1 - 5"},
                      ids, None, {})
    assert eng.currency("ash", "luck") == 1 and eng.sheet_problems("ash") == []
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


# ---------------------------------------------------------------- GM inputs are used or refused (§2.13.5)

@pytest.mark.parametrize("action, kwargs, fragment", [
    ("rest", {"gm": {"tags": ["aided"]}}, "rest has no roll|automatic has no roll"),
    ("strike", {"target": "bram", "gm": {"difficulty": "hard"}}, "derived from state"),
    ("recall", {"gm": {"difficulty": "easy", "tag": ["aided"]}}, "gm has no 'tag'"),
    ("rest", {"spend": 1}, "rest has no cost; leave out spend"),
])
def test_a_gm_input_the_procedure_ignores_is_refused(lantern, action, kwargs, fragment):
    eng = lantern_table(lantern)
    before = frozen(eng)
    with pytest.raises(EngineError, match=fragment):
        eng.commit_action("ash", action, **kwargs)
    assert frozen(eng) == before


def test_unmodelled_resolution_names_bad_stats_and_can_oppose(lantern):
    eng = lantern_table(lantern)
    with pytest.raises(EngineError, match="No stat 'zzz'"):
        eng.resolve_unmodelled("ash", "check", stat="zzz", difficulty="easy")
    result = eng.resolve_unmodelled("ash", "opposed", stat="might", target="bram")
    assert result["outcome"] in ("fail", "pass")
    resolution = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "gm_resolution"][-1]
    assert resolution["target"] == "bram"
    with pytest.raises(EngineError, match="is opposed"):
        eng.resolve_unmodelled("ash", "opposed", stat="might", target="bram", difficulty="easy")


# ---------------------------------------------------------------- decks: hands by controller

def test_a_player_handles_the_cards_of_the_character_they_control(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, "tidewrack", lambda d: d["randomizers"]["decks"][0].update(players_draw=True))
    eng = Engine.start_campaign(pack, "s", {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"}, entity_id="ash_pc")
    eng.start_session()
    eng.set_scene("deck")
    card = eng.draw_card("omens", by="ash", to="ash_pc")
    eng.discard_card("omens", card, "ash_pc", by="ash")  # the PC's id is not the seat's
    with pytest.raises(EngineError, match="a player draws into their own hand"):
        eng.draw_card("omens", by="ash", to="bram")
    with pytest.raises(EngineError, match="only ash_pc's controller or the GM"):
        eng.discard_card("omens", card, "ash_pc", by="bram")


# ---------------------------------------------------------------- event store and CLI (§5.6)

def test_a_fork_is_all_or_nothing(lantern):
    eng = lantern_table(lantern)
    head = eng.store.head(eng.campaign_id)[0]
    for seq in (0, head + 1, -1):
        with pytest.raises(EventStoreError, match="fork seq must be from 1 to"):
            eng.store.fork(eng.campaign_id, seq, f"bad{seq}")
    assert eng.store.campaigns() == [eng.campaign_id]
    assert eng.store.fork(eng.campaign_id, head, "good") == head


def _tob(*args):
    return subprocess.run([sys.executable, "-m", "basilisk.cli", *args], capture_output=True, text=True)


def test_verify_never_passes_a_store_that_is_not_there(tmp_path):
    missing = tmp_path / "typo.db"
    with pytest.raises(EventStoreError, match="no event store at"):
        EventStore(missing, create=False)
    run = _tob("verify", str(missing))
    assert run.returncode == 1 and "no event store at" in run.stderr and not missing.exists()
    EventStore(tmp_path / "empty.db").close()
    run = _tob("verify", str(tmp_path / "empty.db"))
    assert run.returncode == 1 and "no campaigns to verify" in run.stdout


# ---------------------------------------------------------------- lint and the scaffold

@pytest.mark.parametrize("edit, fragment", [
    (lambda d: d["actions"][2]["outcome_effects"]["pass"][0].update(amount=-2), "amount cannot be negative"),
    (lambda d: d["actions"][2]["outcome_effects"]["pass"].append(
        {"primitive": "transfer_item", "from": "actor", "to": "actor", "item": "rope"}), "are the same holder"),
])
def test_effects_that_cannot_mean_anything_fail_lint(packs_dir, tmp_path, edit, fragment):
    found = [f.message for f in errors(lint(_variant(packs_dir, tmp_path, "lanternlight", edit)))]
    assert any(fragment in m for m in found), found


@pytest.mark.parametrize("edit, fragment", [
    (lambda d: d["gm"]["consequence_tables"][0]["entries"][0].update(weight=0), "weight must be a positive integer"),
    (lambda d: d["randomizers"]["decks"][0].update(players_draw="yes"), "players_draw is true or false"),
])
def test_draw_settings_must_be_well_formed(packs_dir, tmp_path, edit, fragment):
    found = [f.message for f in errors(lint(_variant(packs_dir, tmp_path, "tidewrack", edit)))]
    assert any(fragment in m for m in found), found


@pytest.mark.parametrize("baseline", ["core.roll_over", "core.banded"])
def test_a_fresh_scaffold_runs_a_smoke_campaign(packs_dir, tmp_path, baseline):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    scaffold("my_game", baseline, dst)
    pack = resolve("my_game", dst)
    engine, report = run_script(smoke_script(pack, sessions=1, seed="scaffold"), dst)
    assert report.actions_taken == {} and report.actions_never_taken == [] and report.rejected == []
    assert engine.state["session"] >= 1 and report.events > 0


# ---------------------------------------------------------------- the offline rule

def test_the_default_run_cannot_open_a_connection():
    with pytest.raises(RuntimeError, match="network access in an offline test"):
        socket.create_connection(("example.com", 80), timeout=1)

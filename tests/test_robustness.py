"""Ids the engine keys state by, errors that never name hidden things, readable
errors from reads, and snapshots at every boundary (T0.33; ARCHITECTURE §5.2,
§5.6, §7, P3; BUILD_PLAN P0.1, P0.3, P0.10)."""

import shutil

import pytest
import yaml

from basilisk.harness.scripted import run_script, smoke_script, verify
from basilisk.kernel import KERNEL_VERSION
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve


def lantern_table(pack):
    eng = Engine.start_campaign(pack, "robust", {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.start_session()
    return eng


def _variant(packs_dir, tmp_path, pid, fn):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / pid / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve(pid, dst)


# ---------------------------------------------------------------- ids (§5.6: state stays canonical)

@pytest.mark.parametrize("call, fragment", [
    (lambda e: e.spawn_entity(7, "Seven"), "entity id 7 must be lowercase letters"),
    (lambda e: e.spawn_entity(None, "Nobody"), "entity id None must be"),
    (lambda e: e.spawn_entity("", "Nobody"), "entity id '' must be"),
    (lambda e: e.spawn_entity("Bad Id!", "X"), "entity id 'Bad Id!' must be"),
    (lambda e: e.spawn_entity("players", "X"), "entity id 'players' is reserved"),
    (lambda e: e.spawn_entity("engine", "X"), "entity id 'engine' is reserved"),
    (lambda e: e.spawn_entity("foe", ""), "an entity's name must be non-empty text"),
    (lambda e: e.spawn_entity("foe", "Foe", stats={"might": 1.5}), "stat 'might' must be an integer"),
    (lambda e: e.create_clock(0, "Doom", 4), "clock id 0 must be"),
    (lambda e: e.create_clock("doom", "", 4), "a clock's label must be non-empty text"),
    (lambda e: e.set_scene(""), "scene id '' must be"),
    (lambda e: e.set_scene("hall", flags={0: 1}), "scene flag 0"),
    (lambda e: e.set_scene("hall", flags={"dark": "yes"}), "scene flag 'dark'"),
    (lambda e: e.create_character("bram", "", {"background": "scholar"}), "a character's name must be non-empty"),
    (lambda e: e.create_character("bram", "Bram", {"background": "scholar"}, entity_id="gm"), "is reserved"),
])
def test_bad_ids_and_names_are_refused_atomically(lantern, call, fragment):
    eng = lantern_table(lantern)
    before = eng.store.head(eng.campaign_id)
    with pytest.raises(EngineError, match=fragment):
        call(eng)
    assert eng.store.head(eng.campaign_id) == before
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()  # still canonical


def test_settings_errors_are_engine_errors(lantern):
    eng = lantern_table(lantern)
    with pytest.raises(EngineError, match="unknown role"):
        eng.request_determinism_change(by="operator", role="wizards", preset="strict")


# ---------------------------------------------------------------- errors never name hidden entities (P3)

def test_an_unknown_target_lists_only_what_the_player_sees(lantern):
    eng = lantern_table(lantern)
    eng.spawn_entity("assassin", "Assassin")
    eng.spawn_entity("guard_1", "Guard")
    eng.set_scene("hall", regions=[{"id": "a"}], placements={"ash": "a", "assassin": "a", "guard_1": "a"})
    eng.set_visibility("assassin", [])
    for target in ("ghost", "assassin"):  # a hidden entity reads as absent too
        with pytest.raises(EngineError) as err:
            eng.commit_action("ash", "strike", target=target)
        message = str(err.value)
        assert "assassin" not in message.replace(f"'{target}'", "") and "guard_1" in message
        assert "spawn_entity" in message  # the promotion rule (§5.2)
    with pytest.raises(EngineError, match="assassin"):  # the GM sees everything
        eng.commit_action("guard_1", "strike", target="assasin", by="gm")


def test_a_draw_to_an_unknown_holder_lists_only_what_the_drawer_sees(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, "tidewrack",
                    lambda d: d["randomizers"]["decks"][0].__setitem__("players_draw", True))
    eng = Engine.start_campaign(pack, "draw", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.spawn_entity("lurker", "Lurker")
    eng.start_session()
    eng.set_scene("deck", participants=["ash", "lurker"])
    eng.set_visibility("lurker", [])
    deck = pack.catalogue("randomizers.decks")[0]["id"]
    with pytest.raises(EngineError) as err:
        eng.draw_card(deck, by="ash", to="nobody")
    assert "lurker" not in str(err.value) and "ash" in str(err.value)


@pytest.mark.parametrize("read", ["position_of", "reachable", "steps_from"])
def test_reads_name_an_unknown_entity(lantern, read):
    eng = lantern_table(lantern)
    eng.set_scene("hall", regions=[{"id": "a"}], placements={"ash": "a"})
    with pytest.raises(EngineError, match="No entity 'nope'"):
        getattr(eng, read)("nope")


# ---------------------------------------------------------------- reactions pass lint (§2.3, §2.4)

def test_a_reaction_action_is_lint_clean(packs_dir, tmp_path):
    def react(d):
        d["actions"].append({"id": "parry", "trigger": "reaction", "procedure": "automatic", "outcome_effects": {}})
        d["presentation"]["rule_cards"]["parry"] = {"title": "Parry", "summary": "Answer a provoke.",
                                                    "category": "action", "icon_id": "shield"}
    assert errors(lint(_variant(packs_dir, tmp_path, "lanternlight", react))) == []


# ---------------------------------------------------------------- snapshots and resume (§5.6)

def test_snapshots_are_taken_at_every_boundary(packs_dir, lantern):
    script = smoke_script(lantern, sessions=2)
    engine, report = run_script(script, packs_dir)
    store, cid = engine.store, report.campaign_id
    marks = {e["seq"] for e in store.read(cid) if e["type"] in ("session_started", "session_ended", "scene_set")}
    encounters = [e["seq"] for e in store.read(cid) if e["type"] == "encounter_started"]
    snaps = {r[0] for r in store.db.execute("SELECT seq FROM snapshots WHERE campaign_id=?", (cid,))}
    assert encounters and {s - 1 for s in encounters} <= snaps  # the state just before each encounter
    assert len(snaps) >= len(marks) // 2
    for seq in sorted(snaps):  # every snapshot is the fold of the log up to it
        snap = store.latest_snapshot(cid, at_or_before=seq)
        assert snap["state_hash"] == hash_obj(fold(store.read(cid, upto=seq)))
    assert verify(store, cid, lantern, script["seed"], report.state_hash) == []


def test_resume_folds_from_the_snapshot_and_refuses_damage(packs_dir, lantern):
    script = smoke_script(lantern, sessions=1)
    engine, report = run_script(script, packs_dir)
    store, cid = engine.store, report.campaign_id
    resumed = Engine.load(lantern, script["seed"], store, cid)
    assert resumed.state_hash() == Engine.load(lantern, script["seed"], store, cid, use_snapshot=False).state_hash() \
        == report.state_hash
    head = store.head(cid)[0]
    store.write_snapshot(cid, head, fold(store.read(cid)), "f" * 64, KERNEL_VERSION)
    with pytest.raises(EngineError, match="taken under another pack or kernel"):
        Engine.load(lantern, script["seed"], store, cid)
    store.write_snapshot(cid, head, fold(store.read(cid)), lantern.hash, KERNEL_VERSION)
    store.db.execute("DROP TRIGGER events_no_update")
    store.db.execute("UPDATE events SET body=replace(body, '\"number\":1', '\"number\":2') WHERE seq=("
                     "SELECT seq FROM events WHERE campaign_id=? AND body LIKE '%session_started%' LIMIT 1)", (cid,))
    with pytest.raises(EngineError, match="log is damaged"):
        Engine.load(lantern, script["seed"], store, cid)

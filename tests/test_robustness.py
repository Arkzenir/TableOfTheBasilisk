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


def test_the_kernel_reads_no_wall_clock(lantern):
    """Event timestamps come from the host (§5.7); without a clock they are null (T0.36)."""
    eng = Engine.start_campaign(lantern, "clockless", {"seats": {"gm": "gm"}})
    assert {e["ts"] for e in eng.store.read(eng.campaign_id)} == {None}
    stamped = Engine.start_campaign(lantern, "stamped", {"seats": {"gm": "gm"}}, clock=lambda: "2026-10-28T00:00:00Z")
    assert {e["ts"] for e in stamped.store.read(stamped.campaign_id)} == {"2026-10-28T00:00:00Z"}


# ---------------------------------------------------------------- T0.37: turns never name the unseen (P3)

def _hidden_encounter(pack, order=None):
    eng = Engine.start_campaign(pack, "unseen", {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.spawn_entity("lurker", "Lurker")
    eng.start_session()
    eng.set_scene("hall", encounter=True, regions=[{"id": "a"}], placements={"ash": "a", "bram": "a", "lurker": "a"})
    eng.set_visibility("lurker", ["bram"])
    if order == "fixed":
        eng.start_encounter(["ash", "lurker", "bram"])
    else:
        eng.start_encounter(first="ash")
    return eng


def test_the_turn_view_hides_unseen_entities(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, "lanternlight", lambda d: d["turn_structure"]["encounter"].update(
        {"order": "fixed"}))
    eng = _hidden_encounter(pack, "fixed")
    assert eng.current_turn("ash")["up_next"] is None and eng.current_turn("bram")["up_next"] == "lurker"
    assert eng.current_turn()["up_next"] == "lurker"  # the scheduler's unscoped view
    seen = eng.end_turn(by="ash")
    assert seen["actor"] is None and seen["kind"] == "unseen" and "lurker" not in seen["budgets"]
    with pytest.raises(EngineError) as err:
        eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    assert "someone else's turn" in str(err.value) and "lurker" not in str(err.value)
    assert eng.current_turn("gm")["actor"] == "lurker"


def test_a_player_hands_off_only_to_someone_they_see(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, "lanternlight", lambda d: d["turn_structure"]["encounter"].update(
        {"order": "handoff", "economy": "none"}))
    eng = _hidden_encounter(pack, "handoff")
    assert eng.current_turn("ash")["actor"] == "ash"
    with pytest.raises(EngineError) as err:
        eng.end_turn(by="ash")
    assert "lurker" not in str(err.value) and "bram" in str(err.value)
    with pytest.raises(EngineError, match="No next participant 'lurker'"):
        eng.end_turn(by="ash", next="lurker")
    assert eng.end_turn(by="ash", next="bram")["actor"] == "bram"


# ---------------------------------------------------------------- T0.37: lint and speed

@pytest.mark.parametrize("edit, fragment", [
    (lambda d: d["actions"][0]["outcome_effects"]["pass"][0].__setitem__("amont", 1),
     "has no parameter 'amont'"),
    (lambda d: d["entity_model"]["resources"][0].update({"min": 30}), "below its min 30"),
])
def test_misspelt_effect_parameters_and_impossible_maxima_fail_lint(packs_dir, tmp_path, edit, fragment):
    found = [f.message for f in errors(lint(_variant(packs_dir, tmp_path, "lanternlight", edit)))]
    assert any(fragment in m for m in found), found


def test_the_incremental_canon_index_equals_a_fresh_build(lantern):
    from basilisk.kernel.canon import CanonIndex
    eng = lantern_table(lantern)
    for n in range(60):
        rec = {"id": f"f{n}", "type": "fact", "name": f"Rumour {n} of the {['north', 'mill', 'quay'][n % 3]}",
               "body": "x", "origin": "prepped", "knowledge": "secret" if n % 4 == 3 else "revealed",
               "depends_on": [f"f{n - 2}"] if n >= 2 else []}
        if rec["knowledge"] == "secret":
            rec["discovery_paths"] = ["ash"]
        eng.write_canon(rec)
        if n % 10 == 9:
            eng.query_canon("players", "mill")
    for scope in ("gm", "players"):
        inc, fresh = eng._canon_index(scope), CanonIndex(eng.state["canon"], scope)
        for field in ("records", "current", "aliases", "tokens", "graph", "predecessor"):
            assert getattr(inc, field) == getattr(fresh, field), (scope, field)


def test_near_collision_candidates_change_no_result():
    import difflib
    import random
    from basilisk.kernel.canon import CanonIndex
    rng = random.Random(7)
    syllables = ["var", "ro", "the", "ka", "mir", "sel", "dun", "tor", "ash", "bel"]
    records = {}
    for n in range(300):
        name = " ".join("".join(rng.choice(syllables) for _ in range(rng.randint(1, 4))) for _ in range(rng.randint(1, 2)))
        records[f"r{n}"] = {"id": f"r{n}", "type": "npc", "name": name, "aliases": [], "body": "", "knowledge": "revealed",
                            "depends_on": [], "discovery_paths": [], "origin": "prepped", "superseded_by": None}
    index = CanonIndex(records, "gm")
    for _ in range(200):
        key = "".join(rng.choice(syllables) for _ in range(rng.randint(1, 5)))
        everything = sorted(index.aliases)
        assert difflib.get_close_matches(key, index.near_candidates(key, 0.85, None), n=3, cutoff=0.85) == \
            difflib.get_close_matches(key, everything, n=3, cutoff=0.85)


def test_plain_copy_is_a_deep_copy(lantern):
    from basilisk.kernel.command import plain_copy
    eng = lantern_table(lantern)
    copied = plain_copy(eng.state)
    assert copied == eng.state and hash_obj(copied) == eng.state_hash()
    copied["entities"]["ash"]["stats"]["might"] = 99
    assert eng.state["entities"]["ash"]["stats"]["might"] != 99

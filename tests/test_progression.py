"""Progression: XP, marks, milestones, and use (T0.27; BUILD_PLAN P0.15, ARCHITECTURE §2.3)."""

import shutil

import pytest
import yaml

from basilisk.harness.scripted import run_script, smoke_script, verify
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.determinism import STRICT, expand
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import free_values, generate

SEATS = {"seats": {"gm": "gm", "ash": "player", "bram": "player"}}


def table(pack, choices):
    eng = Engine.start_campaign(pack, "prog", SEATS, clock=lambda: None)
    eng.create_character("ash", "Ash", choices)
    eng.start_session()
    eng.set_scene("s", flags={"danger": 1})
    return eng


def variant(packs_dir, tmp_path, pack_id, progression):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / pack_id / "pack.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["progression"] = progression
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return resolve(pack_id, dst)


def events(eng, kind):
    return [e for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


def progress(eng, eid="ash"):
    return eng._progress(eng.state["entities"][eid])


def replays(eng):
    return hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def legal(eng, eid="ash"):
    """Lanternlight's advances that fit the rolled stats: each within -1..3, Lamplighter at Wits 1+."""
    stats = eng.state["entities"][eid]["stats"]
    out = [a["id"] for a in eng.pack.get("progression")["advances"]
           if all(stats[k] + d <= 3 for k, d in a["stats"].items())]
    return [a for a in out if a != "lamplighter" or stats["wits"] >= 1]


def frozen(eng):
    return eng.store.head(eng.campaign_id), eng.state_hash()


def test_xp_from_failures_and_session_ends(lantern):
    eng = table(lantern, {"background": "soldier"})
    for _ in range(6):
        eng.commit_action("ash", "recall", gm={"difficulty": "hard"})
    fails = sum(1 for e in events(eng, "procedure_resolved") if e["payload"]["outcome"] == "fail")
    assert progress(eng)["points"] == fails  # one point per failed roll, nothing for a pass
    eng.end_session()
    assert progress(eng)["points"] == fails + 2
    awards = [e["payload"]["reason"] for e in events(eng, "progress_awarded")]
    assert awards.count("session_end") == 1 and awards.count("outcome:fail") == fails
    assert progress(eng)["pending"] == sum(1 for t in (4, 9, 15, 22, 30) if fails + 2 >= t)
    assert replays(eng)


def test_an_advance_is_an_enumerated_logged_choice(lantern):
    eng = table(lantern, {"background": "soldier"})
    eng.end_session()
    eng.start_session()
    eng.end_session()  # 4 XP: the first threshold
    assert progress(eng)["pending"] == 1
    options = eng.advance_options("ash")
    assert options == legal(eng) and options
    pick = options[-1]
    stat, delta = next(iter(next(a for a in eng.pack.get("progression")["advances"] if a["id"] == pick)["stats"].items()))
    before = eng.state["entities"]["ash"]["stats"][stat]
    eng.take_advance("ash", pick)
    assert eng.state["entities"]["ash"]["stats"][stat] == before + delta
    assert progress(eng) == {"points": 4, "pending": 0, "advances": [pick], "uses": {}}
    judged = events(eng, "judgement_input")[-1]["payload"]
    assert judged["control"] == "advance" and judged["choice"] == pick and judged["options"] == options
    assert eng.sheet_problems("ash") == [] and replays(eng)


def test_no_advance_the_pack_does_not_offer(lantern):
    eng = table(lantern, {"background": "soldier"})  # Might 1 to 3 after the roll
    with pytest.raises(EngineError, match="no advance due"):
        eng.take_advance("ash", "nimbler")
    for _ in range(15):
        eng.end_session()
        eng.start_session()  # 30 XP: five advances due
    before = frozen(eng)
    with pytest.raises(EngineError, match="No advance 'flight'"):
        eng.take_advance("ash", "flight")
    with pytest.raises(EngineError, match="does not control"):
        eng.take_advance("ash", "nimbler", by="bram")
    assert frozen(eng) == before
    while eng.state["entities"]["ash"]["stats"]["might"] < 3:
        eng.take_advance("ash", "hardier")
    assert "hardier" not in eng.advance_options("ash")  # past the stat's range
    before = frozen(eng)
    with pytest.raises(EngineError, match="No advance 'hardier'"):
        eng.take_advance("ash", "hardier")
    assert frozen(eng) == before
    while options := eng.advance_options("ash"):
        assert options == legal(eng)  # Lamplighter appears only once Wits reaches 1
        eng.take_advance("ash", options[0])


def test_once_advances_are_taken_once(lantern):
    eng = table(lantern, {"background": "scholar"})  # Wits 1 or more
    for _ in range(15):
        eng.end_session()
        eng.start_session()  # 30 XP: every threshold
    assert eng.state["entities"]["ash"]["stats"]["wits"] >= 1
    eng.take_advance("ash", "lamplighter")
    assert "lamplighter" not in eng.advance_options("ash")
    while options := eng.advance_options("ash"):
        eng.take_advance("ash", options[0])
        assert eng.sheet_problems("ash") == []
    assert replays(eng)


def test_marks_on_misses(tide):
    eng = table(tide, {"playbook": "warden"})
    for _ in range(8):
        eng.commit_action("ash", "defy_danger")
        for slot, info in eng.open_rulings().items():
            eng.fill_ruling(slot, info["entries"][0])
    bad = sum(1 for e in events(eng, "procedure_resolved") if e["payload"]["outcome"] in ("miss", "fail"))
    assert progress(eng)["points"] == bad
    eng.end_session()
    assert progress(eng)["points"] == bad  # marks come only from outcomes here
    assert progress(eng)["pending"] == sum(1 for t in (3, 6, 10, 15) if bad >= t)
    assert replays(eng)


MILESTONE = {"model": "milestone", "advances": [{"id": "hardier", "stats": {"might": 1}},
                                                {"id": "sharper", "stats": {"wits": 1}}]}


def test_milestones_come_from_the_gm(packs_dir, tmp_path, lantern):
    pack = variant(packs_dir, tmp_path, "lanternlight", MILESTONE)
    assert errors(lint(pack)) == []
    eng = table(pack, {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.end_session()
    assert not events(eng, "progress_awarded")  # nothing at a session's end
    with pytest.raises(EngineError, match="only the GM"):
        eng.award_milestone("ash", by="ash")
    eng.award_milestone()  # every player character
    assert progress(eng, "ash")["pending"] == 1 and progress(eng, "bram")["pending"] == 1
    eng.award_milestone("ash")
    assert progress(eng, "ash")["pending"] == 2
    eng.take_advance("ash", "sharper")
    assert progress(eng, "ash")["pending"] == 1 and replays(eng)
    xp = table(lantern, {"background": "soldier"})
    with pytest.raises(EngineError, match="does not use milestone"):
        xp.award_milestone()


def test_use_raises_the_stat_used(packs_dir, tmp_path):
    pack = variant(packs_dir, tmp_path, "lanternlight", {"model": "use", "use": {"threshold": 2}})
    assert errors(lint(pack)) == []
    eng = table(pack, {"background": "scholar"})
    start = eng.state["entities"]["ash"]["stats"]["wits"]
    for _ in range(2):
        eng.commit_action("ash", "recall", gm={"difficulty": "easy"})  # Recall adds Wits
    assert eng.state["entities"]["ash"]["stats"]["wits"] == start + 1
    auto = events(eng, "advance_taken")[-1]["payload"]
    assert auto["automatic"] and auto["option"] == "use:wits"
    assert progress(eng)["uses"]["wits"] == 0
    for _ in range(12):
        eng.commit_action("ash", "recall", gm={"difficulty": "easy"})
    assert eng.state["entities"]["ash"]["stats"]["wits"] == 3  # never past its range
    assert eng.sheet_problems("ash") == [] and replays(eng)


def test_packs_without_progression_log_nothing(packs_dir, tmp_path):
    pack = variant(packs_dir, tmp_path, "lanternlight", {"model": "milestone"})  # the core default
    eng = table(pack, {"background": "soldier"})
    eng.commit_action("ash", "recall", gm={"difficulty": "hard"})
    eng.end_session()
    assert not events(eng, "progress_awarded") and "progress" not in eng.state["entities"]["ash"]


@pytest.mark.parametrize("prog, fragment", [
    ({"model": "levels"}, "No progression model 'levels'"),
    ({"model": "xp", "thresholds": [5, 3], "awards": [{"when": "session_end"}], "advances": MILESTONE["advances"]},
     "rising positive"),
    ({"model": "xp", "thresholds": [5], "advances": MILESTONE["advances"]}, "needs awards"),
    ({"model": "marks", "thresholds": [3], "awards": [{"when": "outcome", "outcomes": ["botch"]}],
      "advances": MILESTONE["advances"]}, "No outcome 'botch'"),
    ({"model": "xp", "thresholds": [3], "awards": [{"when": "dawn"}], "advances": MILESTONE["advances"]},
     "when must be"),
    ({"model": "use"}, "use.threshold"),
    ({"model": "milestone", "advances": [{"id": "x", "stats": {"luck": 1}}]}, "No stat 'luck'"),
    ({"model": "milestone", "advances": [{"id": "x", "requires": "import os"}]}, "advance x"),
])
def test_bad_progression_fails_lint(packs_dir, tmp_path, prog, fragment):
    found = [f.message for f in errors(lint(variant(packs_dir, tmp_path, "lanternlight", prog)))
             if f.code == "progression"]
    assert any(fragment in m for m in found), found


def test_tools_offer_only_the_packs_advances(packs_dir, tmp_path, lantern):
    strict = expand({"players": {"preset": STRICT}, "gm": {"preset": STRICT}})
    player = generate(lantern, strict, "players", "ash")
    assert sorted(player["take_advance"]["advance_id"]["enum"]) == ["hardier", "lamplighter", "nimbler", "sharper", "steadier"]
    assert "entity_id" not in player["take_advance"] and "award_milestone" not in player
    assert not free_values(player)
    assert "award_milestone" not in generate(lantern, strict, "gm", "gm")  # an xp pack
    gm = generate(variant(packs_dir, tmp_path, "lanternlight", MILESTONE), strict, "gm", "gm")
    assert "award_milestone" in gm and "entity_id" in gm["take_advance"]


@pytest.mark.parametrize("pack_id", ["lanternlight", "tidewrack"])
def test_a_scripted_campaign_advances_and_replays(packs_dir, pack_id):
    pack = resolve(pack_id, packs_dir)
    script = smoke_script(pack)
    eng, _ = run_script(script, packs_dir)
    taken = events(eng, "advance_taken")
    assert taken, "the smoke campaign reaches at least one threshold"
    assert all(eng.sheet_problems(p) == [] for p in ("ash", "bram", "cyra", "dov"))
    assert verify(eng.store, eng.campaign_id, pack, seed=script["seed"]) == []
    again, _ = run_script(script, packs_dir)
    assert again.store.head(again.campaign_id) == eng.store.head(eng.campaign_id)


@pytest.mark.parametrize("prog", [MILESTONE, {"model": "use", "use": {"threshold": 3}}], ids=["milestone", "use"])
def test_milestone_and_use_campaigns_advance_and_replay(packs_dir, tmp_path, prog):
    pack = variant(packs_dir, tmp_path, "lanternlight", prog)
    script = smoke_script(pack)
    eng, _ = run_script(script, tmp_path / "packs")
    assert events(eng, "advance_taken")
    assert all(eng.sheet_problems(p) == [] for p in ("ash", "bram", "cyra", "dov"))
    assert verify(eng.store, eng.campaign_id, pack, seed=script["seed"]) == []
    again, _ = run_script(script, tmp_path / "packs")
    assert again.store.head(again.campaign_id) == eng.store.head(eng.campaign_id)

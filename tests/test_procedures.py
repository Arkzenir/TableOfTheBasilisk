"""The reference procedure shapes (T0.17; ARCHITECTURE §2.5; BUILD_PLAN P0.4, P0.6).

Each outcome is recomputed by hand from the logged dice and the pack's rule
and compared with what the engine resolved."""

import shutil
from fractions import Fraction

import pytest
import yaml

from basilisk.kernel.conformance import outcome_probabilities, outcome_reachability
from basilisk.kernel.engine import Engine, EngineError
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve

POOL_PACK = {
    "meta": {"id": "pooltest", "version": "0.1.0", "extends": "core@0.1.0", "name": "Pool test",
             "license": "CC0-1.0", "attribution_text": "Pool test fixture (CC0)."},
    "rules_text": {"mode": "inline", "full_text": "Roll attr + skill d10s; 8+ is a success."},
    "randomizers": {"dice_grammar": {"operators": ["sum", "count"]}},
    "entity_model": {"stats": [{"id": "attr", "range": [1, 3], "default": 2},
                               {"id": "skill", "range": [0, 3], "default": 1}]},
    "resolution": {
        "outcome_scales": [{"id": "degrees", "ordered": ["failure", "success", "strong", "legendary"]}],
        "procedures": [{"id": "pool", "kind": "roll", "inputs": ["actor", "difficulty"],
                        "steps": [{"roll": "({attr}+{skill})d10count>=8"},
                                  {"interpret": {"scale": "degrees", "compare": "successes", "against": "difficulty",
                                                 "margins": [[-99, -1], [0, 0], [1, 2], [3, 99]]}}]}],
        "difficulty_ladders": [{"id": "need", "rungs": [{"id": "one", "label": "One", "value": 1},
                                                        {"id": "two", "label": "Two", "value": 2}], "range": [1, 4]}],
    },
    "actions": [{"id": "attempt", "trigger": "declared", "procedure": "pool", "difficulty": {"ladder": "need"},
                 "outcome_effects": {}}],
    "presentation": {"rule_cards": {
        "attempt": {"title": "Attempt", "summary": "Roll the pool.", "category": "action", "icon_id": "dice"},
        "pool": {"title": "Pool", "summary": "Count successes.", "category": "procedure", "icon_id": "d10"}}},
}


@pytest.fixture(scope="module")
def packs(packs_dir, tmp_path_factory):
    dst = tmp_path_factory.mktemp("procs") / "packs"
    shutil.copytree(packs_dir, dst)
    (dst / "pooltest").mkdir()
    (dst / "pooltest" / "pack.yaml").write_text(yaml.safe_dump(POOL_PACK, sort_keys=False))
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["actions"].append({"id": "wrestle", "trigger": "declared", "target": "entity", "stat": "might",
                            "procedure": "opposed", "outcome_effects": {}})
    data["resolution"] = {"procedures": [{"id": "duck", "kind": "roll", "inputs": ["actor", "difficulty"],
                                          "steps": [{"roll": "1d20"},
                                                    {"interpret": {"scale": "pass_fail", "compare": "<=",
                                                                   "against": "difficulty"}}]}]}
    data["actions"].append({"id": "dodge", "trigger": "declared", "procedure": "duck",
                            "difficulty": {"derived": "8 + actor.grace * 2"}, "outcome_effects": {}})
    cards = data["presentation"]["rule_cards"]
    cards["wrestle"] = {"title": "Wrestle", "summary": "Might against Might.", "category": "action", "icon_id": "hands"}
    cards["dodge"] = {"title": "Dodge", "summary": "Roll under 8 + twice Grace.", "category": "action", "icon_id": "dash"}
    cards["duck"] = {"title": "Roll under", "summary": "d20 at or under the target.", "category": "procedure", "icon_id": "d20"}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return dst


def table(pack, seed, seats=None):
    eng = Engine.start_campaign(pack, seed, {"seats": seats or {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    choice = {s["id"]: s["options"][0]["id"] for s in pack.get("chargen.steps") or [] if s["kind"] == "choice"}
    eng.create_character("ash", "Ash", choice)
    eng.spawn_entity("foe", "Foe", {"might": 1} if "might" in pack.by_id("entity_model.stats") else {})
    eng.start_session()
    eng.set_scene("test", flags={"danger": 1})
    return eng


def last(eng, kind):
    return [e for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


def test_roll_over_check(lantern):
    for i in range(20):
        eng = table(lantern, f"over-{i}")
        eng.commit_action("ash", "recall", gm={"difficulty": "moderate"})
        roll = last(eng, "roll_made")[-1]["payload"]
        resolved = last(eng, "procedure_resolved")[-1]["payload"]
        by_hand = roll["groups"][0]["value"] + roll["variables"]["mod"]  # 1d20 + mod
        assert roll["total"] == by_hand
        assert resolved["outcome"] == ("pass" if by_hand >= 12 else "fail")


def test_banded_move(tide):
    for i in range(20):
        eng = table(tide, f"band-{i}")
        eng.commit_action("ash", "defy_danger")
        roll = last(eng, "roll_made")[-1]["payload"]
        total = sum(roll["groups"][0]["rolls"]) + roll["variables"]["mod"]  # 2d6 + mod
        expected = "miss" if total <= 6 else "partial" if total <= 9 else "full"
        assert last(eng, "procedure_resolved")[-1]["payload"]["outcome"] == expected


def test_pool_counts_successes_and_grades_by_margin(packs):
    pack = resolve("pooltest", packs)
    assert errors(lint(pack)) == []
    seen = set()
    for i in range(40):
        eng = table(pack, f"pool-{i}")
        need = ("one", "two")[i % 2]
        eng.commit_action("ash", "attempt", gm={"difficulty": need})
        roll = last(eng, "roll_made")[-1]["payload"]
        assert len(roll["groups"][0]["rolls"]) == 3  # (attr 2 + skill 1) d10: stats name the dice
        successes = sum(1 for r in roll["groups"][0]["rolls"] if r >= 8)
        margin = successes - (1 if need == "one" else 2)
        expected = "failure" if margin < 0 else "success" if margin == 0 else "strong" if margin <= 2 else "legendary"
        outcome = last(eng, "procedure_resolved")[-1]["payload"]["outcome"]
        assert outcome == expected
        seen.add(outcome)
    assert {"failure", "success", "strong"} <= seen
    probs = outcome_probabilities(pack, "pool", 0, 1)  # attr + skill bound to 0: zero dice
    assert probs["failure"] == 1


def test_pool_probabilities_are_exact(packs):
    pack = resolve("pooltest", packs)
    from basilisk.kernel import dice
    dist = dice.distribution("({attr}+{skill})d10count>=8", {"attr": 1, "skill": 1})  # 2d10, 8+ succeeds
    assert dist == {0: Fraction(49, 100), 1: Fraction(42, 100), 2: Fraction(9, 100)}
    reach = outcome_reachability(pack)["pool"]
    assert reach == {"failure": True, "success": True, "strong": True, "legendary": True}


def test_opposed_checks_both_roll_and_ties_go_to_the_defender(packs):
    pack = resolve("lanternlight", packs)
    assert errors(lint(pack)) == []
    outcomes = set()
    for i in range(40):
        eng = table(pack, f"opp-{i}")
        eng.commit_action("ash", "wrestle", target="foe")
        rolls = last(eng, "roll_made")[-2:]
        theirs, mine = rolls[0]["payload"], rolls[1]["payload"]
        assert theirs["purpose"] == "opposed:opposed:foe" and mine["purpose"] == "procedure:opposed"
        resolved = last(eng, "procedure_resolved")[-1]["payload"]
        assert resolved["difficulty"]["value"] == theirs["total"] and resolved["difficulty"]["origin"] == "opposed"
        expected = "pass" if mine["total"] > theirs["total"] else "fail"  # a tie goes to the target
        assert resolved["outcome"] == expected
        outcomes.add(expected)
    assert outcomes == {"pass", "fail"}
    eng = table(pack, "opp-x")
    probs = outcome_probabilities(pack, "opposed", 0, 0)  # d20 vs d20, equal modifiers
    assert probs["pass"] == Fraction(19, 40) and probs["fail"] == Fraction(21, 40)


def test_opposed_needs_a_target_and_cannot_be_peeked(packs):
    pack = resolve("lanternlight", packs)
    eng = table(pack, "opp-y")
    with pytest.raises(EngineError, match="needs a target"):
        eng.resolve_unmodelled("ash", "opposed", stat="might")
    with pytest.raises(EngineError, match="two rolls"):
        eng._run_procedure(pack.by_id("resolution.procedures")["opposed"], eng.state["entities"]["ash"],
                           eng.state["entities"]["foe"], "might", None, {"peek": True}, 0)


def test_roll_under(packs):
    pack = resolve("lanternlight", packs)
    for i in range(20):
        eng = table(pack, f"under-{i}")
        eng.commit_action("ash", "dodge")
        roll = last(eng, "roll_made")[-1]["payload"]
        target = 8 + eng.state["entities"]["ash"]["stats"]["grace"] * 2
        assert last(eng, "procedure_resolved")[-1]["payload"]["outcome"] == ("pass" if roll["total"] <= target else "fail")


def test_opposed_is_in_core_and_every_family(packs_dir):
    for pid in ("core", "core.roll_over", "core.banded"):
        proc = resolve(pid, packs_dir, allow_abstract=True).by_id("resolution.procedures")["opposed"]
        roll = {k: v for s in proc["steps"] for k, v in s.items()}["roll"]
        assert roll == {"core": "1d6 + {mod}", "core.roll_over": "1d20 + {mod}", "core.banded": "2d6 + {mod}"}[pid]

"""Step dice (T0.18; ARCHITECTURE §2.4; BUILD_PLAN P0.2)."""

import math
import shutil

import pytest
import yaml

from basilisk.harness.scripted import verify
from basilisk.kernel import dice
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.conformance import outcome_reachability
from basilisk.kernel.engine import Engine, EngineError
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.rng import Randomizer

STEP_PACK = {
    "meta": {"id": "steptest", "version": "0.1.0", "extends": "core@0.1.0", "name": "Step test",
             "license": "CC0-1.0", "attribution_text": "Step-dice test fixture (CC0)."},
    "rules_text": {"mode": "inline", "full_text": "Your trait is a die from d4 to d12; beat 4."},
    "randomizers": {"dice_grammar": {"operators": ["sum", "step"], "step_sizes": [4, 6, 8, 10, 12]}},
    "entity_model": {"stats": [{"id": "trait", "range": [4, 12], "default": 6}]},
    "resolution": {
        "procedures": [{"id": "trait_roll", "kind": "roll", "inputs": ["actor", "difficulty"],
                        "steps": [{"modifiers": {"from": ["conditions"]}}, {"roll": "1d{trait} + {mod}"},
                                  {"interpret": {"scale": "pass_fail", "compare": ">=", "against": "difficulty"}}]}],
        "difficulty_ladders": [{"id": "tn", "rungs": [{"id": "standard", "label": "Standard", "value": 4}],
                                "range": [2, 8]}],
    },
    "actions": [{"id": "try_it", "trigger": "declared", "procedure": "trait_roll", "difficulty": {"ladder": "tn"},
                 "outcome_effects": {}}],
    "presentation": {"rule_cards": {
        "try_it": {"title": "Try", "summary": "Roll your trait die.", "category": "action", "icon_id": "die"},
        "trait_roll": {"title": "Trait roll", "summary": "Roll the trait die; beat 4.", "category": "procedure",
                       "icon_id": "die"}}},
}


@pytest.fixture(scope="module")
def step_dir(packs_dir, tmp_path_factory):
    dst = tmp_path_factory.mktemp("step") / "packs"
    shutil.copytree(packs_dir, dst)
    (dst / "steptest").mkdir()
    (dst / "steptest" / "pack.yaml").write_text(yaml.safe_dump(STEP_PACK, sort_keys=False))
    return dst


@pytest.fixture(scope="module")
def step(step_dir):
    return resolve("steptest", step_dir)


def table(pack, seed="step-seed"):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm"}}, clock=lambda: None)
    eng.spawn_entity("scout", "Scout", {"trait": 10})
    eng.spawn_entity("odd", "Odd", {"trait": 5})  # within the stat range, but not a legal die size
    eng.start_session()
    eng.set_scene("field")
    return eng


def test_the_die_size_comes_from_the_stat(step):
    assert errors(lint(step)) == []
    eng = table(step)
    eng.commit_action("scout", "try_it", gm={"difficulty": "standard"})
    roll = [e for e in eng.store.read(eng.campaign_id) if e["type"] == "roll_made"][-1]["payload"]
    assert roll["groups"][0]["dice"] == "1d10" and roll["variables"]["trait"] == 10
    assert verify(eng.store, eng.campaign_id, step, "step-seed") == []  # re-derives from the seed


def test_an_illegal_size_is_refused_atomically(step):
    eng = table(step)
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    with pytest.raises(EngineError, match="d5 is not a legal size"):
        eng.commit_action("odd", "try_it", gm={"difficulty": "standard"})
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before


def test_exact_distribution_and_10k_rolls():
    for size in (4, 6, 8, 10, 12):
        exact = dice.distribution("1d{t}", {"t": size})
        assert set(exact) == set(range(1, size + 1)) and all(p == exact[1] for p in exact.values())
        rng = Randomizer("step-dist")
        counts = [0] * size
        for i in range(10_000):
            v = dice.evaluate("1d{t}", {"t": size}, lambda sub, lo, hi, c=i: rng.integer(c, sub, lo, hi),
                              step_sizes=[4, 6, 8, 10, 12]).total
            counts[v - 1] += 1
        e = 10_000 / size
        chi2 = sum((c - e) ** 2 / e for c in counts)
        assert chi2 < (size - 1) + 6 * math.sqrt(2 * (size - 1)) + 10
    assert dice.value_range("1d{t} + 1", {"t": (4, 12)}) == (2, 13)


def test_reachability_with_step_dice(step):
    assert outcome_reachability(step)["trait_roll"] == {"fail": True, "pass": True}


@pytest.mark.parametrize("grammar, fragment", [
    ({"operators": ["sum"]}, "not enabled by the pack: ['step']"),
    ({"operators": ["sum", "step"], "step_sizes": None}, "needs dice_grammar.step_sizes"),
    ({"operators": ["sum", "step"], "step_sizes": [1, 6]}, "die sizes of 2 or more"),
    ({"operators": ["sum", "step"], "step_sizes": [6, 200]}, "exceeds max_sides"),
])
def test_step_dice_lint(step_dir, tmp_path, grammar, fragment):
    dst = tmp_path / "packs"
    shutil.copytree(step_dir, dst)
    path = dst / "steptest" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["randomizers"]["dice_grammar"] = {k: v for k, v in grammar.items() if v is not None}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f.message for f in errors(lint(resolve("steptest", dst)))]
    assert any(fragment in m for m in found), found

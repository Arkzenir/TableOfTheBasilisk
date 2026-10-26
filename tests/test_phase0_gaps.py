"""Remaining Phase 0 test lines (T0.22; BUILD_PLAN P0.3, P0.5, P0.6, P0.12)."""

import random
import shutil

import pytest
import yaml

from basilisk.harness.scripted import determinism_check, run_script, smoke_script, verify
from basilisk.kernel import expr
from basilisk.kernel.determinism import apply_change, expand
from basilisk.kernel.packs import discover, resolve
from basilisk.kernel.tools import generate
from conftest import PACKS

PLAYABLE = sorted(p for p in discover(PACKS) if not resolve(p, PACKS).data["meta"]["abstract"])


# ---------------------------------------------------------------- P0.6: core supplies a default tactical profile

def test_core_supplies_a_default_tactical_profile(packs_dir, tmp_path):
    core = resolve("core", packs_dir, allow_abstract=True)
    assert core.get("spatial.tactical_profile.weights") == {"threats_here": 1, "allies_here": 1, "closer": 1}
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    del data["spatial"]["tactical_profile"]  # a game that authors no profile of its own
    for action in data["actions"]:
        action.pop("annotation_categories", None)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pack = resolve("lanternlight", dst)
    assert pack.get("spatial.tactical_profile.weights") == core.get("spatial.tactical_profile.weights")
    from basilisk.kernel.engine import Engine
    eng = Engine.start_campaign(pack, "p", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("x", regions=[{"id": "a", "adjacency": ["b", "c"]}, {"id": "b"}, {"id": "c"}],
                  placements={"ash": "a", "foe": "c"})
    assert [m["id"] for m in eng.enumerate_moves("ash", 100)] == ["c", "b"]  # ranked by the defaults


# ---------------------------------------------------------------- P0.5: flipping one control changes only its role

@pytest.mark.parametrize("pack_id", ["lanternlight", "tidewrack"])
def test_flipping_one_control_changes_only_that_roles_schema(pack_id, packs_dir):
    pack = resolve(pack_id, packs_dir)
    base = expand({})  # players strict, GM standard
    for role, control in (("gm", "difficulty"), ("gm", "situational_modifiers"), ("players", "spend_amounts")):
        current = base[role][control]
        flipped = apply_change(base, role, None, {control: "strict" if current == "standard" else "standard"},
                               None, None)
        other = "players" if role == "gm" else "gm"
        assert generate(pack, flipped, other) == generate(pack, base, other), (role, control)
        changed = generate(pack, flipped, role) != generate(pack, base, role)
        relevant = (control != "difficulty" or pack.catalogue("resolution.difficulty_ladders")) and \
                   (control != "spend_amounts" or any("amounts" in (a.get("cost") or {}) for a in pack.catalogue("actions")))
        assert changed == bool(relevant), (role, control)


# ---------------------------------------------------------------- P0.12: every preset, each with a mid-campaign change

PRESETS = {
    "all_strict": {"players": {"preset": "strict"}, "gm": {"preset": "strict"}},
    "all_standard": {"players": {"preset": "standard"}, "gm": {"preset": "standard"}},
    "default": None,
}


@pytest.mark.parametrize("preset", sorted(PRESETS))
@pytest.mark.parametrize("pack_id", PLAYABLE)
def test_three_session_campaign_under_every_preset(pack_id, preset, packs_dir):
    pack = resolve(pack_id, packs_dir)
    script = smoke_script(pack, sessions=3, determinism=PRESETS[preset], seed=f"{preset}-seed")
    engine, report = run_script(script, packs_dir)
    assert report.settings_changes >= 1 and not report.actions_never_taken
    changed = [e for e in engine.store.read(engine.campaign_id) if e["type"] == "determinism_changed"]
    assert changed, "the change was applied at a scene boundary"
    assert verify(engine.store, report.campaign_id, pack, script["seed"], report.state_hash) == []
    assert determinism_check(script, packs_dir) == []


# ---------------------------------------------------------------- P0.3: evaluator properties

def _random_expr(rng, depth=0):
    if depth > 3 or rng.random() < 0.3:
        return rng.choice([str(rng.randint(-9, 9)), "actor.a", "actor.b", "scene.flag", "actor.conditions.x"])
    kind = rng.randint(0, 5)
    a, b = _random_expr(rng, depth + 1), _random_expr(rng, depth + 1)
    if kind == 0:
        return f"({a} {rng.choice(['+', '-', '*'])} {b})"
    if kind == 1:
        return f"({a} {rng.choice(['<', '<=', '==', '!=', '>', '>='])} {b})"
    if kind == 2:
        return f"({a} {rng.choice(['and', 'or'])} {b})"
    if kind == 3:
        return f"({a} if {b} else {_random_expr(rng, depth + 1)})"
    if kind == 4:
        return f"{rng.choice(['min', 'max'])}({a}, {b})"
    return f"div({a}, {rng.choice(['2', '3', '-4', '7'])})"


def test_the_evaluator_is_total_terminating_and_deterministic():
    rng = random.Random(20261026)
    ctx = {"actor": {"a": 5, "b": -3, "conditions": expr.Lenient({"x": 1})}, "scene": expr.Lenient({"flag": 1})}
    for _ in range(2_000):
        src = _random_expr(rng)
        first = expr.evaluate(src, ctx)  # never raises on well-formed input, always an int
        assert isinstance(first, int) and not isinstance(first, bool)
        assert expr.evaluate(src, ctx) == first  # deterministic


@pytest.mark.parametrize("rounding", ["floor", "ceil", "half_up"])
def test_division_follows_the_packs_rounding(rounding):
    import math
    from fractions import Fraction
    rng = random.Random(rounding)
    for _ in range(2_000):
        a, b = rng.randint(-1000, 1000), rng.choice([n for n in range(-12, 13) if n])
        exact = Fraction(a, b)
        expected = {"floor": math.floor(exact), "ceil": math.ceil(exact),
                    "half_up": math.floor(exact + Fraction(1, 2))}[rounding]
        assert expr.evaluate(f"div({a}, {b})", {}, rounding) == expected, (a, b)


@pytest.mark.parametrize("pack_id", PLAYABLE)
def test_derived_values_use_each_packs_rounding(pack_id):
    pack = resolve(pack_id, PACKS)
    rounding = pack.get("presentation.rounding", "floor")
    assert rounding in expr.ROUNDING
    for d in pack.catalogue("entity_model.derived"):
        for v in range(-3, 4):
            names = {s["id"]: v for s in pack.catalogue("entity_model.stats")}
            assert isinstance(expr.evaluate(d["expr"], {**names, "actor": names}, rounding), int)

"""Generated property tests, one set per playable pack (T0.10; ARCHITECTURE §2.10, BUILD_PLAN P0.7).

Every pack on disk that can be played gets the same three checks, so a new
pack is covered the moment it exists:

- every outcome on every rolled procedure's scale is reachable (exact dice
  distributions where they exist);
- every action is resolvable from some sampled state;
- no effect sequence leaves a sheet invalid.
"""

import random
from fractions import Fraction

import pytest

from basilisk.kernel import dice
from basilisk.kernel.conformance import outcome_probabilities, outcome_reachability
from basilisk.kernel.engine import Engine, EngineError
from basilisk.kernel.packs import discover, resolve
from basilisk.kernel.spatial import declared_backends
from conftest import PACKS

PLAYABLE = sorted(p for p in discover(PACKS) if not resolve(p, PACKS).data["meta"]["abstract"])
SEATS = {"gm": "gm", "ash": "player", "bram": "player", "cyra": "player"}


def _pack(pack_id):
    return resolve(pack_id, PACKS)


# ---------------------------------------------------------------- exact distributions

@pytest.mark.parametrize("expr, value, probability", [
    ("2d6", 7, Fraction(1, 6)),
    ("1d20 + {mod}", 21, Fraction(1, 20)),        # with mod = 1
    ("4d6kh3", 18, Fraction(21, 1296)),
    ("3dF", 0, Fraction(7, 27)),
    ("5d10count>=8", 5, Fraction(243, 100000)),
    ("2d20kl1", 20, Fraction(1, 400)),
])
def test_exact_distributions(expr, value, probability):
    dist = dice.distribution(expr, {"mod": 1})
    assert sum(dist.values()) == 1 and dist[value] == probability
    lo, hi = dice.value_range(expr, {"mod": (1, 1)})
    assert (min(dist), max(dist)) == (lo, hi)


def test_unbounded_rolls_have_no_exact_distribution():
    assert dice.distribution("1d6!") is None


# ---------------------------------------------------------------- outcome bands

@pytest.mark.parametrize("pack_id", PLAYABLE)
def test_every_outcome_band_is_reachable(pack_id):
    pack = _pack(pack_id)
    reach = outcome_reachability(pack)
    assert reach, f"{pack_id} has no rolled procedures to check"
    for proc, outcomes in reach.items():
        for outcome, ok in outcomes.items():
            assert ok is not False, f"{pack_id}: {proc} can never produce {outcome}"
        probs = outcome_probabilities(pack, proc, 0, None if "bands" in str(pack.by_id("resolution.procedures")[proc]) else 12)
        if probs is not None:
            assert sum(probs.values()) == 1


# ---------------------------------------------------------------- sampled states

def _choices(pack, rng, taken):
    out = {}
    for step in pack.get("chargen.steps") or []:
        if step["kind"] == "choice":
            opts = [o["id"] for o in step["options"] if not step.get("unique_per_table") or o["id"] not in taken]
            out[step["id"]] = rng.choice(opts)
            if step.get("unique_per_table"):
                taken.add(out[step["id"]])
        elif step["kind"] == "assign":  # a random arrangement of the array
            values = list(step["values"])
            rng.shuffle(values)
            out[step["id"]] = dict(zip(step["targets"], values))
    return out


def _sampled_table(pack, seed: int):
    """A table in a randomly chosen but seeded state: characters, an NPC with
    random stats, scene flags, and maybe an encounter scene."""
    rng = random.Random(seed)
    eng = Engine.start_campaign(pack, f"prop-{seed}", {"seats": SEATS}, clock=lambda: None)
    taken: set = set()
    for seat in ("ash", "bram", "cyra"):
        eng.create_character(seat, seat.title(), _choices(pack, rng, taken))
    stats = {s["id"]: rng.randint(*s.get("range", [0, 0])) for s in pack.catalogue("entity_model.stats")}
    eng.spawn_entity("npc_x", "Someone", stats)
    eng.start_session()
    flags = {f: rng.randint(0, 1) for f in ("danger", "dim", "storm")}
    encounter = rng.random() < 0.5
    backends = declared_backends(pack)
    people = ["ash", "bram", "cyra", "npc_x"]
    if "zone_graph" in backends and rng.random() < 0.8:  # positions, so zone-targeted actions exist
        names = [f"z{i}" for i in range(rng.randint(2, 5))]
        regions = [{"id": z, "adjacency": names[i + 1:i + 2]} for i, z in enumerate(names)]
        eng.set_scene("sample", flags=flags, encounter=encounter, regions=regions,
                      placements={e: rng.choice(names) for e in people})
    elif "range_bands" in backends and rng.random() < 0.8:
        eng.set_scene("sample", flags=flags, encounter=encounter, participants=people)
    else:
        eng.set_scene("sample", flags=flags, encounter=encounter)
    return eng, rng


def _gm_inputs(pack, action, rng):
    spec = action.get("difficulty") or {}
    if "ladder" in spec:
        rungs = pack.by_id("resolution.difficulty_ladders")[spec["ladder"]]["rungs"]
        return {"difficulty": rng.choice(rungs)["id"]}
    return {}


def _try(eng, rng, entity, cand):
    action = eng.pack.by_id("actions")[cand["action_id"]]
    cost = action.get("cost") or {}
    spend = min(cost["amounts"]) if "amounts" in cost else None
    by = "gm" if eng.state["entities"][entity]["controller"] == "gm" else None
    eng.commit_action(entity, cand["action_id"], target=cand["target"], spend=spend,
                      gm=_gm_inputs(eng.pack, action, rng), by=by)
    for slot, info in sorted(eng.open_rulings().items()):
        eng.fill_ruling(slot, rng.choice(info["entries"]))


@pytest.mark.parametrize("pack_id", PLAYABLE)
def test_every_action_is_resolvable_from_sampled_states(pack_id):
    pack = _pack(pack_id)
    missing = set(pack.by_id("actions"))
    for seed in range(30):
        if not missing:
            break
        eng, rng = _sampled_table(pack, seed)
        for entity in ("ash", "bram", "cyra", "npc_x"):
            for cand in eng.enumerate_action_candidates(entity, 100):
                if cand["action_id"] in missing:
                    try:
                        _try(eng, rng, entity, cand)
                        missing.discard(cand["action_id"])
                    except EngineError:
                        pass  # refused atomically; another state may allow it
    assert not missing, f"{pack_id}: never resolvable from 30 sampled states: {sorted(missing)}"


@pytest.mark.parametrize("pack_id", PLAYABLE)
def test_no_effect_sequence_yields_an_invalid_sheet(pack_id):
    pack = _pack(pack_id)
    entities = ("ash", "bram", "cyra", "npc_x")
    for seed in range(4):
        eng, rng = _sampled_table(pack, 100 + seed)
        for step in range(60):
            entity = rng.choice(entities)
            if rng.random() < 0.7:
                cands = eng.enumerate_action_candidates(entity, 100)
                if cands:
                    try:
                        _try(eng, rng, entity, rng.choice(cands))
                    except EngineError:
                        pass
            else:  # a pack effect at an extreme amount, straight through the primitives
                effect = _random_effect(pack, rng, entity)
                if effect:
                    try:
                        eng._apply_effect(effect, {"actor": entity, "target": entity, "self": entity}, None, {})
                    except EngineError:
                        pass
            for e in entities:
                assert eng.sheet_problems(e) == [], f"{pack_id} seed {seed} step {step}: {e}"


def _random_effect(pack, rng, entity):
    kinds = []
    for r in pack.catalogue("entity_model.resources"):
        kinds.append({"primitive": "modify_resource", "target": entity, "resource": r["id"],
                      "amount": rng.choice([-99, -3, 3, 99])})
    for t in pack.catalogue("entity_model.tracks"):
        kinds.append({"primitive": "mark_track", "target": entity, "track": t["id"], "amount": rng.choice([1, 9])})
        kinds.append({"primitive": "clear_track", "target": entity, "track": t["id"]})
    for c in pack.catalogue("entity_model.conditions"):
        kinds.append({"primitive": rng.choice(["add_condition", "remove_condition"]), "target": entity,
                      "condition": c["id"]})
    for item in pack.catalogue("entity_model.items"):  # weight limits must hold too
        kinds.append({"primitive": "create_item", "target": entity, "item": item["id"]})
    for c in pack.catalogue("gm.meta_currencies"):
        kinds.append({"primitive": "earn_currency", "target": entity, "currency": c["id"], "amount": rng.choice([1, 99])})
    return rng.choice(kinds) if kinds else None

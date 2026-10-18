"""Gate P0 checks not covered elsewhere (T0.13 evidence; BUILD_PLAN Gate P0).

Each test names the gate item it demonstrates."""

import math

import pytest

from basilisk.harness.scripted import run_script, smoke_script, verify
from basilisk.kernel import dice, terms
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.determinism import STRICT
from basilisk.kernel.engine import Engine, fold
from basilisk.kernel.packlint import _rolls_in
from basilisk.kernel.packs import discover, resolve
from basilisk.kernel.rng import Randomizer
from conftest import PACKS

PLAYABLE = sorted(p for p in discover(PACKS) if not resolve(p, PACKS).data["meta"]["abstract"])


# ---------------------------------------------------------------- "Fork at any seq produces correct divergent branches"

@pytest.mark.parametrize("pack_id", ["lanternlight", "tidewrack"])
def test_fork_at_every_seq_gives_a_correct_divergent_branch(pack_id, packs_dir):
    pack = resolve(pack_id, packs_dir)
    script = smoke_script(pack, sessions=1, seed="fork-seed")
    source, report = run_script(script, packs_dir)
    store, cid = source.store, report.campaign_id
    events = list(store.read(cid))
    for k in range(1, len(events) + 1):
        fork_id = f"fork-{k}"
        store.fork(cid, k, fork_id)
        assert store.verify_chain(fork_id) == []
        forked = list(store.read(fork_id))
        assert forked[-1]["type"] == "campaign_forked" and forked[-1]["payload"]["source_seq"] == k
        assert hash_obj(fold(forked[:-1])) == hash_obj(fold(events[:k]))  # the branch starts exactly at seq k
    # branches continue independently: play on two forks differently, the source is untouched
    head = store.head(cid)
    late = len(events) - 1
    a = Engine.load(pack, script["seed"], store, f"fork-{late}", clock=lambda: None)
    b = Engine.load(pack, script["seed"], store, f"fork-{late}", clock=lambda: None)  # same fork, two engines
    a.start_session()
    a.set_scene("branch_a")
    c = Engine.load(pack, script["seed"], store, f"fork-{late - 1}", clock=lambda: None)
    c.start_session()
    c.set_scene("branch_c", encounter=True)
    assert store.head(cid) == head
    assert store.head(f"fork-{late}") != store.head(f"fork-{late - 1}")
    for fid in (f"fork-{late}", f"fork-{late - 1}"):
        assert verify(store, fid, pack, script["seed"]) == []
    assert b.state_hash() != a.state_hash()  # b was loaded before a moved on


# ---------------------------------------------------------------- "10k-roll distribution passes for every operator and die type in use"

def _rolled_expressions():
    out = set()
    for pack_id in PLAYABLE:
        for _, src in _rolls_in(resolve(pack_id, PACKS)):
            if dice.has_dice(src):
                out.add(src)
    # every operator the grammar offers, beyond those the shipped packs use
    out |= {"4d6kh3", "2d20kl1", "4dF", "6d10count>=8"}
    return sorted(out)


@pytest.mark.parametrize("src", _rolled_expressions())
def test_10k_rolls_match_the_exact_distribution(src):
    variables = {v: 0 for v in dice.variables_used(src)}
    exact = dice.distribution(src, variables)
    assert exact is not None
    rng = Randomizer("distribution-seed")
    counts: dict[int, int] = {}
    n = 10_000
    for i in range(n):
        total = dice.evaluate(src, variables, lambda sub, lo, hi, c=i: rng.integer(c, sub, lo, hi)).total
        counts[total] = counts.get(total, 0) + 1
    assert set(counts) <= set(exact)  # nothing outside the support
    # chi-square, merging tail bins whose expected count is under 5
    bins, obs, exp = [], 0, 0.0
    for value in sorted(exact):
        obs += counts.get(value, 0)
        exp += float(exact[value]) * n
        if exp >= 5:
            bins.append((obs, exp))
            obs, exp = 0, 0.0
    if exp and bins:
        o, e = bins.pop()
        bins.append((o + obs, e + exp))
    df = max(1, len(bins) - 1)
    chi2 = sum((o - e) ** 2 / e for o, e in bins)
    assert chi2 < df + 6 * math.sqrt(2 * df) + 10, (src, chi2, df)  # far beyond p = 0.001


# ---------------------------------------------------------------- "zero model-supplied numbers reach resolution from a strict role"

@pytest.mark.parametrize("pack_id", PLAYABLE)
def test_strict_roles_supply_no_numbers_audited_from_judgement_input(pack_id, packs_dir):
    pack = resolve(pack_id, packs_dir)
    script = smoke_script(pack, sessions=2, determinism={"players": {"preset": "strict"}, "gm": {"preset": "strict"}})
    script["smoke"]["toggle_gm"] = False  # strict throughout
    engine, _ = run_script(script, packs_dir)
    judged = resolved = 0
    for ev in engine.store.read(engine.campaign_id):
        p = ev["payload"]
        if ev["type"] == "judgement_input" and p["setting"] == STRICT:
            judged += 1
            choice = p["choice"]
            if isinstance(choice, dict):  # situational modifiers: tags from the list, no free value
                assert choice.get("free", 0) == 0 and set(choice.get("tags", [])) <= set(p["options"])
            else:
                assert choice in p["options"], (p["control"], choice)
        if ev["type"] == "procedure_resolved":
            resolved += 1
            assert (p.get("difficulty") or {}).get("origin") != "gm-value"
            assert not any(m["kind"] == "free" for m in p["modifiers"])
    assert judged and resolved


# ---------------------------------------------------------------- "zero canon records with an excluded term are accepted, across scripted campaigns"

def test_no_excluded_term_reaches_canon_in_a_scripted_campaign(packs_dir):
    pack = resolve("tidewrack_excluded", packs_dir)
    script = smoke_script(pack, sessions=3, seed="terms-campaign")
    attempts = ["Morrowgaunt", "the Gaunt of the reef", "A pilot", "Ysolde's lantern", "A quiet cove"]
    script["steps"] = [{"do": "write_canon", "expect_error": True,
                        "record": {"type": "npc", "name": name, "body": "Seen at the quay.",
                                   "knowledge": "revealed", "origin": "improvised"}}
                       for name in attempts]
    engine, report = run_script(script, packs_dir)
    canon = engine.state.get("canon") or {}
    assert len(report.rejected) == 3  # the three names carrying excluded terms
    assert {r["name"] for r in canon.values()} >= {"A pilot", "A quiet cove"}
    for rec in canon.values():
        for text in [rec["name"], *rec.get("aliases", []), rec["body"]]:
            assert terms.find(pack, text) == [], rec


# ---------------------------------------------------------------- "replay against a mismatched kernel version is refused"

def test_replay_against_another_kernel_version_is_refused(lantern, monkeypatch):
    from basilisk.kernel import engine as engine_module
    from basilisk.kernel.engine import EngineError
    eng = Engine.start_campaign(lantern, "pin-seed", {"seats": {"gm": "gm"}}, clock=lambda: None)
    monkeypatch.setattr(engine_module, "KERNEL_VERSION", "9.9.9")  # a later kernel build
    with pytest.raises(EngineError, match="kernel mismatch"):
        Engine.load(lantern, "pin-seed", eng.store, eng.campaign_id)


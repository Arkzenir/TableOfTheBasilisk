"""Generated conformance checks (§2.10, BUILD_PLAN P0.7).

Pure functions over a resolved pack, used by the generated property tests.

`outcome_reachability(pack)` answers, for every procedure that rolls: can
each outcome on its scale happen at all? It uses the exact distribution of
the roll (`dice.distribution`) at the lowest and highest modifier a
character's stats allow, and, for a compared roll, against every rung of
every difficulty ladder. That is an under-approximation of the reachable
states, so an outcome it calls reachable really is. Where no exact
distribution exists (exploding dice), the outcome is reported as unknown
(None) and the caller samples instead.
"""

from __future__ import annotations

from fractions import Fraction

from . import dice
from .resolution import interpret_total


def _steps(proc: dict) -> dict:
    return {k: v for step in proc.get("steps") or [] for k, v in step.items()}


def modifier_range(pack) -> tuple[int, int]:
    """The stat contribution a roll can carry: the lowest and highest stat."""
    ranges = [s.get("range", [0, 0]) for s in pack.catalogue("entity_model.stats")] or [[0, 0]]
    return min(r[0] for r in ranges), max(r[1] for r in ranges)


def _stat_variables(pack, value: int) -> dict[str, int]:
    """Every stat and derived name bound to one value, for rolls that name stats."""
    names = [s["id"] for s in pack.catalogue("entity_model.stats")] + \
            [d["id"] for d in pack.catalogue("entity_model.derived")]
    return {n: value for n in names}


def outcome_probabilities(pack, proc_id: str, mod: int, against: int | None) -> dict[str, Fraction] | None:
    """Exact probability of each outcome of one roll, or None if not computable.
    For an opposed check, `against` is the other side's modifier: both rolls
    are distributions."""
    proc = pack.by_id("resolution.procedures")[proc_id]
    steps = _steps(proc)
    interp = steps["interpret"]
    scale = pack.by_id("resolution.outcome_scales")[interp["scale"]]["ordered"]
    dist = dice.distribution(steps["roll"], {**_stat_variables(pack, mod), "mod": mod})
    if dist is None:
        return None
    out = {o: Fraction(0) for o in scale}
    if interp.get("against") == "opposed":
        theirs = dice.distribution((interp.get("opposed") or {}).get("roll") or "1d6 + {mod}",
                                   {**_stat_variables(pack, against or 0), "mod": against or 0})
        if theirs is None:
            return None
        for total, p in dist.items():
            for other, q in theirs.items():
                out[interpret_total(interp, scale, total, {"value": other, "origin": "opposed"})] += p * q
        return out
    for total, p in dist.items():
        out[interpret_total(interp, scale, total, {"value": against or 0})] += p
    return out


def outcome_reachability(pack) -> dict[str, dict[str, bool | None]]:
    """{procedure: {outcome: reachable}} for every procedure that rolls."""
    lo, hi = modifier_range(pack)
    rungs = sorted({int(r["value"]) for lad in pack.catalogue("resolution.difficulty_ladders")
                    for r in lad.get("rungs") or []}) or [None]
    out: dict[str, dict[str, bool | None]] = {}
    for proc in pack.catalogue("resolution.procedures"):
        interp = _steps(proc).get("interpret") or {}
        if interp.get("automatic") or "roll" not in _steps(proc):
            continue
        scale = pack.by_id("resolution.outcome_scales")[interp["scale"]]["ordered"]
        seen: dict[str, bool | None] = {o: False for o in scale}
        if "bands" in interp:
            against_values = [None]
        elif interp.get("against") == "opposed":
            against_values = [lo, hi]  # the other side's stat
        else:
            against_values = rungs
        for mod in (lo, hi):
            for against in against_values:
                probs = outcome_probabilities(pack, proc["id"], mod, against)
                if probs is None:
                    seen = {o: (True if seen[o] else None) for o in scale}
                    continue
                for o, p in probs.items():
                    if p > 0:
                        seen[o] = True
        out[proc["id"]] = seen
    return out

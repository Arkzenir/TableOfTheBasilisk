"""Generated conformance checks (§2.10, BUILD_PLAN P0.7).

Pure functions over a resolved pack, used by the generated property tests.

`outcome_reachability(pack)` answers, for every procedure that rolls: can
each outcome on its scale happen at all? It uses the exact distribution of
the roll (`dice.distribution`) with every stat at the low and then the high
end of its own range. The stat counts in `mod` only if the procedure draws
modifiers from it. A compared roll is checked against every rung of every
difficulty ladder, an opposed roll against the other side at either end.
Every state it checks is one a real character can be in, so an outcome it
calls reachable really is. Where no exact distribution exists (exploding
dice), the outcome is reported as unknown (None) and the caller samples
instead.
"""

from __future__ import annotations

from fractions import Fraction

from . import dice
from .resolution import interpret_total

ENDS = ("low", "high")


def _steps(proc: dict) -> dict:
    return {k: v for step in proc.get("steps") or [] for k, v in step.items()}


def modifier_range(pack) -> tuple[int, int]:
    """The stat contribution a roll can carry: the lowest and highest stat."""
    ranges = [s.get("range", [0, 0]) for s in pack.catalogue("entity_model.stats")] or [[0, 0]]
    return min(r[0] for r in ranges), max(r[1] for r in ranges)


def _stats_at(pack, end: str) -> dict[str, int]:
    """Every stat at the low or high end of its own range."""
    out = {}
    for s in pack.catalogue("entity_model.stats"):
        lo, hi = s.get("range", [s.get("default", 0)] * 2)
        out[s["id"]] = lo if end == "low" else hi
    return out


def _variables(pack, proc: dict, at: int | str) -> dict[str, int]:
    """Roll variables: stats (for pool counts and step dice) and `mod`. `at` is a
    modifier value, or an end of the stat ranges."""
    if not isinstance(at, str):
        return {**_stats_at(pack, "low"), "mod": int(at)}
    sources = (_steps(proc).get("modifiers") or {}).get("from", [])
    lo, hi = modifier_range(pack)
    return {**_stats_at(pack, at), "mod": (lo if at == "low" else hi) if "stat" in sources else 0}


def outcome_probabilities(pack, proc_id: str, mod: int | str, against: int | str | None) -> dict[str, Fraction] | None:
    """Exact probability of each outcome of one roll, or None if not computable.
    `mod` is a modifier, or "low" / "high" for every stat at that end of its
    range. For an opposed check, `against` is the other side's modifier or end;
    otherwise it is the difficulty value."""
    proc = pack.by_id("resolution.procedures")[proc_id]
    steps = _steps(proc)
    interp = steps["interpret"]
    scale = pack.by_id("resolution.outcome_scales")[interp["scale"]]["ordered"]
    dist = dice.distribution(steps["roll"], _variables(pack, proc, mod))
    if dist is None:
        return None
    out = {o: Fraction(0) for o in scale}
    if interp.get("against") == "opposed":
        theirs = dice.distribution((interp.get("opposed") or {}).get("roll") or "1d6 + {mod}",
                                   _variables(pack, proc, against if against is not None else 0))
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
            against_values: list = [None]
        elif interp.get("against") == "opposed":
            against_values = list(ENDS)
        else:
            against_values = rungs
        for end in ENDS:
            for against in against_values:
                probs = outcome_probabilities(pack, proc["id"], end, against)
                if probs is None:
                    seen = {o: (True if seen[o] else None) for o in scale}
                    continue
                for o, p in probs.items():
                    if p > 0:
                        seen[o] = True
        out[proc["id"]] = seen
    return out

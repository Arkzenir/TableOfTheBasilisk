"""Resolution procedures (§2.5) and GM resolution of unmodelled actions.

Mixed into `Engine`. A procedure gathers modifiers from state, derives or
takes a difficulty, rolls through the engine's logged randomizer, and maps
the total onto the pack's ordered outcome scale. Every model-chosen input is
logged as `judgement_input` (§2.13).
"""

from __future__ import annotations

from typing import Any

from . import expr
from .command import EngineError, _suggest, atomic
from .determinism import STRICT


class ResolutionCommands:
    """Engine commands for resolution. Uses the engine's state, `_emit`, `_roll`,
    `_judge`, and seat roles."""

    @atomic
    def resolve_unmodelled(self, entity_id: str, procedure_id: str, *, stat: str | None = None,
                           difficulty: Any = None, tags: list[str] | None = None, outcome: str | None = None,
                           by: str | None = None, peek: bool = False) -> dict:
        self._require_settled()
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM resolves unmodelled actions")
        procs = self.pack.by_id("resolution.procedures")
        if procedure_id not in procs:
            raise EngineError(_suggest("procedure", procedure_id, procs))
        ent = self._entity(entity_id)
        mode = self.mode("unmodelled_actions", by)
        if outcome is not None and mode == STRICT:
            raise EngineError("under strict settings the GM maps the action onto a procedure; the engine rolls")
        seq = self._emit("gm_resolution", {"entity": entity_id, "procedure": procedure_id, "stat": stat,
                                           "direct_outcome": outcome}, actor=by)
        self._judge(by, "unmodelled_actions", mode, {"procedure": procedure_id, "stat": stat, "outcome": outcome},
                    sorted(procs), seq)
        ladder = (self.pack.catalogue("resolution.difficulty_ladders") or [{}])[0].get("id")
        out, rank, _ = self._run_procedure(procs[procedure_id], ent, None, stat,
                                           {"ladder": ladder} if ladder else None,
                                           {"difficulty": difficulty, "tags": tags or [], "peek": peek}, seq,
                                           direct_outcome=outcome, continuation={"kind": "unmodelled"})
        if out is None:
            return {"seq": seq, "pending": self.pending_peek()}
        return {"seq": seq, "outcome": out, "rank": rank}

    # ------------------------------------------------------------ resolution (§2.5)

    def _scale(self, proc_id: str) -> list[str]:
        proc = self.pack.by_id("resolution.procedures")[proc_id]
        steps = {k: v for step in proc.get("steps") or [] for k, v in step.items()}
        return self.pack.by_id("resolution.outcome_scales")[steps["interpret"]["scale"]]["ordered"]

    def _interpret(self, proc_id: str, total: int, difficulty: dict | None) -> str:
        """Map a roll total onto the procedure's outcome scale (§2.5)."""
        proc = self.pack.by_id("resolution.procedures")[proc_id]
        interp = {k: v for step in proc.get("steps") or [] for k, v in step.items()}["interpret"]
        scale = self._scale(proc_id)
        if "bands" in interp:
            idx = len(interp["bands"]) - 1
            for i, (lo, hi) in enumerate(interp["bands"]):
                if total <= hi:
                    idx = i
                    break
            return scale[max(0, idx)]
        against = difficulty["value"] if difficulty else 0
        ok = total >= against if interp["compare"] == ">=" else total <= against
        return scale[1] if ok else scale[0]

    def _resolved(self, proc_id: str, entity_id: str, outcome: str, total: int | None, difficulty: dict | None,
                  modifiers: list[dict], roll_seq: int | None, direct: bool, cause: int) -> int:
        scale = self._scale(proc_id)
        proc = self.pack.by_id("resolution.procedures")[proc_id]
        interp = {k: v for step in proc.get("steps") or [] for k, v in step.items()}["interpret"]
        return self._emit("procedure_resolved", {
            "procedure": proc_id, "entity": entity_id, "scale": interp["scale"], "outcome": outcome,
            "rank": scale.index(outcome), "ranks": len(scale), "total": total, "difficulty": difficulty,
            "modifiers": modifiers, "roll_seq": roll_seq, "direct": direct,
        }, caused_by=cause)

    def _run_procedure(self, proc: dict, ent: dict, target: dict | None, stat: str | None,
                       difficulty_spec: dict | None, gm_inputs: dict, cause: int,
                       direct_outcome: str | None = None,
                       continuation: dict | None = None) -> tuple[str | None, int | None, int | None]:
        """Run a procedure to an outcome. With `gm_inputs["peek"]` on a fudgeable
        procedure, stop after the roll and return (None, None, None): the GM
        settles it with `peek_roll` (§5.5)."""
        steps = {k: v for step in proc.get("steps") or [] for k, v in step.items()}
        interp = steps["interpret"]
        scale = self._scale(proc["id"])
        modifiers: list[dict] = []
        difficulty: dict | None = None
        total = None
        roll_seq = None

        if gm_inputs.get("peek") and (interp.get("automatic") or direct_outcome is not None):
            raise EngineError(f"peek refused: {proc['id']} has no roll to peek at")
        if interp.get("automatic"):
            outcome = scale[-1]
        elif direct_outcome is not None:
            if direct_outcome not in scale:
                raise EngineError(_suggest("outcome", direct_outcome, scale))
            outcome = direct_outcome
        else:
            sources = (steps.get("modifiers") or {}).get("from", [])
            if "stat" in sources and stat:
                value = self._derived(ent)[stat]
                modifiers.append({"source": stat, "kind": "stat", "value": value, "origin": "state"})
            if "conditions" in sources:
                conds = self.pack.by_id("entity_model.conditions")
                for cid in sorted(ent["conditions"]):
                    if conds.get(cid, {}).get("modifier"):
                        modifiers.append({"source": cid, "kind": "condition",
                                          "value": int(conds[cid]["modifier"]), "origin": "state"})
            if "tags" in sources:
                modifiers += self._situational(ent, target, gm_inputs, cause)

            if "difficulty" in (proc.get("inputs") or []):
                difficulty = self._difficulty(difficulty_spec, ent, target, gm_inputs.get("difficulty"), cause)

            mod = sum(m["value"] for m in modifiers)
            if gm_inputs.get("peek"):
                refusal = self._peek_refusal(proc["id"])
                if refusal:
                    raise EngineError(f"peek refused: {refusal}")
            result, roll_seq = self._roll(steps["roll"], {"mod": mod}, cause, f"procedure:{proc['id']}")
            total = result.total
            outcome = self._interpret(proc["id"], total, difficulty)
            if gm_inputs.get("peek"):
                self._open_peek({"procedure": proc["id"], "entity": ent["id"], "roll_seq": roll_seq,
                                 "expression": steps["roll"], "variables": {"mod": mod}, "total": total,
                                 "outcome": outcome, "rank": scale.index(outcome), "ranks": len(scale),
                                 "modifiers": modifiers, "difficulty": difficulty, "cause": cause,
                                 "continuation": continuation or {"kind": "none"}}, cause)
                return None, None, None

        seq = self._resolved(proc["id"], ent["id"], outcome, total, difficulty, modifiers, roll_seq,
                             direct_outcome is not None, cause)
        return outcome, scale.index(outcome), seq

    def _situational(self, ent: dict, target: dict | None, gm_inputs: dict, cause: int) -> list[dict]:
        tags = self.pack.by_id("resolution.situational_tags")
        ctx = self._ctx(ent, target)
        out = []
        for tid, tag in tags.items():
            if "derive" in tag and expr.evaluate(tag["derive"], ctx, self.rounding):
                out.append({"source": tid, "kind": "tag", "value": int(tag["value"]), "origin": "auto"})
        chosen = list(gm_inputs.get("tags") or [])
        cap = int(self.pack.get("resolution.tags_cap_per_roll", 2))
        if len(chosen) > cap:
            raise EngineError(f"at most {cap} situational tags per roll")
        mode = self.mode("situational_modifiers", self.gm_seat)
        for tid in chosen:
            if tid not in tags:
                raise EngineError(_suggest("situational tag", tid, [t for t in tags if "derive" not in tags[t]]))
            if "derive" in tags[tid]:
                raise EngineError(f"{tid} is derived from state and cannot be added by hand")
            out.append({"source": tid, "kind": "tag", "value": int(tags[tid]["value"]), "origin": "gm"})
        free = gm_inputs.get("free_modifier")
        if free:
            if mode == STRICT:
                raise EngineError("free modifiers are not available under strict settings; choose tags instead")
            bound = int(self.pack.get("resolution.free_modifier_max", 2))
            if not (-bound <= int(free) <= bound):
                raise EngineError(f"free modifier must be within ±{bound}")
            out.append({"source": "free_modifier", "kind": "free", "value": int(free), "origin": "gm"})
        if chosen or free:
            self._judge(self.gm_seat, "situational_modifiers", mode, {"tags": chosen, "free": free or 0},
                        [t for t in tags if "derive" not in tags[t]], cause)
        return out

    def _difficulty(self, spec: dict | None, ent: dict, target: dict | None, supplied: Any, cause: int) -> dict:
        if not spec:
            raise EngineError("this procedure needs a difficulty but the action declares none")
        if "derived" in spec:
            value = expr.evaluate(spec["derived"], self._ctx(ent, target), self.rounding)
            return {"value": value, "origin": "derived", "rung": None}
        ladder = self.pack.by_id("resolution.difficulty_ladders")[spec["ladder"]]
        rungs = {r["id"]: r for r in ladder["rungs"]}
        mode = self.mode("difficulty", self.gm_seat)
        if supplied is None:
            raise EngineError(f"the GM must choose a difficulty: {', '.join(rungs)}")
        if isinstance(supplied, str):
            if supplied not in rungs:
                raise EngineError(_suggest("difficulty rung", supplied, rungs))
            self._judge(self.gm_seat, "difficulty", mode, supplied, list(rungs), cause)
            return {"value": int(rungs[supplied]["value"]), "origin": "gm-rung", "rung": supplied}
        if isinstance(supplied, bool) or not isinstance(supplied, int):
            raise EngineError("difficulty must be a rung id or an integer")
        if mode == STRICT:
            raise EngineError(f"under strict settings difficulty is a rung: {', '.join(rungs)}")
        lo, hi = ladder.get("range") or [min(r["value"] for r in rungs.values()), max(r["value"] for r in rungs.values())]
        if not (lo <= supplied <= hi):
            raise EngineError(f"difficulty must be between {lo} and {hi}")
        self._judge(self.gm_seat, "difficulty", mode, supplied, [lo, hi], cause)
        return {"value": supplied, "origin": "gm-value", "rung": None}

"""Progression: XP, marks, milestones, and use-based advancement (§2.3, §2.4, BUILD_PLAN P0.15).

    progression:
      model: xp | marks | milestone | use
      awards:      [{when: session_end | outcome, amount, outcomes?, procedures?}]   # xp, marks
      thresholds:  [points for the 1st advance, the 2nd, ...]                     # xp, marks
      use:         {threshold}                                                    # use
      advances:    [{id, label, stats: {stat: delta}, tags: [...], requires, once}]

- **xp / marks:** points come only from the pack's awards, logged by the engine:
  at a session's end, or when a player's procedure lands on a listed outcome
  (mark-on-failure is an `outcome` award on the failing outcomes). Each
  threshold reached makes one advance due. `marks` differs only in name.
- **milestone:** the GM awards a milestone; each makes one advance due. At arc
  boundaries the campaign layer awards them (BUILD_PLAN P3.6).
- **use:** every roll that adds a stat counts a use of it; at `use.threshold`
  uses the stat rises by one, within its range, automatically, and its count
  starts again.
- **Advancing** is an enumerated choice, like chargen (§1.5): the engine lists
  the advances the pack offers that are legal now (requires, once, stat
  ranges) and the player picks by id, logged as a `judgement_input`.

Progress lives on the entity under `progress`, created by its first event, so
older logs and packs without progression fold unchanged. Every award and
advance carries its exact changes (D-003).
"""

from __future__ import annotations

from . import expr
from .command import EngineError, _suggest, atomic

EVENT_TYPES = frozenset({"progress_awarded", "advance_taken"})
MODELS = ("xp", "marks", "milestone", "use")
EMPTY = {"points": 0, "pending": 0, "advances": [], "uses": {}}


def spec(pack) -> dict:
    return dict(pack.get("progression") or {})


def active(pack) -> bool:
    return spec(pack).get("model") in MODELS and bool(spec(pack).get("advances") or spec(pack).get("model") == "use")


def lint_progression(pack) -> list[str]:
    p, out = spec(pack), []
    if not p or p.get("model") in (None, "milestone") and not p.get("advances") and len(p) <= 1:
        return []  # declared but unused (the core default) is fine
    model = p.get("model")
    if model not in MODELS:
        return [_suggest("progression model", model, MODELS)]
    stats = {s["id"] for s in pack.catalogue("entity_model.stats")}
    procs = pack.by_id("resolution.procedures")
    outcomes = {o for s in pack.catalogue("resolution.outcome_scales") for o in s["ordered"]}
    for a in p.get("awards") or []:
        if a.get("when") not in ("session_end", "outcome"):
            out.append(f"award {a}: when must be session_end or outcome")
        amount = a.get("amount", 1)
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
            out.append(f"award {a}: amount must be a positive integer")
        for o in a.get("outcomes") or []:
            if o not in outcomes:
                out.append(f"award: " + _suggest("outcome", o, outcomes))
        for pid in a.get("procedures") or []:
            if pid not in procs:
                out.append(f"award: " + _suggest("procedure", pid, procs))
    if model in ("xp", "marks"):
        th = p.get("thresholds") or []
        if not th or any(isinstance(t, bool) or not isinstance(t, int) or t < 1 for t in th) or th != sorted(set(th)):
            out.append("thresholds must be rising positive integers")
        if not p.get("awards"):
            out.append(f"the {model} model needs awards: what earns points")
    if model == "use":
        th = (p.get("use") or {}).get("threshold")
        if isinstance(th, bool) or not isinstance(th, int) or th < 1:
            out.append("use.threshold must be a positive integer")
    elif not p.get("advances"):
        out.append(f"the {model} model needs advances to choose from")
    ids = [a.get("id") for a in p.get("advances") or []]
    if len(ids) != len(set(ids)):
        out.append("duplicate advance ids")
    for a in p.get("advances") or []:
        for sid, delta in (a.get("stats") or {}).items():
            if sid not in stats:
                out.append(f"advance {a.get('id')}: " + _suggest("stat", sid, stats))
            if isinstance(delta, bool) or not isinstance(delta, int):
                out.append(f"advance {a.get('id')}: stat changes must be integers")
        if "requires" in a:
            try:
                expr.compile_expr(str(a["requires"]))
            except expr.ExprError as e:
                out.append(f"advance {a.get('id')}: {e}")
    return out


def apply_event(state: dict, ev: dict) -> None:
    """Fold one progression event: exact changes, like `effect_applied`."""
    from .engine import _set_path
    for change in ev["payload"]["changes"]:
        _set_path(state, change["path"], change.get("value"), change.get("delete", False))


class ProgressionCommands:
    """Awards and advances. Mixed into `Engine`."""

    def _progress(self, ent: dict) -> dict:
        return {**EMPTY, **(ent.get("progress") or {})}

    def _due(self, points: int, taken: int) -> int:
        thresholds = spec(self.pack).get("thresholds") or []
        return max(0, sum(1 for t in thresholds if points >= t) - taken)

    def _award(self, eid: str, amount: int, reason: str, cause: int | None) -> None:
        ent = self.state["entities"][eid]
        prog = self._progress(ent)
        model = spec(self.pack)["model"]
        points = prog["points"] + (amount if model in ("xp", "marks") else 0)
        if model == "milestone":
            pending = prog["pending"] + amount
        else:
            pending = self._due(points, len(prog["advances"]))
        new = {**prog, "points": points, "pending": pending}
        self._emit("progress_awarded", {"entity": eid, "amount": amount, "reason": reason,
                                        "changes": [{"path": ["entities", eid, "progress"], "value": new}]},
                   caused_by=cause)

    def _progress_on_session_end(self) -> None:
        if not active(self.pack) or spec(self.pack)["model"] not in ("xp", "marks"):
            return
        for a in spec(self.pack).get("awards") or []:
            if a.get("when") == "session_end":
                for eid in sorted(e for e, ent in self.state["entities"].items() if ent["kind"] == "pc"):
                    self._award(eid, int(a.get("amount", 1)), "session_end", None)

    def _progress_on_outcome(self, proc_id: str, entity_id: str, outcome: str, modifiers: list, cause: int) -> None:
        ent = self.state["entities"].get(entity_id)
        if not active(self.pack) or ent is None or ent["kind"] != "pc":
            return
        p = spec(self.pack)
        if p["model"] in ("xp", "marks"):
            for a in p.get("awards") or []:
                if a.get("when") == "outcome" and outcome in (a.get("outcomes") or []) and \
                        (not a.get("procedures") or proc_id in a["procedures"]):
                    self._award(entity_id, int(a.get("amount", 1)), f"outcome:{outcome}", cause)
        elif p["model"] == "use":
            for m in modifiers:
                if m["kind"] == "stat":
                    self._use(entity_id, m["source"], cause)

    def _use(self, eid: str, stat: str, cause: int) -> None:
        ent = self.state["entities"][eid]
        prog = self._progress(ent)
        uses = dict(prog["uses"])
        uses[stat] = uses.get(stat, 0) + 1
        threshold = int((spec(self.pack).get("use") or {}).get("threshold", 1))
        changes = []
        _, hi = next((s.get("range", [None, None]) for s in self.pack.catalogue("entity_model.stats")
                       if s["id"] == stat), [None, None])
        if uses[stat] >= threshold and hi is not None and ent["stats"][stat] < hi:
            uses[stat] = 0
            changes.append({"path": ["entities", eid, "stats", stat], "value": ent["stats"][stat] + 1})
            new = {**prog, "uses": uses, "advances": prog["advances"] + [f"use:{stat}"]}
            changes.append({"path": ["entities", eid, "progress"], "value": new})
            self._emit("advance_taken", {"entity": eid, "option": f"use:{stat}", "automatic": True,
                                         "changes": changes}, caused_by=cause)
            return
        changes.append({"path": ["entities", eid, "progress"], "value": {**prog, "uses": uses}})
        self._emit("progress_awarded", {"entity": eid, "amount": 1, "reason": f"use:{stat}", "changes": changes},
                   caused_by=cause)

    def advance_models(self) -> bool:
        """Whether this pack's progression is live (declared with something to advance)."""
        return active(self.pack)

    def advance_options(self, entity_id: str) -> list[str]:
        """The advances the entity may take now, in pack order."""
        ent = self._entity(entity_id)
        if not active(self.pack) or self._progress(ent)["pending"] < 1:
            return []
        ranges = {s["id"]: s.get("range", [None, None]) for s in self.pack.catalogue("entity_model.stats")}
        out = []
        for a in spec(self.pack).get("advances") or []:
            if a.get("once") and a["id"] in self._progress(ent)["advances"]:
                continue
            if "requires" in a and not expr.evaluate(str(a["requires"]), self._ctx(ent, None), self.rounding):
                continue
            if any(not (ranges[s][0] <= ent["stats"][s] + d <= ranges[s][1]) for s, d in (a.get("stats") or {}).items()):
                continue
            out.append(a["id"])
        return out

    @atomic
    def take_advance(self, entity_id: str, option_id: str, by: str | None = None) -> None:
        """Take one due advance (§1.5 pattern): an id from `advance_options`."""
        ent = self._entity(entity_id)
        by = by or ent["controller"]
        if by != ent["controller"] and self._role(by) != "gm":
            raise EngineError(f"{by!r} does not control {entity_id!r}")
        prog = self._progress(ent)
        if prog["pending"] < 1:
            raise EngineError(f"{entity_id} has no advance due")
        options = self.advance_options(entity_id)
        if option_id not in options:
            raise EngineError(_suggest("advance", option_id, options))
        advance = next(a for a in spec(self.pack)["advances"] if a["id"] == option_id)
        changes = [{"path": ["entities", entity_id, "stats", s], "value": ent["stats"][s] + int(d)}
                   for s, d in sorted((advance.get("stats") or {}).items())]
        if advance.get("tags"):
            changes.append({"path": ["entities", entity_id, "tags"],
                            "value": sorted(set(ent["tags"]) | set(advance["tags"]))})
        new = {**prog, "pending": prog["pending"] - 1, "advances": prog["advances"] + [option_id]}
        changes.append({"path": ["entities", entity_id, "progress"], "value": new})
        seq = self._emit("advance_taken", {"entity": entity_id, "option": option_id, "automatic": False,
                                           "changes": changes}, actor=by)
        self._judge(by, "advance", None, option_id, options, seq)

    @atomic
    def award_milestone(self, entity_id: str | None = None, by: str | None = None) -> None:
        """Milestone model: the GM awards one advance to a character, or to every PC."""
        by = by or self.gm_seat
        if by != "engine" and self._role(by) != "gm":
            raise EngineError("only the GM awards milestones")
        if not active(self.pack) or spec(self.pack)["model"] != "milestone":
            raise EngineError(f"pack {self.pack.id} does not use milestone progression")
        targets = [entity_id] if entity_id else sorted(e for e, ent in self.state["entities"].items()
                                                        if ent["kind"] == "pc")
        for eid in targets:
            if self._entity(eid)["kind"] != "pc":
                raise EngineError(f"{eid} is not a player character")
            self._award(eid, 1, "milestone", None)

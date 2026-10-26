"""Candidate generation and mastery tiering (§1.4.2, §1.4.3).

The engine hands an agent a short, ranked list of legal options by id; the
agent picks one. Nothing here returns coordinates (§1.4.1).

Scoring is split along the P8 line:

- The kernel computes generic **features** for a candidate position, counted
  over the entities the observing seat can see (never hidden ones):
  `threats_here`, `threats_adjacent`, `allies_here`, `allies_adjacent`,
  `closer` (steps gained towards the nearest threat), `elevation_change`, and
  for actions `target_threat` / `target_ally`.
  A threat is a visible entity on the other side (GM-controlled versus
  player-controlled); an ally is one on the same side.
- The pack's `spatial.tactical_profile` supplies `weights` for those features,
  `factors` (expressions adding system-specific weight, optionally limited to
  some actions), annotation
  `categories` with their order, and `annotation_templates`.

Mastery tiers are kernel settings. A higher tier returns more of the same
ranked list and more annotation categories, so a lower tier's output is always
a strict information subset of a higher tier's on the same state.

Read-only: nothing here emits events or touches the randomizer.
"""

from __future__ import annotations

import string
from typing import Any

from . import expr
from .command import EngineError, _suggest

# Kernel settings (Appendix C kernel_config): (highest mastery, min options, max options).
MASTERY_TIERS = ((33, 4, 5), (66, 7, 8), (100, 10, 12))
CANDIDATE_CAP = 12
FEATURES = ("threats_here", "threats_adjacent", "allies_here", "allies_adjacent", "closer", "elevation_change",
            "target_threat", "target_ally", "provokes")
PLACEHOLDERS = {"region", "label", "action", "target", "threats_here", "allies_here", "provokers"}
APPLIES_TO = ("move", "action")


def tier_of(mastery: int) -> tuple[int, int]:
    """(tier index, option count) for a mastery value. The count rises with
    mastery inside a tier, so it never falls as mastery grows."""
    if isinstance(mastery, bool) or not isinstance(mastery, int) or not 0 <= mastery <= 100:
        raise EngineError("mastery must be an integer from 0 to 100")
    low = 0
    for i, (high, lo, hi) in enumerate(MASTERY_TIERS):
        if mastery <= high:
            count = lo + (mastery - low) * (hi - lo + 1) // (high - low + 1)
            return i, min(count, CANDIDATE_CAP)
        low = high + 1
    raise AssertionError("tiers must cover 0..100")


def profile(pack) -> dict:
    sp = pack.get("spatial")
    return dict(sp.get("tactical_profile") or {}) if isinstance(sp, dict) else {}


def template_fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}


def lint_profile(pack) -> list[str]:
    """Problems in a pack's tactical profile, for pack lint (§2.10). Under
    `spatial: none` the tactical tools are absent, so the profile is dormant
    and not checked (§2.12)."""
    if not isinstance(pack.get("spatial"), dict):
        return []
    prof, out = profile(pack), []
    cats = prof.get("categories") or []
    ids = [c.get("id") for c in cats]
    if len(ids) != len(set(ids)):
        out.append("duplicate annotation category ids")
    for c in cats:
        if c.get("order") not in (1, 2):
            out.append(f"category {c.get('id')}: order must be 1 (first-order) or 2 (second-order)")
    for key, weight in (prof.get("weights") or {}).items():
        if key not in FEATURES:
            out.append(_suggest("tactical feature", key, FEATURES))
        if isinstance(weight, bool) or not isinstance(weight, int):
            out.append(f"weight {key} must be an integer")
    for kind in ("factors", "annotation_templates"):
        for item in prof.get(kind) or []:
            where = f"{kind} {item.get('id')}"
            if item.get("applies_to") not in APPLIES_TO:
                out.append(f"{where}: applies_to must be move or action")
            try:
                expr.compile_expr(str(item.get("when", "1")))
            except expr.ExprError as e:
                out.append(f"{where}: {e}")
            if kind == "factors" and (isinstance(item.get("weight"), bool) or not isinstance(item.get("weight"), int)):
                out.append(f"{where}: weight must be an integer")
            known = pack.by_id("actions")
            for aid in item.get("actions") or []:
                if aid not in known:
                    out.append(f"{where}: " + _suggest("action", aid, known))
            if kind == "annotation_templates":
                if item.get("category") not in ids:
                    out.append(f"{where}: " + _suggest("category", item.get("category"), ids))
                try:
                    bad = template_fields(str(item.get("text", ""))) - PLACEHOLDERS
                except ValueError as e:
                    bad = {f"malformed text ({e})"}
                if bad or not str(item.get("text", "")).strip():
                    out.append(f"{where}: text needs content and may use only {{{'}, {'.join(sorted(PLACEHOLDERS))}}}"
                               + (f"; found {sorted(bad)}" if bad else ""))
    for action in pack.catalogue("actions"):
        for cat in action.get("annotation_categories") or []:
            if cat not in ids:
                out.append(f"action {action['id']}: " + _suggest("annotation category", cat, ids))
    return out


class TacticalCommands:
    """Read-only candidate queries. Mixed into `Engine`; uses spatial helpers,
    `view`, and the action checks."""

    # ------------------------------------------------------------ context

    def _observer(self, entity_id: str) -> str:
        return self.state["entities"][entity_id]["controller"]

    def _side(self, ent: dict) -> str:
        return "gm" if self._role(ent["controller"]) == "gm" else "players"

    def _seen(self, observer: str, actor_id: str) -> list[str]:
        """Entities the observer can see, other than the actor, in id order."""
        spatial = self._spatial()
        return [e for e in sorted(self.state["entities"])
                if e != actor_id and self.visible(observer, e) and (spatial is None or self._in_scene(e))]

    def _region_view(self, actor_id: str, at: str | None) -> dict:
        """The region an entity stands in (or would stand in at `at`), for
        expressions: elevation, terrain, cover. Neutral where a backend has no regions."""
        spatial = self._spatial()
        region = self._backend(spatial).region(spatial, self.state["entities"], actor_id, at) if spatial else None
        if region is None:
            return expr.Lenient({"elevation": 0, "terrain": expr.Lenient(), "cover": expr.Lenient()})
        return expr.Lenient({"elevation": region["elevation"],
                             "terrain": expr.Lenient({region["terrain"]: 1} if region["terrain"] else {}),
                             "cover": expr.Lenient({region["cover"]: 1} if region["cover"] else {})})

    def _features(self, actor_id: str, origin: str | None, focus: str | None,
                  target_id: str | None = None) -> tuple[dict, dict]:
        """Kernel features for the actor at position `focus` (where a move or
        action leads), measured against position `origin` (where it stands);
        None means its current position. Also returns the ids behind the counts,
        for template text. Only entities the seat can see count."""
        ent = self.state["entities"][actor_id]
        observer, side = self._observer(actor_id), self._side(ent)
        seen = self._seen(observer, actor_id)
        threats = [e for e in seen if self._side(self.state["entities"][e]) != side]
        allies = [e for e in seen if self._side(self.state["entities"][e]) == side]
        s_from, s_to = self.steps_from(actor_id, origin), self.steps_from(actor_id, focus)

        def within(group, steps, n):
            return [e for e in group if steps.get(e) == n]

        def nearest(steps):
            found = [steps[t] for t in threats if t in steps]
            return min(found) if found else None

        provokers = [e for e in self._provokers(actor_id, focus) if e in seen] if focus and origin is None else []
        names = {"threats_here": within(threats, s_to, 0), "allies_here": within(allies, s_to, 0),
                 "provokers": provokers}
        d_from, d_to = nearest(s_from), nearest(s_to)
        target = self.state["entities"].get(target_id) if target_id else None
        feats = {
            "threats_here": len(names["threats_here"]),
            "threats_adjacent": len(within(threats, s_to, 1)),
            "allies_here": len(names["allies_here"]),
            "allies_adjacent": len(within(allies, s_to, 1)),
            "closer": (d_from - d_to) if d_from is not None and d_to is not None else 0,
            "elevation_change": self._region_view(actor_id, focus)["elevation"]
                                - self._region_view(actor_id, origin)["elevation"],
            "target_threat": int(target is not None and self._side(target) != side),
            "target_ally": int(target is not None and self._side(target) == side),
            "provokes": len(provokers),
        }
        return feats, names

    def _ctx_for(self, actor_id: str, origin: str | None, focus: str | None,
                 target_id: str | None) -> tuple[dict, dict, dict]:
        feats, names = self._features(actor_id, origin, focus, target_id)
        ent = self.state["entities"][actor_id]
        target = self.state["entities"].get(target_id) if target_id else None
        ctx = self._ctx(ent, target, {**feats, "region": self._region_view(actor_id, focus),
                                      "here": self._region_view(actor_id, origin)})
        if target is None:  # templates may read target.conditions.* or target.tags.*: no target reads as 0
            ctx["target"] = expr.Lenient({"conditions": expr.Lenient(), "tags": expr.Lenient()})
        return ctx, feats, names

    def _fill(self, names: dict, region: str | None, label: str = "", action: str = "", target: str | None = None) -> dict:
        return {"region": region or "", "label": label, "action": action, "target": target or "",
                "threats_here": ", ".join(names["threats_here"]) or "none",
                "allies_here": ", ".join(names["allies_here"]) or "none",
                "provokers": ", ".join(names.get("provokers") or []) or "none"}

    def _score(self, applies_to: str, ctx: dict, feats: dict, action_id: str | None = None) -> int:
        prof = profile(self.pack)
        score = 0
        if applies_to == "move":
            score += sum(int(w) * feats[k] for k, w in (prof.get("weights") or {}).items())
        for factor in prof.get("factors") or []:
            if factor.get("applies_to") != applies_to:
                continue
            if factor.get("actions") and action_id not in factor["actions"]:
                continue
            if expr.evaluate(str(factor.get("when", "1")), ctx, self.rounding):
                score += int(factor["weight"])
        return score

    def _annotations(self, applies_to: str, ctx: dict, fill: dict, tier: int,
                     categories: list[str] | None = None) -> list[dict]:
        if tier == 0:
            return []  # bare positions (§1.4.3)
        prof = profile(self.pack)
        order = {c["id"]: c["order"] for c in prof.get("categories") or []}
        out = []
        for tpl in prof.get("annotation_templates") or []:
            cat = tpl["category"]
            if tpl.get("applies_to") != applies_to or (tier == 1 and order.get(cat) != 1):
                continue
            if categories is not None and cat not in categories:
                continue
            if expr.evaluate(str(tpl.get("when", "1")), ctx, self.rounding):
                out.append({"category": cat, "text": str(tpl["text"]).format_map(fill)})
        return out

    # ------------------------------------------------------------ queries

    def _label(self, position: str) -> str:
        spatial = self._spatial()
        return self._backend(spatial).label(spatial, self.state["entities"], position) if spatial else position

    def enumerate_moves(self, entity_id: str, mastery: int) -> list[dict]:
        """Ranked, tiered move candidates for an entity (§1.4.2). Empty outside a
        spatial scene or when the entity is not placed in it. The same shape
        under every backend; zone scenes also name the region."""
        self._entity(entity_id)
        tier, count = tier_of(mastery)
        if not self._in_scene(entity_id):
            return []
        zone = self._spatial()["mode"] == "zone"
        ranked = []
        for pos in self.reachable(entity_id):
            ctx, feats, names = self._ctx_for(entity_id, None, pos, None)
            fill = self._fill(names, pos, self._label(pos))
            ranked.append((-self._score("move", ctx, feats), pos, ctx, fill))
        ranked.sort(key=lambda r: (r[0], r[1]))
        out = []
        for _, pos, ctx, fill in ranked[:count]:
            cand = {"id": pos, "position_id": pos, "label": fill["label"],
                    "annotations": self._annotations("move", ctx, fill, tier)}
            if zone:
                cand["region_id"] = pos
            out.append(cand)
        return out

    def _action_targets(self, entity_id: str, action: dict, position: str | None) -> list[str | None]:
        kind = action.get("target", "none")
        if kind == "entity":
            return self._seen(self._observer(entity_id), entity_id)
        if kind == "zone":
            return self.reachable(entity_id, at=position) if self._spatial() is not None else []
        return [None]

    def enumerate_action_candidates(self, entity_id: str, mastery: int, position_id: str | None = None) -> list[dict]:
        """Ranked, tiered action candidates (§7.1 `enumerate_actions`), each an
        (action, target) pair the engine would accept. `position_id` asks what
        would be available from a position one move away instead."""
        ent = self._entity(entity_id)
        tier, count = tier_of(mastery)
        here = self.position_of(entity_id)
        position = None
        if position_id is not None and position_id != here:
            if position_id not in self.reachable(entity_id):
                raise EngineError(_suggest("position", position_id, ([here] if here else []) + self.reachable(entity_id)))
            position = position_id
        order = {a["id"]: i for i, a in enumerate(self.pack.catalogue("actions"))}
        actions = self.pack.by_id("actions")
        ranked = []
        for aid in self.available_actions(entity_id):
            action = actions[aid]
            for tid in self._action_targets(entity_id, action, position):
                target_ent = self.state["entities"].get(tid) if action.get("target") == "entity" else None
                if target_ent is not None and not (self._requires_ok(action, ent, target_ent)
                                                   and (action.get("trigger") != "fiction"
                                                        or self._eligible(action, ent, target_ent))):
                    continue
                focus = tid if action.get("target") == "zone" else position
                ctx, feats, names = self._ctx_for(entity_id, position, focus, tid if target_ent else None)
                fill = self._fill(names, focus or here, action=aid, target=tid)
                ranked.append((-self._score("action", ctx, feats, aid), order[aid], tid or "", aid, tid, ctx, fill))
        ranked.sort(key=lambda r: r[:3])
        out = []
        for _, _, _, aid, tid, ctx, fill in ranked[:count]:
            out.append({"id": f"{aid}@{tid}" if tid else aid, "action_id": aid, "target": tid,
                        "annotations": self._annotations("action", ctx, fill, tier,
                                                         actions[aid].get("annotation_categories") or [])})
        return out

    def preview(self, entity_id: str, action_id: str, mastery: int, target: str | None = None) -> dict:
        """What an action would do (§7.1): procedure, cost, difficulty kind,
        legal targets, effects per outcome, and tiered annotations. Never rolls,
        and never shows a value derived from what the seat cannot see."""
        ent = self._entity(entity_id)
        actions = self.pack.by_id("actions")
        if action_id not in actions:
            raise EngineError(_suggest("action", action_id, actions))
        action = actions[action_id]
        tier, _ = tier_of(mastery)
        targets = self._action_targets(entity_id, action, None)
        if target is not None and target not in targets:
            raise EngineError(_suggest("target", target, [t for t in targets if t]))
        spec = action.get("difficulty")
        if isinstance(spec, dict) and "ladder" in spec:
            ladder = self.pack.by_id("resolution.difficulty_ladders").get(spec["ladder"], {})
            difficulty = {"kind": "ladder", "rungs": [r["id"] for r in ladder.get("rungs", [])]}
        elif isinstance(spec, dict) and "derived" in spec:
            difficulty = {"kind": "derived"}
        else:
            difficulty = None
        target_ent = self.state["entities"].get(target) if action.get("target") == "entity" and target else None
        focus = target if action.get("target") == "zone" and target else None
        ctx, _, names = self._ctx_for(entity_id, None, focus, target if target_ent else None)
        fill = self._fill(names, focus or self.position_of(entity_id), action=action_id, target=target)
        return {
            "action_id": action_id,
            "available": action_id in self.available_actions(entity_id),
            "procedure": action.get("procedure"),
            "stat": action.get("stat"),
            "trigger": action.get("trigger", "declared"),
            "cost": dict(action.get("cost") or {}) or None,
            "difficulty": difficulty,
            "target_kind": action.get("target", "none"),
            "targets": [t for t in targets if t],
            "outcomes": {o: [dict(e) for e in effects or []]
                         for o, effects in (action.get("outcome_effects") or {}).items()},
            "annotations": self._annotations("action", ctx, fill, tier, action.get("annotation_categories") or []),
        }

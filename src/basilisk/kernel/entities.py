"""Entities: player characters from chargen (§1.5) and GM-spawned entities
(§5.2, §5.3). Mixed into `Engine`.

A spawned entity is an `npc` or a `prop` (§8.2). A prop can be targeted,
damaged, and tagged like any entity, but it is never a default encounter
participant and never rolls; `interactable: false` makes it scenery that no
action can target. The GM spawns from a pack template (`entity_model.templates`,
picked by id, so no model-supplied number crosses); the engine command also
takes the full spec, for prep and scripted harnesses, each field checked
against the pack.
"""

from __future__ import annotations

from . import expr
from .command import EngineError, _suggest, atomic, check_id, check_name, gm_call

KINDS = ("npc", "prop")


# ---------------------------------------------------------------- point-buy chargen (§1.5)

def point_cost(step: dict, value: int) -> int:
    """What one stat at `value` costs in a `points` step: `cost` per point above
    the range's low end, or, when `cost` is a list, its entry for the value
    (one cost per value, from the range's low end up)."""
    cost = step.get("cost", 1)
    if isinstance(cost, list):
        return int(cost[value - step["range"][0]])
    return (value - step["range"][0]) * int(cost)


def allocate_points(step: dict, order: list[str] | None = None) -> dict[str, int]:
    """A legal allocation for a `points` step: every target starts low, then
    one target at a time (in `order`) rises while the pool allows. For
    scripted actors and generated tests; agents choose their own."""
    lo, hi = step["range"]
    order = list(order or step["targets"])
    alloc = {t: lo for t in step["targets"]}
    spent = sum(point_cost(step, lo) for _ in step["targets"])
    raised = True
    while raised:
        raised = False
        for t in order:
            if alloc[t] < hi:
                extra = point_cost(step, alloc[t] + 1) - point_cost(step, alloc[t])
                if spent + extra <= step["pool"]:
                    alloc[t] += 1
                    spent += extra
                    raised = True
    return alloc


def lint_points(step: dict, stats: dict) -> list[str]:
    """Problems in one `points` chargen step, for pack lint (§2.10)."""
    where, out = f"step {step.get('id')}", []
    targets = step.get("targets") or []
    if not targets:
        out.append(f"{where}: a points step needs targets")
    for target in targets:
        if target not in stats:
            out.append(f"{where}: " + _suggest("stat", target, stats))
    rng, pool, cost = step.get("range"), step.get("pool"), step.get("cost", 1)
    if not (isinstance(rng, list) and len(rng) == 2 and all(isinstance(v, int) and not isinstance(v, bool)
                                                            for v in rng) and rng[0] <= rng[1]):
        return out + [f"{where}: range must be [min, max], integers with min <= max; got {rng!r}"]
    for target in targets:
        lo, hi = stats.get(target, {}).get("range", rng)
        if not (lo <= rng[0] and rng[1] <= hi):
            out.append(f"{where}: range {rng} goes outside {target}'s range {lo}..{hi}")
    if isinstance(pool, bool) or not isinstance(pool, int) or pool < 0:
        out.append(f"{where}: pool must be a non-negative integer, not {pool!r}")
        return out
    if isinstance(cost, list):  # one cost per value, low end first (canonical keys are strings, D-059)
        if len(cost) != rng[1] - rng[0] + 1:
            return out + [f"{where}: the cost list needs one entry per value from {rng[0]} to {rng[1]} "
                          f"({rng[1] - rng[0] + 1}), not {len(cost)}"]
        if any(isinstance(c, bool) or not isinstance(c, int) or c < 0 for c in cost) or cost != sorted(cost):
            return out + [f"{where}: costs must be non-negative integers that never fall as the value rises"]
    elif isinstance(cost, bool) or not isinstance(cost, int) or cost < 1:
        return out + [f"{where}: cost must be a positive integer or a list of costs per value, not {cost!r}"]
    if "exact" in step and not isinstance(step["exact"], bool):
        out.append(f"{where}: exact is true or false")
    low = len(targets) * point_cost(step, rng[0])
    high = len(targets) * point_cost(step, rng[1])
    if pool < low or (step.get("exact", True) and pool > high):
        out.append(f"{where}: a pool of {pool} cannot be spent within the range (it costs {low} to {high})")
    elif step.get("exact", True) and targets and sum(
            point_cost(step, v) for v in allocate_points(step).values()) != pool:
        out.append(f"{where}: no allocation spends the pool of {pool} exactly at these costs")
    return out
TEMPLATE_FIELDS = ("kind", "stats", "resources", "tags", "items", "conditions")


def _template_stats(pack, stats: dict) -> dict[str, int]:
    """Stats at their defaults, overridden, then the derived values, for limits."""
    base = {s["id"]: int(s.get("default", 0)) for s in pack.catalogue("entity_model.stats")}
    base.update({k: v for k, v in stats.items() if isinstance(v, int) and not isinstance(v, bool)})
    rounding = pack.get("presentation.rounding", "floor")
    for d in pack.catalogue("entity_model.derived"):
        base[d["id"]] = expr.evaluate(d["expr"], {**base, "actor": base}, rounding)
    return base


def lint_templates(pack) -> list[str]:
    """Problems in `entity_model.templates`, for pack lint (§2.10). Limits that
    depend on a broken formula are skipped: the expression lint reports it."""
    try:
        return _template_problems(pack)
    except expr.ExprError:
        return []


def _template_problems(pack) -> list[str]:
    out = []
    stats = pack.by_id("entity_model.stats")
    resources = pack.by_id("entity_model.resources")
    conditions = pack.by_id("entity_model.conditions")
    declared_tags = set(pack.get("entity_model.tags") or [])
    weighted = (pack.get("entity_model.inventory") or {}).get("model") == "weight"
    items = pack.by_id("entity_model.items")
    rounding = pack.get("presentation.rounding", "floor")
    for t in pack.catalogue("entity_model.templates"):
        where = f"template {t.get('id')}"
        if not t.get("label"):
            out.append(f"{where}: needs a label")
        if t.get("kind", "npc") not in KINDS:
            out.append(f"{where}: kind must be npc or prop, not {t.get('kind')!r}")
        for sid, value in (t.get("stats") or {}).items():
            if sid not in stats:
                out.append(f"{where}: " + _suggest("stat", sid, stats))
                continue
            lo, hi = stats[sid].get("range", [value, value])
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                out.append(f"{where}: stat {sid} must be an integer from {lo} to {hi}, not {value!r}")
        own = _template_stats(pack, t.get("stats") or {})
        for rid, value in (t.get("resources") or {}).items():
            if rid not in resources:
                out.append(f"{where}: " + _suggest("resource", rid, resources))
                continue
            lo = int(resources[rid].get("min", 0))
            hi = expr.evaluate(resources[rid]["max"], {**own, "actor": own}, rounding)
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                out.append(f"{where}: resource {rid} must be an integer from {lo} to {hi}, not {value!r}")
        for tag in t.get("tags") or []:
            if declared_tags and tag not in declared_tags:
                out.append(f"{where}: " + _suggest("tag", tag, sorted(declared_tags)))
        for cid in t.get("conditions") or []:
            if cid not in conditions:
                out.append(f"{where}: " + _suggest("condition", cid, conditions))
        if weighted:
            for item in t.get("items") or []:
                if item not in items:
                    out.append(f"{where}: " + _suggest("item", item, items))
            spec = pack.get("entity_model.inventory") or {}
            if spec.get("limit_expr"):
                limit = expr.evaluate(spec["limit_expr"], {**own, "actor": own}, rounding)
                carried = sum(int(items.get(i, {}).get("weight", 0)) for i in t.get("items") or [])
                if carried > limit:
                    out.append(f"{where}: its items weigh {carried}, more than its carry limit {limit}")
    return out


class EntityCommands:
    """Character creation and spawning."""

    def _new_entity(self, entity_id: str, name: str, kind: str, controller: str, stats: dict[str, int]) -> dict:
        ent = {
            "id": entity_id, "name": name, "kind": kind, "controller": controller,
            "stats": {}, "resources": {}, "tracks": {}, "conditions": {}, "tags": [],
            "inventory": [], "zone": None, "currencies": {}, "details": [],
        }
        for s in self.pack.catalogue("entity_model.stats"):
            value = int(stats.get(s["id"], s.get("default", 0)))
            lo, hi = s.get("range", [value, value])
            ent["stats"][s["id"]] = max(lo, min(hi, value))
        unknown = set(stats) - set(ent["stats"])
        if unknown:
            raise EngineError(_suggest("stat", sorted(unknown)[0], ent["stats"]))
        for r in self.pack.catalogue("entity_model.resources"):
            ent["resources"][r["id"]] = self._max(ent, r)
        for t in self.pack.catalogue("entity_model.tracks"):
            ent["tracks"][t["id"]] = 0
        for c in self.pack.catalogue("gm.meta_currencies"):
            if c.get("holder", "each_player") == "each_player" and kind == "pc":  # pools are shared (§2.3)
                ent["currencies"][c["id"]] = int(c.get("start", 0))
        return ent

    @atomic
    def create_character(self, agent_id: str, name: str, choices: dict[str, str] | None = None,
                         entity_id: str | None = None) -> str:
        if self.seats.get(agent_id) != "player":
            raise EngineError(f"{agent_id!r} is not a player seat")
        entity_id = check_id("entity", entity_id or agent_id)
        check_name("a character's name", name)
        if entity_id in self.state["entities"]:
            raise EngineError(f"entity {entity_id!r} already exists")
        choices = dict(choices or {})
        start = self._emit("chargen_started", {"agent": agent_id, "entity": entity_id}, actor=agent_id)
        stats: dict[str, int] = {}
        tags: list[str] = []
        details: list[str] = []
        unique: dict[str, str] = {}
        items: list[str] = []  # starting equipment and currencies from choices (§1.5)
        grants: dict[str, int] = {}
        tables = self.pack.by_id("randomizers.tables")
        for step in self.pack.get("chargen.steps") or []:
            kind = step["kind"]
            if kind == "roll":
                for target in step["targets"]:
                    result, _ = self._roll(step["roll"], {}, start, f"chargen:{step['id']}:{target}", actor="engine")
                    stats[target] = result.total
            elif kind == "choice":
                options = {o["id"]: o for o in step.get("options") or []}
                taken = set(self.state["chargen_taken"].get(step["id"], [])) if step.get("unique_per_table") else set()
                available = [o for o in options if o not in taken]
                pick = choices.get(step["id"])
                if pick not in options:
                    raise EngineError(_suggest(f"option for {step['id']}", pick, available))
                if pick in taken:
                    raise EngineError(f"{pick!r} is already taken at this table ({step['id']} is unique per table)")
                self._judge(agent_id, "chargen_choice", None, pick, available, start)
                stats.update(options[pick].get("stats") or {})
                tags += options[pick].get("tags") or []
                items += options[pick].get("items") or []
                for cid, amount in (options[pick].get("currencies") or {}).items():
                    grants[cid] = grants.get(cid, 0) + int(amount)
                if step.get("unique_per_table"):
                    unique[step["id"]] = pick
            elif kind == "assign":  # place a fixed array of values onto stats (§1.5)
                pick = choices.get(step["id"])
                values, targets = list(step["values"]), list(step["targets"])
                if not isinstance(pick, dict) or sorted(pick) != sorted(targets):
                    raise EngineError(f"{step['id']}: assign each of {', '.join(targets)} one of the values "
                                      f"{values}, as {{stat: value}}")
                if sorted(pick.values()) != sorted(values):
                    raise EngineError(f"{step['id']}: the values must be exactly {sorted(values)}, each used once; "
                                      f"got {sorted(pick.values())}")
                self._judge(agent_id, "chargen_assign", None, {t: pick[t] for t in targets}, values, start)
                stats.update({t: int(pick[t]) for t in targets})
            elif kind == "points":  # point-buy: spend a pool over the targets (§1.5)
                pick = choices.get(step["id"])
                targets, (lo, hi), pool = list(step["targets"]), step["range"], int(step["pool"])
                if not isinstance(pick, dict) or sorted(pick) != sorted(targets):
                    raise EngineError(f"{step['id']}: give each of {', '.join(targets)} a value from {lo} to {hi}, "
                                      "as {stat: value}")
                for target in targets:
                    value = pick[target]
                    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                        raise EngineError(f"{step['id']}: {target} must be an integer from {lo} to {hi}, "
                                          f"not {value!r}")
                spent = sum(point_cost(step, pick[t]) for t in targets)
                exact = step.get("exact", True)
                if spent > pool or (exact and spent != pool):
                    raise EngineError(f"{step['id']}: that costs {spent} points; spend "
                                      + (f"exactly {pool}" if exact else f"at most {pool}"))
                self._judge(agent_id, "chargen_points", None, {t: pick[t] for t in targets},
                            {"pool": pool, "range": [lo, hi], "cost": step.get("cost", 1), "exact": exact}, start)
                stats.update({t: int(pick[t]) for t in targets})
            elif kind == "table":
                table = tables[step["table"]]
                result, roll_seq = self._roll(table["roll"], {}, start, f"chargen:{step['id']}", actor="engine")
                entry = next(e for e in table["entries"] if e["range"][0] <= result.total <= e["range"][1])
                self._emit("table_rolled", {"table": table["id"], "value": result.total, "text": entry.get("text", "")},
                           caused_by=roll_seq)
                details.append(entry.get("text", ""))
        ent = self._new_entity(entity_id, name, "pc", agent_id, stats)
        ent["tags"] = sorted(set(tags))
        ent["details"] = details
        ent["inventory"] = list(items)
        currencies = self.pack.by_id("gm.meta_currencies")
        for cid, amount in sorted(grants.items()):
            ent["currencies"][cid] = min(int(currencies[cid].get("max", 10**6)), ent["currencies"].get(cid, 0) + amount)
        limit = self.capacity(ent)
        if limit is not None and self.carried(ent) > limit:
            raise EngineError(f"{entity_id} would start carrying {self.carried(ent)} of {limit}: "
                              "these choices give more equipment than the character can carry")
        for hook in self._hooks_at("sheet.validate"):  # cross-field constraints (§2.7)
            problems = self._call_hook(hook["name"], "sheet.validate", self._sheet_view(ent), {}, start, rolls=False)
            if problems:
                raise EngineError(f"{entity_id}'s sheet breaks {hook['name']}: {'; '.join(map(str, problems))}")
        self._emit("character_created", {"entity": ent, "unique_choices": unique, "choices": choices},
                   actor=agent_id, caused_by=start)
        return entity_id

    def _spawn_spec(self, template: str | None, given: dict) -> dict:
        templates = self.pack.by_id("entity_model.templates")
        if template is not None and template not in templates:
            raise EngineError(_suggest("template", template, templates))
        spec = {k: (templates[template].get(k) if template else None) for k in TEMPLATE_FIELDS}
        spec.update({k: v for k, v in given.items() if v is not None})
        spec["kind"] = spec.get("kind") or "npc"
        if spec["kind"] not in KINDS:
            raise EngineError(_suggest("kind", spec["kind"], KINDS))
        for key in ("stats", "resources"):
            spec[key] = dict(spec.get(key) or {})
        for key in ("tags", "items", "conditions"):
            spec[key] = list(spec.get(key) or [])
        return spec

    def _outfit(self, ent: dict, spec: dict) -> None:
        """A spawned entity's starting resources, tags, items, and conditions,
        each checked against the pack."""
        resources = self.pack.by_id("entity_model.resources")
        for rid, value in sorted(spec["resources"].items()):
            if rid not in resources:
                raise EngineError(_suggest("resource", rid, resources))
            lo, hi = int(resources[rid].get("min", 0)), self._max(ent, resources[rid])
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise EngineError(f"resource {rid} starts from {lo} to {hi}, not {value!r}")
            ent["resources"][rid] = value
        declared = set(self.pack.get("entity_model.tags") or [])
        for tag in spec["tags"]:
            check_id("tag", tag)
            if declared and tag not in declared:
                raise EngineError(_suggest("tag", tag, sorted(declared)))
        ent["tags"] = sorted(set(spec["tags"]))
        weighted = self._inventory_model() == "weight"
        catalogue = self.pack.by_id("entity_model.items")
        for item in spec["items"]:
            if weighted and item not in catalogue:
                raise EngineError(_suggest("item", item, catalogue))
            check_id("item", item)
        ent["inventory"] = list(spec["items"])
        limit = self.capacity(ent)
        if limit is not None and self.carried(ent) > limit:
            raise EngineError(f"{ent['id']} would start carrying {self.carried(ent)} of {limit}")
        conditions = self.pack.by_id("entity_model.conditions")
        for cid in spec["conditions"]:
            if cid not in conditions:
                raise EngineError(_suggest("condition", cid, conditions))
            value = {"since_scene": self.state["scene"]["index"]}
            if conditions[cid].get("stacking", "none") == "intensity":
                value["level"] = 1
            ent["conditions"][cid] = value

    @atomic
    @gm_call()
    def spawn_entity(self, entity_id: str, name: str, stats: dict[str, int] | None = None,
                     zone: str | None = None, by: str | None = None, template: str | None = None,
                     kind: str | None = None, resources: dict[str, int] | None = None,
                     tags: list[str] | None = None, items: list[str] | None = None,
                     conditions: list[str] | None = None, interactable: bool | None = None) -> str:
        """Instantiate fiction into state (§5.2): from a pack template by id, a
        name, and optionally the spec's own fields, which override the template's."""
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM can spawn entities")
        check_id("entity", entity_id)
        check_name("an entity's name", name)
        spec = self._spawn_spec(template, {"kind": kind, "stats": stats, "resources": resources, "tags": tags,
                                           "items": items, "conditions": conditions})
        for sid, value in spec["stats"].items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise EngineError(f"stat {sid!r} must be an integer, not {value!r}")
        if entity_id in self.state["entities"]:
            raise EngineError(f"entity {entity_id!r} already exists")
        if interactable is not None and not isinstance(interactable, bool):
            raise EngineError("interactable is true or false")
        if zone is not None:
            self._check_position(zone)
        relative = zone is not None and (self._spatial() or {}).get("mode") == "bands"
        ent = self._new_entity(entity_id, name, spec["kind"], "gm", spec["stats"])
        self._outfit(ent, spec)
        if interactable is False:  # written only when false, so older entities read the same
            ent["interactable"] = False
        ent["zone"] = None if relative else zone
        self._emit("entity_spawned", {"entity": ent}, actor=by)
        if relative:  # a band position is relative to others: join the scene there
            self._place(entity_id, zone, by)
        return entity_id

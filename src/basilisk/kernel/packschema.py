"""Static checks on a resolved pack beyond references (§2.3, §2.10): unknown keys,
names inside expressions, and values that contradict each other.

- **Unknown keys.** Every mapping §2.3 defines has a closed set of keys, so a
  misspelt key (`outcome_efects`) is an error rather than a silently missing rule.
  Maps keyed by the pack's own ids (outcome effects, rule cards, vocabulary,
  tactical weights) are checked by their own lints.
- **Names in expressions.** An expression may only read names that exist where
  it is evaluated: bare stats and earlier derived values for an entity's own
  formulas, and `actor.*`, `target.*`, `scene.*` (plus the tactical features)
  for rules evaluated in play. A lint-clean pack therefore never fails at run
  time with "unknown name".
- **Consistency.** Rounding is one the evaluator knows; presentation and GM
  lists name real ids; defaults, starts, and spend amounts sit inside the
  ranges the pack declares, so a new sheet is valid by construction (§1.5).
"""

from __future__ import annotations

from . import expr, tactics

E_ = "entity_model"
SCHEMA: dict[str, set[str]] = {
    "": {"meta", "rules_text", "vocabulary", "randomizers", "entity_model", "resolution", "actions",
         "turn_structure", "time", "clocks", "gm", "progression", "chargen", "spatial", "presentation", "hooks",
         "fixtures"},
    "meta": {"id", "version", "extends", "name", "license", "attribution_text", "excluded_terms", "kernel_compat",
             "abstract", "attributions", "kernel_version", "lineage"},
    "meta.excluded_terms[]": {"term", "aliases"},
    "rules_text": {"mode", "full_text", "digest", "sections", "max_section_tokens"},
    "randomizers": {"dice_grammar", "decks", "tables"},
    "randomizers.dice_grammar": {"operators", "max_dice", "max_sides", "step_sizes"},
    "randomizers.decks[]": {"id", "label", "cards", "reshuffle_rule", "players_draw"},
    "randomizers.tables[]": {"id", "roll", "entries"},
    "randomizers.tables[].entries[]": {"range", "text"},
    E_: {"stats", "derived", "resources", "tracks", "conditions", "tags", "inventory", "items", "harm"},
    f"{E_}.stats[]": {"id", "range", "default", "private"},
    f"{E_}.derived[]": {"id", "expr", "private"},
    f"{E_}.resources[]": {"id", "min", "max", "on_zero", "private"},
    f"{E_}.tracks[]": {"id", "boxes", "on_fill", "private"},
    f"{E_}.conditions[]": {"id", "modifier", "duration", "stacking", "max_level"},
    f"{E_}.inventory": {"model", "limit_expr"},
    f"{E_}.items[]": {"id", "label", "weight"},
    f"{E_}.harm": {"targets"},
    "resolution": {"outcome_scales", "procedures", "difficulty_ladders", "situational_tags", "tags_cap_per_roll",
                   "free_modifier_max"},
    "resolution.outcome_scales[]": {"id", "ordered"},
    "resolution.procedures[]": {"id", "kind", "inputs", "steps"},
    "resolution.procedures[].steps[]": {"modifiers", "roll", "hook", "interpret"},
    "resolution.procedures[].steps[].modifiers": {"from"},
    "resolution.procedures[].steps[].interpret": {"scale", "compare", "against", "bands", "margins", "opposed",
                                                  "ties", "automatic"},
    "resolution.procedures[].steps[].interpret.opposed": {"roll", "stat"},
    "resolution.difficulty_ladders[]": {"id", "rungs", "range"},
    "resolution.difficulty_ladders[].rungs[]": {"id", "label", "value"},
    "resolution.situational_tags[]": {"id", "value", "derive"},
    "actions[]": {"id", "trigger", "target", "modes", "requires", "eligibility", "stat", "cost", "procedure",
                  "difficulty", "slot", "points", "outcome_effects", "annotation_categories"},
    "actions[].cost": {"currency", "amount", "amounts", "range"},
    "actions[].difficulty": {"ladder", "derived"},
    "turn_structure": {"encounter"},
    "turn_structure.encounter": {"order", "initiative", "first", "economy", "slots", "points"},
    "turn_structure.encounter.initiative": {"roll", "each_round"},
    "turn_structure.encounter.slots[]": {"id", "count"},
    "time": {"units", "between_sessions"},
    "time.units[]": {"id", "label", "per"},
    "time.between_sessions": {"unit", "amount"},
    "gm": {"gm_rolls", "fudgeable_procedures", "lethality_levers", "meta_currencies", "consequence_tables"},
    "gm.meta_currencies[]": {"id", "holder", "start", "max", "visible", "private"},
    "gm.consequence_tables[]": {"id", "entries"},
    "gm.consequence_tables[].entries[]": {"id", "label", "effects", "weight", "severity"},
    "progression": {"model", "awards", "thresholds", "use", "advances"},
    "progression.awards[]": {"when", "amount", "outcomes", "procedures"},
    "progression.use": {"threshold"},
    "progression.advances[]": {"id", "label", "stats", "tags", "requires", "once"},
    "chargen": {"steps"},
    "chargen.steps[]": {"id", "kind", "targets", "roll", "options", "values", "table", "unique_per_table"},
    "chargen.steps[].options[]": {"id", "label", "stats", "tags", "items", "currencies"},
    "spatial": {"backends", "bands", "terrain", "cover", "movement", "provokes", "tactical_profile"},
    "spatial.bands[]": {"id", "label"},
    "spatial.terrain[]": {"id", "label"},
    "spatial.cover[]": {"id", "label"},
    "spatial.movement": {"steps_per_move"},
    "spatial.provokes": {"when"},
    "spatial.tactical_profile": {"categories", "weights", "factors", "annotation_templates"},
    "spatial.tactical_profile.categories[]": {"id", "order"},
    "spatial.tactical_profile.factors[]": {"id", "applies_to", "actions", "weight", "when"},
    "spatial.tactical_profile.annotation_templates[]": {"id", "applies_to", "category", "text", "when"},
    "presentation": {"nameplate_resources", "sheet", "assertion_terms", "rounding", "rule_cards"},
    "presentation.sheet": {"public"},
    "hooks[]": {"point", "name", "version", "source"},
}
VOCABULARY_KEYS = {"label", "short", "plural"}
CARD_KEYS = {"title", "summary", "category", "icon_id"}
ENTITY_OPEN = ("conditions", "tags", "region")  # read as 0 when absent: any id after them
FREE_NAMESPACES = ("scene",)  # scene flags are the GM's, set per scene


def unknown_keys(pack) -> list[str]:
    """Keys §2.3 does not define, by path, with the keys that are allowed."""
    out: list[str] = []

    def walk(node, path: str, where: str) -> None:
        if isinstance(node, dict):
            allowed = SCHEMA.get(path)
            if allowed is not None:
                for key in sorted(set(node) - allowed, key=str):
                    out.append(f"{where or 'pack'}: unknown key {key!r}; keys here are {', '.join(sorted(allowed))}")
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key), f"{where}.{key}" if where else str(key))
        elif isinstance(node, list):
            for item in node:
                label = item.get("id", "?") if isinstance(item, dict) else "?"
                walk(item, path + "[]", f"{where}[{label}]")

    walk(pack.data, "", "")
    for vid, entry in (pack.get("vocabulary") or {}).items():
        if not isinstance(entry, dict) or set(entry) - VOCABULARY_KEYS:
            out.append(f"vocabulary.{vid}: entries are {{{', '.join(sorted(VOCABULARY_KEYS))}}}")
    for cid, card in (pack.get("presentation.rule_cards") or {}).items():
        if isinstance(card, dict) and set(card) - CARD_KEYS:
            extra = sorted(set(card) - CARD_KEYS)
            out.append(f"rule card {cid}: unknown key {extra[0]!r}; keys are {', '.join(sorted(CARD_KEYS))}")
    return out


def _entity_names(pack) -> set[str]:
    """What `view(entity)` offers an expression (§2.2): stats, derived values,
    resources, tracks, currencies, and the carried weight."""
    names = set()
    for dotted in (f"{E_}.stats", f"{E_}.derived", f"{E_}.resources", f"{E_}.tracks", "gm.meta_currencies"):
        names |= {i["id"] for i in pack.catalogue(dotted)}
    if (pack.get(f"{E_}.inventory") or {}).get("model") == "weight":
        names.add("carried")
    return names


def _chain_problem(chain: str, own: set[str] | None, entity: set[str], extra: set[str]) -> str | None:
    parts = chain.split(".")
    head = parts[0]
    if head in expr.FUNCS:
        return None
    if own is not None:  # an entity's own formula: bare names, or actor.<name>
        if head == "actor" and len(parts) == 2 and parts[1] in own:
            return None
        if len(parts) == 1 and head in own:
            return None
        return f"unknown name {chain!r}; this formula can read {', '.join(sorted(own)) or 'nothing'}"
    if head in FREE_NAMESPACES or head in extra:
        return None
    if head in ("actor", "target"):
        if len(parts) >= 2 and parts[1] in ENTITY_OPEN:
            return None
        if len(parts) == 2 and parts[1] in entity:
            return None
        return f"unknown name {chain!r}; an entity offers {', '.join(sorted(entity))}, " \
               f"and {', '.join(ENTITY_OPEN)}.<id>"
    return f"unknown name {chain!r}; rules read actor.*, target.*, or scene.*"


def _scoped_expressions(pack):
    """Yield (where, source, own names or None, extra top-level names)."""
    stats = {s["id"] for s in pack.catalogue(f"{E_}.stats")}
    derived = [d["id"] for d in pack.catalogue(f"{E_}.derived")]
    for i, d in enumerate(pack.catalogue(f"{E_}.derived")):
        yield f"derived {d['id']}", d.get("expr"), stats | set(derived[:i]), set()
    own = stats | set(derived)
    for r in pack.catalogue(f"{E_}.resources"):
        if isinstance(r.get("max"), str):
            yield f"resource {r['id']} max", r["max"], own, set()
    inv = pack.get(f"{E_}.inventory") or {}
    if inv.get("limit_expr"):
        yield "inventory limit_expr", inv["limit_expr"], own, set()
    for t in pack.catalogue("resolution.situational_tags"):
        if "derive" in t:
            yield f"tag {t['id']} derive", t["derive"], None, set()
    for a in pack.catalogue("actions"):
        for key in ("requires", "eligibility"):
            if key in a:
                yield f"action {a['id']} {key}", a[key], None, set()
        if isinstance(a.get("difficulty"), dict) and "derived" in a["difficulty"]:
            yield f"action {a['id']} difficulty", a["difficulty"]["derived"], None, set()
    for adv in (pack.get("progression") or {}).get("advances") or []:
        if "requires" in adv:
            yield f"advance {adv.get('id')} requires", adv["requires"], None, set()
    provokes = pack.get("spatial.provokes")
    if isinstance(provokes, dict) and "when" in provokes:
        yield "spatial.provokes when", provokes["when"], None, set()
    features = set(tactics.FEATURES) | {"region", "here"}
    prof = pack.get("spatial.tactical_profile") or {}
    for kind in ("factors", "annotation_templates"):
        for item in prof.get(kind) or []:
            if "when" in item:
                yield f"tactical {kind[:-1]} {item.get('id')} when", item["when"], None, features


def name_problems(pack) -> list[str]:
    """Names an expression reads that would not exist when it is evaluated."""
    entity = _entity_names(pack)
    out = []
    for where, src, own, extra in _scoped_expressions(pack):
        if src is None or isinstance(src, (int, bool)):
            continue
        try:
            chains = expr.names_used(str(src))
        except expr.ExprError:
            continue  # the syntax lint reports it
        for chain in sorted(chains):
            problem = _chain_problem(chain, own, entity, extra)
            if problem:
                out.append(f"{where}: {problem}")
    return out


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _stat_samples(pack):
    """(label, stats with derived values) at the stats' defaults, their lowest,
    and their highest values, for checking formulas statically."""
    stats = pack.catalogue(f"{E_}.stats")
    picks = [("their defaults", lambda s: s.get("default", 0))]
    if all(s.get("range") for s in stats):
        picks += [("their lowest", lambda s: s["range"][0]), ("their highest", lambda s: s["range"][1])]
    rounding = pack.get("presentation.rounding", "floor")
    for label, pick in picks:
        own = {s["id"]: int(pick(s)) for s in stats}
        try:
            for d in pack.catalogue(f"{E_}.derived"):
                own[d["id"]] = expr.evaluate(d["expr"], {**own, "actor": own}, rounding)
        except expr.ExprError:
            return
        yield label, own


def consistency_problems(pack) -> list[str]:
    """References and ranges the other lints do not cover (§2.3, §2.10)."""
    out = []
    rounding = pack.get("presentation.rounding", "floor")
    if rounding not in expr.ROUNDING:
        out.append(f"presentation.rounding {rounding!r} is not one of {', '.join(sorted(expr.ROUNDING))}")
    counters = {i["id"] for d in (f"{E_}.resources", f"{E_}.tracks", "gm.meta_currencies") for i in pack.catalogue(d)}
    for phrase, target in (pack.get("presentation.assertion_terms") or {}).items():
        if target not in counters:
            out.append(f"assertion term {phrase!r} names {target!r}, which is not a resource, track, or currency")
    known = set()
    for dotted in (f"{E_}.stats", f"{E_}.derived", f"{E_}.resources", f"{E_}.tracks", f"{E_}.conditions",
                   f"{E_}.items", "gm.meta_currencies", "actions", "resolution.procedures",
                   "resolution.situational_tags", "resolution.outcome_scales", "time.units",
                   "randomizers.decks", "gm.consequence_tables"):
        known |= {i["id"] for i in pack.catalogue(dotted)}
    if isinstance(pack.get("spatial"), dict):  # `spatial: none` has no bands
        known |= {b["id"] for b in pack.get("spatial.bands") or [] if isinstance(b, dict)}
    known |= set(pack.get(f"{E_}.tags") or [])
    known |= {o for s in pack.catalogue("resolution.outcome_scales") for o in s.get("ordered") or []}
    for vid in sorted(pack.get("vocabulary") or {}):
        if vid not in known:
            out.append(f"vocabulary {vid!r} names nothing the pack declares")
    procs = {p["id"] for p in pack.catalogue("resolution.procedures")}
    for pid in pack.get("gm.fudgeable_procedures") or []:
        if pid not in procs:
            out.append(f"gm.fudgeable_procedures: unknown procedure {pid!r}; procedures: {', '.join(sorted(procs))}")
    for s in pack.catalogue(f"{E_}.stats"):
        lo, hi = s.get("range") or (None, None)
        default = s.get("default", 0)
        if lo is not None and _int(default) and not lo <= default <= hi:
            out.append(f"stat {s['id']}: default {default} is outside its range {lo}..{hi}")
    rounding_ok = rounding in expr.ROUNDING
    for r in pack.catalogue(f"{E_}.resources"):
        if _int(r.get("min")) and _int(r.get("max")) and r["min"] > r["max"]:
            out.append(f"resource {r['id']}: min {r['min']} is above max {r['max']}")
        elif _int(r.get("min")) and isinstance(r.get("max"), str) and rounding_ok:
            for label, own in _stat_samples(pack):  # a formula maximum, at the stats' extremes
                try:
                    cap = expr.evaluate(r["max"], {**own, "actor": own}, rounding)
                except expr.ExprError:
                    break  # the name and syntax lints report it
                if r["min"] > cap:
                    out.append(f"resource {r['id']}: max {r['max']!r} is {cap} with stats at {label}, "
                               f"below its min {r['min']}")
                    break
    for c in pack.catalogue("gm.meta_currencies"):
        start, cap = c.get("start", 0), c.get("max")
        if not _int(start) or start < 0 or (_int(cap) and start > cap):
            out.append(f"currency {c['id']}: start {start!r} must be an integer from 0 to its max {cap}")
    for a in pack.catalogue("actions"):
        modes = a.get("modes", ["free", "encounter"])
        if not isinstance(modes, list) or set(modes) - {"free", "encounter"} or not modes:
            out.append(f"action {a['id']}: modes are a list of free and encounter, not {modes!r}")
        if a.get("target", "none") not in ("none", "entity", "zone"):
            out.append(f"action {a['id']}: target must be none, entity or zone, not {a.get('target')!r}")
        cost = a.get("cost") or {}
        if "amount" in cost and (not _int(cost["amount"]) or cost["amount"] < 1):
            out.append(f"action {a['id']}: cost amount must be a positive integer")
        if "amounts" in cost:
            lo, hi = cost.get("range") or (min(cost["amounts"]), max(cost["amounts"]))
            bad = [v for v in cost["amounts"] if not _int(v) or not lo <= v <= hi or v < 1]
            if bad:
                out.append(f"action {a['id']}: spend amounts {bad} are outside its range {lo}..{hi}")
    return out

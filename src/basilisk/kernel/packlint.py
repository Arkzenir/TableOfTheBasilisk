"""Pack conformance: static lint and strict-readiness (§2.10, §2.13).

`lint()` returns findings; any finding with level "error" fails the load.
`readiness()` reports which determinism controls the pack can support on strict.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import decks, dice, expr, progression, rules, sheets, spatial, tactics, terms, timekeeping, turns
from .command import _suggest
from .determinism import CONTROLS, ROLES, STRICT, expand
from .effects import PRIMITIVES, RESERVED, TARGET_SYMBOLS, references
from .packs import ResolvedPack
from .tools import generate

CARD_TITLE_MAX = 32
CARD_SUMMARY_MAX = 120
RULES_TEXT_TOKEN_BUDGET = 30_000  # rough: chars / 4
REQUIRED_SECTIONS = ("randomizers", "entity_model", "resolution", "presentation")
HOLDERS = ("each_player", "party", "gm")  # gm.meta_currencies holder (§2.3)


@dataclass
class Finding:
    level: str  # "error" | "warning"
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.code}: {self.message}"


def _effects_in(pack: ResolvedPack):
    """Yield (where, effect) for every effect anywhere in the pack, including
    the effects nested inside `trigger_procedure` outcomes."""
    for where, e in _top_effects(pack):
        yield from _with_nested(where, e)


def _with_nested(where: str, e: dict):
    yield where, e
    if isinstance(e, dict) and e.get("primitive") == "trigger_procedure":
        for outcome, inner in (e.get("outcome_effects") or {}).items():
            for sub in inner or []:
                yield from _with_nested(f"{where} -> {e.get('procedure')} [{outcome}]", sub)


def _top_effects(pack: ResolvedPack):
    for action in pack.catalogue("actions"):
        for outcome, effects in (action.get("outcome_effects") or {}).items():
            for e in effects or []:
                yield f"action {action['id']} [{outcome}]", e
    for track in pack.catalogue("entity_model.tracks"):
        for e in track.get("on_fill") or []:
            yield f"track {track['id']} on_fill", e
    for res in pack.catalogue("entity_model.resources"):
        for e in res.get("on_zero") or []:
            yield f"resource {res['id']} on_zero", e
    for table in pack.catalogue("gm.consequence_tables"):
        for entry in table.get("entries") or []:
            for e in entry.get("effects") or []:
                yield f"consequence {table['id']}.{entry['id']}", e


def _expressions_in(pack: ResolvedPack):
    for d in pack.catalogue("entity_model.derived"):
        yield f"derived {d['id']}", d.get("expr")
    for r in pack.catalogue("entity_model.resources"):
        yield f"resource {r['id']} max", r.get("max")
    for t in pack.catalogue("resolution.situational_tags"):
        if "derive" in t:
            yield f"tag {t['id']} derive", t["derive"]
    for a in pack.catalogue("actions"):
        for key in ("requires", "eligibility"):
            if key in a:
                yield f"action {a['id']} {key}", a[key]
        if isinstance(a.get("difficulty"), dict) and "derived" in a["difficulty"]:
            yield f"action {a['id']} difficulty", a["difficulty"]["derived"]


def _rolls_in(pack: ResolvedPack):
    for p in pack.catalogue("resolution.procedures"):
        for step in p.get("steps") or []:
            if "roll" in step:
                yield f"procedure {p['id']}", step["roll"]
            opposed = (step.get("interpret") or {}).get("opposed") or {}
            if opposed.get("roll"):
                yield f"procedure {p['id']} opposed", opposed["roll"]
    for t in pack.catalogue("randomizers.tables"):
        yield f"table {t['id']}", t.get("roll", "")
    for s in pack.get("chargen.steps") or []:
        if s.get("kind") == "roll":
            yield f"chargen {s['id']}", s.get("roll", "")
    for where, e in _effects_in(pack):
        for key in ("amount", "value"):
            if isinstance(e.get(key), str):
                yield f"{where} {key}", e[key]


def readiness(pack: ResolvedPack) -> dict[str, bool]:
    procs = pack.by_id("resolution.procedures")
    ready = {c: True for c in CONTROLS}
    for a in pack.catalogue("actions"):
        proc = procs.get(a.get("procedure"))
        if proc and "difficulty" in (proc.get("inputs") or []) and not a.get("difficulty"):
            ready["difficulty"] = False
        if a.get("trigger") == "fiction" and "eligibility" not in a:
            ready["fiction_triggers"] = False
        cost = a.get("cost") or {}
        if "range" in cost and "amounts" not in cost:
            ready["spend_amounts"] = False
    tables = pack.by_id("gm.consequence_tables")
    for _, e in _effects_in(pack):
        if e.get("primitive") == "request_gm_ruling":
            t = tables.get(e.get("table"))
            if not t or not t.get("entries") or any("effects" not in en for en in t["entries"]):
                ready["ruling_slots"] = False
    if not any(p.get("kind", "roll") == "roll" for p in procs.values()):
        ready["unmodelled_actions"] = False
    return ready


def lint(pack: ResolvedPack) -> list[Finding]:
    out: list[Finding] = []

    def err(code, msg):
        out.append(Finding("error", code, msg))

    def warn(code, msg):
        out.append(Finding("warning", code, msg))

    abstract = pack.data["meta"].get("abstract", False)
    for section in REQUIRED_SECTIONS:
        if section not in pack.data:
            err("schema", f"missing section {section!r}")
    if any(f.level == "error" for f in out):
        return out

    # duplicate ids --------------------------------------------------------
    for cat in ("entity_model.stats", "entity_model.derived", "entity_model.resources",
                "entity_model.tracks", "entity_model.conditions", "resolution.outcome_scales",
                "resolution.procedures", "resolution.difficulty_ladders", "resolution.situational_tags",
                "actions", "gm.meta_currencies", "gm.consequence_tables", "randomizers.tables"):
        ids = [i["id"] for i in pack.catalogue(cat)]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            err("duplicate-id", f"{cat}: {sorted(dupes)}")

    stats = pack.by_id("entity_model.stats")
    resources = pack.by_id("entity_model.resources")
    tracks = pack.by_id("entity_model.tracks")
    conditions = pack.by_id("entity_model.conditions")
    currencies = pack.by_id("gm.meta_currencies")
    scales = pack.by_id("resolution.outcome_scales")
    procs = pack.by_id("resolution.procedures")
    ladders = pack.by_id("resolution.difficulty_ladders")
    tags = pack.by_id("resolution.situational_tags")
    ctables = pack.by_id("gm.consequence_tables")
    rtables = pack.by_id("randomizers.tables")
    for c in currencies.values():  # who holds it (§2.3)
        if c.get("holder", "each_player") not in HOLDERS:
            err("reference", f"currency {c['id']}: " + _suggest("holder", c.get("holder"), HOLDERS))
        if not isinstance(c.get("visible", True), bool):
            err("currency", f"currency {c['id']}: visible must be true or false")
    if pack.get("gm.lethality_levers"):
        warn("reserved", "gm.lethality_levers is reserved for the lethality trait (BUILD_PLAN P2.5); "
                         "nothing reads it yet")
    known = {"resource": resources, "track": tracks, "condition": conditions,
             "currency": currencies, "consequence_table": ctables}

    # outcome scales are totally ordered lists of unique outcomes ----------
    for s in scales.values():
        ordered = s.get("ordered") or []
        if len(ordered) < 2 or len(set(ordered)) != len(ordered):
            err("outcome-scale", f"{s['id']}: needs at least two unique, ordered outcomes")

    # procedures -----------------------------------------------------------
    for p in procs.values():
        interp = next((st["interpret"] for st in p.get("steps") or [] if "interpret" in st), None)
        if not interp:
            err("procedure", f"{p['id']}: no interpret step")
            continue
        scale = scales.get(interp.get("scale"))
        if not scale:
            err("reference", f"procedure {p['id']}: unknown outcome scale {interp.get('scale')!r}")
            continue
        n = len(scale["ordered"])
        if "bands" in interp:
            bands = interp["bands"]
            if len(bands) != n:
                err("procedure", f"{p['id']}: {len(bands)} bands for a {n}-outcome scale")
            for (a_lo, a_hi), (b_lo, _) in zip(bands, bands[1:]):
                if b_lo != a_hi + 1:
                    err("procedure", f"{p['id']}: bands are not contiguous at {a_hi}/{b_lo}")
        elif "margins" in interp:  # degrees of success by margin over the difficulty (§2.5)
            margins = interp["margins"]
            if len(margins) != n:
                err("procedure", f"{p['id']}: {len(margins)} margin bands for a {n}-outcome scale")
            for (a_lo, a_hi), (b_lo, _) in zip(margins, margins[1:]):
                if b_lo != a_hi + 1:
                    err("procedure", f"{p['id']}: margin bands are not contiguous at {a_hi}/{b_lo}")
            if interp.get("compare", ">=") not in (">=", "<=", "successes"):
                err("procedure", f"{p['id']}: compare must be >=, <=, or successes")
        elif interp.get("against") == "opposed":
            if n != 2:
                err("procedure", f"{p['id']}: an opposed check needs a two-outcome scale")
            if interp.get("ties", "target") not in ("actor", "target"):
                err("procedure", f"{p['id']}: ties must go to actor or target")
            if "target" not in (p.get("inputs") or []):
                err("procedure", f"{p['id']}: an opposed check needs target among its inputs")
        elif "compare" in interp:
            if n != 2:
                err("procedure", f"{p['id']}: compare needs a two-outcome scale")
            if interp["compare"] not in (">=", "<=", "successes"):
                err("procedure", f"{p['id']}: compare must be >=, <=, or successes")
        elif not interp.get("automatic"):
            err("procedure", f"{p['id']}: interpret needs bands, margins, compare, an opposed roll, or automatic")

    # actions --------------------------------------------------------------
    for a in pack.catalogue("actions"):
        proc = procs.get(a.get("procedure"))
        if not proc:
            err("reference", f"action {a['id']}: unknown procedure {a.get('procedure')!r}")
            continue
        if "stat" in (proc.get("inputs") or []) and a.get("stat") not in stats:
            err("reference", f"action {a['id']}: unknown stat {a.get('stat')!r}")
        diff = a.get("difficulty")
        if isinstance(diff, dict) and "ladder" in diff and diff["ladder"] not in ladders:
            err("reference", f"action {a['id']}: unknown ladder {diff['ladder']!r}")
        interp = next((st["interpret"] for st in proc.get("steps") or [] if "interpret" in st), {})
        outcomes = set((scales.get(interp.get("scale")) or {}).get("ordered") or [])
        extra = set(a.get("outcome_effects") or {}) - outcomes
        if extra:
            err("reference", f"action {a['id']}: outcomes {sorted(extra)} are not on scale {interp.get('scale')}")
        cost = a.get("cost") or {}
        if cost and cost.get("currency") not in currencies:
            err("reference", f"action {a['id']}: unknown currency {cost.get('currency')!r}")
        if a.get("trigger", "declared") not in ("declared", "fiction", "reaction"):
            err("action", f"action {a['id']}: trigger must be declared, fiction or reaction")

    # effects --------------------------------------------------------------
    for where, e in _effects_in(pack):
        prim = e.get("primitive")
        if prim not in PRIMITIVES:
            err("effect", f"{where}: unknown primitive {prim!r}")
            continue
        if prim in RESERVED:
            err("effect", f"{where}: primitive {prim!r} is reserved and not implemented in this kernel")
        if prim == "trigger_procedure":
            proc = procs.get(e.get("procedure"))
            if not proc:
                err("reference", f"{where}: unknown procedure {e.get('procedure')!r}; procedures: {', '.join(procs)}")
            else:
                if "stat" in (proc.get("inputs") or []) and e.get("stat") not in stats:
                    err("reference", f"{where}: {e.get('procedure')} needs a stat; unknown {e.get('stat')!r}")
                spec = e.get("difficulty")
                if "difficulty" in (proc.get("inputs") or []) and not spec:
                    err("effect", f"{where}: {e.get('procedure')} needs a difficulty fixed by the pack "
                                  "({derived: expr} or {ladder, rung})")
                if isinstance(spec, dict) and "ladder" in spec:
                    ladder = ladders.get(spec["ladder"])
                    if not ladder or spec.get("rung") not in {r["id"] for r in ladder.get("rungs") or []}:
                        err("reference", f"{where}: unknown ladder rung {spec.get('ladder')}/{spec.get('rung')}")
                scale = scales.get(({k: v for s in proc.get("steps") or [] for k, v in s.items()}.get("interpret")
                                    or {}).get("scale"), {}).get("ordered", [])
                for outcome in (e.get("outcome_effects") or {}):
                    if outcome not in scale:
                        err("reference", f"{where}: outcome {outcome!r} is not on {e.get('procedure')}'s scale")
                rolls = not ({k: v for s in proc.get("steps") or [] for k, v in s.items()}.get("interpret")
                             or {}).get("automatic")
                if rolls and not pack.get("gm.gm_rolls", True) and where.startswith(("track ", "resource ")):
                    err("effect", f"{where}: any entity can reach this, and a GM-side one would have to roll "
                                  f"{e.get('procedure')}, but the GM never rolls (gm.gm_rolls: false)")
        missing = [p for p in PRIMITIVES[prim] if p not in e]
        if missing:
            err("effect", f"{where}: {prim} is missing {missing}")
        tgt = e.get("target")
        if tgt == "gm":  # the GM's pool (§2.3): only for a currency the GM's side holds
            held = (currencies.get(e.get("currency")) or {}).get("holder", "each_player")
            if prim not in ("earn_currency", "spend_currency") or held != "gm":
                err("effect", f"{where}: target gm is only for earn_currency or spend_currency on a GM-held "
                              f"currency (holder: gm)")
        elif tgt is not None and tgt not in TARGET_SYMBOLS:
            warn("effect", f"{where}: target {tgt!r} is a literal entity id")
        for kind, ref in references(e).items():
            if kind in known and ref not in known[kind]:
                err("reference", f"{where}: unknown {kind} {ref!r}")

    # conditions have exits ------------------------------------------------
    removable = {e.get("condition") for _, e in _effects_in(pack) if e.get("primitive") == "remove_condition"}
    for c in conditions.values():
        if c.get("duration", "until_removed") == "until_removed" and c["id"] not in removable:
            err("condition-exit", f"condition {c['id']} lasts until removed but nothing removes it")
        if c.get("duration", "until_removed") not in ("scene", "session", "until_removed"):
            err("condition", f"condition {c['id']}: duration must be scene, session or until_removed")
        stacking = c.get("stacking", "none")
        if stacking not in ("none", "intensity"):
            err("condition", f"condition {c['id']}: stacking must be none or intensity")
        if stacking == "intensity":
            top = c.get("max_level", 3)
            if isinstance(top, bool) or not isinstance(top, int) or not 2 <= top <= 10:
                err("condition", f"condition {c['id']}: max_level must be an integer from 2 to 10")

    # roll expressions -----------------------------------------------------
    grammar = pack.get("randomizers.dice_grammar", {}) or {}
    enabled = set(grammar.get("operators") or ["sum"])
    sizes = grammar.get("step_sizes")
    if sizes is not None:
        if not isinstance(sizes, list) or not sizes or any(isinstance(z, bool) or not isinstance(z, int) or z < 2
                                                           for z in sizes):
            err("roll", "dice_grammar.step_sizes must be a list of die sizes of 2 or more")
        elif max(sizes) > int(grammar.get("max_sides", 100)):
            err("roll", f"step size d{max(sizes)} exceeds max_sides {grammar.get('max_sides', 100)}")
    if "step" in enabled and not sizes:
        err("roll", "the step operator needs dice_grammar.step_sizes, the legal die sizes")
    for where, src in _rolls_in(pack):
        for problem in dice.check_expression(src, enabled, int(grammar.get("max_dice", 20)),
                                             int(grammar.get("max_sides", 100)), grammar.get("step_sizes")):
            err("roll", f"{where}: {problem}")

    # other expressions ----------------------------------------------------
    for where, src in _expressions_in(pack):
        if src is None:
            continue
        try:
            expr.compile_expr(str(src))
        except expr.ExprError as e:
            err("expression", f"{where}: {e}")

    # chargen --------------------------------------------------------------
    for step in pack.get("chargen.steps") or []:
        kind = step.get("kind")
        if kind == "roll":
            for target in step.get("targets") or []:
                if target not in stats:
                    err("chargen", f"step {step['id']}: unknown stat {target!r}")
        elif kind == "choice":
            for opt in step.get("options") or []:
                for sid in (opt.get("stats") or {}):
                    if sid not in stats:
                        err("chargen", f"step {step['id']}.{opt.get('id')}: unknown stat {sid!r}")
        elif kind == "table":
            if step.get("table") not in rtables:
                err("chargen", f"step {step['id']}: unknown table {step.get('table')!r}")
        elif kind == "assign":
            targets, values = step.get("targets") or [], step.get("values") or []
            for target in targets:
                if target not in stats:
                    err("chargen", f"step {step['id']}: unknown stat {target!r}")
            if len(values) != len(targets) or not targets:
                err("chargen", f"step {step['id']}: needs one value per target ({len(values)} values, "
                               f"{len(targets)} targets)")
            for value in values:
                for target in targets:
                    lo, hi = stats.get(target, {}).get("range", [value, value])
                    if not lo <= value <= hi:
                        err("chargen", f"step {step['id']}: value {value} is outside {target}'s range {lo}..{hi}")
        else:
            err("chargen", f"step {step.get('id')}: kind must be roll, choice, assign or table")
    for t in rtables.values():
        try:
            rng = dice.value_range(t.get("roll", ""))
        except dice.DiceError:
            continue  # already reported
        covered = sorted(tuple(e["range"]) for e in t.get("entries") or [])
        if rng and covered:
            expect = rng[0]
            for lo, hi in covered:
                if lo != expect:
                    err("table-coverage", f"table {t['id']}: no entry for {expect}..{lo - 1}")
                expect = hi + 1
            if expect != rng[1] + 1:
                err("table-coverage", f"table {t['id']}: no entry for {expect}..{rng[1]}")

    # rule cards (§8.6) ----------------------------------------------------
    cards = pack.get("presentation.rule_cards") or {}
    if not abstract:
        needed = [a["id"] for a in pack.catalogue("actions")]
        needed += list(procs) + list(conditions) + list(currencies) + list(tags)
        for cid in needed:
            if cid not in cards:
                err("rule-card", f"no rule card for {cid!r}")
    for cid, card in cards.items():
        if len(str(card.get("title", ""))) > CARD_TITLE_MAX:
            err("rule-card", f"{cid}: title longer than {CARD_TITLE_MAX}")
        if len(str(card.get("summary", ""))) > CARD_SUMMARY_MAX:
            err("rule-card", f"{cid}: summary longer than {CARD_SUMMARY_MAX}")

    # rules text: inline budget, or digest, sections, and coverage (§2.11) --
    rule_errors, rule_warnings = rules.lint_rules(pack, abstract, RULES_TEXT_TOKEN_BUDGET)
    for problem in rule_errors:
        err("rules-text", problem)
    for problem in rule_warnings:
        warn("rules-text", problem)

    # spatial (§1.4) -------------------------------------------------------
    sp = pack.get("spatial")
    if sp not in (None, "none") and not isinstance(sp, dict):
        err("spatial", "spatial must be a mapping with backends, or none")
    for backend in spatial.declared_backends(pack):
        if backend not in spatial.BACKENDS:
            planned = " (planned for v2, §11.4)" if backend == "square_grid" else ""
            err("spatial", f"unknown backend {backend!r}{planned}; available: {', '.join(spatial.BACKENDS)}")
    if isinstance(sp, dict):
        movement = sp.get("movement") or {}
        steps = movement.get("steps_per_move", 1)
        if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 6:
            err("spatial", "movement.steps_per_move must be an integer from 1 to 6")
        provokes = sp.get("provokes")
        if provokes is not None:
            if not isinstance(provokes, dict):
                err("spatial", "provokes must be a mapping with an optional when expression")
            else:
                try:
                    expr.compile_expr(str(provokes.get("when", "1")))
                except expr.ExprError as e:
                    err("spatial", f"provokes.when: {e}")
    bands = spatial.values(pack, "bands")
    if "range_bands" in spatial.declared_backends(pack) and len(bands) < 2:
        err("spatial", "range_bands needs spatial.bands: at least two bands, closest first")
    for b in bands:
        if not isinstance(b, dict) or not spatial.ID_RE.match(str(b.get("id", ""))) or not b.get("label"):
            err("spatial", f"band {b!r}: needs a lowercase id and a label")
    for key in ("terrain", "cover", "bands"):
        ids = [v.get("id") for v in spatial.values(pack, key)]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            err("duplicate-id", f"spatial.{key}: {sorted(dupes)}")

    for problem in tactics.lint_profile(pack):
        err("tactical-profile", problem)
    for problem in turns.lint_turns(pack):
        err("turn-structure", problem)
    for problem in decks.lint_decks(pack):
        err("deck", problem)
    for problem in sheets.lint_sheet(pack):
        err("sheet", problem)
    for problem in sheets.lint_harm(pack):
        err("harm", problem)
    for problem in progression.lint_progression(pack):
        err("progression", problem)

    # inventory (§2.3) ---------------------------------------------------------
    inv = pack.get("entity_model.inventory") or {}
    model = inv.get("model", "abstract")
    if model not in ("abstract", "weight"):
        err("inventory", f"inventory model {model!r}: abstract or weight" + (" (slots is not built yet)" if model == "slots" else ""))
    items = pack.catalogue("entity_model.items")
    item_ids = [i.get("id") for i in items]
    if len(item_ids) != len(set(item_ids)):
        err("inventory", "duplicate item ids")
    for item in items:
        w = item.get("weight", 0)
        if isinstance(w, bool) or not isinstance(w, int) or w < 0:
            err("inventory", f"item {item.get('id')}: weight must be a non-negative integer")
    if model == "weight":
        if not items:
            err("inventory", "the weight model needs entity_model.items with weights")
        if inv.get("limit_expr"):
            try:
                expr.compile_expr(str(inv["limit_expr"]))
            except expr.ExprError as e:
                err("inventory", f"limit_expr: {e}")
    for problem in terms.lint_terms(pack):
        err("excluded-term", problem)
    for problem in timekeeping.lint_time(pack):
        err("time", problem)

    # tool schemas generate under every preset ----------------------------
    for preset in ("strict", "standard"):
        eff = expand({"players": {"preset": preset}, "gm": {"preset": preset}})
        for role in ROLES:
            try:
                generate(pack, eff, role)
            except Exception as e:  # noqa: BLE001 - any failure is a lint error
                err("tool-schema", f"{role}/{preset}: {e}")

    # licensing ------------------------------------------------------------
    lic = str(pack.data["meta"].get("license") or "")
    if not abstract and (not lic or lic.startswith("UNSET")):
        warn("license", "license not set; the pack cannot be cleared for broadcast (§1.2)")

    return out


def strict_report(pack: ResolvedPack) -> dict[str, bool]:
    return {c: ready for c, ready in readiness(pack).items()}


def errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.level == "error"]


__all__ = ["Finding", "lint", "readiness", "strict_report", "errors", "STRICT"]

"""Tool schema generation (§2.12, §2.13.4, §7.1).

Tool names are fixed by the kernel; arguments and enumerations come from the
resolved pack and the role's determinism settings. A capability the pack or
settings do not provide is absent from the schema, not denied at call time.

Under strict settings every argument with mechanical effect is an enum.
`free_values()` audits a schema for anything a model could fill freely.
"""

from __future__ import annotations

from typing import Any

from . import canon, spatial, turns
from .determinism import STANDARD, setting_for
from .packs import ResolvedPack

NARRATIVE = {"type": "string", "x-narrative": True}
ID = {"type": "string", "format": "id"}


def _enum(values: list) -> dict:
    return {"enum": sorted(set(values), key=str)}


def _spend_schema(pack: ResolvedPack, mode: str) -> dict | None:
    amounts, lo, hi = [], None, None
    for action in pack.catalogue("actions"):
        cost = action.get("cost") or {}
        if "amounts" in cost:
            amounts += cost["amounts"]
            r = cost.get("range") or [min(cost["amounts"]), max(cost["amounts"])]
            lo = r[0] if lo is None else min(lo, r[0])
            hi = r[1] if hi is None else max(hi, r[1])
    if not amounts:
        return None
    if mode == STANDARD:
        return {"type": "integer", "minimum": lo, "maximum": hi}
    return _enum(amounts)


def _difficulty_schema(pack: ResolvedPack, mode: str) -> dict | None:
    ladders = pack.catalogue("resolution.difficulty_ladders")
    if not ladders:
        return None
    rungs = [r["id"] for lad in ladders for r in lad.get("rungs", [])]
    if mode == STANDARD:
        lo = min((lad.get("range") or [0, 0])[0] for lad in ladders)
        hi = max((lad.get("range") or [0, 0])[1] for lad in ladders)
        return {"oneOf": [_enum(rungs), {"type": "integer", "minimum": lo, "maximum": hi}]}
    return _enum(rungs)


def _region_schema(pack: ResolvedPack) -> dict:
    region: dict[str, Any] = {"id": ID, "label": NARRATIVE, "adjacency": {"type": "array", "items": ID}}
    for key in ("terrain", "cover"):
        values = [v["id"] for v in spatial.values(pack, key)]
        if values:
            region[key] = _enum(values)
    # elevation is accepted by the engine but not offered to models: it is a free
    # number, and strict schemas may not carry one (§2.13.4)
    return {"type": "array", "items": region, "maxItems": spatial.MAX_REGIONS}


def generate(pack: ResolvedPack, effective: dict, role: str, seat: str | None = None) -> dict[str, dict]:
    def mode(control: str) -> str:
        return setting_for(effective, role, control, seat)

    action_ids = [a["id"] for a in pack.catalogue("actions")]
    tools: dict[str, dict] = {
        "post_to_table": {"text": NARRATIVE, "kind": _enum(["in_character", "rules_query", "banter", "react", "table_talk"])},
        "pass": {},
        "read_sheet": {},
        "query_canon": {"query": NARRATIVE},  # an id or a name; scoped by the dispatcher (§6.2)
    }
    commit: dict[str, Any] = {"action_id": _enum(action_ids), "target": ID}
    spend = _spend_schema(pack, mode("spend_amounts"))
    if spend:
        commit["spend"] = spend
    if role == "gm":
        commit["actor"] = ID  # the GM acts for NPCs
    if action_ids:
        tools["commit_action"] = commit
    tools["enumerate_actions"] = {}
    order = turns.structure(pack).get("order")
    if order != "spotlight":
        tools["end_turn"] = {"next": ID} if order == "handoff" else {}  # handoff: who goes next
    backends = spatial.declared_backends(pack)
    zones, bands = "zone_graph" in backends, "range_bands" in backends
    if zones or bands:
        tools["look"] = {}  # the caller's own view of the scene: regions and visible tokens (§7.1, §8.2)
        # Tactical tools (§1.4.2, §7.1). Results are tiered by the seat's rules_mastery,
        # which the dispatcher supplies from campaign traits; it is never a model argument.
        tools["enumerate_moves"] = {}
        tools["enumerate_actions"] = {"position_id": ID}
        if action_ids:
            tools["preview"] = {"action_id": _enum(action_ids), "target": ID}

    if role == "gm":
        tag_ids = [t["id"] for t in pack.catalogue("resolution.situational_tags") if "derive" not in t]
        cap = int(pack.get("resolution.tags_cap_per_roll", 2))
        rule: dict[str, Any] = {"tags": {"type": "array", "items": _enum(tag_ids), "maxItems": cap}}
        diff = _difficulty_schema(pack, mode("difficulty"))
        if diff:
            rule["difficulty"] = diff
        if mode("situational_modifiers") == STANDARD:
            bound = int(pack.get("resolution.free_modifier_max", 2))
            rule["free_modifier"] = {"type": "integer", "minimum": -bound, "maximum": bound}
        tools["rule_on_action"] = rule

        entries = [e["id"] for t in pack.catalogue("gm.consequence_tables") for e in t.get("entries", [])]
        if entries and mode("ruling_slots") == STANDARD:
            tools["fill_ruling"] = {"slot_id": ID, "entry_id": _enum(entries)}

        procs = [p["id"] for p in pack.catalogue("resolution.procedures") if p.get("kind", "roll") == "roll"]
        stats = [s["id"] for s in pack.catalogue("entity_model.stats")]
        if procs:
            unmodelled: dict[str, Any] = {"actor": ID, "procedure": _enum(procs)}
            if stats:
                unmodelled["stat"] = _enum(stats)
            if diff:
                unmodelled["difficulty"] = diff
            unmodelled["tags"] = rule["tags"]
            if mode("unmodelled_actions") == STANDARD:
                outcomes = [o for s in pack.catalogue("resolution.outcome_scales") for o in s["ordered"]]
                unmodelled["outcome"] = _enum(outcomes)
            tools["resolve_unmodelled"] = unmodelled

        tools["start_encounter"] = {"participants": {"type": "array", "items": ID}}
        if order == "handoff":
            tools["start_encounter"]["first"] = ID
        tools["end_encounter"] = {}
        if order == "spotlight":
            tools["next_round"] = {}
        tools["advance_clock"] = {"clock_id": ID, "amount": _enum([1, 2, 3])}
        tools["spawn_entity"] = {"entity_id": ID, "name": NARRATIVE}
        tools["set_scene"] = {"scene_id": ID}
        if zones:
            tools["set_scene"]["regions"] = _region_schema(pack)
            tools["set_scene"]["placements"] = {"type": "array", "items": {"entity_id": ID, "region_id": ID}}
        if bands:
            band_ids = [b["id"] for b in spatial.values(pack, "bands")]
            tools["set_scene"]["participants"] = {"type": "array", "items": ID, "maxItems": spatial.MAX_PARTICIPANTS}
            tools["set_scene"]["ranges"] = {"type": "array", "items": {
                "between": {"type": "array", "items": ID, "maxItems": 2}, "band": _enum(band_ids)}}
        if zones or bands:
            # a position is a region id, or band:entity in a band scene (§1.4)
            tools["place_entity"] = {"entity_id": ID, "position_id": ID}
            tools["set_visibility"] = {"entity_id": ID, "visible_to": {"type": "array", "items": ID}}
        ids = {"type": "array", "items": ID}
        tools["write_canon"] = {
            "type": _enum(list(canon.RECORD_TYPES)), "name": NARRATIVE,
            "aliases": {"type": "array", "items": NARRATIVE}, "body": NARRATIVE,
            "knowledge": _enum(list(canon.KNOWLEDGE)), "origin": _enum(list(canon.ORIGINS)),
            "depends_on": ids, "discovery_paths": ids,
        }
        tools["reveal"] = {"fact_id": ID}
        if pack.get("gm.gm_rolls", True) and pack.get("gm.fudgeable_procedures") and mode("fudging") == STANDARD:
            tools["peek_roll"] = {}
    return tools


def free_values(schema: Any, path: str = "") -> list[str]:
    """Paths in a schema where a model could supply an unenumerated number or free text
    with mechanical effect. Narrative text and engine-validated ids are allowed."""
    found: list[str] = []
    if isinstance(schema, dict):
        if schema.get("x-narrative") or schema.get("format") == "id":
            return found
        if "enum" in schema:
            return found
        if schema.get("type") in ("integer", "number", "string"):
            found.append(path or "$")
            return found
        for key, value in schema.items():
            if key == "items":
                found += free_values(value, f"{path}[]")
            elif key == "oneOf":
                for i, option in enumerate(value):
                    found += free_values(option, f"{path}|{i}")
            elif isinstance(value, dict):
                found += free_values(value, f"{path}.{key}" if path else key)
    return found

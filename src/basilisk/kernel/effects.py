"""The closed set of effect primitives (§2.6).

Packs compose these in data. The engine turns each into concrete state
changes, emitted as `effect_applied` events whose payload carries the exact
changes, so the reducer that folds events into state stays trivial and
pack-agnostic.
"""

from __future__ import annotations

# primitive -> required parameters ("target" is implied for entity primitives)
PRIMITIVES: dict[str, tuple[str, ...]] = {
    "modify_resource": ("target", "resource", "amount"),
    "set_resource": ("target", "resource", "value"),
    "mark_track": ("target", "track", "amount"),
    "clear_track": ("target", "track"),
    "add_condition": ("target", "condition"),
    "remove_condition": ("target", "condition"),
    "add_tag": ("target", "tag"),
    "remove_tag": ("target", "tag"),
    "move": ("target", "to"),
    "transfer_item": ("from", "to", "item"),
    "create_item": ("target", "item"),
    "destroy_item": ("target", "item"),
    "advance_clock": ("clock", "amount"),
    "earn_currency": ("target", "currency", "amount"),
    "spend_currency": ("target", "currency", "amount"),
    "trigger_procedure": ("procedure",),
    "request_gm_ruling": ("table",),
}

# Defined by the architecture but not yet implemented by this kernel build.
RESERVED = {"trigger_procedure"}

# Symbolic targets an effect may name; anything else must be an entity id.
TARGET_SYMBOLS = {"actor", "target", "self"}


def references(effect: dict) -> dict[str, str]:
    """Catalogue references made by an effect: {kind: id}."""
    refs = {}
    for key, kind in (
        ("resource", "resource"), ("track", "track"), ("condition", "condition"),
        ("currency", "currency"), ("table", "consequence_table"), ("clock", "clock"),
    ):
        if key in effect:
            refs[kind] = effect[key]
    return refs

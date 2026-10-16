"""Determinism settings (§2.13).

Settings decide, per role and per control, whether a model picks inputs from
an engine-generated list (strict) or may supply a bounded value (standard).
Dice, resolution, effects, legality checks, and derivable tags are
deterministic under every setting.

Effective settings are always stored fully expanded in the event log, so
replay never depends on the defaults in this file.
"""

from __future__ import annotations

import copy

STRICT, STANDARD = "strict", "standard"
VALUES = (STRICT, STANDARD)
ROLES = ("players", "gm")

# control -> roles it applies to
CONTROLS: dict[str, tuple[str, ...]] = {
    "difficulty": ("gm",),
    "situational_modifiers": ("gm",),
    "ruling_slots": ("gm",),
    "unmodelled_actions": ("gm",),
    "fudging": ("gm",),
    "fiction_triggers": ("players", "gm"),
    "spend_amounts": ("players", "gm"),
}

DEFAULTS = {"players": {"preset": STRICT}, "gm": {"preset": STANDARD}}
DEFAULT_MIN_SCENES_BETWEEN_CHANGES = 1


class SettingsError(ValueError):
    pass


def _expand_role(role: str, spec: dict | None, overrides: dict | None) -> dict[str, str]:
    spec = spec or {}
    preset = spec.get("preset", DEFAULTS[role]["preset"])
    if preset not in VALUES:
        raise SettingsError(f"{role}: unknown preset {preset!r}")
    out = {c: preset for c, roles in CONTROLS.items() if role in roles}
    for control, value in (overrides or {}).items():
        if control not in CONTROLS:
            raise SettingsError(f"unknown control {control!r}")
        if role not in CONTROLS[control]:
            raise SettingsError(f"control {control!r} does not apply to {role}")
        if value not in VALUES:
            raise SettingsError(f"{role}.{control}: value must be strict or standard")
        out[control] = value
    return out


def expand(config: dict | None) -> dict:
    """Campaign `determinism:` config -> fully explicit effective settings."""
    config = config or {}
    overrides = config.get("overrides") or {}
    unknown = set(config) - {"players", "gm", "overrides", "seat_overrides", "min_scenes_between_changes"}
    if unknown:
        raise SettingsError(f"unknown determinism keys {sorted(unknown)}")
    eff = {
        "players": _expand_role("players", config.get("players"), overrides.get("players")),
        "gm": _expand_role("gm", config.get("gm"), overrides.get("gm")),
        "seats": {},
        "min_scenes_between_changes": int(
            config.get("min_scenes_between_changes", DEFAULT_MIN_SCENES_BETWEEN_CHANGES)
        ),
    }
    for seat, seat_over in (config.get("seat_overrides") or {}).items():
        for control, value in seat_over.items():
            if control not in CONTROLS or value not in VALUES:
                raise SettingsError(f"bad seat override {seat}.{control}={value!r}")
        eff["seats"][seat] = dict(seat_over)
    return eff


def apply_change(effective: dict, role: str | None = None, preset: str | None = None,
                 overrides: dict | None = None, seat: str | None = None,
                 seat_overrides: dict | None = None) -> dict:
    """Return new effective settings after a change request."""
    new = copy.deepcopy(effective)
    if role is not None:
        if role not in ROLES:
            raise SettingsError(f"unknown role {role!r}")
        current = new[role]
        base_preset = preset
        if base_preset is not None:
            if base_preset not in VALUES:
                raise SettingsError(f"unknown preset {base_preset!r}")
            current = {c: base_preset for c in current}
        for control, value in (overrides or {}).items():
            if control not in current:
                raise SettingsError(f"control {control!r} does not apply to {role}")
            if value not in VALUES:
                raise SettingsError(f"{control}: value must be strict or standard")
            current[control] = value
        new[role] = current
    if seat is not None:
        for control, value in (seat_overrides or {}).items():
            if control not in CONTROLS or value not in VALUES:
                raise SettingsError(f"bad seat override {control}={value!r}")
        if seat_overrides:
            new["seats"][seat] = {**new["seats"].get(seat, {}), **seat_overrides}
        else:
            new["seats"].pop(seat, None)
    return new


def setting_for(effective: dict, role: str, control: str, seat: str | None = None) -> str:
    if seat and control in effective.get("seats", {}).get(seat, {}):
        return effective["seats"][seat][control]
    return effective[role].get(control, STANDARD)


def unsupported_strict(effective: dict, readiness: dict[str, bool]) -> list[str]:
    """Controls set to strict that the pack cannot support."""
    bad = []
    for role in ROLES:
        for control, value in effective[role].items():
            if value == STRICT and not readiness.get(control, True):
                bad.append(f"{role}.{control}")
    for seat, over in effective.get("seats", {}).items():
        for control, value in over.items():
            if value == STRICT and not readiness.get(control, True):
                bad.append(f"seat {seat}.{control}")
    return bad

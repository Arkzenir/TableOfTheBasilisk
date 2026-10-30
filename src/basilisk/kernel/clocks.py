"""Clocks and off-air advancement (§7.6.1, §7.6.2 axiom 15, BUILD_PLAN P0.11).

A clock fills toward its total. Faction clocks are the pacing engine: they
advance on schedule unless the party interferes, and what they achieve
becomes canon (§7.6.1).

    create_clock(id, label, total, visible,
                 schedule={every: n, amount: k},          # optional, off-air
                 stages=[{at: segment, record: {...}}])   # optional, prepped canon

- **Off-air advancement.** When a session starts, before play resumes, every
  scheduled clock that is not paused advances `amount` segments once every
  `every` gaps between sessions since it was created. Prep (before session 1)
  has no gap to pass, so the first advance is at the start of session 2.
  Each advance is an ordinary `advance_clock` effect with `reason: off_air`.
- **Stages are prepped world changes.** When a clock's fill crosses a stage's
  mark — off-air or during play, however it was advanced — the engine writes
  the stage's canon record (`origin: prepped`, as the GM wrote it) and logs
  `clock_stage_reached`. A stage fires once, even if the clock later drops and
  refills. Records are validated when the clock is created and again when they
  are written.
- **Interference.** The GM can `pause_clock` (the party has stalled the
  faction); effects in packs can also lower a clock.
- **Limits are the pack's** (§2.3 `clocks`), with kernel defaults: a clock's
  `segments` (its total), one GM `advance` (also a schedule's `amount`), and a
  schedule's `every`, counted in sessions (`every_sessions`) or in an in-world
  time unit (`every_units`). Each is an inclusive `[min, max]`. A pack's own
  effects may move a clock by any amount; the limits bound the GM's choices.

Clocks created without a schedule or stages fold exactly as before.
"""

from __future__ import annotations

import copy

from . import timekeeping
from .command import EngineError, _suggest, atomic, check_id, check_name, gm_call

EVENT_TYPES = frozenset({"clock_stage_reached", "clock_paused"})

# Kernel defaults for the pack's `clocks` block (§2.3): inclusive [min, max].
DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "segments": (1, 100),        # a clock's total
    "advance": (1, 3),           # one GM advance, and a schedule's amount
    "every_sessions": (1, 12),   # a schedule counted in gaps between sessions
    "every_units": (1, 1000),    # a schedule counted in an in-world time unit
}


def limits(pack) -> dict[str, tuple[int, int]]:
    """The clock limits in force: the pack's, over the kernel defaults."""
    declared = pack.get("clocks") or {}
    out = dict(DEFAULT_LIMITS)
    for key, value in declared.items() if isinstance(declared, dict) else ():
        if key in out and isinstance(value, list) and len(value) == 2:
            out[key] = (value[0], value[1])
    return out


def advance_amounts(pack) -> list[int]:
    lo, hi = limits(pack)["advance"]
    return list(range(lo, hi + 1))


def lint_clocks(pack) -> list[str]:
    """Problems in a pack's `clocks` block, for pack lint (§2.10)."""
    declared = pack.get("clocks")
    if declared is None:
        return []
    if not isinstance(declared, dict):
        return [f"clocks is a mapping of {', '.join(DEFAULT_LIMITS)} to [min, max]"]
    out = []
    for key, value in declared.items():
        if key not in DEFAULT_LIMITS:
            out.append(_suggest("clock limit", key, DEFAULT_LIMITS))
            continue
        if not (isinstance(value, list) and len(value) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) for v in value) and 1 <= value[0] <= value[1]):
            lo, hi = DEFAULT_LIMITS[key]
            out.append(f"clocks.{key} must be [min, max], integers with 1 <= min <= max (default [{lo}, {hi}]); "
                       f"got {value!r}")
    return out


def apply_event(state: dict, ev: dict) -> None:
    """Fold one clock event. Called from `engine.apply_event`."""
    t, p = ev["type"], ev.get("payload") or {}
    clock = state["clocks"][p["clock"]]
    if t == "clock_stage_reached":
        clock["fired"].append(p["at"])
    elif t == "clock_paused":
        clock["paused"] = bool(p["paused"])


def created_clock(p: dict) -> dict:
    """The folded form of a `clock_created` payload."""
    clock = {"label": p["label"], "filled": 0, "total": p["total"], "visible": p["visible"]}
    if "schedule" in p or "stages" in p:  # optional fields: older payloads fold unchanged
        clock.update({"schedule": copy.deepcopy(p.get("schedule")), "stages": copy.deepcopy(p.get("stages") or []),
                      "created_session": p["created_session"], "fired": [], "paused": False})
        if "created_elapsed" in p:
            clock["created_elapsed"] = p["created_elapsed"]
    return clock


class ClockCommands:
    """Clock commands. Mixed into `Engine`; writes canon through `CanonCommands`."""

    def _clock(self, clock_id: str) -> dict:
        if clock_id not in self.state["clocks"]:
            raise EngineError(_suggest("clock", clock_id, self.state["clocks"]))
        return self.state["clocks"][clock_id]

    @atomic
    @gm_call()
    def create_clock(self, clock_id: str, label: str, total: int, visible: bool = True, by: str | None = None,
                     schedule: dict | None = None, stages: list[dict] | None = None) -> None:
        by = self._gm_only(by, "create clocks")
        check_id("clock", clock_id)
        check_name("a clock's label", label)
        if clock_id in self.state["clocks"]:
            raise EngineError(f"clock {clock_id!r} exists")
        lo, hi = limits(self.pack)["segments"]
        if isinstance(total, bool) or not isinstance(total, int) or not lo <= total <= hi:
            raise EngineError(f"a clock's total must be an integer from {lo} to {hi} segments")
        payload = {"clock_id": clock_id, "label": label, "total": int(total), "visible": bool(visible)}
        if schedule is not None or stages is not None:
            payload.update({"schedule": self._check_schedule(schedule), "stages": self._check_stages(stages, total),
                            "created_session": self.state["session"]})
            if (schedule or {}).get("unit"):  # scheduled on in-world time: count from now
                payload["created_elapsed"] = self.elapsed()
        self._emit("clock_created", payload, actor=by)

    def _check_schedule(self, schedule: dict | None) -> dict | None:
        if schedule is None:
            return None
        every, amount, unit = schedule.get("every"), schedule.get("amount", 1), schedule.get("unit")
        if set(schedule) - {"every", "amount", "unit"}:
            raise EngineError("a schedule has every (sessions), amount (segments), and optionally unit: "
                              "an in-world time unit that every then counts instead")
        bounds = limits(self.pack)
        for name, value, (lo, hi) in (("every", every, bounds["every_units" if unit else "every_sessions"]),
                                      ("amount", amount, bounds["advance"])):
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise EngineError(f"schedule {name} must be an integer from {lo} to {hi}")
        if unit is not None:
            ids = [u["id"] for u in timekeeping.units(self.pack)]
            if unit not in ids:
                raise EngineError(_suggest("time unit", unit, ids))
            return {"every": every, "amount": amount, "unit": unit}
        return {"every": every, "amount": amount}

    def _check_stages(self, stages: list[dict] | None, total: int) -> list[dict]:
        out = []
        for stage in stages or []:
            at = stage.get("at") if isinstance(stage, dict) else None
            if isinstance(at, bool) or not isinstance(at, int) or not 1 <= at <= total:
                raise EngineError(f"a stage needs at: a segment from 1 to {total}")
            if any(s["at"] == at for s in out):
                raise EngineError(f"two stages at segment {at}")
            record = stage.get("record")
            if not isinstance(record, dict) or record.get("origin", "prepped") != "prepped":
                raise EngineError("a stage needs a record: the canon the GM prepped for that point "
                                  "(origin prepped)")
            self._canon_record({**record, "origin": "prepped"}, "engine")  # validates now; written later
            out.append({"at": at, "record": {**copy.deepcopy(record), "origin": "prepped"}})
        return sorted(out, key=lambda s: s["at"])

    @atomic
    @gm_call(lambda e, a: advance_amounts(e.pack))
    def advance_clock(self, clock_id: str, amount: int, by: str | None = None) -> None:
        self._gm_only(by, "advance clocks")  # the change is the engine's; gm_call logs whose choice it was
        amounts = advance_amounts(self.pack)
        if isinstance(amount, bool) or amount not in amounts:
            raise EngineError(f"a clock advances {amounts[0]} to {amounts[-1]} segments at a time")
        self._apply_effect({"primitive": "advance_clock", "clock": clock_id, "amount": amount},
                           {"actor": None, "target": None, "self": None}, None, {})

    @atomic
    @gm_call(lambda e, a: sorted(e.state["clocks"]))
    def pause_clock(self, clock_id: str, paused: bool = True, by: str | None = None) -> None:
        """Hold (or release) a scheduled clock: the party has interfered."""
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM pauses clocks")
        clock = self._clock(clock_id)
        if clock.get("schedule") is None:
            raise EngineError(f"{clock_id} has no schedule to pause")
        if clock["paused"] == bool(paused):
            raise EngineError(f"{clock_id} is already {'paused' if paused else 'running'}")
        self._emit("clock_paused", {"clock": clock_id, "paused": bool(paused)}, actor=by)

    def _clock_moved(self, clock_id: str, old: int, new: int, cause: int) -> None:
        """Write the canon for every stage the fill has just crossed (axiom 15)."""
        clock = self.state["clocks"][clock_id]
        for stage in clock.get("stages") or []:
            if old < stage["at"] <= new and stage["at"] not in clock["fired"]:
                rec, flags = self._canon_record(stage["record"], "engine")
                seq = self._emit("canon_written", {"record": rec, "flags": flags}, actor="engine", caused_by=cause)
                self._emit("clock_stage_reached", {"clock": clock_id, "at": stage["at"], "record": rec["id"]},
                           actor="engine", caused_by=seq)

    def _advance_off_air(self) -> None:
        """Between sessions: advance every scheduled, running clock that is due."""
        finished = self.state["session"]
        if finished < 1:
            return  # nothing has been played yet
        for clock_id in sorted(self.state["clocks"]):
            clock = self.state["clocks"][clock_id]
            schedule = clock.get("schedule")
            if not schedule or schedule.get("unit") or clock["paused"] or clock["filled"] >= clock["total"]:
                continue  # time-scheduled clocks move with in-world time instead
            # gaps between sessions since creation: a clock made during (or after) session n
            # first advances at the start of n + 1; one made in prep, after session 1
            created = clock["created_session"]
            elapsed = finished - (created - 1 if created >= 1 else 0)
            if elapsed > 0 and elapsed % schedule["every"] == 0:
                self._apply_effect({"primitive": "advance_clock", "clock": clock_id, "amount": schedule["amount"],
                                    "reason": "off_air"}, {"actor": None, "target": None, "self": None}, None, {})

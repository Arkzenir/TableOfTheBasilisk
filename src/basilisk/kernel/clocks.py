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

Clocks created without a schedule or stages fold exactly as before.
"""

from __future__ import annotations

import copy

from . import timekeeping
from .command import EngineError, _suggest, atomic

EVENT_TYPES = frozenset({"clock_stage_reached", "clock_paused"})


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
    def create_clock(self, clock_id: str, label: str, total: int, visible: bool = True, by: str | None = None,
                     schedule: dict | None = None, stages: list[dict] | None = None) -> None:
        if clock_id in self.state["clocks"]:
            raise EngineError(f"clock {clock_id!r} exists")
        if isinstance(total, bool) or not isinstance(total, int) or total < 1:
            raise EngineError("a clock's total must be a positive integer")
        payload = {"clock_id": clock_id, "label": label, "total": int(total), "visible": bool(visible)}
        if schedule is not None or stages is not None:
            payload.update({"schedule": self._check_schedule(schedule), "stages": self._check_stages(stages, total),
                            "created_session": self.state["session"]})
            if (schedule or {}).get("unit"):  # scheduled on in-world time: count from now
                payload["created_elapsed"] = self.elapsed()
        self._emit("clock_created", payload, actor=by or self.gm_seat)

    def _check_schedule(self, schedule: dict | None) -> dict | None:
        if schedule is None:
            return None
        every, amount, unit = schedule.get("every"), schedule.get("amount", 1), schedule.get("unit")
        if set(schedule) - {"every", "amount", "unit"}:
            raise EngineError("a schedule has every (sessions), amount (segments), and optionally unit: "
                              "an in-world time unit that every then counts instead")
        for name, value, lo, hi in (("every", every, 1, 1000 if unit else 12), ("amount", amount, 1, 3)):
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
    def advance_clock(self, clock_id: str, amount: int, by: str | None = None) -> None:
        if amount not in (1, 2, 3):
            raise EngineError("clock advances are 1, 2 or 3")
        self._apply_effect({"primitive": "advance_clock", "clock": clock_id, "amount": amount},
                           {"actor": None, "target": None, "self": None}, None, {})

    @atomic
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

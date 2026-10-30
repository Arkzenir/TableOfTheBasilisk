"""In-world time: watches, days, and the calendar (§2.2 "Clocks and time", BUILD_PLAN P0.11).

A pack declares its units, smallest first; each says how many of it make the
next one up:

    time:
      units: [{id, label, per}]        # per: how many make the next unit; the last has none
      between_sessions: {unit, amount} # optional: time that passes off-air

State keeps one number, the elapsed count of the smallest unit, created by the
first advance (older logs fold unchanged). The date is derived from it by
mixed radix: with watches (4 per day) and days (28 per season), elapsed 9 is
season 1, day 3, watch 2 (counting from 1).

Clocks may be scheduled on in-world time as well as on sessions: a schedule
`{every, amount, unit}` advances the clock `amount` segments for every
`every` units that pass. Rounds and turns are the turn controller's (§2.4).
"""

from __future__ import annotations

from .command import EngineError, _suggest, atomic, gm_call

EVENT_TYPES = frozenset({"time_advanced"})
MAX_ADVANCE = 1_000  # units per engine advance (off-air time included); a kernel ceiling
DEFAULT_ADVANCE = (1, 12)  # a GM call's range per unit, unless the unit declares `advance`


def units(pack) -> list[dict]:
    return list((pack.get("time") or {}).get("units") or [])


def advance_limits(pack, unit_id: str) -> tuple[int, int]:
    """How much of `unit_id` one GM `advance_time` may move (§2.3 `units[].advance`)."""
    unit = next((u for u in units(pack) if u["id"] == unit_id), None)
    if unit is None:
        raise EngineError(_suggest("time unit", unit_id, [u["id"] for u in units(pack)]))
    value = unit.get("advance")
    return (value[0], value[1]) if isinstance(value, list) and len(value) == 2 else DEFAULT_ADVANCE


def advance_amounts(pack) -> list[int]:
    """Every amount some unit allows, for the GM tool's enum; the engine checks per unit."""
    spans = [advance_limits(pack, u["id"]) for u in units(pack)]
    return list(range(min(lo for lo, _ in spans), max(hi for _, hi in spans) + 1)) if spans else []


def unit_size(pack, unit_id: str) -> int:
    """How many of the smallest unit make one `unit_id`."""
    size = 1
    for u in units(pack):
        if u["id"] == unit_id:
            return size
        size *= int(u.get("per") or 1)
    raise EngineError(_suggest("time unit", unit_id, [u["id"] for u in units(pack)]))


def breakdown(pack, elapsed: int) -> dict[str, int]:
    """The date for an elapsed count, each unit counted from 1."""
    out, left = {}, elapsed
    us = units(pack)
    for i, u in enumerate(us):
        if i < len(us) - 1:
            per = int(u["per"])
            out[u["id"]] = left % per + 1
            left //= per
        else:
            out[u["id"]] = left + 1
    return out


def lint_time(pack) -> list[str]:
    out = []
    us = units(pack)
    ids = [u.get("id") for u in us]
    if len(ids) != len(set(ids)):
        out.append("duplicate time unit ids")
    for i, u in enumerate(us):
        per = u.get("per")
        if i < len(us) - 1 and (isinstance(per, bool) or not isinstance(per, int) or per < 2):
            out.append(f"time unit {u.get('id')}: per must be an integer of 2 or more (how many make a {us[i + 1].get('id')})")
        if not u.get("label"):
            out.append(f"time unit {u.get('id')}: needs a label")
        adv = u.get("advance")
        if adv is not None and not (isinstance(adv, list) and len(adv) == 2
                                    and all(isinstance(v, int) and not isinstance(v, bool) for v in adv)
                                    and 1 <= adv[0] <= adv[1] <= MAX_ADVANCE):
            out.append(f"time unit {u.get('id')}: advance must be [min, max], integers with 1 <= min <= max "
                       f"<= {MAX_ADVANCE} (default [{DEFAULT_ADVANCE[0]}, {DEFAULT_ADVANCE[1]}]); got {adv!r}")
    between = (pack.get("time") or {}).get("between_sessions")
    if between is not None:
        if between.get("unit") not in ids:
            out.append("time.between_sessions: " + _suggest("time unit", between.get("unit"), ids))
        amount = between.get("amount", 1)
        if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= MAX_ADVANCE:
            out.append(f"time.between_sessions.amount must be from 1 to {MAX_ADVANCE}")
    return out


def apply_event(state: dict, ev: dict) -> None:
    """Fold one time event. Called from `engine.apply_event`."""
    if ev["type"] == "time_advanced":
        state["time"] = {"elapsed": ev["payload"]["to"]}


class TimeCommands:
    """Time commands. Mixed into `Engine`; drives time-scheduled clocks."""

    def elapsed(self) -> int:
        return (self.state.get("time") or {}).get("elapsed", 0)

    def current_time(self) -> dict | None:
        """The date (§8.4 overlay, prompts): each unit counted from 1, with labels.
        None when the pack keeps no calendar."""
        if not units(self.pack):
            return None
        parts = breakdown(self.pack, self.elapsed())
        labels = {u["id"]: u["label"] for u in units(self.pack)}
        text = ", ".join(f"{labels[u]} {parts[u]}" for u in reversed(list(parts)))
        return {"elapsed": self.elapsed(), "units": parts, "text": text}

    @atomic
    @gm_call(lambda e, a: [u["id"] for u in units(e.pack)])
    def advance_time(self, unit: str, amount: int = 1, by: str | None = None) -> dict:
        """Let in-world time pass (GM): `amount` of `unit`, carrying into larger units."""
        by = by or self.gm_seat
        if by != "engine" and self._role(by) != "gm":
            raise EngineError("only the GM moves in-world time")
        self._require_settled()
        if by != "engine" and units(self.pack):
            lo, hi = advance_limits(self.pack, unit)
            if isinstance(amount, bool) or not isinstance(amount, int) or not lo <= amount <= hi:
                raise EngineError(f"advance time by {lo} to {hi} {unit}")
        return self._advance_time(unit, amount, by)

    def _advance_time(self, unit: str, amount: int, by: str, reason: str | None = None) -> dict:
        if not units(self.pack):
            raise EngineError(f"pack {self.pack.id} keeps no calendar (no time.units)")
        if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= MAX_ADVANCE:
            raise EngineError(f"advance time by 1 to {MAX_ADVANCE} {unit}")
        frm = self.elapsed()
        to = frm + amount * unit_size(self.pack, unit)
        payload = {"unit": unit, "amount": amount, "from": frm, "to": to}
        if reason:
            payload["reason"] = reason
        seq = self._emit("time_advanced", payload, actor=by)
        self._time_moved(frm, to, seq)
        return self.current_time()

    def _time_moved(self, frm: int, to: int, cause: int) -> None:
        """Advance every running clock scheduled on in-world time, once per
        interval that has just completed since the clock was made."""
        for clock_id in sorted(self.state["clocks"]):
            clock = self.state["clocks"][clock_id]
            schedule = clock.get("schedule") or {}
            if not schedule.get("unit") or clock.get("paused") or clock["filled"] >= clock["total"]:
                continue
            interval = schedule["every"] * unit_size(self.pack, schedule["unit"])
            start = clock.get("created_elapsed", 0)
            crossed = (to - start) // interval - (max(frm, start) - start) // interval
            if crossed > 0:
                self._apply_effect({"primitive": "advance_clock", "clock": clock_id,
                                    "amount": schedule["amount"] * crossed, "reason": "time"},
                                   {"actor": None, "target": None, "self": None}, cause, {})

    def _time_between_sessions(self) -> None:
        between = (self.pack.get("time") or {}).get("between_sessions")
        if between and self.state["session"] >= 1:
            self._advance_time(between["unit"], int(between.get("amount", 1)), "engine", reason="off_air")

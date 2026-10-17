"""`peek_roll` and fudging (§5.5, §2.5, §2.13).

The GM may ask to see a roll before it goes public, by passing `peek: true`
with its ruling on an action whose procedure the pack lists as fudgeable.
The engine rolls, logs `roll_peeked`, and pauses the action: nothing has been
resolved or applied yet. The GM then settles it with `peek_roll`:

- `keep` — the roll stands.
- `reroll` — one more roll through the logged randomizer. **Direction of drama
  only:** a reroll whose outcome would lower the party-side rank on the
  procedure's outcome scale is refused (atomically, so trying again gives the
  same refusal). The party side of a rank is the rank itself when a player's
  entity rolled, and the mirror of it when a GM-controlled entity rolled. The
  kernel never needs to know what the outcomes are called.

Then the procedure resolves with the final roll and the action's effects apply.
`procedure_resolved` names the final roll, so rule cards show only the public
result (§8.6); the peek and any reroll live in the log for the archive.

Fudging exists only where the pack declares `gm.gm_rolls: true`, for its
`gm.fudgeable_procedures`, and while the GM's `fudging` control is standard.
The GM's `fudging` trait caps peeks per session (`peek_cap`). Older logs never
contain these events and fold unchanged.
"""

from __future__ import annotations

import copy

from .command import EngineError, atomic
from .determinism import STANDARD

EVENT_TYPES = frozenset({"roll_peeked", "roll_fudged", "peek_settled"})
PEEKS_AT_FULL_TRAIT = 4  # peeks per session at fudging 100; a kernel setting
DECISIONS = ("keep", "reroll")


def peek_cap(fudging: int) -> int:
    """Peeks allowed per session for a GM `fudging` trait of 0..100."""
    return max(0, min(100, int(fudging))) * PEEKS_AT_FULL_TRAIT // 100


def fudging_available(pack, gm_mode: str) -> bool:
    return bool(pack.get("gm.gm_rolls", True)) and bool(pack.get("gm.fudgeable_procedures")) and gm_mode == STANDARD


# ====================================================================== reducer

def apply_event(state: dict, ev: dict) -> None:
    """Fold one fudging event. Called from `engine.apply_event`."""
    t, p = ev["type"], ev.get("payload") or {}
    f = state.setdefault("fudging", {"session": 0, "peeks": 0, "pending": None})
    if t == "roll_peeked":
        if f["session"] != state["session"]:
            f["session"], f["peeks"] = state["session"], 0
        f["peeks"] += 1
        f["pending"] = {**copy.deepcopy(p), "seq": ev["seq"]}
    elif t == "roll_fudged":
        f["pending"]["fudged"] = True
    elif t == "peek_settled":
        f["pending"] = None


# ====================================================================== commands

class FudgeCommands:
    """GM fudging. Mixed into `Engine`; works with `ResolutionCommands`."""

    def _pending(self) -> dict | None:
        return (self.state.get("fudging") or {}).get("pending")

    def _require_settled(self) -> None:
        pending = self._pending()
        if pending:
            raise EngineError(f"a peeked roll ({pending['slot']}) is waiting for the GM: peek_roll keep or reroll")

    def peeks_left(self) -> int:
        f = self.state.get("fudging") or {}
        used = f.get("peeks", 0) if f.get("session") == self.state["session"] else 0
        return max(0, peek_cap(self.state["campaign"].get("gm_fudging", 50)) - used)

    def _peek_refusal(self, proc_id: str) -> str | None:
        if not self.pack.get("gm.gm_rolls", True):
            return "the GM never rolls in this pack, so there is nothing to peek at"
        if proc_id not in (self.pack.get("gm.fudgeable_procedures") or []):
            return f"{proc_id} is not fudgeable; fudgeable: {', '.join(self.pack.get('gm.fudgeable_procedures') or []) or 'none'}"
        if self.mode("fudging", self.gm_seat) != STANDARD:
            return "fudging is off while the GM's fudging control is strict"
        if self.peeks_left() < 1:
            return "no peeks left this session (capped by the GM's fudging trait)"
        return None

    def _party_rank(self, entity_id: str, rank: int, ranks: int) -> int:
        """The rank as the party sees it: a player's success is good for the
        party; a GM-controlled entity's success is bad for it."""
        return rank if self._side_of(entity_id) == "players" else ranks - 1 - rank

    def _open_peek(self, peek: dict, cause: int) -> None:
        reason = self._peek_refusal(peek["procedure"])
        if reason:
            raise EngineError(f"peek refused: {reason}")
        slot = f"p{self.store.head(self.campaign_id)[0] + 1}"
        self._emit("roll_peeked", {"slot": slot, **peek,
                                   "party_rank": self._party_rank(peek["entity"], peek["rank"], peek["ranks"])},
                   actor=self.gm_seat, caused_by=cause)

    def pending_peek(self) -> dict | None:
        """The GM's private view of a paused roll. Never shown to players or on cards."""
        p = self._pending()
        if not p:
            return None
        return {"slot": p["slot"], "procedure": p["procedure"], "entity": p["entity"], "total": p["total"],
                "outcome": p["outcome"], "rank": p["rank"], "ranks": p["ranks"], "peeks_left": self.peeks_left()}

    @atomic
    def peek_roll(self, decision: str, by: str | None = None) -> dict:
        """Settle a peeked roll: keep it, or reroll once (direction of drama only)."""
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM can settle a peeked roll")
        p = self._pending()
        if not p:
            raise EngineError("no peeked roll is waiting")
        if decision not in DECISIONS:
            raise EngineError(f"decision must be one of {', '.join(DECISIONS)}")
        total, roll_seq, outcome, rank = p["total"], p["roll_seq"], p["outcome"], p["rank"]
        self._judge(by, "fudging", STANDARD, decision, list(DECISIONS), p["seq"])
        if decision == "reroll":
            result, new_seq = self._roll(p["expression"], p["variables"], p["seq"], f"fudge:{p['procedure']}", actor=by)
            new_outcome = self._interpret(p["procedure"], result.total, p["difficulty"])
            scale = self._scale(p["procedure"])
            new_rank = scale.index(new_outcome)
            if self._party_rank(p["entity"], new_rank, p["ranks"]) < p["party_rank"]:
                raise EngineError("reroll refused: it would lower the party-side outcome (direction of drama, "
                                  "§5.5). Keep the roll.")
            self._emit("roll_fudged", {"slot": p["slot"], "from_roll_seq": roll_seq, "to_roll_seq": new_seq,
                                       "from_total": total, "to_total": result.total,
                                       "from_rank": rank, "to_rank": new_rank}, actor=by, caused_by=new_seq)
            total, roll_seq, outcome, rank = result.total, new_seq, new_outcome, new_rank
        self._emit("peek_settled", {"slot": p["slot"], "decision": decision, "roll_seq": roll_seq, "total": total},
                   actor=by, caused_by=p["seq"])
        proc_seq = self._resolved(p["procedure"], p["entity"], outcome, total, p["difficulty"], p["modifiers"],
                                  roll_seq, False, p["cause"])
        cont = p["continuation"]
        if cont["kind"] == "action":
            self._apply_outcome(cont["action"], outcome, cont["ids"], cont["variables"], proc_seq)
        return {"outcome": outcome, "rank": rank, "decision": decision}

"""Seeded card decks (§2.4, §5.5, BUILD_PLAN P0.2).

A pack declares decks under `randomizers.decks`:

    decks: [{id, cards: [{id, label} | id], reshuffle_rule, players_draw?}]

Deck order is game state (§5.5): a shuffle consumes one roll counter through
`Randomizer.shuffle`, and `deck_shuffled` records both the cards shuffled and
the exact resulting order, so replay folds the order without re-running the
shuffle and `verify --seed` can re-derive it. A deck is created by its first
shuffle, which happens on its first draw; `state["decks"]` exists only once a
deck has been used, so older logs fold unchanged.

Reshuffle rules (`reshuffle_rule`):
- `when_empty` — drawing from an empty pile first shuffles the discards back in.
- `every_draw` — every draw is from a fresh shuffle of all cards not held.
- `scene` / `session` — the deck is reshuffled whole at each scene or session start.
- `manual` — only the GM's `reshuffle_deck` refills it; an empty pile refuses draws.

A drawn card goes to the discard pile face up, or into a holder's hand with
`to=`; `discard_card` returns a held card to the discards. Pile order is never
shown to any seat: views give counts, the face-up discards, and a seat's own hand.
"""

from __future__ import annotations

import copy

from .canon import ID_RE
from .command import EngineError, _suggest, atomic, gm_call

EVENT_TYPES = frozenset({"deck_shuffled", "card_drawn", "card_discarded"})
RESHUFFLE_RULES = ("when_empty", "every_draw", "scene", "session", "manual")


def card_ids(deck: dict) -> list[str]:
    return [c["id"] if isinstance(c, dict) else str(c) for c in deck.get("cards") or []]


def lint_decks(pack) -> list[str]:
    """Problems in a pack's decks, for pack lint (§2.10)."""
    out = []
    ids = [d.get("id") for d in pack.catalogue("randomizers.decks")]
    if len(ids) != len(set(ids)):
        out.append("duplicate deck ids")
    for deck in pack.catalogue("randomizers.decks"):
        where = f"deck {deck.get('id')}"
        if not ID_RE.match(str(deck.get("id", ""))):
            out.append(f"{where}: id must be lowercase letters, digits and underscores")
        cards = card_ids(deck)
        if not cards:
            out.append(f"{where}: needs at least one card")
        if len(cards) != len(set(cards)):
            out.append(f"{where}: duplicate card ids")
        for c in cards:
            if not ID_RE.match(c):
                out.append(f"{where}: card id {c!r} must be lowercase letters, digits and underscores")
        if deck.get("reshuffle_rule") not in RESHUFFLE_RULES:
            out.append(f"{where}: " + _suggest("reshuffle rule", deck.get("reshuffle_rule"), RESHUFFLE_RULES))
    return out


# ====================================================================== reducer

def apply_event(state: dict, ev: dict) -> None:
    """Fold one deck event. Called from `engine.apply_event`."""
    t, p = ev["type"], ev.get("payload") or {}
    decks = state.setdefault("decks", {})
    if t == "deck_shuffled":
        deck = decks.setdefault(p["deck"], {"draw": [], "discard": [], "held": {}})
        deck["draw"], deck["discard"] = list(p["order"]), []
        state["roll_counter"] = p["counter"] + 1
    elif t == "card_drawn":
        deck = decks[p["deck"]]
        deck["draw"].remove(p["card"])
        if p.get("to"):
            deck["held"].setdefault(p["to"], []).append(p["card"])
        else:
            deck["discard"].append(p["card"])
    elif t == "card_discarded":
        deck = decks[p["deck"]]
        deck["held"][p["holder"]].remove(p["card"])
        if not deck["held"][p["holder"]]:
            del deck["held"][p["holder"]]
        deck["discard"].append(p["card"])


# ====================================================================== commands

class DeckCommands:
    """Deck commands and views. Mixed into `Engine`."""

    def _deck_def(self, deck_id: str) -> dict:
        decks = self.pack.by_id("randomizers.decks")
        if deck_id not in decks:
            raise EngineError(_suggest("deck", deck_id, decks))
        return decks[deck_id]

    def _deck_state(self, deck_id: str) -> dict | None:
        return (self.state.get("decks") or {}).get(deck_id)

    def _shuffle(self, deck_id: str, reason: str, actor: str = "engine", cause: int | None = None) -> int:
        """Shuffle every card not in a hand into a fresh draw pile."""
        held = {c for cards in ((self._deck_state(deck_id) or {}).get("held") or {}).values() for c in cards}
        cards = [c for c in card_ids(self._deck_def(deck_id)) if c not in held]
        counter = self.state["roll_counter"]
        order = self.rng.shuffle(counter, cards)
        return self._emit("deck_shuffled", {"deck": deck_id, "counter": counter, "cards": cards, "order": order,
                                            "reason": reason}, actor=actor, caused_by=cause)

    def _reshuffle_at(self, boundary: str) -> None:
        """Scene and session boundaries reshuffle the decks whose rule says so."""
        for deck in self.pack.catalogue("randomizers.decks"):
            if deck["reshuffle_rule"] == boundary and self._deck_state(deck["id"]) is not None:
                self._shuffle(deck["id"], boundary)

    @atomic
    @gm_call(lambda e, a: sorted(d["id"] for d in e.pack.catalogue("randomizers.decks")))
    def draw_card(self, deck_id: str, by: str | None = None, to: str | None = None) -> str:
        """Draw the top card. With `to`, it goes to that holder's hand (a seat
        or entity id); otherwise it is turned face up onto the discards."""
        deck = self._deck_def(deck_id)
        by = by or self.gm_seat
        if self._role(by) != "gm" and not deck.get("players_draw"):
            raise EngineError(f"only the GM draws from {deck_id}")
        if to is not None and to not in self.seats and (to not in self.state["entities"] or not self.visible(by, to)):
            holders = list(self.seats) + [e for e in self.state["entities"] if self.visible(by, e)]
            raise EngineError(_suggest("holder", to, holders))  # never names an entity the drawer cannot see
        rule = deck["reshuffle_rule"]
        state = self._deck_state(deck_id)
        if state is None:
            cause = self._shuffle(deck_id, "first_draw", by)
        elif rule == "every_draw":
            cause = self._shuffle(deck_id, "every_draw", by)
        elif not state["draw"]:
            if rule != "when_empty":
                raise EngineError(f"{deck_id} is empty; its reshuffle rule is {rule}"
                                  + ("; the GM can reshuffle_deck" if rule == "manual" else ""))
            cause = self._shuffle(deck_id, "when_empty", by)
        else:
            cause = None
        pile = self._deck_state(deck_id)["draw"]
        if not pile:
            raise EngineError(f"{deck_id} has no cards left to draw: every card is in a hand")
        card = pile[0]
        self._emit("card_drawn", {"deck": deck_id, "card": card, "by": by, "to": to}, actor=by, caused_by=cause)
        return card

    @atomic
    @gm_call(lambda e, a: sorted(d["id"] for d in e.pack.catalogue("randomizers.decks")))
    def reshuffle_deck(self, deck_id: str, by: str | None = None) -> None:
        """GM reshuffle: every card not in a hand goes back into the pile."""
        self._deck_def(deck_id)
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM reshuffles decks")
        self._shuffle(deck_id, "manual", by)

    @atomic
    @gm_call(lambda e, a: sorted(d["id"] for d in e.pack.catalogue("randomizers.decks")))
    def discard_card(self, deck_id: str, card: str, holder: str, by: str | None = None) -> None:
        """Return a held card to the discards."""
        self._deck_def(deck_id)
        by = by or self.gm_seat
        if self._role(by) != "gm" and by != holder:
            raise EngineError(f"only {holder} or the GM can discard {holder}'s cards")
        hand = ((self._deck_state(deck_id) or {}).get("held") or {}).get(holder, [])
        if card not in hand:
            raise EngineError(_suggest(f"card in {holder}'s hand", card, hand))
        self._emit("card_discarded", {"deck": deck_id, "card": card, "holder": holder}, actor=by)

    def deck_view(self, deck_id: str, seat: str) -> dict:
        """What a seat may know of a deck: pile size, the face-up discards, and
        its own hand. Never the pile order; the GM also sees every hand."""
        self._deck_def(deck_id)
        state = self._deck_state(deck_id) or {"draw": card_ids(self._deck_def(deck_id)), "discard": [], "held": {}}
        held = state["held"]
        if self._role(seat) == "gm":
            hands = copy.deepcopy(held)
        else:  # the seat's own hand and the hands of entities it controls
            mine = {seat} | {e for e, ent in self.state["entities"].items() if ent["controller"] == seat}
            hands = {h: list(cards) for h, cards in held.items() if h in mine}
        return {"deck": deck_id, "in_pile": len(state["draw"]), "discard": list(state["discard"]), "hands": hands}

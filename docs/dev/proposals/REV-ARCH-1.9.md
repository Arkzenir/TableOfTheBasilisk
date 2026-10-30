# Draft revision: ARCHITECTURE 1.9 (joining and leaving an encounter)

**Status:** proposed, not applied. Nothing in `docs/ARCHITECTURE.md` changes and nothing is built until the owner approves. If it is approved, it is built as its own task (proposed: T0.39) and the 1.9 text is applied then.

**Why:** the fourth Phase 0 audit (T0.38) found that an encounter's participants are fixed when it starts.
- **Late arrivals never act.** An entity spawned while an encounter runs (reinforcements, a summoned creature, a character who walks in) is not a participant. `commit_action` refuses it ("not taking part in this encounter"), and no command adds it.
- **The defeated keep their turns.** Nothing removes a participant, so a fled, captured, or downed entity is still called in turn order every round. A pack can stop it acting through `requires` (lanternlight's `actor.conditions.down == 0`), but its turn still comes up and has to be passed.
- **The only workaround** is `end_encounter` followed by `start_encounter`. That re-rolls initiative, refills every budget, and restarts the round count, so it changes the mechanics, not just the roster.

§2.4 (turn order) and §5.7 (event list) say nothing about the roster changing mid-encounter, so this is a design gap rather than a bug. It is the GM's call in the fiction, so it belongs on the GM's surface.

---

## A. Header: version and revision note

**Current:** `**Version:** 1.8 (revised design freeze for v1)`
**Proposed:** `**Version:** 1.9 (revised design freeze for v1)`, plus:

> **Revision notes (1.9):** after the fourth Phase 0 audit (T0.38, D-053 to D-055):
> - §2.4, §5.7, §7.1: the GM adds an entity to a running encounter (`join_encounter`) or takes one out (`leave_encounter`); the turn order adapts by strategy.

---

## B. Semantics (⚑ decide)

Two GM commands, both `@atomic` and `@gm_call` (so each is a logged judgement input), and two new events. Older logs contain neither event, so they fold unchanged and `KERNEL_VERSION` does not need to move for this.

**`join_encounter(entity_id, after=None)`**: event `participant_joined {entity, position}`.
- The entity must be in the scene (or anywhere, in a scene without positions) and not already a participant.
- Where it goes in the order depends on the strategy:

| Order | The joiner |
|---|---|
| `initiative` | Rolls the pack's initiative roll now (logged) and is placed by its total in the current sequence. If its slot is already past this round, it first acts next round. |
| `fixed` | Is placed after `after` (default: last). |
| `deck` | Joins the next round's shuffle. |
| `sides` | Acts with its side, from that side's next turn. |
| `spotlight`, `handoff` | Is added to the participants and can be handed the spotlight at once. |

- Its budget is filled when its first turn starts, as for everyone else.

**`leave_encounter(entity_id, reason)`**: event `participant_left {entity, reason}`, with `reason` one of `defeated | fled | removed` (an enum, so it is safe under strict).
- The entity is removed from the participants, the current sequence, and the budgets.
- If it was taking its turn, the turn passes as if it had ended (`end_turn` semantics, logged).
- If it was the last member of a side under `sides`, that side's turns are skipped.
- If no participant is left, the encounter stays open: ending it is still the GM's call (`end_encounter`).
- Leaving the encounter does not remove the entity from the scene or from state. It remains in canon and on sheets, and can rejoin.

**Options considered:**
1. **(Recommended) Explicit GM commands, as above.** The roster changes only by a logged GM decision, and the change is visible on the overlay.
2. **Automatic join on spawn.** `spawn_entity` during an encounter would add the entity at once. This is simpler for the GM, but it removes the choice of whether something arrives in the fight or only in the scene, and it does nothing for leaving.
3. **A pack-declared skip rule** (for example `turn_structure.encounter.skip_when: "actor.conditions.down"`) that passes a participant's turn automatically. This is complementary to option 1, not a replacement: it handles the downed but not the fled, and does nothing for late arrivals. Proposed as a later addition if a pack needs it.

---

## C. §2.4 Variation points (Turn order row)

**Current:** `| Turn order | None (spotlight), individual initiative, side-based, handoff ("popcorn"), fixed, deck-drawn | — |`
**Proposed:** unchanged row, plus a sentence after the table:

> The roster of an encounter can change while it runs: the GM adds an entity (`join_encounter`) or takes one out (`leave_encounter`, as defeated, fled, or removed), and each ordering strategy places a joiner its own way (initiative rolls on joining; a deck-drawn order shuffles it in next round).

---

## D. §5.7 Event schema (mechanics)

**Current:** `encounter_started, round_started, turn_started, economy_spent, encounter_ended`
**Proposed:** `encounter_started, round_started, turn_started, economy_spent, participant_joined, participant_left, encounter_ended`

---

## E. §7.1 Tool surface (GM-only block and the table)

**Proposed additions to the GM-only block:**
```
join_encounter(entity_id, after?)  → add an entity to the running encounter; its order per strategy
leave_encounter(entity_id, reason) → defeated | fled | removed; its turn passes if it is current
```
**Proposed table rows:** `| join_encounter / leave_encounter | — | ✓ | — |`

---

## F. What the build would add (for the task, not the architecture)

- `kernel/turns.py`: the two commands, reducer cases for the two events, `EVENT_TYPES`, and `docs/dev/EVENTS.md` rows.
- `kernel/tools.py`: the two GM tools, with `reason` as an enum and `after` only for `fixed`.
- Tests: every order strategy with a join before and after the joiner's slot, a leave by the current actor, the last member of a side leaving, and replay of both events.
- The smoke harness: spawn a reinforcement mid-encounter and have one NPC leave, so every gated campaign exercises both.

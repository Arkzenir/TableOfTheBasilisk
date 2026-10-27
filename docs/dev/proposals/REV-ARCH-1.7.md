# Draft revision: ARCHITECTURE 1.7 (§2.3 pack schema: `gm` block)

**Status:** approved by the owner as proposed (B as recommended, with the `visible` flag) and applied to `docs/ARCHITECTURE.md` on 2026-10-27; built as T0.32 (D-047). Kept as the record of the review.
**Why:** ARCHITECTURE 1.6 says §2.3 describes the build. The second audit found three places in the `gm` block where it does not:
- `gm_rolls: false` was read only by fudging. T0.31 now enforces it everywhere.
- `holder: party` was not implemented. T0.31 builds it as a shared pool.
- `holder: gm` gives every NPC its own copy rather than one GM pool.
- `lethality_levers` is declared but nothing reads it.

This draft proposes the GM-holder semantics (a design decision, so not built yet) and the §2.3 wording for all four.

---

## A. Header: version and revision note

**Current:** `**Version:** 1.6 (revised design freeze for v1)`
**Proposed:** `**Version:** 1.7 (revised design freeze for v1)`, plus:

> **Revision notes (1.7):**
> - §2.3 `gm` block, matching the build after the second Phase 0 audit (T0.31, D-046):
>   - `gm_rolls: false` means no GM-side entity rolls;
>   - a `party` currency is one shared pool;
>   - a `gm` currency is one pool on the GM's side;
>   - `lethality_levers` is reserved for trait implementation (BUILD_PLAN P2.5).

---

## B. Semantics of a GM-held currency (⚑ decide)

**Built today:**
- `holder: gm` puts a separate copy, with its own `start`, on every GM-controlled entity at spawn.
- A doom or momentum pool therefore splits across NPCs, and a currency that players' actions feed (for example "spending Luck adds 1 Doom") has no single place to land.
- No shipped pack uses `holder: gm`, so nothing depends on this behaviour.

**Proposed:** a `gm` currency is **one pool held by the GM's side**, mirroring the party's pool that T0.31 builds.
- **Storage:** `state.currencies.gm.<id>`. It reads its `start` until the first change creates it, so older logs fold unchanged.
- **Who draws on it:** every GM-controlled entity. An NPC's action `cost` spends from the pool. `earn_currency` / `spend_currency` with `target: actor` (or `target`, `self`) resolving to a GM-side entity changes the pool. A player character cannot hold it.
- **How player actions feed it:** a new target symbol, `target: gm`, valid only on `earn_currency` and `spend_currency` with a GM-held currency, so a player's outcome effect can add to the GM's pool. Lint refuses `target: gm` anywhere else.
- **Who sees it:** the GM's sheet views show it. Whether the overlay shows players the pool (doom is usually public) is a presentation choice. Proposed: a `visible: true | false` flag on the currency, default `true`, read by P4's overlay; nothing in P0 reads it.
- **Spending without an action:** none in P0. A GM-intrusion style spend is an action with a `cost`, committed for an NPC, or an outcome effect. A dedicated GM tool waits for a pack that needs one.

**Alternatives:**
1. **Keep per-NPC copies** and document them. This is simple, but it cannot express doom/momentum pools, which §2.4 names as a case the kernel covers.
2. **The GM pool, with no `target: gm` symbol.** Players' effects could not feed it; only NPC actions would change it. This is smaller, but it rules out the common "a player's spend feeds the GM" pattern.

**Recommendation:** the proposal above. It needs no new event type (`effect_applied` carries the path), and `KERNEL_VERSION` stays as D-045 says.

---

## C. §2.3 `gm` block wording

**Current:**
```
  gm:
    gm_rolls: bool
    fudgeable_procedures: [procedure_id]
    lethality_levers: [{ id, effect }]
    meta_currencies: [{ id, holder: gm | party | each_player, start, max }]
    consequence_tables: [{ id, entries: [{ id, label, effects, weight, severity }] }]
```

**Proposed** (assuming B is approved as proposed):
```
  gm:
    gm_rolls: bool                    # false: no GM-side entity rolls, as actor or as an opposed side (§2.4)
    fudgeable_procedures: [procedure_id]
    lethality_levers: [{ id, effect }]   # reserved: read by the lethality trait (BUILD_PLAN P2.5), not by P0
    meta_currencies: [{ id, holder: each_player | party | gm, start, max, visible }]
                                      # each_player: one on every player character
                                      # party: one pool every player character draws on
                                      # gm: one pool every GM-side entity draws on; `target: gm` feeds it
    consequence_tables: [{ id, entries: [{ id, label, effects, weight, severity }] }]
```

If B is not approved, the `gm:` comment line becomes "gm: one on every GM-side entity" and `visible` is dropped.

---

## D. Follow-up if approved

These are one task (T0.32):
- Build the GM pool and the `target: gm` symbol, with lint and tests.
- Make `lethality_levers` a lint warning ("reserved until P2.5; nothing reads it") when a pack declares any.
- Apply sections A and C to `docs/ARCHITECTURE.md`, and add the decision to DECISIONS.

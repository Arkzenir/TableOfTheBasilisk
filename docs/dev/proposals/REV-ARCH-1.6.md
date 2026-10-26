# Draft revision: ARCHITECTURE 1.6 (§2.3 pack schema, §5.7 event schema)

**Status:** draft for owner review. Nothing below has been applied to `docs/ARCHITECTURE.md`.
**Why:** Phase 0 is built (T0.2 to T0.23). Two design sections describe it as it was planned, not as it is: the abbreviated pack schema (§2.3) and the abbreviated event list (§5.7). D-009 deferred §5.7 to "the next design revision"; this is that revision. `docs/dev/EVENTS.md` stays the exact registry (a test enforces it). These sections stay summaries, but true ones.
**Owner direction:** the flagged Gate P0 item 8 and the hook return shape (D-033) are accepted for now and will be re-audited when the P0 architecture is finalised. Point C3 below records the hook shape so the re-audit has it in writing.

Points marked **⚑ Decide** describe design text that the build does not implement. Each needs a call: change the doc to match the build, or keep the design and add a task.

---

## A. Header: version and revision note

**Current:** `**Version:** 1.5 (revised design freeze for v1)`
**Proposed:** `**Version:** 1.6 (revised design freeze for v1)`, plus:

> **Revision notes (1.6):**
> - §2.3 (pack schema) and §5.7 (event schema) now describe what Phase 0 built (T0.2 to T0.23). `docs/dev/EVENTS.md` remains the exact event registry.
> - Mechanical state changes are logged as one `effect_applied` event that names its primitive (D-003), not as one event type per primitive.

---

## B. §5.7 Event schema: the `# system`, `# mechanics`, and `# world` groups

**Current** (system, mechanics, and world groups):
```
  # system
  pack_pinned, kernel_pinned, axis_dormant
  determinism_settings_recorded, determinism_change_requested, determinism_changed
  ...
  # mechanics
  roll_made, roll_peeked, roll_fudged
  deck_shuffled, card_drawn, table_rolled
  procedure_resolved, gm_ruling_requested, gm_ruling_filled
  effect_applied, condition_added, condition_removed, track_marked
  currency_earned, currency_spent
  token_moved, action_committed
  clock_advanced
  # world
  canon_written, canon_superseded, fact_revealed, entity_spawned
  scene_set, scene_closed
```

**Proposed:**
```
  # system
  campaign_started            # pins pack_hash, kernel_version, seed commitment (§2.9)
  campaign_forked
  axis_dormant                # P2.5 (traits)
  determinism_settings_recorded, determinism_change_requested, determinism_changed
  session_started, session_ended
  ...
  # mechanics
  roll_made                   # dice, weighted draws, and hook draws; every one on the roll counter
  roll_peeked, roll_fudged, peek_settled
  deck_shuffled, card_drawn, card_discarded, table_rolled
  procedure_resolved, gm_resolution, gm_ruling_requested, gm_ruling_filled
  effect_applied              # every primitive (§2.6), naming it and carrying the exact changes
  action_committed, judgement_input
  hook_ran                    # §2.7
  encounter_started, round_started, turn_started, economy_spent, encounter_ended
  clock_created, clock_stage_reached, clock_paused
  time_advanced
  chargen_started, character_created
  # world
  canon_written, canon_superseded, fact_revealed
  entity_spawned
  scene_set                   # carries the spatial layout when the scene has one
  visibility_set, move_provoked
  rules_queried
```

The `# table`, `# audience`, `# meta`, and `# production` groups are unchanged; they belong to P1 to P5. `judgement_input` moves from `# meta` to `# mechanics`, since it is emitted by the kernel.

**⚑ Decide (B1):** `scene_closed` is in the design but not built. A scene closes when the next `scene_set` or `session_ended` arrives, and the events that close it (condition expiry, `encounter_ended`) are logged then. Proposed: drop `scene_closed`. Or keep it, and add a task to emit it explicitly.

---

## C. §2.3 What a system pack declares

**Proposed replacement for the schema block.** Additions are marked `# new`; changed lines are marked `# was: …`.

```
system_pack:
  meta:
    id, version, extends            # extends: pack_id@version | null
    name, license, attribution_text
    excluded_terms: [{ term, aliases }]   # names the licence does not cover (§1.2)
    kernel_compat                   # kernel version range the pack is tested against

  rules_text:
    mode: inline | sectioned        # §2.11
    full_text                       # inline: the whole text, layer 2 of every context
    digest                          # sectioned: always-loaded summary, layer 2
    sections: [{ id, title, aliases, body, refs, parent }]
    max_section_tokens

  vocabulary:                       # display terms; kernel IDs never change
    { <id>: { label, short, plural } }

  randomizers:
    dice_grammar: { operators: [sum, keep, explode, count, fate, step], max_dice, max_sides,
                    step_sizes }                         # new: legal step-die sizes
    decks:   [{ id, cards: [{ id, label } | id], reshuffle_rule, players_draw }]   # was: cards, reshuffle_rule
    tables:  [{ id, roll, entries: [{ range, text }] }]

  entity_model:
    stats:      [{ id, range, default, private }]     # new: private (sheet views, §7.1)
    derived:    [{ id, expr }]
    resources:  [{ id, min, max, on_zero }]           # was: max_expr, regain, spend
    tracks:     [{ id, boxes, on_fill }]
    conditions: [{ id, modifier, duration: scene | session | until_removed }]   # was: modifiers, duration, stacking, exit
    tags:       [id]
    inventory:  { model }                             # see ⚑ C2

  resolution:
    outcome_scales:     [{ id, ordered: [worst … best] }]
    procedures:         [{ id, kind, inputs, steps }]     # §2.5
      # steps: modifiers {from}; roll; hook (resolution.step, §2.7); interpret, one of:
      #   bands | margins (degrees of success) + compare >= | <= | successes | compare >= | <=
      #   against: opposed + ties: actor | target | automatic
    difficulty_ladders: [{ id, rungs: [{ id, label, value }], range }]
    situational_tags:   [{ id, value, derive?: expr }]
    tags_cap_per_roll, free_modifier_max                    # new: strict/standard bounds (§2.13)

  actions:
    [{ id, trigger: declared | fiction | reaction, target: none | entity | zone,
       modes: [free, encounter], requires, eligibility, stat, cost: { currency, amount | amounts, range },
       procedure, difficulty: { ladder } | { derived },
       slot, points,                                         # new: action economy (§2.4)
       outcome_effects, annotation_categories }]

  turn_structure:
    encounter: { order: initiative | sides | handoff | fixed | deck | spotlight,
                 initiative?: { roll, each_round }, first?: players | gm,     # new
                 economy: none | slots | points, slots?: [{ id, count }], points?: n }

  time:                                                      # new (§2.2 Clocks and time)
    units: [{ id, label, per }]                              # smallest first
    between_sessions: { unit, amount }

  gm:
    gm_rolls: bool
    fudgeable_procedures: [procedure_id]
    lethality_levers: [{ id, effect }]
    meta_currencies: [{ id, holder: gm | party | each_player, start, max }]   # was: earn, spend
    consequence_tables: [{ id, entries: [{ id, label, effects, weight, severity }] }]

  progression:  { model: xp | milestone | marks | use, ... }  # see ⚑ C4
  chargen:      { steps: [{ id, kind: roll | choice | assign | table,
                            targets, roll, options, values, table, unique_per_table }] }   # was: roll | assign | choice, source

  spatial:
    backends: [zone_graph | range_bands | square_grid] | none
    bands: [{ id, label }]                     # closest first (range_bands)
    terrain: [{ id }], cover: [{ id }]         # region values (zone_graph)
    movement: { steps_per_move }               # was: movement
    provokes: { when }                         # was: provokes
    tactical_profile: { categories: [{ id, order: 1 | 2 }], weights, factors, annotation_templates }

  presentation:
    nameplate_resources: [id]
    sheet: { public: [id] }                    # new: what party summaries show (§7.1)
    assertion_terms: { phrase → resource|track id }
    rounding: floor | ceil | half_up
    rule_cards: { <action|procedure|condition|currency|tag id>: { title, summary, category, icon_id } }

  hooks:    [{ point, name, version }]         # source in hooks/<name>.py beside the pack (§2.7)
  # golden fixtures live in fixtures/golden.yaml by convention (§2.10)   # was: fixtures: [path]
```

**⚑ Decide (C1): conditions `stacking` and `exit`.** The build has no stacking rule: a condition is held or not. Its exit is its `duration` or an effect that removes it, and lint refuses a condition with no exit (§2.10). Proposed: the schema above, with no `stacking` or `exit` fields. Or keep stacking, and add a task.

**⚑ Decide (C2): `inventory: { model: slots | weight | abstract, limit_expr }`.** Inventory is a plain list of item ids, and `model` is read nowhere. Proposed: write `inventory: { model: abstract }  # v1: a list of item ids; slots and weight are v2`, and add the slot and weight models to §11.4. Or build them in Phase 0, as a new task.

**⚑ Decide (C3): `harm: { targets, on_zero, on_fill }`.** No separate `harm` section exists. Harm is composed from resources and tracks with their own `on_zero` / `on_fill` triggers (and, since T0.23, triggered procedures). Proposed: delete the `harm` line and add a sentence to §2.3: "Harm is composed from resources, tracks, and their triggers; it has no section of its own." Separately, for the re-audit you asked for: §2.7's hook shape `(state_view, params, rng) → [events]` was implemented as point-specific results (D-033).

**⚑ Decide (C4): `progression`.** It is declared in §2.3 and listed in §2.4 (XP, milestones, marks, use), but no BUILD_PLAN step builds it and the kernel ignores it. Proposed: leave §2.3 as it is and add progression to BUILD_PLAN as a P3 step, since campaigns need it, or as a P0 task if you want Phase 0 to include it.

---

## D. After approval (not design docs)

- Apply A to C to `docs/ARCHITECTURE.md` with the 1.6 revision note.
- Update D-009 ("§5.7 updated in revision 1.6"), and record each ⚑ answer in DECISIONS.
- Any "keep the design" answer becomes a new task in `docs/dev/TASKS.md`.

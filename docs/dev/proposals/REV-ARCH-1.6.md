# Draft revision: ARCHITECTURE 1.6 (§2.3 pack schema, §5.7 event schema)

**Status:** approved by the owner and applied to `docs/ARCHITECTURE.md` on 2026-10-26 (D-042). Kept as the record of the review.
**Owner answers (2026-10-26, D-036, D-037):** B1 keep `scene_closed` (built, T0.24); C1 keep `stacking` (built as intensity levels, T0.25); C2 add the `weight` inventory model, no `slots` (built, T0.26); C3 harm is a declaration of targets only (built, T0.28); C4 progression is BUILD_PLAN P0.15 (built, T0.27). Sections B and C below now match the build. What is left is the owner's review of the text itself.
**Why:** Phase 0 is built (T0.2 to T0.28). Two design sections describe it as it was planned, not as it is: the abbreviated pack schema (§2.3) and the abbreviated event list (§5.7). D-009 deferred §5.7 to "the next design revision"; this is that revision. `docs/dev/EVENTS.md` stays the exact registry (a test enforces it). These sections stay summaries, but true ones.
**Owner direction:** the flagged Gate P0 item 8 and the hook return shape (D-033) are accepted for now and will be re-audited when the P0 architecture is finalised. Point C3 below records the hook shape so the re-audit has it in writing.

The former **⚑ Decide** points are now **✔ Decided** notes, each naming the owner's answer and the task that built it.

---

## A. Header: version and revision note

**Current:** `**Version:** 1.5 (revised design freeze for v1)`
**Proposed:** `**Version:** 1.6 (revised design freeze for v1)`, plus:

> **Revision notes (1.6):**
> - §2.3 (pack schema) and §5.7 (event schema) now describe what Phase 0 built (T0.2 to T0.28), including the owner's decisions of 2026-10-26: the `scene_closed` marker, condition stacking by intensity, weight inventory, harm as a declaration of targets, and progression (BUILD_PLAN P0.15). `docs/dev/EVENTS.md` remains the exact event registry.
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
  progress_awarded, advance_taken   # §2.4 progression (BUILD_PLAN P0.15)
  # world
  canon_written, canon_superseded, fact_revealed
  entity_spawned
  scene_set                   # carries the spatial layout when the scene has one
  scene_closed                # after the events that close the scene, before the next scene_set or session_ended
  visibility_set, move_provoked
  rules_queried
```

The `# table`, `# audience`, `# meta`, and `# production` groups are unchanged; they belong to P1 to P5. `judgement_input` moves from `# meta` to `# mechanics`, since it is emitted by the kernel.

**✔ Decided (B1):** keep `scene_closed` as a marker (owner, D-036). Built in T0.24 (D-038): `{scene_id, index, reason: next_scene | session_ended}`, logged after `encounter_ended` and condition expiry.

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
    conditions: [{ id, modifier, duration: scene | session | until_removed,
                   stacking: none | intensity, max_level }]   # was: modifiers, duration, stacking, exit
    tags:       [id]
    inventory:  { model: abstract | weight, limit_expr }  # was: slots | weight | abstract
    items:      [{ id, label, weight }]               # new: the weight model's catalogue
    harm:       { targets: [resource or track id] }   # was: targets, on_zero, on_fill

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

  progression:                                               # §2.4, BUILD_PLAN P0.15
    model: xp | marks | milestone | use
    awards:     [{ when: session_end | outcome, amount, outcomes, procedures }]   # xp, marks
    thresholds: [points]                                     # xp, marks: one advance per threshold
    use:        { threshold }                                # use: uses of a stat before it rises
    advances:   [{ id, label, stats: { stat: delta }, tags, requires, once }]
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

**✔ Decided (C1): conditions `stacking`.** Keep it (owner, D-036). Built in T0.25 (D-039) as `stacking: intensity` with `max_level` (2 to 10): applying a held condition raises its level, its modifier scales with the level, and `remove_condition` may lower it by `levels`. `exit` is not a field: a condition's exit is its `duration` or an effect that removes it, and lint refuses a condition with neither (§2.10).

**✔ Decided (C2): inventory.** `abstract` (any item id, no limit) or `weight` (only catalogue items, carried weight against `limit_expr`); no `slots` for now (owner, D-036). Built in T0.26 (D-040). Proposed §11.4 line: "Slot-based inventory."

**✔ Decided (C3): `harm`.** A declaration of which resources and tracks count as harm, targets only, so later systems (lethality, metrics, the overlay, fudging's "unearned death") can read it; `on_zero` and `on_fill` stay on the resources and tracks themselves (owner, D-037). Built in T0.28 with `harm_state(entity)`. Proposed §2.3 sentence: "Harm names its targets; the mechanics stay on each resource and track." Separately, for the re-audit you asked for: §2.7's hook shape `(state_view, params, rng) → [events]` was implemented as point-specific results (D-033).

**✔ Decided (C4): `progression`.** A Phase 0 kernel mechanism, BUILD_PLAN P0.15 with its own Gate P0 line (owner, D-036; BUILD_PLAN 1.5). Built in T0.27 (D-041). The `award` key is `when`, not `on`, because YAML reads a bare `on` as a boolean. Arc-boundary milestones wait for P3.6.

---

## D. After approval (not design docs)

- Apply A to C to `docs/ARCHITECTURE.md` with the 1.6 revision note.
- Update D-009 ("§5.7 updated in revision 1.6"). The answers are already recorded (D-036 to D-041) and built (T0.24 to T0.28).

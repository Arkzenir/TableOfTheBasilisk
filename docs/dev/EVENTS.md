# Event registry

The code-level list of event types (`EVENT_TYPES` in `src/basilisk/kernel/engine.py`). `tests/test_docs.py` fails if this table and the code disagree. ARCHITECTURE §5.7 is the design-level summary; this file is exact.

**Folds** = changes state in `apply_event`. **Passive** = recorded for audit, cards, and metrics; does not change state.

| Type | Kind | Emitted by | Payload |
|---|---|---|---|
| `campaign_started` | folds | `Engine.start_campaign` | `campaign_id, pack_id, pack_hash, kernel_version, seed_commitment, seats, gm_lethality` |
| `determinism_settings_recorded` | folds | `Engine.start_campaign` | `settings` (fully expanded) |
| `determinism_change_requested` | folds | `request_determinism_change` | `from, to` |
| `determinism_changed` | folds | scene or session boundary | `from, to, request_seq, scene_index` |
| `session_started` | folds | `start_session` | `number` |
| `session_ended` | folds | `end_session` | `number` |
| `scene_set` | folds | `set_scene` | `scene_id, index, flags, encounter`, plus `spatial` only for a spatial scene: `{mode: zone, regions[{id, label, adjacency, terrain, elevation, cover}]}` (adjacency normalised: undirected, sorted) or `{mode: bands, bands, participants, ranges{"a\|b": band}}` (every pair present; unset pairs start at the furthest band) |
| `roll_made` | folds | any roll or weighted draw | `counter, purpose, expression, total, groups, variables` (+ `weights` for draws) |
| `effect_applied` | folds | every effect primitive; also condition expiry (`params.reason: duration`) and GM placement (`move`, `params.reason: placement`). A `move` in a band scene changes `scene.spatial.ranges` (and, for a newcomer, `participants`) instead of the entity's `zone` | `primitive, target, params, changes[{path, value \| delete}]` |
| `character_created` | folds | `create_character` | `entity, unique_choices, choices` |
| `entity_spawned` | folds | `spawn_entity` | `entity` |
| `clock_created` | folds | `create_clock` | `clock_id, label, total, visible` |
| `action_committed` | folds | `commit_action` | `entity, by, action, target, spend, trigger, eligible` |
| `gm_ruling_requested` | folds | `request_gm_ruling` effect | `slot, table, mode, ids, entries` |
| `gm_ruling_filled` | folds | engine draw or `fill_ruling` | `slot, entry, by` |
| `canon_written` | folds | `write_canon`, `supersede_canon` | `record` (full, engine-assigned `id`; the reducer sets `created_at` to the event's seq), `flags[{name, near, record}]` (near-collisions), `supersedes` (only from `supersede_canon`) |
| `canon_superseded` | folds | `supersede_canon` | `old, new` (sets `superseded_by` on `old`) |
| `fact_revealed` | folds | `reveal` | `id, from` (sets `knowledge` to `revealed`) |
| `visibility_set` | folds | `set_visibility` | `entity, visible_to` (sorted seat ids, or `null` to make the entity visible to every seat again); reset by the next `scene_set` |
| `encounter_started` | folds | `start_encounter` | `order, economy, participants` (creates `state.encounter`) |
| `round_started` | folds | `start_encounter`, `end_turn` at the end of a round, `next_round` | `round, sequence` (the round's order: initiative rolls or deck draws precede it as `roll_made`), `budgets` (spotlight: every participant's refreshed budget) |
| `turn_started` | folds | `start_encounter`, `end_turn` | `round, index, actor` (entity id, or side `players` / `gm`), `budgets` (refreshed for whoever is in play) |
| `economy_spent` | folds | `commit_action` during an encounter | `entity, key` (slot id or `points`), `amount, remaining` |
| `encounter_ended` | folds | `end_encounter`; also `set_scene` and `end_session` while an encounter runs | `round` (removes `state.encounter`) |
| `deck_shuffled` | folds | first draw from a deck, `reshuffle_deck`, reshuffle rules (`every_draw`, `when_empty`, `scene`, `session`) | `deck, counter, cards` (shuffled, in pack order, hands excluded), `order` (the new pile, top first), `reason`; sets `roll_counter` to `counter + 1` (creates `state.decks` on first use) |
| `card_drawn` | folds | `draw_card` | `deck, card, by, to` (a holder's hand, or `null` for face up onto the discards) |
| `card_discarded` | folds | `discard_card` | `deck, card, holder` |
| `chargen_started` | passive | `create_character` | `agent, entity` |
| `judgement_input` | passive | any model-chosen mechanical input | `seat, control, setting, choice, options` |
| `procedure_resolved` | passive | resolution runner | `procedure, entity, scale, outcome, rank, ranks, total, difficulty, modifiers, roll_seq, direct` |
| `table_rolled` | passive | chargen table step | `table, value, text` |
| `gm_resolution` | passive | `resolve_unmodelled` | `entity, procedure, stat, direct_outcome` |
| `campaign_forked` | passive | `EventStore.fork` | `source_campaign, source_seq, source_hash` |

## Adding an event type

1. Emit it through `Engine._emit` (or the store, for orchestrator-level events).
2. Handle it in `apply_event`: either fold it, or add it to `_PASSIVE`.
3. Add it to `EVENT_TYPES` and to this table.
4. If logs that already exist would fold differently, bump `KERNEL_VERSION`.

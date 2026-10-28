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
| `scene_closed` | folds | `set_scene` (closing the previous scene), `end_session` | `scene_id, index, reason` (`next_scene` or `session_ended`); logged after the events that close the scene (encounter end, condition expiry) and before the next `scene_set` or `session_ended`; sets `scene.closed` |
| `scene_set` | folds | `set_scene` | `scene_id, index, flags, encounter`, plus `spatial` only for a spatial scene: `{mode: zone, regions[{id, label, adjacency, terrain, elevation, cover}]}` (adjacency normalised: undirected, sorted) or `{mode: bands, bands, participants, ranges{"a\|b": band}}` (every pair present; unset pairs start at the furthest band) |
| `roll_made` | folds | any roll, weighted draw, or hook draw | `counter, purpose, expression, total, groups, variables` (+ `weights` for weighted draws; `expression: hook` with `draws[[lo, hi, value]]` for a hook's draws, one sub-index each) |
| `effect_applied` | folds | every effect primitive (`trigger_procedure` logs one with no changes, then the procedure's events and its outcome's effects follow, caused by it); also condition expiry (`params.reason: duration`), off-air clock advancement (`advance_clock`, `params.reason: off_air`, at `start_session`), and GM placement (`move`, `params.reason: placement`). A `move` in a band scene changes `scene.spatial.ranges` (and, for a newcomer, `participants`) instead of the entity's `zone` | `primitive, target, params, changes[{path, value \| delete}]` |
| `character_created` | folds | `create_character` | `entity, unique_choices, choices` |
| `entity_spawned` | folds | `spawn_entity` | `entity` |
| `clock_created` | folds | `create_clock` | `clock_id, label, total, visible`, plus `schedule{every, amount, unit?}, stages[{at, record}], created_session` only when the clock has a schedule or stages, and `created_elapsed` when the schedule runs on in-world time |
| `action_committed` | folds | `commit_action` | `entity, by, action, target, spend, trigger, eligible`, plus `declared` (the move the player declared) only when the GM substituted another fiction-triggered move (`gm.substitute`, followed by a GM `judgement_input` with control `fiction_triggers`) |
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
| `roll_peeked` | folds | `commit_action` / `resolve_unmodelled` with the GM's `peek` | `slot, procedure, entity, roll_seq, expression, variables, total, outcome, rank, ranks, party_rank, modifiers, difficulty, cause, continuation` (pauses the action: creates `state.fudging.pending`, counts toward the session cap) |
| `roll_fudged` | folds | `peek_roll reroll` | `slot, from_roll_seq, to_roll_seq, from_total, to_total, from_rank, to_rank` (the reroll itself is the `roll_made` at `to_roll_seq`) |
| `peek_settled` | folds | `peek_roll` | `slot, decision` (`keep` / `reroll`), `roll_seq, total` (the final roll); clears the pending peek, then `procedure_resolved` and the action's effects follow |
| `clock_stage_reached` | folds | a clock's fill crossing a stage mark (`advance_clock`, off-air advancement, effects) | `clock, at, record` (the canon id just written by the preceding `canon_written`) |
| `clock_paused` | folds | `pause_clock` | `clock, paused` (a paused clock skips off-air advancement) |
| `time_advanced` | folds | `advance_time`; `start_session` when the pack sets `time.between_sessions` (`reason: off_air`) | `unit, amount, from, to` (elapsed counts of the smallest unit; creates `state.time`); time-scheduled clocks then advance with `effect_applied` (`reason: time`) |
| `progress_awarded` | folds | `end_session` (a `session_end` award), a player character's `procedure_resolved` (an `outcome` award, or a stat use under the `use` model), `award_milestone` | `entity, amount, reason` (`session_end`, `outcome:<id>`, `use:<stat>`, `milestone`), `changes[{path, value}]` setting `entities.<id>.progress` `{points, pending, advances, uses}` (created by the first one) |
| `advance_taken` | folds | `take_advance` (followed by its `judgement_input`); a stat use reaching `use.threshold` (`automatic: true`, option `use:<stat>`) | `entity, option, automatic, changes[{path, value}]`: the stat changes, any tags, and the new `progress` |
| `chargen_started` | passive | `create_character` | `agent, entity` |
| `judgement_input` | passive | any model-chosen mechanical input; and every GM call (`@gm_call`, D-044), after the call's own events and caused by the first of them | `seat, control, setting, choice, options`; for a GM call, `control` is the command's name, `setting` is null, `choice` its arguments (null ones omitted), and `options` the list it was chosen from where the engine has one, else null |
| `procedure_resolved` | passive | resolution runner | `procedure, entity, scale, outcome, rank, ranks, total, difficulty, modifiers, roll_seq, direct`; for an opposed check `difficulty` is `{value, origin: opposed, rung: null, roll_seq, stat}`, naming the other side's roll |
| `table_rolled` | passive | chargen table step | `table, value, text` |
| `gm_resolution` | passive | `resolve_unmodelled` | `entity, procedure, stat, direct_outcome` |
| `rules_queried` | passive | `query_rules` | `seat, query, via` (`id`, `ref`, `alias`, `partial`, or `null` for a miss), `sections` (ids returned, never their text), `suggestions` (titles, on a miss) |
| `move_provoked` | passive | a `move` effect that leaves a threat's reach, when the pack declares `spatial.provokes` | `mover, by` (the provoking entities), `to`; a reaction may answer it (§2.4) |
| `hook_ran` | passive | every pack hook invocation (`resolution.step`, `sheet.validate` at chargen) | `hook, point, result` (what the hook returned, after its double run agreed), `roll_seq` (its draws, if any) |
| `campaign_forked` | passive | `EventStore.fork` | `source_campaign, source_seq, source_hash` |

## Adding an event type

1. Emit it through `Engine._emit` (or the store, for orchestrator-level events).
2. Handle it in `apply_event`: either fold it, or add it to `_PASSIVE`.
3. Add it to `EVENT_TYPES` and to this table.
4. If logs that already exist would fold differently, bump `KERNEL_VERSION`.

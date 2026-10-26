# Decisions

Implementation choices the design docs didn't dictate. Append new entries at the bottom; never edit an accepted entry. Supersede it with a new one instead.

Template:

```
## D-NNN Title
- Date: YYYY-MM-DD · Status: accepted | superseded by D-NNN
- Context: what forced a choice
- Decision: what we chose
- Consequences: what this commits us to; what to revisit
- Sources: URLs consulted (with access date) when external facts were involved
```

---

## D-001 Python and SQLite for the kernel and harness
- Date: 2026-10-15 · Status: accepted
- Context: a solo developer, fast iteration, and good LLM SDK coverage. The event log must be durable and portable.
- Decision: Python 3.11+, standard library first, PyYAML as the only runtime dependency. Event store on SQLite in WAL mode, with append-only triggers.
- Consequences: integer-only arithmetic is enforced by `canonical()`. Performance is ample for one table; revisit only if soak runs show otherwise.

## D-002 HMAC-SHA256 randomizer instead of Python `random`
- Date: 2026-10-15 · Status: accepted
- Context: rolls must be identical on any machine and any Python version, and verifiable after the seed is published (§5.5).
- Decision: each integer is HMAC-SHA256(seed, "counter:sub:attempt") with rejection sampling. The log stores a commitment to the seed, never the seed itself.
- Consequences: `tob verify --seed` can re-derive every roll. The seed must be kept secret until the campaign ends.

## D-003 `effect_applied` events carry exact state changes
- Date: 2026-10-15 · Status: accepted
- Context: replay must not depend on re-running rules, which may later change.
- Decision: the engine computes changes; the reducer only applies `{path, value|delete}`.
- Consequences: the reducer is pack-agnostic and trivially replayable. Event payloads are slightly larger.

## D-004 Engine commands are atomic
- Date: 2026-10-15 · Status: accepted
- Context: a command can fail midway (bad GM input, an effect precondition).
- Decision: the `@atomic` decorator wraps each command in an SQLite transaction plus an in-memory state restore.
- Consequences: rejected commands leave no events. Harnesses can attempt and recover freely.

## D-005 Demo packs are kernel fixtures, not the broadcast game
- Date: 2026-10-15 · Status: accepted
- Decision: `lanternlight` (roll-over) and `tidewrack` (banded) are tiny original CC0 games that exist to prove two-family support. The broadcast system is T0.1.

## D-006 Hooks refused until the sandbox exists
- Date: 2026-10-15 · Status: accepted
- Decision: `HOOK_REGISTRY` is empty, so any pack declaring a hook fails to load. This satisfies §2.7's refusal requirement until T0.12.

## D-007 Determinism defaults: players strict, GM standard
- Date: 2026-10-15 · Status: accepted
- Decision: per ARCHITECTURE §2.13.2 (v1.3). Settings are stored fully expanded in the log, so code defaults can change without affecting replay.

## D-008 AGENTS.md is canonical; tool-specific files import it
- Date: 2026-10-15 · Status: accepted
- Context: the project is developed with a desktop coding agent (currently Claude Code) and must stay agent-agnostic.
- Decision: `AGENTS.md` holds all agent instructions. `CLAUDE.md` imports it with `@AGENTS.md`, because Claude Code reads CLAUDE.md, not AGENTS.md. `.claude/settings.json` enforces part of the approval list for Claude Code. Git hooks enforce the gate for every agent and human.
- Sources: Claude Code memory docs, https://code.claude.com/docs/en/memory (accessed 2026-10-15).

## D-009 `docs/dev/EVENTS.md` is the exact event registry
- Date: 2026-10-15 · Status: accepted
- Context: ARCHITECTURE §5.7 is an abbreviated design list; the code has more types (e.g. `chargen_started`, `gm_resolution`).
- Decision: EVENTS.md mirrors `EVENT_TYPES` exactly, with a test enforcing it. ARCHITECTURE §5.7 stays a summary and is updated at the next design revision. Updated in revision 1.6 (2026-10-26, D-042).

## D-010 Canon store: records in state, indexes derived per scope
- Date: 2026-10-16 · Status: accepted
- Context: T0.2 (§1.3, §6.2, §6.5). The docs fix the record shape and the rules but not the index mechanics.
- Decision:
  - Records live under `state["canon"]`, keyed by id. The key is created by the first canon event, so logs written before the store existed fold to the same state hash. No `KERNEL_VERSION` bump.
  - `CanonIndex` (alias table, word table, relation graph) is rebuilt from state per scope: `gm`, or `players`. A seat id maps to its role's scope. The player index is built from a record set with every `secret` removed. Player-visible records also lose `discovery_paths`, lose `depends_on` ids the scope cannot see, and show the first visible successor as `superseded_by`. If every successor is secret, they show none, because the table still holds the old belief.
  - Indexes are cached on the engine by a fingerprint of `(id, superseded_by, knowledge)`, the only mutable fields. `atomic` clears the cache on rollback, because a rolled-back id and seq can be reused.
  - Name keys: lowercase words, possessives and punctuation stripped, plus a second key without filler words (`the`, `that`, `a`, …). Resolution order: exact id, then alias key, then partial (every query word appears in the record's names). An exact key clash with any current record, secrets included, is rejected. A difflib ratio ≥ 0.85 is flagged in the `canon_written` payload.
  - `knowledge` and `origin` are required, with no defaults. A `secret` needs at least one discovery path (§7.6.2 axioms 3 and 10). Discovery paths may name canon records or entities.
  - Scene bundle: breadth-first, 2 hops over `depends_on` and `discovery_paths` edges (both directions), with superseded ids redirected to their successors.
  - `supersede_canon` is an engine command but not a model tool. Corrections belong to the post-session pass (§7.6.3), which the orchestrator will drive.
  - `atomic`, `EngineError`, and `_suggest` moved to `kernel/command.py` so that command mixins can use them. `engine.py` re-exports them, and it was already past ~800 lines.
- Consequences: player-scoped queries cannot reach a secret through any phrasing. The per-character knowledge tier (§6.2) is not modelled yet: every player seat shares one table-knowledge index.

## D-011 Shared player canon; personal, fallible copies in notes; no mid-session retcons
- Date: 2026-10-16 · Status: accepted (owner, answering HANDOFF questions 4 and 5)
- Decision:
  - **Character knowledge.** Every player seat queries the same canon (the `players` index, secrets excluded). The kernel has no per-character canon scope. Each agent keeps its own copy of what it learned in its notes (§6.4). Those copies are free text and never validated or corrected against canon, so an agent can recall things incorrectly. Per-agent recaps add controlled error through `memory_fidelity` (§6.3). The validation pass (§1.3.3) checks GM narration, not a player's misremembering.
  - **No retcons mid-session.** `supersede_canon` is refused between `session_started` and `session_ended`. During play the GM may still `write_canon` new records and `reveal` secrets. Supersede stays allowed before the first session (Session 0 prep) and between sessions (the post-session pass).
  - The open/closed check reads the event log instead of a folded flag. Adding a flag to state would change the folded state of every existing log and force a `KERNEL_VERSION` bump. The check scans the log, which is acceptable because supersede is rare and off-air.
- Consequences: ARCHITECTURE §6.2 was revised to match this decision (version 1.4, approved by the owner on 2026-10-16). Note tools are task T1.10.


## D-012 Broadcast system: SRD 5.1, sectioned rules text in v1
- Date: 2026-10-16 · Status: accepted (owner). ARCHITECTURE 1.5, BUILD_PLAN 1.4.
- Context: the owner chose the D&D 5e SRD (2014 rules) because more viewers know them. The design said v1 ships one inline rules-light pack, with sectioned text deferred to v2. §1.2 does not list the OGL 1.0a.
- Decision:
  - The source is the **SRD 5.1 under CC-BY 4.0** (D-015). The required notice is copied verbatim from the source. The stream uses no D&D trademarks.
  - **Sectioned rules text is v1** (§2.11). `query_rules` resolves by key: section ID, then catalogue ref, then alias, then partial match, with key normalisation shared with canon. Vector search over rules stays in v2.
  - **Rules handling is system-agnostic by construction.** The kernel has no section taxonomy, and sections are opaque text. Structure (`parent`, `refs`) is pack data. Inline packs may declare sections too.
  - **The broadcast pack is written as late as possible** (BUILD_PLAN P4.0, gating Phase 4). Gate P0 and Phases 1–3 develop against `lanternlight` and `tidewrack`, plus a data-only sectioned variant. The owner supplies the source document at P4.0.
  - No grid in v1. SRD distances map to range bands. `SquareGrid` stays in v2, to be added when appropriate.
- Consequences: new tasks T0.14 (sectioned rules text) and T0.15 (sectioned fixture variant). T0.1 is deferred to P4.0.

## D-013 First provider adapter: Anthropic (Claude)
- Date: 2026-10-16 · Status: accepted (owner, answering HANDOFF question 2)
- Decision: T1.5 targets the Anthropic Messages API. The owner will create a dedicated account and supply its API key through an environment variable when live work begins. No key is needed before then. All tests stay offline, using cassettes and the mock adapter.
- Note: check the API shape, tool-call format, and model names against Anthropic's current docs when T1.5 starts, and record the URL and date here.

## D-014 Finish Track 0 before Track 1
- Date: 2026-10-16 · Status: accepted (owner, answering HANDOFF question 3)
- Decision: complete the Track 0 tasks (Gate P0) before starting any Track 1 task, including the parallel-safe ones.

## D-015 SRD 5.1 licence: CC-BY 4.0, not the OGL 1.0a
- Date: 2026-10-16 · Status: accepted (owner chose CC-BY 4.0 after the research below). ARCHITECTURE §1.2 and BUILD_PLAN P4.0 and P0.14 updated.
- Context: the owner noted that SRD 5.1 is dual-released: under the OGL 1.0a (since 2016) and under CC-BY 4.0 (since January 2023), with the same text. A user may pick either licence. The owner thinks the OGL may suit the project better. The design text first assumed CC-BY only.
- What each requires, to verify against the current source and licences at P4.0:
  - **CC-BY 4.0:** an attribution statement, and nothing else. It is irrevocable and is already on the §1.2 permitted list.
  - **OGL 1.0a:** the full licence text distributed with the work, a Section 15 copyright notice, an explicit designation of Open Game Content and Product Identity, and no use of trademarks or claims of compatibility beyond what the licence allows. Content derived from Open Game Content becomes Open Game Content itself, a share-alike effect that §1.2 already flags as a caveat for generated content. Choosing it adds the OGL 1.0a to the §1.2 permitted list in an ARCHITECTURE revision note.
- Until decided: the kernel, packs, and harness are unaffected. `meta.license` and `meta.attribution_text` already hold either licence. Not legal advice.
- **Research (2026-10-16, not legal advice). Recommendation: CC-BY 4.0.**
  - CC-BY 4.0 permits this use. "Share" explicitly includes public performance. Adapting the text and commercial use (donations) are allowed. Attribution may be given "in any reasonable manner based on the medium": the overlay about panel plus the VOD description, each with a link to the SRD and the licence, noting that the text was adapted. A breach is cured automatically if fixed within 30 days of discovery. The licence is irrevocable, and the licensor gives no endorsement, so the stream must not imply any WotC connection.
  - The OGL 1.0a fits a live AI stream poorly. Its "Distribute" includes broadcast and public display. That triggers its terms on every stream: a copy of the licence "with every copy" (§10), clear identification of which portions are Open Game Content (§8), which is impractical for improvised narration, and the §6 and §15 notices. §7 also forbids indicating compatibility with trademarks, whereas the CC release's notice explicitly allows "compatible with fifth edition." On top of that come the 2023 deauthorization episode and OGL share-alike for derived content.
  - **The main real risk is the same under either licence:** non-SRD WotC IP. Trademarks are not licensed (CC-BY §2(b)), and much of D&D's IP is absent from the SRD, for example named settings, beholders, and mind flayers. LLMs will produce these names from memory. Mitigation: a pack-supplied list of excluded terms, checked by the validation pass (§1.3.3) before TTS, and canon seeded only from the SRD and original material. Do not rely on WotC's Fan Content Policy as a fallback, because WotC can withdraw it.
  - Minor: CC 4.0 forbids applying effective technological measures to the material (§2(a)(5)), and CC's wiki notes that platforms with built-in DRM are an unsettled area. The risk is low, because the SRD remains freely available at its source, but a lawyer should confirm it as part of the §11.3 review.
  - Separate issues: purely AI-generated output may get little copyright protection in the US (Copyright Office, AI report Part 2, January 2025), which affects control over clips, not compliance. Provider terms for public performance are already listed in §11.3.
  - Sources: https://creativecommons.org/licenses/by/4.0/legalcode.en · https://creativecommons.org/using-cc-licensed-works-for-ai-training-2/ · https://wiki.creativecommons.org/wiki/4.0/Technical_protection_measures · https://rpgbot.net/dnd35/ogl/ (OGL 1.0a text) · https://slyflourish.com/what_5e_in_cc_means_to_you.html · https://company.wizards.com/en/legal/fancontentpolicy · https://copyright.gov/newsnet/2025/1060.html

## D-016 ZoneGraph: spatial scenes are opt-in per scene; visibility by seat
- Date: 2026-10-16 · Status: accepted (T0.3; §1.4, §8.2). The docs fix the interface and the scene schema but not these mechanics.
- Decision:
  - **A scene is spatial only when `set_scene` is given `regions`.** Its layout goes into the `scene_set` payload under `spatial` and into state under `state["scene"]["spatial"]`, and only then. Logs written before this change fold to the same state hash, so there is no `KERNEL_VERSION` bump. In a scene without regions, `zone` stays a plain label and `move` is unchecked (theatre of the mind).
  - **Adjacency is undirected.** A link listed on either side counts for both. The engine stores the normalised form (sorted ids, regions sorted by id) in the event, so a replay does not depend on how the GM listed them. Self-links, unknown ids, duplicate ids, unknown fields, and more than 64 regions (`MAX_REGIONS`) are refused.
  - **`terrain` and `cover` are pack catalogues** (`spatial.terrain`, `spatial.cover`, lists of `{id}`). A region may use only declared values, so a pack declaring none allows none. `elevation` is an integer the engine accepts but the tool schema does not offer, because it would be a free number under strict settings (§2.13.4).
  - **Positions stay on the entity** (`entities.<id>.zone`). An entity is in the scene when its zone is one of the scene's regions. A ZoneGraph `move` is one step to an adjacent region. Moving an entity that is not in the scene is refused. GM placement (`place_entity`, or `placements` on `set_scene`) has no adjacency check and is logged as `effect_applied` with primitive `move` and `params.reason: placement`, like condition expiry uses `reason: duration`.
  - **Visibility is by seat.** `visible_to` on a token is a list of seat ids, stored under `scene.spatial.visibility` and reset at every scene. A missing entry means visible to all. The GM sees everything, and a seat always sees what it controls. A player targeting an entity it cannot see gets the same "No entity" error as for an entity that does not exist, listing only what it can see (P3: absent, not denied). New event `visibility_set`.
  - **Region existence is checked when the action is committed; adjacency is checked when the move effect runs.** An illegal move found then rolls the whole command back, so no events are written.
  - Tools: `look` for every role, and for the GM `set_scene.regions` / `placements`, `place_entity`, and `set_visibility`, all only when the pack permits `zone_graph`. Dispatch is P1.2.
- Consequences: smoke campaigns now run on a three-region line and hide one NPC from one seat in encounter scenes. The lanternlight demo scenario has a spatial scene. T0.4 and T0.5 are unblocked. `engine.py` is now about 920 lines, past the ~800 guideline; splitting it along a § boundary is a follow-up.

## D-017 Candidate generation: kernel features, pack weights, prefix tiers
- Date: 2026-10-17 · Status: accepted (T0.4; §1.4.2, §1.4.3). The docs fix the split (kernel heuristics, pack weights and templates) and the tier table, but not the mechanics.
- Decision:
  - **Kernel features** (fixed names, no game nouns): `threats_here`, `threats_adjacent`, `allies_here`, `allies_adjacent`, `closer` (steps gained towards the nearest threat), `elevation_change`, and for actions `target_threat` / `target_ally`. A threat is a visible entity on the other side, GM-controlled versus player-controlled; an ally is on the same side. **Only entities the observing seat can see are counted**, so hidden entities cannot be inferred from rankings or annotations (tested).
  - **Pack profile** `spatial.tactical_profile`: `categories [{id, order: 1|2}]` (added to the abbreviated §2.3 schema; §1.4.3 says order is declared per category), `weights {feature: int}` (moves), `factors [{id, applies_to: move|action, actions?, when, weight}]`, and `annotation_templates [{id, applies_to, category, when, text}]`. Text placeholders are limited to `{region, label, action, target, threats_here, allies_here}`. An action's `annotation_categories` selects which action templates apply to it. Unknown features, categories, actions, or placeholders fail lint. Under `spatial: none` the profile is dormant and not checked.
  - **Ranking:** score descending, then catalogue order, then id. Integer-only and deterministic. Scores are never shown, only the order.
  - **Tiers are prefixes of one ranked list.** The count rises with mastery inside each tier band (4–5, 7–8, 10–12, capped at 12). Tier 0 has no annotations, tier 1 has order-1 categories, tier 2 has all. So a lower tier is always a prefix of a higher tier's list with a subset of its annotations, which is what the acceptance criteria require. `MASTERY_TIERS` and `CANDIDATE_CAP` are kernel constants for now (Appendix C `kernel_config`).
  - **Mastery is an argument, not state.** Traits are campaign config held by the orchestrator, so the dispatcher passes `rules_mastery`. It is never a model-supplied tool argument.
  - **API:** the old id list became `available_actions()`; it is used for legality and `judgement_input` options, which are unchanged, so logs are byte-identical. The agent-facing ranked view is `enumerate_action_candidates(entity, mastery, position_id=None)`, which the `enumerate_actions` tool maps to. Candidates are (action, target) pairs. Zone-targeted actions describe the destination region and appear only in spatial scenes.
  - **`preview`** never rolls and never shows a derived difficulty value, only `{"kind": "derived"}` or the ladder's rung ids, because a value derived from a target's stats would leak it. Its annotations are tiered like candidates.
  - All of this is read-only: no events, no randomizer use.
- Consequences: both demo packs carry a tactical profile, and the house pack overrides one inherited factor after removing Inspire (references are re-checked after merge, §2.8). Tools `enumerate_moves`, `enumerate_actions.position_id`, and `preview` appear when the pack permits `zone_graph`. Gate P0's "zero illegal moves across 10,000 candidates" and "mastery tiers differ" are covered by `tests/test_tactics.py` for ZoneGraph; RangeBands joins the volume test with T0.5.

## D-018 RangeBands: one band per pair; a move shifts one pair by one band
- Date: 2026-10-17 · Status: accepted (T0.5; §1.4, §8.2). The docs say only "relative distance bands between entities … band set from the pack".
- Decision:
  - **Pack data:** `spatial.bands: [{id, label}]`, ordered closest first, with at least two bands. Lint enforces this when `range_bands` is permitted. `tidewrack` now permits only `range_bands`, with `close / near / far`.
  - **Scene:** `set_scene(participants=[...], ranges=[{between: [a, b], band}])`. The layout records **every pair** of participants (keys `"a|b"`, sorted). Unset pairs start at the furthest band, so the state is complete and replay never depends on defaults. At most 16 participants (`MAX_PARTICIPANTS`). A scene uses regions or participants, never both. Placements belong to zone scenes and ranges to band scenes.
  - **Position ids** are `band:entity`: "this band from that entity". A move shifts the mover's band to one other participant by exactly one step. Other pairs are unchanged, which is the usual abstraction for band systems: the pack's rules, not the kernel, decide what moving away from one foe means for others. GM placement (`place_entity`, or `spawn_entity(zone=…)`) sets any band and adds a newcomer to the participants, placed far from everyone else. Moving relative to yourself is refused.
  - **Visibility:** a seat's candidate moves, legal targets, and `scene_view` ranges are measured only from entities it can see. A move measured from a hidden entity gets the same "No position" error as a nonexistent one.
  - **One interface for both backends:** `build`, `contains`, `position_of`, `check_position`, `moves`, `check_move`, `move_changes`, `place_changes`, `steps` (to every other entity), `region`, `label`, and `view`. The candidate generator (D-017) now works on positions and `steps_from`, so its features mean the same under both: `threats_here` is a threat at 0 steps (same region, or the closest band), `threats_adjacent` at 1. Candidates carry `id`, `position_id`, `label`, and `annotations` under every backend; zone candidates also keep `region_id`.
  - **Tool surface:** `place_entity` takes `position_id` (renamed from `region_id`; nothing dispatches tools yet). `set_scene` offers `regions` / `placements` and/or `participants` / `ranges` according to the pack's backends. Every other spatial tool is identical.
  - Zone scenes are unaffected: smoke and demo logs on the zone packs are byte-identical to the previous commit.
- Consequences: P0.10 is complete. A pack that changes nothing but its backend list runs unchanged under either backend (tested with Lanternlight under RangeBands).

## D-019 Turn controller: explicit encounters, budgets refresh on your own turn
- Date: 2026-10-17 · Status: accepted (T0.6; §2.4, P0.4, §4.1). The docs list the orders and economies but not their mechanics.
- Decision:
  - **Encounters are explicit.** `start_encounter` (GM, in a scene set with `encounter=True`) begins one. `end_encounter`, `set_scene`, or `end_session` ends it, each emitting `encounter_ended`. `state["encounter"]` exists only while one runs, so older logs and scenes that never start one fold unchanged: no kernel bump. Free play is never gated.
  - **Orders** (`turn_structure.encounter.order`):
    - `initiative` rolls the pack's `initiative.roll` (dice with `{stat}` variables) once, or every round with `each_round`. Highest first; ties break by entity id.
    - `sides` alternates `players` and `gm` (pack `first`), and any member of the side in play acts.
    - `handoff` has the finisher name who goes next among those who have not gone; the last of a round names anyone but itself to open the next. The pick is a model choice, logged as `judgement_input` with control `turn_handoff`.
    - `fixed` uses the GM's participant order every round.
    - `deck` is a fresh seeded shuffle each round, drawn one card at a time as equal-weight `roll_made` draws. `tob verify --seed` re-derives these with no change. T0.8 decks can reuse the pattern.
    - `spotlight` has no turns: `end_turn` is refused, and the GM's `next_round` refreshes budgets.
  - **Economies:**
    - `none`
    - `slots: [{id, count}]`: an action uses its `slot`, or the first slot.
    - `points: n`: an action costs its `points`, or 1. A cost of 0 is free.
    - A budget refreshes when its owner's turn starts (for sides, every member's), so an off-turn `trigger: reaction` spends from what the owner's next turn restores. That is the common "one reaction per round" behaviour without a separate rule.
  - **Enforcement in `commit_action`:** during an encounter, an entity must be a participant, and it must be its turn (or its side's) unless the action is a reaction. The budget must cover the cost. A refusal is atomic. `economy_spent` records the exact `remaining`, so replay never recomputes it. `available_actions`, and so the `judgement_input` options and the candidate generator, leave out what the turn or the budget forbids.
  - **`current_turn()`** returns the order, the round, the actor (entity or side), the seats that may act (which the scheduler's Stage 1 needs for `own_turn_in_turn_order`), the budgets, and `up_next`. `up_next` wraps to the next round's opener unless the order reshuffles or rerolls.
  - **Tools:** `end_turn` (with `next` under `handoff`) for every role unless the order is `spotlight`. For the GM: `start_encounter` (with `first` under `handoff`), `end_encounter`, and `next_round` under `spotlight`.
  - NPC turns are taken by the GM seat, like any NPC action.
- Consequences: Lanternlight now declares `initiative` (`1d20 + {grace}`) with `action` and `minor` slots (Recall is minor; its rules text says so). Tidewrack keeps `spotlight` / `none`. Smoke campaigns play encounter scenes turn by turn under each pack's structure. P0.4 is complete apart from the reserved `trigger_procedure` primitive.

## D-020 Decks: shuffles record their order; draws are engine commands
- Date: 2026-10-18 · Status: accepted (T0.8; §2.4, §5.5, P0.2). The docs give `decks: [{id, cards, reshuffle_rule}]` and the event names, and say deck order is game state.
- Decision:
  - **Pack data:** `randomizers.decks: [{id, cards: [{id, label} | id], reshuffle_rule, players_draw?}]`. Card ids are lowercase ids. Lint class `deck`.
  - **Shuffles are logged with their result.** A shuffle consumes one roll counter through `Randomizer.shuffle`. `deck_shuffled` carries `counter`, the `cards` shuffled (pack order, hands excluded), and the resulting `order`. The reducer folds the order and advances `roll_counter`; it never re-runs the shuffle (D-003). `verify --seed` re-derives every shuffle. A deck comes into state with its first shuffle, which happens on its first draw, so older logs fold unchanged.
  - **Reshuffle rules:**
    - `when_empty`: an empty pile first shuffles in every card not in a hand
    - `every_draw`: a fresh shuffle before each draw
    - `scene` / `session`: a full reshuffle at each boundary, only for decks already in use
    - `manual`: only `reshuffle_deck` refills; an empty pile refuses draws
  - **Draws are engine commands, not effect primitives.** The §2.6 primitive set is closed and lists no draw, and adding one would be a design change. Packs that need a draw inside a rule can request it when one exists; until then the GM (or a seat, for `players_draw` decks) draws through the tools. Drawn cards go face up onto the discards, or into a holder's hand (`to=`: a seat or entity id); `discard_card` returns them.
  - **Hidden information:** pile order is never in any view or tool result. `deck_view` gives the pile size, the face-up discards, and the seat's own hands (including entities it controls); the GM sees every hand.
  - `turn_structure` `deck` order (D-019) keeps its own equal-weight draws for now. It could be moved onto a pack deck later without changing this module.
- Consequences: Tidewrack declares an `omens` deck (`when_empty`), and its rules text says the GM turns one over when the weather of the story shifts. Smoke campaigns draw from every declared deck each scene, alternating face up and into a hand. Scenario steps `draw_card`, `reshuffle_deck`, and `discard_card` were added.

## D-021 Fudging: peek pauses the action; a reroll may not lower the party-side rank
- Date: 2026-10-18 · Status: accepted (T0.7; §5.5, §2.5, §2.13, §8.6). The docs fix the conditions and the direction-of-drama rule but not the mechanics.
- Decision:
  - **A peek is asked for with the ruling.** The GM passes `peek: true` in its inputs to `commit_action` (the `rule_on_action` tool) or to `resolve_unmodelled`. Commands are synchronous and atomic, so the roll cannot be interrupted from outside. Instead the engine rolls, logs `roll_peeked` with everything needed to finish (the roll expression and variables, modifiers, difficulty, and a continuation naming the action, its ids, and its variables), and returns `pending`. Nothing is resolved or applied until the GM calls `peek_roll(keep | reroll)`. Until then `commit_action`, `resolve_unmodelled`, `set_scene`, and `end_session` are refused, so the paused action cannot be lost.
  - **One reroll per peek, direction of drama only.** The reroll is a normal logged roll (`purpose: fudge:<procedure>`). The party-side rank is the rank for a player-controlled entity and its mirror (`ranks - 1 - rank`) for a GM-controlled one. A reroll that would lower it is refused atomically, so retrying gives the same refusal and the GM must keep the roll. Equal rank is allowed (a "different number, same result" reroll changes nothing the party feels).
  - **Cap:** peeks per session = `fudging * 4 // 100` (0 to 4). The trait comes from `gm_traits.fudging`, default 50, and is now recorded in `campaign_started` as `gm_fudging`. Older campaigns without it read as 50. `PEEKS_AT_FULL_TRAIT` is a kernel setting.
  - **Availability:** `gm.gm_rolls`, a procedure listed in `gm.fudgeable_procedures`, the GM's `fudging` control on standard, peeks left, and a procedure that actually rolls. Each failure gives its own refusal. Tools: `rule_on_action.peek` and `resolve_unmodelled.peek` (booleans), plus `peek_roll {decision: keep | reroll}`, all present only when fudging is available. The players' schema never has them.
  - **Cards:** `procedure_resolved` names the final roll and is caused by the action, so the action card shows only the public result. `roll_peeked`, `roll_fudged`, and `peek_settled` are never rendered live. One known tell: a fudged card's `roll #` counter skips the peeked roll's number. Hiding it would mean renumbering public counters, which the seed re-derivation depends on. The archive reveals fudges anyway (§5.5).
  - New events `roll_peeked`, `roll_fudged` (the two the task names), and `peek_settled` (clears the pause, for both decisions).
- Consequences: Lanternlight (GM rolls, `check` fudgeable) supports fudging. Tidewrack's GM never rolls, so the tool is absent there; the banded scale is tested on a variant with `gm_rolls: true`. The rule "refused iff the party-side rank would fall" is tested on both scales, for both a player's and a GM entity's roll, with the reroll result derived independently from the seed.

## D-022 Sheet views: the summary is the full view minus its private fields
- Date: 2026-10-18 · Status: accepted (T0.9; §7.1, P0.8). The docs name the two views (own sheet in full, others in summary) but not what is private.
- Decision:
  - **One builder, one filter.** `full_sheet(entity)` lists every field (stats, derived, resources with max, tracks with boxes, currencies, conditions, tags, inventory, chargen details). Each field has a `section`, the pack's `label` and `short` (vocabulary first, then rule-card title, then the id), its `value`, and `private`. `summarise()` drops every private field. A summary therefore cannot contain a field the full view marks private: the acceptance criterion holds by construction and is also tested over whole smoke campaigns on three packs.
  - **Public is opt-in, decided by the pack:** conditions (the table can see them), `presentation.nameplate_resources` (the overlay already shows them), and `presentation.sheet.public`. Everything else is private, including stats, inventory, and details. A catalogue entry with `private: true` can never be public. Lint class `sheet`.
  - **Who sees what:** `read_sheet(seat)` returns the seat's own entity (it must name one if it controls several). Another entity's full sheet "does not exist" for a player, and the error points to `read_party_sheets`. The GM reads any sheet in full. `read_party_sheets(seat)` returns other PCs in summary for a player, and every PC in full for the GM.
  - Pure reads; no events.
- Consequences: Lanternlight shows Vigor (nameplate) and Guard publicly; Tidewrack shows Grit and Harm. Tools: `read_sheet` (GM: `entity_id`) and `read_party_sheets` for every role. P0.8 is complete.

## D-023 Off-air clocks: per-clock schedules at session start; stages are prepped canon
- Date: 2026-10-18 · Status: accepted (T0.11; §7.6.1, §7.6.2 axiom 15, P0.11). The docs say clocks advance off-air "per its own schedule" and that resulting world changes are written as canon before play resumes.
- Decision:
  - **Schedule:** `create_clock(..., schedule={every, amount})` advances `amount` (1 to 3) segments once every `every` (1 to 12) gaps between sessions. A gap is passed at `start_session`, before `session_started`, so the canon exists before play resumes. A clock made during session *n* first advances at the start of *n + 1*. Prep, before session 1, has no gap, so the first advance is at the start of session 2. Each advance is a normal `advance_clock` effect with `reason: off_air`. A full or paused clock is skipped.
  - **Stages:** `stages=[{at, record}]` are the world changes the GM prepped for "if the party never interferes" (§7.6.1). Records are written with `origin: prepped`, are validated by `_canon_record` at creation (missing fields, bad enums, secrets without discovery paths), and are validated again when written. A stage fires when the fill crosses its mark from below, however the clock moved: off-air, `advance_clock` in play, or a pack effect. It fires once only (`fired` list), even if the clock is pushed back and refills. Each firing is `canon_written` followed by `clock_stage_reached`, both by the engine and caused by the advance.
  - **Interference:** `pause_clock(clock, paused)` (GM) holds a scheduled clock; pack effects can lower a clock. Pausing an unscheduled clock is refused.
  - Clocks without a schedule or stages keep their old folded shape, and older logs fold unchanged.
  - Calendar and watch tracking (§2.4 "Clocks and time") is not part of this task and stays a roadmap todo.
- Consequences: smoke campaigns use a scheduled `pressure` clock with two stages, so every campaign run exercises off-air advancement and canon from clocks. Tools: the GM gets `pause_clock`. Creating scheduled clocks belongs to the P3 prep tools.

## D-024 query_rules: a pack-pinned index, ids-only lookup log, inline packs searchable too
- Date: 2026-10-18 · Status: accepted (T0.14; §2.11, §6.5 Layer 0, §8.6, P0.13).
- Decision:
  - **Index:** `SectionIndex` is built once per engine from the pinned, resolved pack, so it never needs invalidating. It holds id → section, catalogue ref → sections (declaration order), name key → sections, and word → sections. Name keys and tokens are canon's own `name_keys` / `tokens` / `FILLER`, imported rather than copied, so the two indexes cannot drift (D-010).
  - **Resolution order:** exact section id, catalogue id via `refs` (every covering section, in declaration order), alias key (titles count as names), then partial (every non-filler query word appears in a section's title or alias words). A miss returns up to three close titles. A pack with no sections answers with a note that its rules are already inline.
  - **Logging:** every lookup emits the passive event `rules_queried` {seat, query, via, sections (ids), suggestions}. §2.11 asks for misses to be logged, and §8.6 has a rules-check card showing the title consulted. Section text never enters the log or a card.
  - **Lint (`rules-text`):**
    - mode is `inline` or `sectioned`
    - inline full text within the existing budget
    - sectioned: a non-empty digest within `DIGEST_TOKEN_BUDGET` (6,000 tokens, approximated as characters / 4 like the inline budget), and at least one section
    - `max_section_tokens` (default 2,000) caps every body
    - unique section ids, a title and body for each, no unknown fields
    - refs must be catalogue ids
    - titles and aliases unique across sections (by name key)
    - `parent` must exist, with no loops
    - sectioned packs only: every action, procedure, and condition is covered by some section's refs
  - **Context:** `rules_layer()` returns layer 2 (§6.1): the inline text, or the digest. The context assembler (P1.3) uses it.
  - Tool `query_rules {query}` (narrative text) for every role.
- Consequences: T0.15 (a shipped, data-only sectioned variant pack) is unblocked. The tests build a sectioned Lanternlight on the fly; T0.15 turns that into a pack under `packs/` that runs in every gate.

## D-025 The sectioned fixture pack, and what "the same event stream" means
- Date: 2026-10-18 · Status: accepted (T0.15; P0.6, P0.13, §2.8, §2.11).
- Decision:
  - `packs/lanternlight_sectioned` extends `lanternlight` and sets only `rules_text`: `mode: sectioned`, an empty `full_text`, a digest, `max_section_tokens: 200`, and 12 sections. They are Lanternlight's text, split, with `actions` as a parent for the six action sections. Its refs cover every action, procedure, and condition, plus stats, resources, the ladder, and tags. No kernel change was needed.
  - **Stream parity:** its smoke campaign matches Lanternlight's event for event (seq, type, actor, cause, session, scene, payload), except for (a) pack identity in `campaign_started` (`campaign_id`, `pack_id`, `pack_hash`) and (b) the answer half of `rules_queried` (`via`, `sections`, `suggestions`). The lookup itself (`seat`, `query`) matches. A lookup is passive and never changes state, which is why the streams can match.
  - Smoke campaigns now make one deterministic `query_rules` per scene (a player asks about an action id), so every gate exercises rule lookups. On inline packs these return the "already in context" note, and on the sectioned pack they resolve by ref. Scenario step `query_rules` was added.
- Consequences: P0.13 is complete. The gate runs four playable packs (two families, two data-only derivatives).

## D-026 Excluded terms: merged up the chain by term; consecutive-word matching
- Date: 2026-10-18 · Status: accepted (T0.16; §1.2, §1.3.3, §2.10, P0.14).
- Decision:
  - **Loader:** resolved `meta` is not deep-merged (only selected fields survive), so the loader gathers `meta.excluded_terms` from every pack in the extends chain and merges them by `term`, root first. A child's entry for the same term replaces its aliases. The key appears in the resolved pack only when some pack declares terms, so every existing pack's hash is unchanged. Removing an inherited term is not supported. A child that needs a name back must not extend that parent; this can be added if a real pack needs it.
  - **Matcher (`terms.find`):** canon's `tokens` (lowercase, punctuation and possessives dropped). A term or alias matches when its words appear **consecutively** in the text. So "Morrow Gaunt", "MORROWGAUNT." and "Morrowgaunt's" match, while "gauntlet" and half of a two-word term do not. Results come back as declared terms, in pack order. The engine exposes it as `excluded_in(text)` for the validation pass and the TTS gate (P3.3).
  - **Canon:** `_canon_record` checks name, aliases, and body, so `write_canon`, `supersede_canon`, and clock stages (at creation and at firing) all refuse. The error names the term and points to `meta.excluded_terms`.
  - **Lint (`excluded-term`):** each entry needs a term with a word, and its aliases must be names. No term may occur in the pack's own catalogue ids (underscores read as spaces), vocabulary labels, rule-card titles, or section titles. If one did, the pack's own text would trip its own check.
  - **Fixture:** `tidewrack_excluded` is a data-only derivative with three invented names (Morrowgaunt, Saltmother Ysolde, Brinehold Compact). The kernel and the tests name no real-world IP.
- Consequences: P0.14 is complete. The SRD pack (P4.0) supplies its real list then.

## D-027 Property tests and golden fixtures
- Date: 2026-10-18 · Status: accepted (T0.10; §2.10, P0.7).
- Decision:
  - **Exact distributions:** `dice.distribution(src, variables)` returns exact `Fraction` probabilities for sums, constants, arithmetic, Fate dice, success counts, and keep-highest/lowest. Keeps are enumerated up to `ENUMERATION_LIMIT` (200,000) combinations. Exploding dice return None (no finite exact answer). Tests pin known values (2d6, 4d6kh3, 3dF, 5d10count>=8, 2d20kl1).
  - **Outcome reachability** (`conformance.outcome_reachability`): for every procedure that rolls, check each outcome's probability at the lowest and highest stat, against every ladder rung (compared rolls) or by band (banded rolls). That under-approximates reachable states, so "reachable" is never a false claim. An outcome that no state reaches fails the test. Where no exact distribution exists the result is None, and callers sample instead.
  - **Generated per pack:** `tests/test_properties.py` parametrises over every playable pack that `discover` finds, so a new pack is covered without editing tests. Sampled states are seeded (`random.Random(seed)` in tests only, never in the kernel): random chargen choices, an NPC with random stats, random scene flags, and a spatial scene under whichever backend the pack permits. "Resolvable" means some candidate (action, target) from `enumerate_action_candidates` commits successfully in some sampled state. "No invalid sheet" runs four seeded 60-step walks mixing candidate commits with primitive effects at extreme amounts, checking `sheet_problems()` for every entity after each step. `sheet_problems` checks stat ranges, resource bounds, track bounds, currency bounds, known conditions, tag sets, the inventory shape, and derived values.
  - **Golden fixtures:** `packs/<id>/fixtures/golden.yaml` for every playable pack, found by convention rather than through the pack's `fixtures` field, so derived packs never inherit a parent's paths. Each run is a smoke campaign (`golden-seed`, 3 sessions, 2 scenes), plus the Lanternlight demo scenario, with its log head hash and event count. A pack without fixtures fails. `TOB_UPDATE_GOLDEN=1` rewrites them deliberately.
  - **Budget:** the full `tob check` takes about 20 s and `--quick` about 1.5 s on the development desktop, within TESTING.md's 60 s and 10 s.
- Consequences: P0.7 is complete. Any change to any pack or to kernel behaviour now shows up as a golden diff that has to be regenerated on purpose.

## D-028 Resolution shapes: margins, opposed rolls, stats as dice variables
- Date: 2026-10-26 · Status: accepted (T0.17; §2.5, P0.4, P0.6). The owner asked for everything left in Phase 0 to be finished before sign-off. An audit found the §2.5 pool shape and `core`'s opposed checks missing.
- Decision:
  - **Interpretations** (one pure function, `resolution.interpret_total`, shared with the conformance checker):
    - `bands` over the total
    - `margins` over the margin of the total over the difficulty, for degrees of success. `compare: successes` reads as `>=`, so a pool's success count is compared with the difficulty. `<=` gives roll-under margins.
    - `compare: >= | <=` pass/fail
    - `against: opposed`
    - `automatic`
  - **Stats name dice:** a procedure's roll variables are the actor's stats and derived values plus `mod`, so `({attr}+{skill})d10count>=8` works. `roll_made` records only the variables an expression uses, so existing logs are unchanged.
  - **Opposed checks:** `core` declares `opposed` (inputs actor, stat, target). The target rolls first (`purpose: opposed:<procedure>:<target>`), using the same stat unless `opposed.stat` names another, plus its condition modifiers. Its total becomes the difficulty (`origin: opposed`). The actor wins on a higher total, and ties go to `ties: target` (the default) or `actor`. `core` rolls 1d6; `core.roll_over` and `core.banded` override with 1d20 and 2d6. An opposed check cannot be peeked (two rolls).
  - Lint understands `margins` (contiguous bands, one per outcome) and opposed (a two-outcome scale, `target` among the inputs, a valid `ties`).
- Consequences: every pack inherits `opposed`, so all pack hashes and golden fixtures changed; they were regenerated deliberately. `lanternlight_sectioned` lists `opposed` in its refs. Live cards label the opposed difficulty as an "opposed roll".

## D-029 Step dice; reachability checks real states only
- Date: 2026-10-26 · Status: accepted (T0.18; §2.4, P0.2, §2.10).
- Decision:
  - **Step dice:** a die's size may be a variable, `1d{trait}`. A pack enables the `step` operator and lists `dice_grammar.step_sizes`, the legal sizes. A size outside the list is refused atomically, with the legal sizes named. Lint requires `step_sizes` when `step` is enabled, sizes of at least 2, and none above `max_sides`. `roll_made` records the size variable among its variables and the group as `1d<size>`. Re-derivation (`verify --seed`) evaluates without the size list, since a logged size was already legal.
  - **Conformance fix found by step dice:** `outcome_reachability` used to bind every stat, and `mod`, to one shared value. That is a state no character need be in. For a step die it claimed "never fails", which was false. It now sets every stat to the low and then the high end of its own range. `mod` carries a stat only when the procedure draws modifiers from one. Every checked state is a real one, so "reachable" is never a false claim and nothing reachable at the extremes is missed.

## D-030 Chargen assign steps
- Date: 2026-10-26 · Status: accepted (T0.19; §1.5, P0.8).
- Decision: a chargen step `{id, kind: assign, targets: [stat ids], values: [ints]}` places a fixed array onto stats. The agent supplies `{stat: value}` covering every target, using each value exactly once. It is logged as `judgement_input` with control `chargen_assign`, recording the arrangement and the array it came from. Anything else is refused atomically, with the array named. Steps run in pack order, so a later choice can still set a stat, as a background does in Lanternlight. Lint checks targets, one value per target, and every value within every target's range. Read views are shown, by test, to be unable to change state: every returned structure is scrambled and the state hash is unchanged.
- Consequences: `lanternlight_house` replaces rolled stats with the array 2/1/0/-1 as a data-only house rule (its golden fixture was regenerated). The smoke harness rotates the array per player, and the property tests shuffle it. 1,000 characters per playable pack are generated and validated in about 2 s.

## D-031 Movement allowance, provokes, and cover as pack data
- Date: 2026-10-26 · Status: accepted (T0.20; §1.4, §2.3 `spatial: movement, cover, provokes`, P0.10).
- Decision:
  - **Movement:** `spatial.movement.steps_per_move` (1 to 6, default 1) is how far one move may go: regions crossed in a zone scene, bands shifted in a band scene. Backends take it as `reach`. Candidates, `reachable`, and move checks honour it. With the default, behaviour and logs are identical to before.
  - **Provokes:** `spatial.provokes: {when: expr}` (`{}` means always) makes a move that leaves a threat's reach provoke it. In a zone scene that is threats sharing the region left; in a band scene, the entity backed away from out of the closest band. `when` is evaluated with `actor` as the provoker and `target` as the mover, so a pack can say a downed foe cannot react. The move logs the passive event `move_provoked {mover, by, to}`. The provoker may answer with a `reaction` action, which the turn controller already allows out of turn. The kernel decides nothing more: what a provoke does is the pack's reaction. Candidates gain the feature `provokes` and the placeholder `{provokers}`, counted over visible threats only.
  - **Cover and terrain in expressions:** an entity's view now carries `region` (`elevation`, `terrain.<id>`, `cover.<id>`) for where it stands, so a derived tag like `target.region.cover.partial == 1` works. An empty view (no target) reads every nested field as 0.
- Consequences: no shipped pack changed, so the golden fixtures are untouched. The tests use variants.

## D-032 In-world time: one elapsed counter, mixed-radix dates
- Date: 2026-10-26 · Status: accepted (T0.21; §2.2 "Clocks and time", P0.11).
- Decision:
  - **Pack data:** `time.units: [{id, label, per}]`, smallest first. `per` says how many make the next unit up; the last unit has none. Optionally `time.between_sessions: {unit, amount}`. Lint class `time`.
  - **State:** `state.time.elapsed` counts the smallest unit and is created by the first `time_advanced`, so older logs fold unchanged. Dates are derived by mixed radix, each unit counted from 1. `current_time()` gives `{elapsed, units, text}`, for example "Moon 1, Day 3, Watch 2". There is no separate date state to drift.
  - **`advance_time(unit, amount)`** (GM, 1 to 1,000) logs `time_advanced {unit, amount, from, to}`. When the pack sets `between_sessions`, `start_session` advances time first (`reason: off_air`), then off-air clocks.
  - **Clocks on in-world time:** a schedule `{every, amount, unit}` advances `amount` segments for every `every` units that pass since the clock was made (`created_elapsed`), however many intervals one advance spans. Time-scheduled clocks are skipped by session-based off-air advancement, and pausing applies to both. Stages fire as before.
  - Tool `advance_time {unit: enum, amount: enum 1..12}` for the GM when the pack keeps a calendar; strict schemas stay free of open numbers.
- Consequences: Lanternlight keeps watches (4 per day), days (28 per moon), and moons, and a day passes between sessions. Smoke campaigns pass a watch per scene. The Lanternlight-family golden fixtures were regenerated deliberately.

## D-033 The hook sandbox: a checked subset of Python, run twice
- Date: 2026-10-26 · Status: accepted (T0.12; §2.7, P0.5, Appendix C `hook_runtime_limits`). Un-deferred by the owner's direction to finish all of Phase 0 before sign-off.
- Decision:
  - **Registration:** a pack declares `hooks: [{point, name, version}]` and ships `hooks/<name>.py` beside its `pack.yaml`. Declarations accumulate along the extends chain by name, each read from the declaring pack's folder. The source text goes into the resolved pack, so it is hashed and pinned (§2.9). A declaration without a source file is an unregistered hook, and the pack is refused (the existing test still holds).
  - **Static check at load (`hooks.check_source`):** exactly one `def hook(view, params, rng)` plus constants. An AST whitelist forbids imports, `while`, lambdas, classes, `try`/`with`/`global`, nested functions, floats, `/`, `**`, and bit operators. Names and attributes may not start with `_`. Calls are allowed only to whitelisted pure builtins, a few container methods, and `rng`. Clock reads, I/O, network, and private randomness cannot be expressed, so a pack that tries does not load. That is the P0.5 test.
  - **Runtime (`hooks.run`):**
    - Builtins are the whitelist only.
    - The view and params are deep copies of plain data, so a hook cannot reach engine state (tested).
    - A step limit of `MAX_STEPS` (10,000 traced lines) applies.
    - `rng(lo, hi)` draws from the engine randomizer on one roll counter, one sub-index per draw. The draws are logged as a `roll_made` with `expression: hook` and `draws`, and `verify --seed` re-derives them.
    - **Every invocation runs twice** on fresh copies with the same draws, and results must agree. Disagreement refuses the command (§2.7's "executed twice … bytes compared").
  - **Wired points:** `resolution.step`, a `hook:` step inside a procedure that sees the total, dice, modifiers, difficulty, actor, and target, and may return `{total}` or `{outcome}`; and `sheet.validate`, which returns a list of problems, is enforced at chargen (atomic refusal), and is included in `sheet_problems`. The other five §2.7 points are listed but refused at load as "reserved in this kernel build" until a pack needs them. A procedure with a hook step cannot be peeked.
  - **Logging:** every invocation emits the passive `hook_ran {hook, point, result, roll_seq}`. `tob pack lint` prints each pack's hook count (P0.6).
  - **Deviation to flag:** §2.7 gives the hook shape as `(state_view, params, rng) → [events]`. Here a hook returns a small, point-specific result (`{total}`/`{outcome}`, or a list of problems), which the kernel validates and turns into events. That keeps "never mutates state directly" and "returns data, not side effects", but a hook cannot emit arbitrary events. The owner should confirm this reading, or ask for an ARCHITECTURE note.
- Consequences: Gate P0 item 10 is now tested for real (`test_gate_p0.py::test_every_shipped_hook_passes_the_contract`). The new fixture `lanternlight_hooked` has a natural 20 that always passes and a natural 1 that always fails (resolution.step), plus a minimum-standing check (sheet.validate). It runs in every gate and has its own golden fixture.

## D-034 The last Phase 0 test lines
- Date: 2026-10-26 · Status: accepted (T0.22; P0.3, P0.5, P0.6, P0.12).
- Decision:
  - **`core`'s default tactical profile** is weights only (`threats_here`, `allies_here`, `closer`, each 1), with no categories or templates. A game that authors no profile still gets sensibly ranked candidates. The shipped games override every default, so their resolved packs, hashes, and golden fixtures are unchanged. (Correction: commit `7001400` says the fixtures were regenerated; the regeneration ran but changed nothing.)
  - **One control, one role:** a test flips GM difficulty, GM situational modifiers, and player spend amounts in turn. It asserts that the other role's schema is identical and that the flipped role's schema changes exactly when the pack has something for that control.
  - **Every preset:** a 3-session smoke campaign on every playable pack under all-strict, all-standard, and default settings. Each makes mid-campaign changes applied at scene boundaries, covers every action, verifies with the seed, and is byte-identical on a second run (18 runs, about 7 s).
  - **Evaluator properties:** 2,000 random well-formed expressions over the whole grammar always evaluate to an integer, and identically twice. `div` matches exact floor, ceil, and half-up on 2,000 random pairs per rounding mode. Every pack's derived values evaluate under its declared rounding.

## D-035 trigger_procedure, and hook memory limits
- Date: 2026-10-26 · Status: accepted (T0.23; §2.6, §2.7, P0.4, P0.5, Appendix C). These close the second Phase 0 audit.
- Decision:
  - **`trigger_procedure`** (no primitive is reserved any more): `{procedure, target?, against?, stat?, difficulty?, outcome_effects}`. `target` rolls (default the actor). `against` is the other side for derived or opposed difficulties (default the target, or the actor if the target rolls). The difficulty is fixed by the pack, either `{derived: expr}` or `{ladder, rung}`. A rung becomes a fixed value, so no model chooses it and no `judgement_input` is logged. The primitive logs an `effect_applied` with no changes. The procedure then runs, caused by it, and the listed outcome's effects apply, with `actor` and `self` meaning the roller. It shares `MAX_TRIGGER_DEPTH` with resource and track triggers, so procedures that trigger each other stop with a named error. Lint checks the procedure, its stat, a required difficulty, ladder rungs, outcome names against the procedure's scale, and the nested effects themselves (`_effects_in` now recurses).
  - **Hook memory** (Appendix C `max_memory`): memory is traced for each hook run, and over `MAX_MEMORY` (16 MB above the starting level) the run is refused. The check happens at every line and again at the end, so one line cannot slip past. Because a single step could still allocate without bound, `range` is capped at `MAX_ITEMS` (100,000) and every `*` is routed through a checked multiply that caps sequence repetition, `*=` included. Numbers multiply freely. The rewrite happens after the static check, so pack code cannot name the injected helper.
  - **Tests added:** every primitive emits events and replays (with a check that the list covers the whole closed set); a triggered "last stand" from pack data; the toggle test's mid-encounter case (the encounter ends at the scene boundary before the change applies); a seat override changing only that seat's schema; and memory-limit cases.
- Known limitation: the step and memory limits use `sys.settrace` and `tracemalloc`, so running the suite under a coverage tool or debugger that installs its own tracer will interfere with hook step counting. Run coverage without the hook tests, or accept the slowdown.

## D-036 Owner decisions on the ARCHITECTURE 1.6 draft
- Date: 2026-10-26 · Status: accepted (owner), except harm, which is pending.
- Decisions:
  - **B1 `scene_closed`:** keep it as a marker. It will be built (T0.24).
  - **C1 condition `stacking`:** keep it, since some systems stack conditions. It will be built (T0.25).
  - **C2 inventory:** add the `weight` model, but no `slots` model for now (T0.26).
  - **C3 `harm`:** the owner asked what it does. The answer and the proposal are in HANDOFF; this is pending.
  - **C4 `progression`:** scheduled as a kernel mechanism in Phase 0, BUILD_PLAN P0.15 with its own Gate P0 line (BUILD_PLAN revision 1.5). Arc-boundary milestones are a line in P3.6 (T0.27). Reasoning: §2.4 lists progression as a kernel variation point, and Phase 0 covers all of §2. When milestones arrive belongs to the campaign layer, so the arc-boundary trigger waits for P3.

## D-037 Harm is a declaration of targets only
- Date: 2026-10-26 · Status: accepted (owner, answering C3 of the 1.6 draft; T0.28).
- Decision: `entity_model.harm: { targets: [resource or track ids] }` names what counts as harm. The mechanics (minimums, maxima, `on_zero`, `on_fill`) stay on each resource and track, and the harm section may not carry triggers (lint class `harm`). `harm_state(entity)` gives later systems (lethality, metrics, the overlay, fudging's "unearned death") each target's value, bounds, and whether lower or higher is worse, without knowing the game.
- Consequence: the word `harm` must be free for kernel source, which the noun lint checks against every pack's catalogue ids. Tidewrack's track was therefore renamed from `harm` to `strain`. Its display label is still "Harm", so play and cards read the same. Lanternlight declares `[vigor, fatigue]` and Tidewrack `[grit, strain]`. Golden fixtures were regenerated deliberately.

## D-038 scene_closed: a marker after the closing events
- Date: 2026-10-26 · Status: accepted (T0.24; §5.7, owner decision D-036 B1).
- Decision: `scene_closed {scene_id, index, reason}` is logged when a scene ends, at the next `set_scene` (`next_scene`) or at `end_session` (`session_ended`). It comes after the events that close the scene (`encounter_ended`, condition expiry) and before the next `scene_set` or `session_ended`, so a reader of the log sees the whole scene, then the marker. It folds to `scene.closed`, so a scene already closed at a session's end is not closed again when the next session opens a scene. The flag exists only in logs that carry the marker, so older logs fold unchanged (no kernel bump). Every campaign's log changed, and the golden fixtures were regenerated deliberately.

## D-039 Condition stacking: intensity levels
- Date: 2026-10-26 · Status: accepted (T0.25; §2.3, owner decision D-036 C1).
- Decision: a condition may declare `stacking: intensity` with `max_level` (2 to 10, default 3). Applying it while held raises its level, up to the cap. `remove_condition` with `levels: n` lowers it, and removes it if that would reach 0. Without `levels` it is removed entirely. Expiry ends every level. Its modifier is multiplied by the level, both on the actor's rolls and on the other side's opposed roll. Expressions read the level (`actor.conditions.<id>`), and sheets show it. `stacking: none` (the default) keeps the old behaviour and the old state shape, with no `level` key, so older logs fold unchanged and no golden fixture changed.
- Not built: a `duration` stacking mode (refresh or extend). Conditions here end at scene or session boundaries, so there is no counted duration to act on. If a pack needs counted durations (for example "3 rounds"), that is a new duration model first.

## D-040 Weight-based inventory
- Date: 2026-10-26 · Status: accepted (T0.26; §2.3, owner decision D-036 C2).
- Decision: `entity_model.inventory: { model: abstract | weight, limit_expr }` and `entity_model.items: [{ id, label, weight }]`. Under `weight`, only catalogue items exist. `create_item` and `transfer_item` refuse, atomically and naming the totals, an item that would take the holder over `limit_expr` (evaluated on the holder's stats). An entity's view carries `carried` and `capacity`, so an encumbrance tag can derive from them, and the sheet's inventory field shows both. `abstract`, the default, behaves as before: any item id, no limit. A `slots` model is refused by lint as not built (owner: not needed for now). Item ids are added to the noun lint's catalogues, so the kernel cannot name a game's items. Lanternlight carries by weight (10 + 2 × Might, four items). Its family's golden fixtures were regenerated deliberately, and the property walk now creates items too.

## D-041 Progression: four models, one advance choice
- Date: 2026-10-26 · Status: accepted (T0.27; BUILD_PLAN P0.15, §2.3, §2.4, owner decision D-036 C4).
- Decision: `progression: { model: xp | marks | milestone | use, awards, thresholds, use, advances }`, in `kernel/progression.py`.
  - **xp / marks:** points come only from the pack's awards, which the engine logs as `progress_awarded`: `when: session_end`, or `when: outcome` on a player character's listed outcomes (optionally only for named procedures). Mark-on-failure is an outcome award on the failing outcomes. Each threshold reached makes one advance due. `marks` differs from `xp` only in name.
  - **milestone:** `award_milestone` (the GM, or the engine) makes one advance due, for one character or every PC. Nothing is awarded at a session's end. Arc-boundary awards wait for P3.6.
  - **use:** every roll that adds a stat counts one use of it. At `use.threshold` uses the stat rises by one, if its range allows, as an automatic `advance_taken` (option `use:<stat>`), and the count starts again. Counting is per stat, not per action; BUILD_PLAN allows either, and stats are what rise.
  - **Advancing:** `advance_options(entity)` lists the pack's advances that are legal now (`requires` true, `once` not yet taken, every stat change within range). `take_advance(entity, id)` refuses anything else, atomically, and logs the pick as a `judgement_input` (control `advance`, like chargen's). The player's tool schema offers `take_advance` with the pack's advance ids as an enum, so nothing free reaches it under strict.
- State: `entities.<id>.progress {points, pending, advances, uses}`, created by the first progression event. Both events carry exact changes (D-003). A pack without progression, or with only the core default `{model: milestone}` and no advances, logs nothing, so older logs fold unchanged (no kernel bump).
- The award key is `when`, not `on`: YAML 1.1 reads a bare `on` as the boolean true.
- Packs: Lanternlight uses `xp` (2 per session end, 1 per failed roll; thresholds 4, 9, 15, 22, 30; four +1 stat advances and a once-only Lamplighter needing Wits 1). Tidewrack uses `marks` (1 per miss or failed roll; thresholds 3, 6, 10, 15). The smoke harness takes every due advance after each session, choosing from the engine's list, so every gated campaign exercises progression; golden fixtures were regenerated deliberately.
- Not built: rule cards for advances (the card lint does not cover them; they are choices, not rules at the table), and advances that grant actions.

## D-042 Gate P0 signed off; ARCHITECTURE 1.6 applied
- Date: 2026-10-26 · Status: accepted (owner; T0.13).
- Decision: the owner ticked all 19 Gate P0 items in HANDOFF and approved the 1.6 draft. Gate P0 is ticked in BUILD_PLAN (revision 1.6), and ARCHITECTURE 1.6 is applied: §2.3's schema and §5.7's event list now describe the build, `scene_closed` and the progression events included, and slot-based inventory is listed in §11.4. In the applied schema the draft's `# was:` and `# new` markers were dropped; the revision note records the change. `docs/dev/proposals/REV-ARCH-1.6.md` stays as the record of the review.
- Carried forward: Gate item 8 (structural evidence) and the hook return shape (D-033) are accepted for now and re-audited when the P0 architecture is finalised.

## D-043 Audit fixes after Gate P0 (T0.29)
- Date: 2026-10-27 · Status: accepted (owner asked for the audit's fixes before pushing).
- **Unbounded stats:** a stat's `range` is optional, so progression checks bounds only where a stat has them (`stat_range`). Before this, a lint-clean pack with rangeless stats crashed `advance_options`.
- **Advance lint:** an advance must change at least one stat or add a tag; `tags` is a list of ids, checked against `entity_model.tags` when the pack lists them (no pack does yet, so unlisted packs accept any tag id, as `add_tag` does).
- **Sheets:** under live progression the full sheet gains a private `progress` field: value is points, with `model`, `pending`, `advances`, and `options` (the same list `take_advance` accepts), so an agent can see that an advance is due without another tool. Summaries drop it, like every private field. `sheet_problems` now also checks stacked levels (1 to `max_level`, and no level on a condition that does not stack) and progress (pending not below 0, every advance known, once-only advances once).
- **Speed:** `load_raw` caches parsed pack YAML by content hash and returns deep copies, and uses libyaml's `CSafeLoader` when present (same resolver, same results; the golden fixtures and pack hashes are unchanged). Pack discovery parses every pack on each resolve, so the full gate fell from about 50 s to about 30 s.
- **CLI:** `tob` reconfigures stdout and stderr to UTF-8 (`errors="replace"`) when the console uses another encoding; `tob sim --cards` crashed on a cp1252 Windows console.
- Left to the owner (open questions in HANDOFF): the scope of `judgement_input` for GM choices outside resolution, and when `KERNEL_VERSION` moves.

## D-044 Every GM call is logged
- Date: 2026-10-27 · Status: accepted (owner: "log all GM calls and choices"; T0.30, §2.13).
- Decision: every engine command the GM can call logs a `judgement_input` when a GM seat makes it, through the `@gm_call` decorator (under `@atomic`, so a refused call logs nothing). `control` is the command's name, `setting` null, `choice` the arguments it was called with, and `options` the list it was chosen from where the engine has one (clock amounts, deck ids, time units, clock ids, player characters), else null. It follows the call's own events and is caused by the first of them. Covered: `set_scene`, `spawn_entity`, `start_encounter`, `end_turn`, `next_round`, `end_encounter`, `draw_card`, `reshuffle_deck`, `discard_card`, `create_clock`, `advance_clock`, `pause_clock`, `advance_time`, `award_milestone`, `place_entity`, `set_visibility`, `write_canon`, `supersede_canon`, `reveal`.
- Already logged under their own controls, so not doubled: `commit_action` (`action_selection`, and the GM's difficulty and tags), `fill_ruling`, `resolve_unmodelled`, `peek_roll`, `take_advance`.
- Not logged: reads (`read_sheet`, `read_party_sheets`, `query_canon`, `enumerate_*`, `look`, `preview`), which change nothing and must not write; table talk (`post_to_table`, `pass`), which is P1's `message_posted`; `query_rules`, which already logs `rules_queried`; and calls by the engine or the operator, which are not model choices. Session boundaries are the scheduler's (P2), not GM tools.
- `tests/test_gm_calls.py` checks that every GM tool in the generated schema, on both packs and both presets, is a read, an already-judged command, or decorated. The strict audit (Gate P0 item 14) reads only strict-setting judgements, so it is unchanged. Event streams changed; golden fixtures were regenerated deliberately.

## D-045 KERNEL_VERSION stays 0.1.0 through the Phase 0 audits
- Date: 2026-10-27 · Status: accepted (owner).
- Decision: `KERNEL_VERSION` stays `0.1.0` until every Phase 0 audit returns complete. At that point the owner decides the bump and the policy for later ones (the audit's suggestion: `0.2.0` as the Phase 0 baseline, then a bump whenever what a command emits changes, not only when folding changes). Until then no campaign is archived, so nothing depends on the pin distinguishing kernel builds.

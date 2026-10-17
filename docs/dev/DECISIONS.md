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
- Decision: EVENTS.md mirrors `EVENT_TYPES` exactly, with a test enforcing it. ARCHITECTURE §5.7 stays a summary and is updated at the next design revision.

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

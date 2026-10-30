# Tasks

Agent-sized work packages. Each one cites its build-plan step (P…) and design sections (§), names what it depends on, and states acceptance criteria that can be checked by tests or `tob` commands.

**Statuses:** `ready` · `in-progress` · `done` · `blocked` (dependency not done) · `human` (needs a decision from the project owner) · `deferred`

**Rules**
- Take the lowest-numbered `ready` task in the track you're working on, unless `HANDOFF.md` says otherwise.
- Set the status to `in-progress` when you start and `done` when the definition of done in `AGENTS.md` is met.
- A task that grows past roughly one focused session should be split. Add `T1.6a`, `T1.6b` here before continuing.
- Gate P1 cannot be signed off before Gate P0 (BUILD_PLAN §0.2). Track 1 tasks marked *parallel-safe* don't depend on unfinished P0 work, but by owner decision (D-014) Track 0 is finished before any Track 1 work begins.

---

## Track 0 — Finish Phase 0 (Gate P0)

### T0.1 Broadcast pack: SRD 5.1 — `deferred` (moved to P4.0)
- **Plan:** P4.0 · §1.1, §1.2, §2.11
- **Decided (D-012):** SRD 5.1 under CC-BY 4.0 (D-015); sectioned rules text; `meta.excluded_terms` for non-SRD names. By owner direction it is written **as late as possible**, so Gate P0 and Phases 1–3 develop against the test packs only. The owner supplies the source document when P4.0 starts.
- **Then (agent):** see BUILD_PLAN P4.0. Copy the attribution text verbatim from the source, use no D&D trademarks, and make zero kernel changes for this pack.

### T0.2 Canon store — `done`
- **Plan:** P0.9 · §1.3, §6.2, §6.5 (Layers 0–1)
- **Deliverables:** `kernel/canon.py`, plus engine commands `write_canon`, `supersede_canon`, `reveal`, and queries `query_canon(scope, id_or_text)` and `scene_bundle(location_id, present_ids)`. New events `canon_written`, `canon_superseded`, `fact_revealed` (documented in `docs/dev/EVENTS.md`).
- **Design notes:**
  - Records live in folded state.
  - The alias table and relation graph are derived indexes, rebuilt deterministically from state rather than stored separately.
  - Player-scoped queries read from a view that never contains `secret` records. Filter at index construction, not at query time.
  - Each record's `origin` is `prepped | improvised` only.
- **Acceptance:**
  - Write 200 records; 1,000 player-scoped queries return zero `secret` records.
  - Aliases resolve on partial and colloquial names.
  - Near-collision names are flagged and exact collisions rejected.
  - Supersede is append-only, and history is retrievable by id.
  - The scene bundle is a pure graph traversal that includes the GM's active secrets only in the GM view.
  - Replay stays byte-identical.

### T0.3 Spatial: ZoneGraph — `done`
- **Plan:** P0.10 · §1.4, §8.2
- **Deliverables:** `kernel/spatial.py` with the `SpatialBackend` interface and `ZoneGraph`. Scene regions and adjacency become part of `set_scene`. `move` is validated against adjacency. Per-observer `visible_to` is supported.
- **Acceptance:**
  - Illegal moves are rejected atomically.
  - Visibility is per observer.
  - The scene schema matches §8.2 for the fields implemented.
  - Replay stays byte-identical.

### T0.4 Candidate generator and mastery tiering — `done`
- **Plan:** P0.10 · §1.4.2, §1.4.3, §2.3 (`spatial.tactical_profile`)
- **Deliverables:**
  - `enumerate_moves` and `enumerate_actions` return annotated, tiered candidates.
  - Scoring uses kernel heuristics weighted by the pack's tactical profile.
  - Annotations come from pack templates.
  - `preview(action_id)` is available.
- **Acceptance:**
  - Zero illegal candidates across 10,000 enumerations, per backend.
  - On identical tactical states, low tiers return strict information subsets of high tiers.
  - The candidate cap of 12 holds.
  - No coordinates appear in any output.

### T0.5 Spatial: RangeBands — `done`
- **Plan:** P0.10 · §1.4
- **Acceptance:** same tool surface as ZoneGraph; the band set comes from the pack; `tidewrack` declares and uses it.

### T0.6 Turn order and action economy — `done`
- **Plan:** P0.4 · §2.4
- **Deliverables:** an encounter-mode turn controller with the strategies `spotlight`, `initiative`, `sides`, `handoff`, `fixed`, and `deck`, and the economies `none`, `slots`, and `points`, all selected by `turn_structure` in the pack. Expose `current_turn` for the scheduler's Stage 1 bid (§4.1).
- **Acceptance:** each strategy cycles correctly through a scripted encounter, and the action economy is enforced atomically.

### T0.7 `peek_roll` and fudging — `done`
- **Plan:** P0.2 · §5.5, §2.5, §2.13
- **Deliverables:**
  - A GM command to peek at a pending roll for a fudgeable procedure.
  - A bounded reroll, with a frequency cap taken from the GM's `fudging` trait in campaign config.
  - New events `roll_peeked` and `roll_fudged`.
- **Acceptance:**
  - A reroll that lowers the party-side outcome rank is refused, verified on both packs' outcome scales.
  - The tool is absent when the pack's GM does not roll or the GM's `fudging` control is strict.
  - Live rule cards never reveal a peek or a reroll.
  - Replay and seed re-derivation still pass.

### T0.8 Decks — `done`
- **Plan:** P0.2 · §2.4
- **Deliverables:** deck state in events, plus shuffle, draw, and reshuffle per the pack's `reshuffle_rule`.
- **Acceptance:** draws replay exactly, and a demo pack uses one deck.

### T0.9 Read views — `done`
- **Plan:** P0.8 · §7.1
- **Deliverables:** pure functions for `read_sheet` (own, full) and `read_party_sheets` (others, summary), in the pack's vocabulary.
- **Acceptance:** the summary view never includes fields the full view marks private.

### T0.10 Property tests and golden fixtures — `done`
- **Plan:** P0.7 · §2.10
- **Deliverables:**
  - Generated tests per pack: every action resolvable from sampled states; every outcome band reachable, using exact dice distributions where possible; no effect sequence yields an invalid sheet.
  - Golden fixtures in `packs/<id>/fixtures/` as `(seed, script) → expected log head hash`.
  - `TOB_UPDATE_GOLDEN=1` regenerates fixtures deliberately.
- **Acceptance:** the tests run within `tob check`'s time budget (`docs/dev/TESTING.md`).

### T0.11 Off-air clock advancement — `done`
- **Plan:** P0.11 · §7.6.2 axiom 15
- **Acceptance:** clocks advance on schedule between sessions and emit canon (needs T0.2) for each world change.

### T0.12 Hook sandbox — `done` (un-deferred 2026-10-26 by owner direction: finish all of Phase 0)
- **Plan:** P0.5 · §2.7, Appendix C `hook_runtime_limits`
- **Deliverables:** pack-supplied hook source in a restricted language: a static check at load (no imports, no I/O, no attribute escapes, no unbounded loops), a runtime with no builtins beyond a whitelist, a step limit, a read-only state view, and randomness only through the kernel `rng` handle (logged); the registry is populated from validated pack hooks; at least the `resolution.step` and `sheet.validate` points wired; a fixture pack that uses hooks.
- **Acceptance:** BUILD_PLAN P0.5's hook test (an unregistered hook is refused; a hook that reads the clock, performs I/O, or draws its own randomness fails the contract and the pack does not load); every hook runs twice on fixtures with identical events.

### T0.14 Sectioned rules text — `done`
- **Plan:** P0.13 · §2.3, §2.11, §6.5 Layer 0
- **Deliverables:**
  - The pack loader accepts `rules_text.mode: sectioned` with `digest`, `sections` (`id`, `title`, `aliases`, `body`, `refs`, optional `parent`), and `max_section_tokens`. Inline packs may also declare `sections`.
  - A deterministic section index built from the resolved pack. Reuse canon's key normalisation (D-010) rather than duplicating it.
  - A `query_rules(section_id | query)` engine query that resolves by exact ID, catalogue ref, alias, then partial match. A miss returns suggestions. A lookup is logged only if the docs require it; check §8.6 rule cards and EVENTS.md before adding an event type.
  - Lint classes in `packlint.py`: digest budget, section cap, alias uniqueness, `parent` resolution without cycles, catalogue coverage by `refs`.
  - `query_rules` appears in generated tool schemas for every role (§7.1 table).
- **Rules:** no section taxonomy in the kernel and no system-specific names; sections are opaque text. Keep the noun lint clean.
- **Acceptance:** BUILD_PLAN P0.13's test, plus one defect of each new lint class caught with a message naming the valid options.

### T0.15 Sectioned fixture variant — `done`
- **Plan:** P0.6 · §2.8, §2.11
- **Deliverables:** a data-only derived pack (e.g. `lanternlight.sectioned`) that extends `lanternlight`, switches `rules_text` to sectioned with a digest, and changes nothing else.
- **Acceptance:** it passes conformance with zero kernel changes. Its scripted campaign matches its parent's event stream apart from rules-lookup events. `query_rules` reaches every section by ID and alias.

### T0.16 Excluded terms — `done`
- **Plan:** P0.14 · §1.2, §1.3.3, §2.3, §2.10
- **Deliverables:**
  - `meta.excluded_terms: [{ term, aliases }]` in the pack loader, inherited and merged like other catalogues.
  - One matcher in the kernel, reusing canon's key normalisation (D-010): case-insensitive and whole-word.
  - `write_canon` refuses records containing an excluded term in names, aliases, or text. The error names the term.
  - A lint class for collisions with catalogue IDs, vocabulary, rule-card titles, and section titles.
  - A fixture pack (e.g. a data-only variant of `tidewrack`) declaring a few invented terms, so tests stay system-agnostic.
- **Rules:** the kernel names no real-world IP; every term comes from pack data. Keep the noun lint clean.
- **Acceptance:** BUILD_PLAN P0.14's test. The validation-pass and TTS-gate integration is done later, in P3.3.

### T0.17 Resolution shapes: pool, opposed, roll-under — `done`
- **Plan:** P0.4, P0.6 · §2.5, §2.8
- **Deliverables:** the pool shape (dice count from stats, successes compared to a difficulty, degrees of success by margin via pack-declared margin bands); opposed checks (both sides roll; ties per pack) in `core`; roll-under covered; actor stats available as roll variables.
- **Acceptance:** BUILD_PLAN P0.4's test: the three reference procedure shapes in §2.5 resolve correctly against hand-computed outcomes, plus opposed and roll-under.

### T0.18 Step dice — `done`
- **Plan:** P0.2 · §2.4
- **Deliverables:** die size from a variable (`1d{trait}`), enabled per pack as the `step` operator, with a pack-declared ladder of legal sizes; exact distributions and value ranges.
- **Acceptance:** seeded rolls, exact distribution, and the 10k distribution test include step dice; an illegal size is refused.

### T0.19 Chargen assign steps and sheet guarantees — `done`
- **Plan:** P0.8, P0.7 · §1.5, §2.10
- **Deliverables:** an `assign` chargen step (place a pack-declared array of values onto stats, chosen by the agent and logged); 1,000 generated characters per pack all schema-valid; read views proven unable to mutate state.
- **Acceptance:** BUILD_PLAN P0.8's test.

### T0.20 Pack movement, provoke, and cover rules — `done`
- **Plan:** P0.10 · §1.4, §2.3 (`spatial: movement, cover, provokes`)
- **Deliverables:** pack-declared movement allowance per move; provoke rules (leaving a threat's reach logs who it provokes, which can be answered with a reaction); region cover and terrain readable in rule expressions; annotations can use them.
- **Acceptance:** moves respect the allowance on both backends; provokes are logged and replay; derived tags can read cover.

### T0.21 Watches and calendar — `done`
- **Plan:** P0.11 · §2.2 (Clocks and time)
- **Deliverables:** pack-declared time units (for example watches within days), `advance_time`, the current date in state, and clocks that can be scheduled on in-world time as well as on sessions.
- **Acceptance:** time advances and rolls over units correctly, is logged, replays, and drives a time-scheduled clock.

### T0.22 Remaining Phase 0 test gaps — `done`
- **Plan:** P0.3, P0.5, P0.6, P0.12
- **Deliverables:** a default tactical profile in `core`; a test that flipping one control changes only the affected role's schema; harness runs of a 3-session campaign under all-strict, all-standard, and default settings, each with a mid-campaign change; evaluator property tests (termination, determinism, rounding per pack).
- **Acceptance:** each BUILD_PLAN test line named above has a test.

### T0.23 Last Phase 0 gaps from the second audit — `done`
- **Plan:** P0.4, P0.5 · §2.6, §2.7, §2.13.3, Appendix C `hook_runtime_limits`
- **Deliverables:** the `trigger_procedure` primitive (a pack effect that runs a procedure and applies its outcome's effects); a test that every primitive emits events and replays exactly; the toggle test's mid-encounter case; seat-override schema regeneration tested; the hook runtime's memory limit (`max_memory`).
- **Acceptance:** BUILD_PLAN P0.4's primitive and toggle tests and P0.5's "only affected seats' schemas change" have tests; no primitive is reserved; a hook cannot exhaust memory.

### T0.24 `scene_closed` marker — `done`
- **Plan:** P0.1, P0.4 · §5.7
- **Deliverables:** a `scene_closed` event emitted when a scene ends (at the next `set_scene` or at `end_session`), after the events that close it (`encounter_ended`, condition expiry) and before the next `scene_set` or `session_ended`. It folds to a `closed` flag, so no scene closes twice; older logs fold unchanged.
- **Acceptance:** every scene in a campaign is closed exactly once, in order; older logs fold unchanged; replay stays byte-identical.

### T0.25 Condition stacking — `done`
- **Plan:** P0.3 · §2.3 (`conditions: stacking`), §2.4
- **Deliverables:** a pack-declared `stacking` rule per condition: `none` (held or not; the default) or `intensity` (re-applying raises a level, up to `max_level`, and modifiers scale with it). Effects and expiry respect it, expressions can read a condition's level, and lint checks the declarations. A `duration` mode was dropped (D-039): conditions end at scene or session boundaries, so there is no counted duration to refresh or extend.
- **Acceptance:** each stacking rule behaves correctly under repeated application and removal, and replays exactly; conditions without a rule behave as now.

### T0.26 Weight-based inventory — `done`
- **Plan:** P0.3 · §2.3 (`inventory: { model, limit_expr }`)
- **Deliverables:** `inventory: { model: abstract | weight, limit_expr }`, with a pack item catalogue carrying weights; `create_item` and `transfer_item` refuse an item that would exceed the holder's limit; a carried-weight value readable in expressions (for an encumbrance tag). `slots` stays out of scope for now (owner, 2026-10-26).
- **Acceptance:** weight limits are enforced atomically on every item primitive; the abstract model behaves as now; replay is exact.

### T0.27 Progression — `done`
- **Plan:** P0.15 · §2.3 (`progression`), §2.4, §1.5
- **Deliverables:** BUILD_PLAN P0.15.
- **Acceptance:** BUILD_PLAN P0.15's test and its Gate P0 line.

### T0.38 Fourth audit: seats, sessions, authority, silent inputs, store and deploy safety — `done`
- **Plan:** P0.1, P0.4, P0.12, deployment tooling · §3.1, §5.4, §2.6, §2.13.5, §5.6, §3.3 · D-053, D-054, D-055
- **Deliverables:**
  - campaign seats and GM traits are validated, with at most four players and one GM;
  - sessions open and close in turn, and a scene needs an open session;
  - `set_scene`, `create_clock` and `advance_clock` are GM-only; session control is the GM's or the operator's;
  - a currency amount that rolls below zero counts as zero, and self-transfers are refused (both linted);
  - GM inputs a procedure would not use are refused, not dropped;
  - `resolve_unmodelled` names bad stats, takes an opposed `target`, and picks the ladder by rung;
  - deck hands follow control;
  - forks are atomic and range-checked;
  - the CLI refuses missing stores and empty backups;
  - a release history makes rollback and pruning safe, and dirty deploys need `--allow-dirty`;
  - the pre-push hook refuses uncommitted changes;
  - offline tests cannot open sockets;
  - a fresh scaffold runs a smoke campaign;
  - `engine.py` is split.

  The encounter join/leave gap is proposed as REV-ARCH-1.9, not built.
- **Acceptance:** `tests/test_authority_and_lifecycle.py`; golden fixtures unchanged; `tob check` passes.

### T0.37 Leak sweep, effect parameters, formula maxima, canon speed — `done`
- **Plan:** P0.4, P0.7, P0.9 · P3, §2.6, §2.10, §6.5 · D-052
- **Deliverables:** every player-reachable command and read swept for hidden-entity names: `current_turn(seat)` and the results of `end_turn` and `next_round` hide unseen entities, out-of-turn and turn-ending errors say "someone else", a player hands off only to someone they can see; effect parameters closed per primitive (`OPTIONAL_PARAMS`); a resource `min` checked against a formula `max` at the stats' defaults and extremes; the dead post-merge duplicate-id checks removed; canon writes no longer rebuild the index (it extends in place) and near-collision checks only compare names whose length could match; command backups use a JSON-shaped copy instead of `deepcopy`; the session-open scan is incremental.
- **Acceptance:** tests in `tests/test_robustness.py`; event streams and golden fixtures unchanged; `tob check` passes.

### T0.36 ARCHITECTURE 1.8 and BUILD_PLAN 1.7 — `done`
- **Plan:** item 12 of the third audit · D-051
- **Deliverables:** §2.3 chargen options, §2.5 example procedures as implemented, §2.8 `core.pool` marked later, §7.1 `rule_on_action`; BUILD_PLAN P0.12 describes the harness as built; revision notes in both. The kernel no longer reads the wall clock by default (timestamps come from the host).
- **Acceptance:** the docs match the build; `tob check` passes.

### T0.35 Starting equipment; the GM substitutes a move — `done`
- **Plan:** P0.4, P0.8 · §1.5, §2.13.1 · D-050
- **Deliverables:** chargen choice options may grant `items` and `currencies` (each-player ones), checked by lint and against the carry limit; `commit_action(gm={"substitute": move})` lets the GM rule that the fiction triggered another fiction move (any legal one under standard, an eligible one under strict), logged as `action_committed.declared` and a GM `judgement_input` (`fiction_triggers`); `rule_on_action.substitute` is an enum of the pack's fiction moves.
- **Acceptance:** `tests/test_grants_and_substitution.py`; `tob check` passes.

### T0.34 Third audit: misspelt keys, expression names, contradictions — `done`
- **Plan:** P0.5, P0.7 · §2.3, §2.10 · D-049
- **Deliverables:** `kernel/packschema.py`: unknown keys refused for every mapping §2.3 defines (and rule cards and vocabulary entries); every name an expression reads resolved where it is evaluated (an entity's own formulas, rules in play, tactical rules); presentation rounding, assertion terms, vocabulary ids, fudgeable procedures, stat defaults, currency starts, spend amounts, action modes and targets checked. Expressions read a currency the entity does not hold as 0.
- **Acceptance:** a defect test for each in `tests/test_packs.py`; every shipped pack lint-clean; `tob check` passes.

### T0.33 Third audit: ids, leaks, reactions, errors, snapshots — `done`
- **Plan:** P0.1, P0.3, P0.4, P0.10 · §5.2, §5.6, §7, P3 · from the third Phase 0 audit (2026-10-27), D-048
- **Deliverables:** entity, clock, and scene ids checked (pattern, reserved names) and names non-empty, so state stays canonical; scene flags and spawned stats type-checked; errors from `commit_action` and `draw_card` name only what the caller can see, and point at `spawn_entity` (§5.2); `trigger: reaction` passes lint; reads name an unknown entity instead of raising `KeyError`; settings and canonical errors surface as `EngineError`; snapshots at every scene set, session start and end, and before every encounter; `Engine.load` checks the hash chain and resumes from the latest snapshot taken under the same pins.
- **Acceptance:** `tests/test_robustness.py`; `tob check` passes.

### T0.32 The GM's currency pool; ARCHITECTURE 1.7 — `done`
- **Plan:** P0.4 · §2.3 (`gm`), §2.4 meta-currency · `docs/dev/proposals/REV-ARCH-1.7.md` (owner-approved), D-047
- **Deliverables:** `holder: gm` is one pool on the GM's side (`state.currencies.gm`), drawn on by every GM-side entity; the effect target `gm` feeds or spends it from anyone's effect; `visible` flag (lint: boolean); lint refuses `target: gm` outside a GM-held currency's earn or spend; `lethality_levers` declared by a pack is a `reserved` warning. ARCHITECTURE 1.7 applied (version, revision note, §2.3 `gm` block).
- **Acceptance:** tests for each; `tob check` passes.

### T0.31 Second Phase 0 audit fixes — `done`
- **Plan:** P0.1, P0.4, P0.5, P0.6, P0.7 · §2.3 (`gm`), §2.4 (who rolls, meta-currency) · from the second audit (2026-10-27), D-046
- **Deliverables:** `gm_rolls: false` enforced: no GM-side entity rolls, as the actor or the opposed side; rolling actions are not offered to it; lint refuses a resource or track trigger that would make one roll. `holder: party` is one shared pool; an unknown holder fails lint. The loader refuses an id declared twice in one pack file (the merge used to fold it unseen). Tests for every untested lint class and for removing a condition an inherited action uses. The verifier checks the kernel pin and each snapshot's pins. `tob pack lint` reports rules-text size against its budget. AGENTS.md no longer says P0 is unfinished.
- **Acceptance:** tests for each; `tob check` passes. The GM-held currency and the §2.3 wording wait for the owner: `docs/dev/proposals/REV-ARCH-1.7.md`.

### T0.30 Log every GM call — `done`
- **Plan:** P0.4 · §2.13, D-044 (owner answer to the audit's question 5)
- **Deliverables:** `@gm_call` on every GM-callable command; a coverage test over the generated GM tools; EVENTS.md and AGENTS.md updated.
- **Acceptance:** each GM call logs its arguments and options; engine, operator, player, and refused calls log nothing; every GM tool is covered; `tob check` passes.

### T0.29 Phase 0 audit fixes — `done`
- **Plan:** P0.3, P0.8, P0.15, P0.12 · from the audit after sign-off (2026-10-27)
- **Deliverables:** progression works with stats that have no `range`; lint refuses advances that change nothing or name tags the pack does not list; the own sheet shows progress (points, pending, advances taken, options); `sheet_problems` checks condition levels and progress; `progression_active()` replaces `advance_models()`; the CLI prints UTF-8 on a legacy Windows console; parsed pack YAML is cached by content and read with libyaml when installed.
- **Acceptance:** tests for each; `tob check` passes, faster.

### T0.28 Harm declaration — `done`
- **Plan:** P0.3 · §2.3 (`harm`), D-036
- **Deliverables:** `entity_model.harm: { targets: [resource or track ids] }`, targets only; a `harm_state(entity)` read for later systems; lint (targets exist, no trigger keys).
- **Acceptance:** both demo packs declare harm and lint clean; `harm_state` reports each target's value, bounds, and which way is worse.

### T0.13 Gate P0 sign-off — `done`
- **Agent prepares:** evidence for every Gate P0 item in `HANDOFF.md`, as the commands run and their results.
- **Owner signs off.** Signed off 2026-10-26: every item ticked in HANDOFF and BUILD_PLAN, and ARCHITECTURE 1.6 applied.
- **Re-opened 2026-10-26:** T0.24 to T0.28 (owner decisions on the 1.6 draft) came first; all are done.
- **Prepared 2026-10-18, refreshed 2026-10-26** after T0.12 and T0.17 to T0.22 finished Phase 0. The evidence table is in `HANDOFF.md`. Item 8 and the hook return shape (D-033) were accepted for now, to be re-audited with the P0 architecture.

---

## Track 1 — Phase 1: first agent

Read `docs/dev/ADAPTERS.md` before T1.3–T1.5.

### T1.1 Schema validator — `ready` · *parallel-safe*
- **Plan:** P1.2 · §2.13.4, §7.5
- **Deliverables:** `orchestrator/validate.py`, which validates tool arguments against the kernel's schema dialect (`enum`, `oneOf`, integer `minimum`/`maximum`, `type: array` with `items`/`maxItems`, `format: id`, `x-narrative`). It returns structured errors that name the field and the valid options. No external dependency.
- **Acceptance:**
  - Every schema produced by `kernel/tools.generate` validates correct calls and rejects malformed ones.
  - Under strict settings, a free number in an enum field is rejected with the list of valid ids.

### T1.2 Tool dispatcher — `blocked` (T1.1)
- **Plan:** P1.2 · §7.1, §2.12, P3
- **Deliverables:** `orchestrator/dispatch.py`, which maps `(seat, tool_name, args)` to engine commands.
  - It uses the seat's generated schema, so a tool that isn't in the schema is an *unknown tool*, not a permission error.
  - It returns structured results the model can read.
  - It records new passive events `tool_call` and `tool_error`.
- **Design notes:** expose only tools whose backing exists. Tools that depend on T0.2 or T0.3 stay absent until those land. Error messages carry the engine's suggestions.
- **Acceptance:**
  - A player calling `read_prep` or `rule_on_action` gets an unknown-tool error.
  - 200 malformed calls reach the engine zero times.
  - ID errors return a suggestion.
  - Both demo packs dispatch through regenerated schemas with no code change.

### T1.3 Mock adapter — `ready` · *parallel-safe*
- **Plan:** P1.1 · §3.3
- **Deliverables:** `adapters/mock.py`, an `AgentAdapter` that serves scripted `Bid`s and `ActResult`s, including malformed tool calls and refusals for negative testing.
- **Acceptance:** used by the T1.2 and T1.7 tests; fully offline.

### T1.4 Recording transport — `ready` · *parallel-safe*
- **Plan:** P1.1 · §7.5
- **Deliverables:** `adapters/transport.py`, a transport interface with three modes: `live`, `record`, and `replay`.
  - Recorded exchanges are written to `tests/fixtures/cassettes/` with credentials and auth headers stripped.
  - Replay matches requests by a canonical hash.
- **Acceptance:** a recorded cassette replays offline with identical results, and a test asserts that no cassette contains anything matching a key pattern.

### T1.5 First provider adapter — `blocked` (T1.2, T1.3, T1.4)
- **Plan:** P1.1 · §3.3, §4.2, §7.5
- **Provider (D-013):** Anthropic (Claude). The owner will supply the key from a dedicated account when live work starts.
- **Deliverables:** `adapters/<provider>.py`, implementing:
  - schema translation from the kernel dialect to the provider's tool format
  - validation-before-engine via T1.1
  - one retry, then degrade to `pass`
  - refusal detection
  - an 800 ms bid timeout
  - usage accounting (tokens in, out, and cached; latency) recorded as events
  
  Pin the provider SDK in an optional dependency group, `pip install -e ".[<provider>]"`.
- **Acceptance (offline):** T1.2's malformed-call suite passes through this adapter using cassettes. Refusals map to `pass`.
- **Acceptance (live, with approval, `TOB_LIVE=1`):** a short session runs and records cassettes.

### T1.6 Context assembler — `blocked` (T1.2)
- **Plan:** P1.3 · §6.1, §6.5
- **Deliverables:** `orchestrator/context.py`.
  - Layered assembly, static-first, so the provider prefix cache holds.
  - Per-beat token budgets with the degradation ladder (notes → transcript → non-scene canon → digest only), logged.
  - A token-estimation interface, so the adapter can supply the provider's tokenizer.
  - Canon layers use T0.2 when available and empty providers until then.
- **Acceptance:** layer order is stable across beats; forced overruns trigger the ladder in order; instrumentation reports tokens by layer.

### T1.7 Single-agent play loop — `blocked` (T1.5, T1.6)
- **Plan:** P1.4
- **Deliverables:** `orchestrator/loop.py`, with a scripted GM driving one adapter-backed player through 100 beats.
- **Acceptance:** zero state corruption, zero illegal actions, zero isolation breaches. A short run on the second pack works without code change.

### T1.8 Metrics report — `blocked` (T1.7)
- **Plan:** P1 gate · §6.5 (instrumentation)
- **Deliverables:** `tob report <db>`, which reads the event log and reports:
  - tool-failure rate per provider
  - prefix-cache hit rate on static layers
  - layer-3 retrieval rate
  - degradation counts
- **Acceptance:** the numbers match a hand-checked fixture log.

### T1.10 Player notes — `blocked` (T1.2)
- **Plan:** P1.2 · §6.4, §7.1, D-011
- **Deliverables:** `orchestrator/notes.py` with the tools `write_note(text, tags)` and `search_notes(query)`.
  - Notes are private per seat, stored as passive events, and structured as fact, subject tag, and session, with free text.
  - Notes are never validated against canon and never corrected by the engine. They are each agent's own, possibly wrong, copy of canon (D-011).
  - Note tools are absent during breaks (§6.4, P5).
- **Acceptance:**
  - No seat can read another seat's notes; there is no tool for it.
  - A note that contradicts canon is stored and returned unchanged.
  - Notes never appear in GM prep or canon.

### T1.9 Gate P1 sign-off — `human`
- **Agent prepares:** evidence for each Gate P1 item.
- **Owner signs off,** after Gate P0.

---

## Track 2 preview — Phase 2 (not yet decomposed)

P2.1 remaining adapters · P2.2 scheduler (deterministic bids, discretionary bids, award, timeouts, speculative bidding) · P2.3 interruption · P2.4 pacing watchdog · P2.5 trait wiring · P2.6 scenario harness · P2.7 recaps · P2.8 metrics · P2.9 human evaluation.

When Track 1 reaches T1.7, propose a T2.x breakdown in `HANDOFF.md` for approval. Use the same format as above. Treat Gate P2 as the critical gate (BUILD_PLAN).

# Table of The Basilisk — Build Plan

**Companion to:** `ARCHITECTURE.md` (referenced throughout as §)
**Purpose:** phased implementation with discrete steps, testable deliverables, and hard gates.

**Revision notes (1.1):** P0 now builds a system-agnostic rules kernel and proves it against two system packs from different resolution families (§2). P5 now builds the donation Board, break time, and the audience-text hardening pipeline (§9.7–§9.9). Section references follow the renumbered architecture document.

**Revision notes (1.2):** P0 adds determinism controls — difficulty ladders, derived modifiers, consequence tables, enum-only schemas under strict settings (§2.13). P4 adds rule cards: every action or rule used in a campaign appears on the livestream as a popup card (§8.6). P4 steps after the overlay are renumbered.

**Revision notes (1.3):** Determinism settings are per role and per control, defaulting to **players strict, GM standard**, and are changeable mid-campaign — by config between sessions, or by an operator control that applies changes at the next scene boundary (§2.13.3, §9.3).

**Revision notes (1.4):** The broadcast pack is the SRD 5.1 under CC-BY 4.0 (not the OGL 1.0a release) with sectioned rules text, which is now in v1 (§1.1, §2.11). Every phase through P3 develops against the kernel test packs, so no work is tuned to one ruleset. P0.13 builds sectioned rules text and proves it on a data-only fixture variant. P0.14 adds pack-declared excluded terms: names a licence does not cover, refused in canon and checked before TTS. The broadcast pack is written as late as possible, in P4.0, and gates Phase 4.

---

## 0. How to use this document

### 0.1 Build order is load-bearing

The temptation is to build toward the visible payoff — the stream, the voices, the map. **Resist it.** The deterministic core and the scheduler must exist and be instrumented before any personality work can be *evaluated*, because without measurement you are tuning twelve interacting dials by vibes against a four-hour session.

The same applies inside P0. The temptation is to build the kernel against the one game you intend to ship and generalise later. **Resist that too.** A kernel tested against one system silently takes that system's shape, and the leaks only show when you try a second. The second pack is built in P0, not afterwards.

The phases are ordered so that each one is independently testable and each one de-risks the next.

### 0.2 Gates are hard

Every phase ends with a gate: a set of measurable conditions. **Do not proceed past a failed gate.** The gate at the end of P2 is the most important one in the project and the one most likely to be skipped.

### 0.3 Phase summary

| Phase | Builds | Testable without | Est. weight |
|---|---|---|---|
| **P0** | Rules kernel, system packs, deterministic core | Any LLM | Large |
| **P1** | One agent, one provider, tool API | Scheduler, broadcast | Medium |
| **P2** | Four agents, adapters, scheduler | Broadcast | **Largest / riskiest** |
| **P3** | Session 0, prep, validation, full loop | Broadcast | Large |
| **P4** | Renderer, TTS, overlay, stream | Audience | Medium |
| **P5** | Donation Board, break time, audience-text hardening | — | Medium |

### 0.4 Pre-build verification

Complete before writing code (§11.3):

- [ ] License terms confirmed current for the source material of every planned system pack; attribution text obtained
- [ ] Provider ToS reviewed for multi-model public performance
- [ ] Legal review of the donation and Board structure initiated (can run parallel through P4)
- [ ] Platform paid-message and payment-processor terms reviewed
- [ ] Data-protection review initiated for storing donor names and messages, including retention and erasure
- [ ] Provider accounts, rate limits, and cheap-tier availability confirmed for all 5 seats

---

## Phase 0 — Rules Kernel and Deterministic Core

**Goal:** a complete, correct, system-agnostic game engine with no LLMs anywhere in it, proven against two system packs from different resolution families. Everything in §2, §5, §1.3, §1.4, §1.5.

**Why first:** this is the system's foundation of truth. If it is wrong, every layer above inherits the error and you will misattribute engine bugs to model behaviour for months. It is also the cheapest point at which to discover that the kernel quietly assumes one game.

### P0.1 Event store

- Append-only log, schema per §5.7
- Monotonic `seq` as the ordering authority
- Fold-to-state with no side effects
- Snapshot write/read at arbitrary `seq`
- Fork: branch a campaign at any `seq` into a new campaign ID
- First event and every snapshot record `pack_hash` and `kernel_version` (§2.9)

**Test:** replay any log to any `seq` and get byte-identical state. Fork at `seq` N, replay both branches, confirm divergence only after N. Attempt replay against a different pack hash or kernel version and confirm refusal.

### P0.2 Randomizer service

- Seeded from `(master_seed, roll_counter)`, per §5.5
- Dice grammar parsed to an AST; operator set enabled per pack — sums, keep/drop, exploding, success counting, roll-under, Fate dice, step dice (§2.4)
- Seeded decks (shuffle, draw, reshuffle rules) and lookup tables on the same stream
- Every roll and draw emits an event with the seed derivation recorded
- `peek_roll` path with the direction-of-drama constraint evaluated by outcome rank (§2.5), and the frequency cap

**Test:** same master seed → identical sequence across runs. 10,000-roll distribution test per operator and die type; exact-distribution check for every roll expression in each shipped pack. Verify `peek_roll` refuses any reroll that worsens the party's position, on both packs' outcome scales.

### P0.3 Entity model and expression language

- Stats, derived values, resources, tracks, conditions, tags, inventory, harm — all pack-declared, none hardcoded (§2.2–§2.3)
- Expression evaluator: integer-only, pack-declared rounding, total, terminating, side-effect-free
- **Kernel noun lint** in CI: the build fails if a system term (`hp`, `ac`, `stress`, `advantage` …) appears in kernel source

**Test:** property tests on the evaluator — termination, determinism, rounding per pack. Lint passes on the kernel and fails on a deliberately polluted copy.

### P0.4 Effects, resolution, and turns

- Closed set of primitive effects (§2.6); compound effects composed from pack data
- Resolution runner: modifiers → roll → interpret on an ordered outcome scale → apply (§2.5)
- GM ruling slots (`request_gm_ruling`) and `trigger: fiction` action handling
- Turn and mode controller: free play and encounter modes; the ordering and action-economy strategies in §2.4
- Meta-currencies: earn/spend by holder
- **Determinism settings** (§2.13): difficulty ladders and derived difficulty; situational tags with automatic derivation from state; consequence tables with seeded, `lethality`-weighted draws; eligibility rules for fiction-triggered moves; enumerated spend amounts
- Settings resolved per role and per control from presets, overrides, and seat overrides; defaults players strict, GM standard
- Mid-campaign changes: `determinism_change_requested` queued, `determinism_changed` applied at the next scene boundary or session start; anything open at the change (encounter, ruling slot, roll) finishes under its starting settings; cooldown enforced
- `judgement_input` events for every model-chosen mechanical input, recording the list it was chosen from

**Test:** every primitive emits events and replays exactly. The three reference procedure shapes in §2.5 resolve correctly against hand-computed outcomes. Every turn-order strategy cycles correctly through a scripted encounter. Derivable tags are applied automatically under every setting and cannot be added or removed by hand. Consequence draws replay exactly from the seed. **Toggle test:** request changes mid-scene, mid-encounter, and with a ruling slot open; confirm each applies only at the next scene boundary, open items finish under their starting settings, a second change inside the cooldown is refused, and the whole campaign replays byte-identically.

### P0.5 System pack loader

- Schema validation for §2.3
- Inheritance and merge rules (§2.8): deep-merge maps, ID-keyed catalogues, explicit removals, post-merge reference validation
- Resolution to a flattened pack; content hash; pinning (§2.9)
- Hook registry and sandboxed hook runtime enforcing the determinism contract (§2.7)
- Tool-schema generation from the resolved pack, including absence of unsupported tools (§2.12)
- Per-role argument generation: enums for controls on strict, bounded values for controls on standard; regeneration of affected seats' schemas when settings change (§2.13)

**Test:** load, validate, flatten, and hash — identical hash across runs and machines. Child-pack overrides and removals apply exactly; removing a condition still referenced by an inherited action fails with a named error. A pack referencing an unregistered hook is refused. A hook that reads the clock, performs I/O, or draws its own randomness fails the contract and the pack does not load. Generate schemas for both packs under all-strict settings and confirm no argument with mechanical effect accepts a free number or free text; under standard, confirm out-of-bounds values are rejected. Flip one control and confirm only the affected role's schema changes.

### P0.6 Baselines and first packs

- `core` — the abstract baseline: shared scaffolding, opposed checks, default tactical profile, generic detail tables
- Family baselines: `core.roll_over` and `core.banded`
- **The playable pack** (`lanternlight`, roll-over), extending its baseline. Measure `full_text` token count against the context budget with room for all other layers
- **A second complete pack from a different resolution family** (`tidewrack`, banded 2d6), complete enough to play a scripted campaign, with its own family baseline. **Not a stub.** A stub proves loading works; only a second real game proves the kernel is a kernel.
- **A data-only sectioned variant** of the playable pack: it switches `rules_text` to sectioned with a digest and changes nothing else (P0.13)

Through Phase 3, "the playable pack" means `lanternlight` and "the second pack" means `tidewrack`. These are original test games, not the broadcast game. The broadcast pack (SRD 5.1) arrives in P4.0.

**Test:** both packs load, pass conformance (P0.7), and run under the same kernel build. Record the hook count for each pack. The sectioned variant passes conformance and its scripted campaign produces the same event stream as its parent, apart from rules-lookup events.

### P0.7 Pack conformance suite and authoring tooling

- `pack new <id> --extends <baseline>` scaffold, which resolves and passes conformance on creation
- Static lint per §2.10: references, outcome-scale ordering, condition exits, chargen coverage, roll-expression validity, schema generation, rules-text budget, rule-card data and length limits
- Strict-readiness report per control (§2.13); controls the pack cannot support on strict are marked unavailable and rejected by config validation
- Generated property tests: chargen validity, every action resolvable, every outcome band reachable, no effect sequence yields an invalid sheet, double-run determinism including hooks
- Golden fixtures: `(seed, state, scripted actions) → expected event stream`, run on every kernel change

**Test:** introduce one defect of each lint class into a copy of a pack; confirm each is caught with a useful message. **Derived-pack test:** build a house-rules pack extending the playable pack — a changed resource, a new condition, a removed action — as data only, and confirm it passes conformance with no kernel change.

### P0.8 Character sheets and chargen

- Sheet schema from the pack's entity model
- Engine-only mutation, via effects (§5.4)
- Chargen runner (§1.5): roll, assign, and choice steps; `unique_per_table`; campaign detail tables
- Read views: full (own), summary (party)

**Test:** 1,000 generated characters per pack, all schema-valid. Attempt direct mutation via the read API and confirm rejection. Confirm a `unique_per_table` choice cannot be taken twice at one table.

### P0.9 Canon store

- Record schema per §1.3.1 (`origin: prepped | improvised` — no audience origin)
- **Alias table** — name/alias/partial → ID, with collision and near-collision detection
- **Relation graph** — ID → related IDs, built at write time
- Append-only with `superseded_by`; no edit path exists
- Knowledge-state filtering: `secret` records physically absent from the player-scoped index
- **Scene bundle assembler** (§6.5 Layer 1) — graph traversal from location + cast IDs, including active secrets for the GM
- Canon digest generator (stub; Utility Model fills it in P3)

**Test:** write 200 records; confirm player-scoped queries never return a `secret`. Confirm alias resolution on partial and colloquial names. Confirm scene bundle assembly is a pure graph traversal with zero vector calls.

### P0.10 Spatial engine

- `SpatialBackend` interface
- `ZoneGraph` and `RangeBands` implementations; `spatial: none` handling
- Pack-supplied movement, cover, provoke, and band rules
- Visibility computation with per-observer `visible_to`
- **Candidate generator** (§1.4.2): kernel heuristics weighted by the pack's tactical profile; annotations from pack templates
- **Mastery tiering** (§1.4.3) — the count/annotation table, with pack-declared annotation categories
- `preview` and `commit` resolution paths

**Test:** for every enumerated move, confirm legality, on both backends and both packs. Confirm a low-mastery tier is a strict subset in *information* but never returns an illegal option. Confirm no coordinate ever needs to leave the engine.

### P0.11 Clocks and time

- Faction clocks: fill, total, visible flag
- Off-air advancement scheduler (§7.6.2 axiom 15)
- Round/turn/watch/calendar tracking

**Test:** advance clocks across simulated sessions with no party interference; confirm canon records are emitted for each world change.

### P0.12 Scripted-actor harness

A test driver that plays the game via the tool API using **hardcoded scripts, not models**. This is the instrument that makes P0 verifiable and remains useful through every later phase.

Pack-agnostic: scripts drive the generated tool surface, and a generic smoke script takes every enumerated action at least once.

**Test:** run a scripted 3-session campaign end to end **on each pack**, under all-strict, all-standard, and default (players strict, GM standard) settings, with one mid-campaign settings change in each run. Zero LLM calls. Confirm each event log is complete and replayable.

### P0.13 Sectioned rules text

- Section schema in the pack loader: `digest`, `sections` with `id`, `title`, `aliases`, `body`, `refs`, optional `parent`, and `max_section_tokens` (§2.3, §2.11). No section taxonomy is built in.
- A deterministic section index built from the resolved pack: exact ID, catalogue ref, alias key, partial match. Key normalisation is shared with the canon index.
- A `query_rules` engine query: key-first, returns suggestions on a miss, and logs every lookup
- Lint: digest budget, section caps, alias uniqueness, `parent` resolution without cycles, catalogue coverage

**Test:** every section is reachable by its ID and by each alias. Every catalogue ID resolves to a covering section. Misses return suggestions. One defect of each new lint class is caught. Index construction is byte-identical across runs. Inline packs that declare sections are searchable the same way.

### P0.14 Excluded terms

- `meta.excluded_terms` in the pack schema, inherited and merged like other catalogues (§2.3, §2.8)
- One deterministic matcher, sharing canon's key normalisation: case-insensitive, whole words, aliases included
- `write_canon` refuses any record whose names, aliases, or text contain an excluded term, naming the term in the error (§1.2)
- Lint: no excluded term collides with a catalogue ID, vocabulary label, rule-card title, or section title
- The matcher is exposed for the validation pass (P3.3) and the TTS gate

**Test:** a fixture pack declares excluded terms. Canon writes containing a term, an alias, or a differently cased form are refused atomically. Near-miss words that only contain a term are accepted. A colliding term fails lint. Results are byte-identical across runs.

### ✅ Gate P0

- [ ] Full campaign replay is byte-identical from the event log, on both packs
- [ ] Fork at any `seq` produces correct divergent branches
- [ ] 10k-roll distribution passes for every operator and die type in use
- [ ] Zero `secret` leakage across 1,000 player-scoped canon queries
- [ ] Zero illegal moves across 10,000 enumerated candidates, per backend
- [ ] Mastery tiers produce measurably different option sets on identical tactical states
- [ ] Scripted 3-session campaign completes on each pack with no LLM involvement
- [ ] **The second pack runs with zero kernel code changes made for it**
- [ ] Kernel noun lint is clean
- [ ] Every hook in every shipped pack passes the determinism contract
- [ ] Replay against a mismatched pack hash or kernel version is refused
- [ ] A derived house-rules pack is built as data only and passes conformance
- [ ] Both shipped packs are strict-ready on every control and carry rule-card data for every action, procedure, condition, currency, and tag
- [ ] For every control set to strict, zero model-supplied numbers reach resolution from that role — enforced by schema, confirmed by auditing `judgement_input` events
- [ ] Mid-campaign settings changes apply only at scene boundaries and replay byte-identically
- [ ] Inline and sectioned rules text both pass conformance, and the sectioned variant runs with zero kernel code changes made for it
- [ ] `query_rules` resolves 100% of section IDs, aliases, and catalogue refs in every shipped pack
- [ ] Zero canon records containing an excluded term are accepted, across scripted campaigns on a pack that declares them

---

## Phase 1 — First Agent

**Goal:** prove a single LLM can play the game through the tool API without breaking isolation or state.

**Scope discipline:** one provider, one agent, no scheduler, no GM. A human or script plays GM. This phase is about the *interface*, not the table.

### P1.1 Adapter layer, first provider

- Internal interface: `bid()`, `act()`, `recap()`, `prep()`
- Tool-schema translation for the chosen provider
- **Validation before the engine** (§7.5): unknown tool, malformed args, nonexistent IDs
- **Fuzzy ID repair** against the alias table and pack catalogues, returning suggestions
- One-retry-then-degrade path
- Refusal detection
- Every call, error, and retry logged as an event

**Test:** inject 200 malformed tool calls; confirm none reach the engine and all produce structured errors. Confirm ID repair converts the majority of ID errors — entity and pack IDs alike — into successful retries.

### P1.2 Tool API surface

- Full player tool set per §7.1, generated from the pack and permission-scoped
- GM tools present but unexposed to the player role
- **Confirm `read_prep` and `peek_roll` are absent from the player schema**, not merely denied
- Schema regeneration for the second pack: same tool names, pack-specific arguments and enumerations; tactical tools absent under `spatial: none`; `peek_roll` absent from the GM schema when the pack's GM does not roll

**Test:** enumerate the player's advertised tool list; confirm GM-only tools do not appear. Attempt a GM tool by name and confirm an unknown-tool response, not a permission denial. Diff generated schemas across both packs and confirm only arguments and enumerations differ. With the GM switched to strict, submit a free numeric difficulty and a free-text ruling; confirm the adapter rejects both and returns the valid IDs. With the GM on standard (the default), confirm a difficulty outside the pack's range is rejected.

### P1.3 Context assembler

- Layered assembly per §6.1, **static-first ordering**
- Prefix-cache preservation verified against the provider
- Token budget enforcement with the degradation ladder (§6.5)
- Per-beat instrumentation: tokens by layer, cache hits, retrieval calls by layer

**Test:** measure prefix cache hit rate across a 100-beat session; target >80% on layers 1–4. Force budget overruns and confirm the degradation ladder fires in order and logs each step.

### P1.4 Single-agent play loop

- Agent takes turns, calls tools, posts to table
- Scripted GM provides scene-setting and adjudication, including filling ruling slots
- Full event logging

**Test:** a 100-beat session with one agent on the playable pack, and a shorter run on the second pack. Zero state corruption, zero illegal actions, zero isolation breaches.

### ✅ Gate P1

- [ ] Tool-failure rate <2% after repair, over 500 calls
- [ ] Zero illegal actions reach the engine
- [ ] Zero isolation breaches (no access to prep, secrets, or other-agent notes)
- [ ] Prefix cache hit rate >80% on static layers
- [ ] Degradation ladder fires correctly under forced budget pressure
- [ ] Layer-3 (vector) retrieval fires on <10% of canon queries
- [ ] The agent plays the second pack through regenerated schemas with no adapter change

---

## Phase 2 — The Table

**The phase that decides whether the project works.** Four players, four providers, the scheduler, and the pacing system. No broadcast, no visuals, no voices — pure text, run offline, measured. Run on the playable pack; the second pack waits until P3.

**Warning:** this phase is unglamorous and will feel slow. It is also where every failure mode of multi-agent LLM systems lives. Budget more time than feels reasonable and do not skip the gate.

### P2.1 Remaining adapters

- Adapters for providers 2–5
- Per-provider capability matrix: tool-call reliability, structured-output reliability, refusal profile, latency distribution, cheap-tier availability
- Normalize everything to the internal interface

**Test:** identical scripted scenario through all five adapters; diff behaviour. Record per-provider tool-failure and refusal rates as the baseline for §3.3 seating decisions.

### P2.2 Scheduler

- **Stage 1** — deterministic bids, no model calls (§4.1), with turn order taken from the pack's turn structure
- **Stage 2** — discretionary bids, cheap tier, structured return
- **Stage 3** — award scoring with trait multipliers
- **800ms hard timeout** with deterministic fallback (§4.2)
- **Speculative bidding** for beat N+1 during beat N generation
- Silence as a positive outcome below `FLOOR_THRESHOLD`
- `pass()` handling
- Thinking-time pauses after consequential GM beats
- Mode hook for break mode (implemented in P5.4) — the scheduler is built so modes swap stage rules and schemas cleanly

**Test:** confirm the majority of beats resolve at Stage 1 with zero model calls. Confirm a deliberately slow provider still wins the floor via deterministic bids. Measure beat latency distribution with and without speculation.

### P2.3 Interruption

- Sentence-chunked streaming generation
- Interrupt check after each chunk against `INTERRUPT_MARGIN`
- **Partial text retained on cut** — this is the point
- Elevated deterministic bid for the interrupted agent next beat
- Kind gating, GM-narration protection, per-scene rate limit

**Test:** force interrupts at known thresholds; confirm partial text is preserved and the interrupted agent reliably resumes. Confirm zero interrupts during GM scene-setting.

### P2.4 Pacing watchdog

- Utility Model integration
- Detectors: stall, loop, convergence, starvation, drag (§4.5)
- Four-step escalation ladder, gentlest first
- **Confirm the watchdog never writes dialogue** — only weights and GM instructions

**Test:** construct deliberate stall and politeness-loop scenarios; confirm detection and correct escalation level. Confirm no watchdog-authored text reaches the table.

### P2.5 Trait implementation

Every axis in Appendix A wired to its mechanism. Critically, the **information-control** ones:

- `rules_mastery` → enumeration tiering (already built in P0.10, now wired to traits)
- `attention` → recent-beat fidelity degradation
- `memory_fidelity` → recap corruption (P2.7)
- `metagaming` → secret-leak injection, logged as `leak_injected`
- `verbosity` → hard token budget
- `thespian_optimizer` → prompt framing switch

Axes whose content the pack does not supply are logged `axis_dormant`, never approximated (§3.4).

**Test:** hold everything constant, vary one axis across its range, diff the output. **Every axis must produce a measurable difference or it is not implemented** — except an axis the pack has made dormant, which must produce *no* difference and a dormant log entry.

### P2.6 Replayable scenario harness

**A first-class deliverable, not a convenience.** Canned table states with fixed dice seeds:

- A combat round
- A social negotiation
- A planning stall
- A rules dispute
- A spotlight-starvation setup
- A scene with an obvious interrupt opportunity

Run repeatedly against different trait configurations. Change one axis, rerun, diff.

Scenarios are authored per pack, because a combat round is system-specific. The playable pack carries the full set; the second pack gets at least the combat round and the rules dispute in P3. A break scenario is added in P5.4.

**Without this you cannot tune twelve interacting dials against a four-hour session.**

### P2.7 Recaps and memory

- Ground-truth recap on the Utility Model
- Per-agent controlled corruption with the §6.3 recipe
- Self-favouring bias
- Cache by `(ground_truth_hash, agent_id, fidelity)`
- GM recap exempt from corruption

**Test:** low-fidelity agents demonstrably misremember names and merge events, while retaining their own moments and anything in their notes.

### P2.8 Metrics pipeline

Automated per run:

| Metric | Watching for |
|---|---|
| Floor share per agent | Domination, starvation |
| In-character vs. out-of-character ratio | Thespian/optimizer axis working |
| Contested-ruling rate | Rules-lawyering axis working |
| Stall length distribution | Watchdog efficacy |
| Repetition score vs. last N beats | Loop pathology |
| **Vocabulary overlap between agents over session time** | **Voice convergence** |
| Interrupt frequency and success rate | `INTERRUPT_MARGIN` tuning |
| Silence ratio | `FLOOR_THRESHOLD` tuning |
| Tool-failure rate per provider | Seat viability |
| Refusal rate per provider | Seat viability |
| Tokens and cost per beat, by layer and agent | Budget reality |
| Layer-3 retrieval hit rate | Recall architecture health |
| Success rate by outcome rank, per procedure | Pack balance; comparable across systems (§2.5) |
| Judgement inputs per session, by role, control, and setting | Size of the judgement surface; what a settings change actually changed (§2.13) |

**Most trait failures appear as numbers before they appear as vibes.** Convergence in particular is very visible as vocabulary overlap climbing over session time.

### P2.9 Human evaluation pass

Metrics cannot tell you whether it is funny. Short clips, blind, rated by humans for whether it reads as a real table.

### ✅ Gate P2 — the critical gate

**Floor distribution**
- [ ] No agent below 12% or above 40% floor share over a full session
- [ ] Floor share correlates with `eagerness` in the intended direction

**Voice**
- [ ] Vocabulary overlap between agents does not rise materially over a 3-hour session
- [ ] Blind human raters can attribute lines to agents better than chance

**Pacing**
- [ ] Stalls longer than the watchdog threshold occur less than once per hour
- [ ] Silence ratio falls within the target band
- [ ] Interrupts occur a few times per session, not per scene, and land coherently

**Traits**
- [ ] Every non-dormant axis produces a measurable output difference under the scenario harness
- [ ] Trait configurations are distinguishable by blind human raters

**Reliability**
- [ ] Tool-failure rate <2% per provider after repair
- [ ] Zero state corruption over a 3-session run
- [ ] Zero isolation breaches
- [ ] Beat latency p95 within the broadcast-viable ceiling

**Cost**
- [ ] Cost per broadcast hour within budget
- [ ] Cost attribution understood — confirm or refute the §6.5 expectation that GM context, not recall, dominates

**Human judgement**
- [ ] Blind raters describe the output as reading like a real table more often than not

**If the table does not work here, it will not work with a map and voices on top of it.**

---

## Phase 3 — The Campaign

**Goal:** the full loop — Session 0, prep, validation, multi-session continuity, arcs — and the first real test of the second pack with live agents.

### P3.1 Session 0

- Pre-session table talk
- Constraint-card deck and dealing from the seeded randomizer (§10.2)
- Pitch generation with a length cap
- **Sealed simultaneous ranked-choice vote**, no inter-pitch discussion, self-votes disallowed
- Tie-break: fewest campaigns GM'd, then master-seed random
- Winner seated as GM
- Pack pinned (§2.9)
- Winner's PC converted to an NPC (§10.5)
- Session runner enforces the no-break window from first pitch to ballot close (§10.3) — enforced now, exercised once breaks exist in P5

**Test:** run 20 Session 0s. Measure pitch diversity with and without constraint cards. Confirm no sycophancy or recency clustering in ballots.

### P3.2 Canon crystallization

- Winning pitch → structured canon, staged per §7.6.2
- **Stage-gate validation between batches** (axiom 4 — the one mechanism that must be machinery)
- Dependency-order generation: factions → locations → NPCs → threads → secrets
- Mechanical prep instantiated through the pack's schema
- Alias registration with collision rejection
- Prep record cap enforced

**Test:** generate 200 records; confirm zero orphan dependencies, zero name collisions, zero contradictions surviving the gate. Deliberately inject a contradiction mid-stage and confirm the gate blocks it.

### P3.3 Validation pass

The full §1.3.3 pipeline on the Utility Model:

1. Entity extraction → alias resolution → unknown-entity flag
2. Fact extraction → canon comparison → contradiction flag
3. **Numeric and track assertion extraction → pack vocabulary mapping → state comparison → mismatch flag**
4. **Active-secret comparison → unintended-reveal flag**

One regeneration on flag; beat cut on second failure.

**Test:** inject known contradictions, false resource claims, and secret leaks into generated text; confirm detection rate and regeneration success, on both packs' vocabularies. Measure pass latency — it must fit the buffer.

*Note:* items 3 and 4 are the v1 additions beyond baseline canon checking. If the pass proves too expensive, cut back to secrets-preloading plus post-session reconciliation (§7.6.4).

### P3.4 Improvisation handling

- `spawn_entity` with the reduced live check (alias collision + dependency existence, both hash lookups)
- `improvised` tagging at low detail
- **Create-not-amend enforcement** — existing facts frozen mid-session
- Post-session promotion: flesh out, link, full validation
- **Reconcile-never-overwrite** policy enforced in the post-session pass

**Test:** confirm the live check adds negligible latency. Confirm the post-session pass cannot emit a supersede record against an aired fact.

### P3.5 Post-session prep pass

- Read the session; identify what was pursued and what was ignored
- Input assembled from play events only — the slot where break content would be excluded is built now (§7.6.2 axiom 13)
- Reactive prep generation under the record cap
- Clock advancement with canon emission
- Unused-prep relocation, weighted by `railroading`
- Improvised-record promotion
- Digest regeneration

**Test:** run 5 consecutive sessions; confirm prep stays ahead of play and canon remains contradiction-free.

### P3.6 Arc detection and compression

- Utility Model identifies closed arcs from the event log
- Campaign-memory recompression at boundaries
- Digest regeneration

**Test:** run a 10-session campaign; confirm arc detection matches human judgement and that session-10 context size is comparable to session-3 context size.

### P3.7 Second-pack campaign

- Full loop — Session 0, chargen, prep, play — on the second pack with live agents
- Scenario harness entries for the second pack (combat round, rules dispute)

**Test:** a 3-session campaign completes. Compare tool-failure rate against the playable pack; expect a brief rise at campaign start that settles within a session (§7.5).

### ✅ Gate P3

- [ ] 20 Session 0s produce materially diverse campaigns
- [ ] Zero canon contradictions survive the stage gate
- [ ] Validation pass detects >90% of injected contradictions, false numbers, and secret leaks
- [ ] Validation pass latency fits inside the broadcast buffer
- [ ] Zero overwrite-type retcons emitted
- [ ] A 10-session campaign completes with stable context size and cost per session
- [ ] Improvised-to-prepped ratio tracks `railroading` in the intended direction
- [ ] **A 3-session campaign runs on the second pack with no kernel, orchestrator, or adapter change**
- [ ] One P3 campaign runs on default settings throughout; another switches the GM to strict mid-campaign. The switch applies cleanly at a scene boundary, and judgement inputs before and after differ in the expected direction

---

## Phase 4 — Broadcast

**Goal:** make it watchable. Renderer, TTS, overlay, buffer, stream.

**Note:** everything here sits on top of a table that already works. If P2 and P3 gates passed, this phase is production engineering rather than research.

### P4.0 Broadcast pack: SRD 5.1

Written as late as possible, so nothing before it is tuned to one ruleset.

- `packs/srd51/`, extending `core.roll_over`, with sectioned rules text, `meta.license: CC-BY-4.0`, and the CC release's attribution statement copied verbatim, noting the text was adapted (§1.2)
- `meta.excluded_terms`: the well-known non-SRD names agents are likely to produce (named settings, places, characters, and creatures the SRD omits), each with aliases. Extend the list whenever a scenario run surfaces a new one
- A digest that names the edition in force (§1.1) and fits the context budget
- Rule-card data for every action, procedure, condition, currency, and tag; strict-ready on every control
- Spatial on ZoneGraph and RangeBands: SRD distances map to range bands in the pack. A grid (`SquareGrid`) stays in v2.
- Golden fixtures, scenario-harness entries (combat round, rules dispute), and the derived house-rules check, as for the test packs
- **Zero kernel, orchestrator, or adapter changes made for it.** Anything it seems to need is raised as a defect, fixed generically, and proven on the test packs first.

**Test:** the pack passes conformance, the scripted campaign covers every action, and `query_rules` reaches every section. A 3-session live campaign completes on it. Compare its rules-dispute and validation-catch rates with the test packs, to measure the contaminated prior (§1.1).

### P4.1 Renderer

- Pure function of scene state (§8.2)
- Diagrammatic vector rendering: regions, adjacency, range bands, tokens, lighting tint, cover hatching — pack-defined values drawn from the pack's presentation data
- **Typography system** — with no art, the type system is the design
- Authored token asset library
- Narration typesetting as a first-class visual element
- Omniscient view for broadcast vs. per-observer views for agents
- Break view layout (§8.4), rendered from fixture Board data until P5

**Test:** identical scene state renders identically across runs, on both packs. Confirm no generated imagery anywhere in the pipeline.

### P4.2 TTS

- Fixed voice per agent, cast for contrast
- NPC voice pool, assigned at `spawn_entity`, **held as state**
- **Board announcer voice**, distinct from every cast and NPC voice (§9.4)
- Generation in the buffer, cached by text hash
- `verbosity` enforced as an audio length cap

**Test:** blind listener test — can raters distinguish all five cast voices and the announcer? Confirm NPC voice consistency across sessions.

### P4.3 Overlay

Per §8.4:
- Always-visible: scene, nameplates with **model badge**, speaker indicator, party resources per the pack's `nameplate_resources`, clocks, system pack attribution, **compact Board** (fixture data until P5)
- Contextual: rule cards (P4.4), enumeration highlight, DM indicator, canon entity cards
- Side panel: live transcript and rules log
- **Bid meter** — the novel element
- **Hidden clocks, audience-only** — dramatic irony as a standing feature
- `one_line_intent` on nameplates (§8.5)

### P4.4 Rule cards

Per §8.6: every action or rule used during a campaign appears on the livestream as a popup card.

- Card renderer as a pure function of events and the resolved pack; no model-written text
- Card kinds: action, triggered rule (linked sub-card), ruling, spend, condition, rules check
- Input provenance labels: state, automatic tag, engine draw, model choice (§2.13)
- Scheduling in the buffer against beat audio, ordered by `seq`
- Cut beats keep their cards
- Popup priority queue with `max_visible`, `min_dwell_ms`, and stacking within `coalesce_window_ms`; the **rules log** keeps every card
- Fudge suppression live; archive re-render with fudges revealed
- `secret_card_mode` redaction for secret-linked actions

**Test:** identical events render identical cards, on both packs. Every action, procedure, condition, currency, and tag in both packs produces a card. Across a scripted combat-heavy session: every state-changing event appears in the rules log, the popup layer never exceeds `max_visible`, and every card airs within its beat. Force a cut on a beat that committed an action and confirm its card still airs. Confirm no live card ever reveals a `peek_roll`, a reroll, or a `secret` record. Blind viewer test: viewers can say what happened mechanically from the cards alone.

### P4.5 Buffer and operator

- 5–10 minute buffer
- Retry cascade orchestration: validation → regeneration → moderation → TTS
- **Beat-granular kill switch** — drop a beat, scheduler continues
- **Stream-granular kill switch**
- Board-item removal control (wired to real data in P5)
- **Determinism control** (§9.3): preset per role and per-control toggles; queues changes for the next scene boundary; shows pack-unsupported options as unavailable
- Overlay determinism indicator and settings-change rule card
- Operator interface exposing nothing else

**Test:** force a retry cascade on a single beat; confirm the buffer absorbs it invisibly. Confirm the operator interface offers no path to instruct an agent, alter a trait, edit any text, or choose any input or outcome. Toggle the GM to strict and back during a live test session; confirm each change lands at a scene boundary, appears on the overlay indicator, and airs a settings-change card.

### P4.6 Moderation

- Utility Model screening before TTS
- **Explicit content standard defined and documented**, written for public display as well as for the pipeline — without it, your effective standard is whichever provider is most permissive
- Regenerate-once, then cut
- Flag rate tracked per provider

### P4.7 Stream output

- Video composition, encoding, platform integration
- Live chat ingestion (read-only; chat is not an agent input)
- Recording for the VOD pipeline

### P4.8 VOD pipeline

- Cut from the recording, not re-run from the sim
- **Permitted/forbidden operations enforced by tooling, not policy alone** (§9.5)
- Silence trimming with a retention target
- Failed-beat removal
- Private-intent reveals as a production choice
- Break segments trimmable or cuttable whole; donor text uneditable
- Rule-card content locked; a card for a state-changing roll cannot be removed while its beat remains

### ✅ Gate P4

- [ ] The broadcast pack (P4.0) passes conformance and was built with zero kernel, orchestrator, or adapter changes made for it
- [ ] Zero excluded terms reach TTS or the overlay in a full live session on the broadcast pack; every catch is logged
- [ ] Renderer output is deterministic from state
- [ ] Every action and rule used in a full session appears as a rule card or, when stacked, in the rules log — none missing
- [ ] Zero live rule cards reveal a fudge or a `secret` record
- [ ] Determinism settings toggle mid-session from the operator control without disrupting the stream
- [ ] All five cast voices and the announcer distinguishable in blind testing
- [ ] Buffer absorbs a worst-case retry cascade without visible disruption
- [ ] Beat-granular kill switch works without ending the stream
- [ ] Moderation flag rate acceptable on all five providers
- [ ] A full session streams end to end unattended
- [ ] VOD tooling makes forbidden operations impossible, not merely discouraged

---

## Phase 5 — Audience Support and Hardening

**Goal:** the donation Board, break time, and the security work that donor text demands.

The principle every step serves (P9): **a donation buys a moment at the table, never a moment in the game.** Every test below is ultimately checking one of two things — that donor text can't reach the fiction, and that while it is in a context, nothing in that context can act.

### P5.1 Donation intake and audience store

- Platform paid-message and/or processor integration
- Donation record per §9.7.1; payment details never stored
- Raw fields quarantined — **no code path from raw fields to any context assembler, overlay, renderer, or TTS**, checked statically in CI
- Per-donor encryption; erasure by key deletion
- Currency normalisation with recorded rate
- Reversal and chargeback handling: removal from Board and queue
- Intake disclosure (§9.7.4), shown before payment

**Test:** an erasure makes a donor's content unreadable everywhere, leaves the event log byte-unchanged, and leaves game-state replay byte-identical. The CI path check fails on a deliberately introduced raw-field read. A reversal removes the item within one overlay refresh.

### P5.2 Sanitisation pipeline

- Stages 1–7 at intake, 8–9 at read time, 10–11 on output (§9.9)
- **Reject or redact; never rewrite**
- Two independent moderation classifiers; a withhold from either withholds
- Stricter standard for display names; impersonation list
- Per-language enablement
- Withhold log by stage and category; donor notification

**Test:** fixture suites for every stage. Stages 1–4 and 7 are deterministic — same input, same output, every run. Confirm no stage emits text the donor did not write, other than fixed redaction markers. Measure false-withhold rate on a benign corpus of realistic donation messages.

### P5.3 The Board

- Deterministic ranking from donation records (§9.7.2)
- Display scope configuration; compact overlay and full break view
- Read queue: filter, order, carryover across sessions, expiry (§9.7.3)
- Reaction allowance by amount band
- Operator removal — removal only
- Live disclosure: queue length, next-break indicator

**Test:** Board order and queue are pure functions of the records; replay reproduces them exactly. The operator interface offers remove and nothing else — no edit, reorder, re-insert, or promote.

### P5.4 Break time

- Break scheduling (§9.8): interval, scene boundaries only, queue-pressure trigger, never mid-encounter or during scene-setting, never in Session 0's pitch-to-ballot window
- Scheduler break mode (§4.8): engine presentation, name-addressed Stage 1, restricted kinds, reaction windows, interrupts, no watchdog
- **Break-mode schema swap**: `post_to_table`, `pass`, `look_board` — nothing else (§7.1)
- Break-mode context assembly (§6.1.1); the GM's built from table knowledge only
- Announcer template reading
- **Echo check** on every reaction
- Break recap from reactions only; excluded from prep input, canon, digest, notes, and the GM's play context (§9.8)
- Break scenario added to the P2.6 harness, with canned pre-sanitised Boards

**Test:**
- Enumerate every seat's advertised tools in break mode: exactly three, for every seat including the GM.
- The GM's break context contains zero `secret` records and zero prep, across 100 breaks.
- The prep pass input contains zero break content.
- No break recap contains a donor-text span over the echo threshold.
- Break scheduling never violates its windows across a simulated 10-session run.
- 20 breaks against canned Boards: items read per break, reaction length by amount band, and silence ratio within targets — and blind raters say the breaks read like a real table reading chat.

### P5.5 Injection red-team

**The most exposed surface in the system.** Donor text is untrusted, it is shown, voiced, and placed in five model contexts, and the people writing it paid — they will be motivated and iterative.

Red-team with the §9.9 corpus: classic prompt injections, Unicode and confusable attacks, delimiter forgery, encoded payloads, split payloads across donors, name impersonation, slur and filter evasion, multilingual evasion, and target-phrase attacks on cast voices.

**Test:** confirm no submission can alter agent behaviour outside its own reaction window, make a cast voice say a target phrase, leak prep or secrets, escape its delimiters, reach any context after its window closes, or appear in canon, notes, prep, or a dossier.

### P5.6 Session 0 audience poll

- Free poll resolved as a weighted block alongside agent ballots (§10.3)
- Donations confer no weight

### P5.7 Operational hardening

- Provider outage failover: can a seat be swapped mid-campaign?
- Cost monitoring with alerting against the per-hour ceiling
- Automated snapshot and resume after crash
- Master-seed and resolved-pack publication at campaign end
- Audience metrics live: items read per break, donation-to-read latency, withhold rate by stage, false-withhold rate, echo-check trips, break share of session time

### ✅ Gate P5

- [ ] Red-team finds no successful injection path, including target-phrase attacks on cast voices
- [ ] Zero donor text found in any play context, prep input, canon record, note, or dossier across a 10-session run
- [ ] Break-mode schemas contain exactly three tools for every seat
- [ ] Board order and read queue are deterministic and replayable
- [ ] Break scheduling never violates its windows
- [ ] Intake and live queue disclosure are accurate
- [ ] Erasure works without rewriting the event log or disturbing game replay
- [ ] False-withhold rate on the benign corpus within target
- [ ] Legal and data-protection reviews complete, structure adjusted if required
- [ ] Cost per broadcast hour within ceiling at production volume
- [ ] Provider outage does not end a campaign

---

## Appendix — Risk register

| Risk | Phase | Mitigation |
|---|---|---|
| Table reads as a panel discussion | P2 | Gate P2 floor/voice/pacing metrics; scheduler is built before anything visible |
| Voice convergence over long sessions | P2 | Multi-provider casting; vocabulary-overlap metric as a tracked gate |
| Trait defaults wrong on first contact | P2 | Scenario harness; expect several tuning cycles, and more per new pack |
| Kernel quietly shaped by the first system | P0 | Second complete pack from another family in P0; noun lint in CI; zero-kernel-change gate |
| Configuration language bloats into a programming language | P0+ | Hooks as the escape hatch; hook count tracked; recurring hooks promoted to kernel strategies |
| Judgement creep — model-chosen numbers steering outcomes | P0 | Players strict by default; GM switchable to strict at any scene boundary; enum or bounded schemas; `judgement_input` metric |
| Settings toggle used to steer a specific moment | P4 | Changes apply only at scene boundaries, with a cooldown; logged, on the overlay, announced by rule card |
| Replay breaks after a pack or kernel change | P0+ | Pack and kernel pinned per campaign; archived-campaign replay corpus gates every kernel release |
| Canon drift over a long campaign | P3 | Append-only IDs, stage gates, validation pass, scene pre-fetch of secrets |
| Cost blowout | P2 | Per-beat ceilings, degradation ladder, prefix caching, early cost attribution |
| Provider refusals breaking beats | P1/P2 | Adapter detection, graceful floor re-award, per-provider refusal metric |
| Prompt injection via donor messages | P5 | Eleven-stage pipeline, nonce-delimited presentation, three-tool break schema, red-team gate |
| Donor words laundered through a cast voice | P5 | Announcer reads donor text; echo check on reactions and break recaps |
| Donor influence reaching the plot | P5 | Break talk excluded from prep, canon, and GM play context; no breaks in the Session 0 vote window |
| GM spoils secrets to chat at a break | P5 | GM break context built from table knowledge only; secret check still runs |
| Small donations never read | P5 | Disclosed reading policy and carryover; ageing variant as a tuning option |
| Erasure requests vs. append-only log | P5 | Donor content outside the event log; per-donor encryption and key deletion |
| Rule cards swamp the screen in combat | P4 | Priority queue, dwell limits, stacking; the rules log keeps everything |
| Rule cards leak fudges or secrets | P4 | Cards show final results only; secret-linked actions redacted |
| Editorial drift undermining trust | P4 | Two-tier product; unedited stream is the public record; VOD tooling enforces limits |
| Regulatory exposure on donations | P5 | Money never buys outcomes; live disclosure; legal and data-protection review |
| Best pitch ≠ best GM | P3 | Accepted in v1 (§10.4); revisit only if unwatchable |

---

## Appendix — What to build first if you only have a weekend

P0.1 (event store), P0.2 (randomizer), and P0.12 (scripted harness).

With those three you have a replayable, verifiable game engine and a way to test everything that comes after. Every other component in this document assumes they exist.

**If you have a second weekend:** P0.3–P0.5 against two deliberately tiny packs from different resolution families — a page of rules each — before writing any real game content. The kernel's shape is set by whatever it is first tested against; make that two things, not one.

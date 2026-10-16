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

### T0.3 Spatial: ZoneGraph — `ready`
- **Plan:** P0.10 · §1.4, §8.2
- **Deliverables:** `kernel/spatial.py` with the `SpatialBackend` interface and `ZoneGraph`. Scene regions and adjacency become part of `set_scene`. `move` is validated against adjacency. Per-observer `visible_to` is supported.
- **Acceptance:**
  - Illegal moves are rejected atomically.
  - Visibility is per observer.
  - The scene schema matches §8.2 for the fields implemented.
  - Replay stays byte-identical.

### T0.4 Candidate generator and mastery tiering — `blocked` (T0.3)
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

### T0.5 Spatial: RangeBands — `blocked` (T0.3)
- **Plan:** P0.10 · §1.4
- **Acceptance:** same tool surface as ZoneGraph; the band set comes from the pack; `tidewrack` declares and uses it.

### T0.6 Turn order and action economy — `ready`
- **Plan:** P0.4 · §2.4
- **Deliverables:** an encounter-mode turn controller with the strategies `spotlight`, `initiative`, `sides`, `handoff`, `fixed`, and `deck`, and the economies `none`, `slots`, and `points`, all selected by `turn_structure` in the pack. Expose `current_turn` for the scheduler's Stage 1 bid (§4.1).
- **Acceptance:** each strategy cycles correctly through a scripted encounter, and the action economy is enforced atomically.

### T0.7 `peek_roll` and fudging — `ready`
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

### T0.8 Decks — `ready`
- **Plan:** P0.2 · §2.4
- **Deliverables:** deck state in events, plus shuffle, draw, and reshuffle per the pack's `reshuffle_rule`.
- **Acceptance:** draws replay exactly, and a demo pack uses one deck.

### T0.9 Read views — `ready`
- **Plan:** P0.8 · §7.1
- **Deliverables:** pure functions for `read_sheet` (own, full) and `read_party_sheets` (others, summary), in the pack's vocabulary.
- **Acceptance:** the summary view never includes fields the full view marks private.

### T0.10 Property tests and golden fixtures — `ready`
- **Plan:** P0.7 · §2.10
- **Deliverables:**
  - Generated tests per pack: every action resolvable from sampled states; every outcome band reachable, using exact dice distributions where possible; no effect sequence yields an invalid sheet.
  - Golden fixtures in `packs/<id>/fixtures/` as `(seed, script) → expected log head hash`.
  - `TOB_UPDATE_GOLDEN=1` regenerates fixtures deliberately.
- **Acceptance:** the tests run within `tob check`'s time budget (`docs/dev/TESTING.md`).

### T0.11 Off-air clock advancement — `ready`
- **Plan:** P0.11 · §7.6.2 axiom 15
- **Acceptance:** clocks advance on schedule between sessions and emit canon (needs T0.2) for each world change.

### T0.12 Hook sandbox — `deferred`
- **Plan:** P0.5 · §2.7
- **Why deferred:** no pack uses hooks, and the loader refuses all hooks until this exists, which satisfies the gate. Build it when a real pack needs one.

### T0.14 Sectioned rules text — `ready`
- **Plan:** P0.13 · §2.3, §2.11, §6.5 Layer 0
- **Deliverables:**
  - The pack loader accepts `rules_text.mode: sectioned` with `digest`, `sections` (`id`, `title`, `aliases`, `body`, `refs`, optional `parent`), and `max_section_tokens`. Inline packs may also declare `sections`.
  - A deterministic section index built from the resolved pack. Reuse canon's key normalisation (D-010) rather than duplicating it.
  - A `query_rules(section_id | query)` engine query that resolves by exact ID, catalogue ref, alias, then partial match. A miss returns suggestions. A lookup is logged only if the docs require it; check §8.6 rule cards and EVENTS.md before adding an event type.
  - Lint classes in `packlint.py`: digest budget, section cap, alias uniqueness, `parent` resolution without cycles, catalogue coverage by `refs`.
  - `query_rules` appears in generated tool schemas for every role (§7.1 table).
- **Rules:** no section taxonomy in the kernel and no system-specific names; sections are opaque text. Keep the noun lint clean.
- **Acceptance:** BUILD_PLAN P0.13's test, plus one defect of each new lint class caught with a message naming the valid options.

### T0.15 Sectioned fixture variant — `blocked` (T0.14)
- **Plan:** P0.6 · §2.8, §2.11
- **Deliverables:** a data-only derived pack (e.g. `lanternlight.sectioned`) that extends `lanternlight`, switches `rules_text` to sectioned with a digest, and changes nothing else.
- **Acceptance:** it passes conformance with zero kernel changes. Its scripted campaign matches its parent's event stream apart from rules-lookup events. `query_rules` reaches every section by ID and alias.

### T0.16 Excluded terms — `ready`
- **Plan:** P0.14 · §1.2, §1.3.3, §2.3, §2.10
- **Deliverables:**
  - `meta.excluded_terms: [{ term, aliases }]` in the pack loader, inherited and merged like other catalogues.
  - One matcher in the kernel, reusing canon's key normalisation (D-010): case-insensitive and whole-word.
  - `write_canon` refuses records containing an excluded term in names, aliases, or text. The error names the term.
  - A lint class for collisions with catalogue IDs, vocabulary, rule-card titles, and section titles.
  - A fixture pack (e.g. a data-only variant of `tidewrack`) declaring a few invented terms, so tests stay system-agnostic.
- **Rules:** the kernel names no real-world IP; every term comes from pack data. Keep the noun lint clean.
- **Acceptance:** BUILD_PLAN P0.14's test. The validation-pass and TTS-gate integration is done later, in P3.3.

### T0.13 Gate P0 sign-off — `human`
- **Agent prepares:** evidence for every Gate P0 item in `HANDOFF.md`, as the commands run and their results.
- **Owner signs off.**

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

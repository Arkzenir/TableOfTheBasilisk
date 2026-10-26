# Roadmap

Status of each `docs/BUILD_PLAN.md` step in this repository.
✅ done and tested · 🟡 partial · ⬜ not started

Work is broken into agent-sized tasks in [`docs/dev/TASKS.md`](docs/dev/TASKS.md); this file tracks build-plan steps.

## Phase 0 — Rules kernel and deterministic core

| Step | Status | Where | Notes |
|---|---|---|---|
| P0.1 Event store | ✅ | `kernel/events.py` | Hash chain, append-only triggers, transactions, snapshots, fork, online backup, pinning checks |
| P0.2 Randomizer | ✅ | `kernel/rng.py`, `kernel/dice.py`, `kernel/decks.py`, `kernel/fudging.py` | Seeded dice, full grammar (keep, explode, count, fate, step dice), lookup tables, weighted draws, seed commitment; seeded decks with five reshuffle rules; `peek_roll` with the direction-of-drama constraint by outcome rank and a per-session cap from the GM's `fudging` trait. Shuffles and rerolls re-derive with `verify --seed` |
| P0.3 Entity model, expressions | ✅ | `kernel/engine.py`, `kernel/expr.py` | Stats, derived, resources, tracks, conditions, tags, currencies, a harm declaration (`harm_state`); inventory is a simple list. Noun lint in the gate |
| P0.4 Effects, resolution, turns | ✅ | `kernel/engine.py`, `kernel/resolution.py`, `kernel/effects.py`, `kernel/turns.py` | All primitives except `trigger_procedure` (reserved); roll-over and banded resolution; ruling slots; fiction triggers; determinism settings with mid-campaign changes; all three §2.5 procedure shapes (roll-over, banded, pool with degrees by margin) plus roll-under and opposed checks (in `core`); encounter turn controller with all six orders (`spotlight`, `initiative`, `sides`, `handoff`, `fixed`, `deck`) and three economies (`none`, `slots`, `points`), and `current_turn` for the scheduler. all 17 primitives implemented, `trigger_procedure` included, each tested to emit events and replay exactly |
| P0.5 Pack loader | ✅ | `kernel/packs.py`, `kernel/tools.py` | Inheritance, merge rules, removals, hashing, kernel compatibility, tool-schema generation. Sandboxed hooks (`kernel/hooks.py`): static contract check at load, whitelisted runtime with a step limit, logged kernel randomness, double runs that must agree, source pinned in the pack hash; `resolution.step` and `sheet.validate` wired, the other §2.7 points reserved. Fixture `lanternlight_hooked` |
| P0.6 Baselines and packs | 🟡 | `packs/` | `core`, `core.roll_over`, `core.banded`, two demo games from different families, three data-only derived packs (house rules, sectioned rules text, excluded terms) and one with hooks (`lanternlight_hooked`). The broadcast pack (SRD 5.1) is P4.0 |
| P0.7 Conformance and authoring | ✅ | `kernel/packlint.py`, `kernel/conformance.py`, `tob pack new` | Scaffold, static lint, strict-readiness, defect-class tests; generated property tests for every playable pack (outcome bands reachable by exact dice distributions, every action resolvable from sampled states, no effect sequence leaves an invalid sheet); golden fixtures in `packs/<id>/fixtures/golden.yaml` |
| P0.8 Sheets and chargen | ✅ | `kernel/engine.py`, `kernel/sheets.py` | Roll, choice, assign, and table steps; `unique_per_table`; 1,000 generated characters per pack all valid; `read_sheet` (own, full) and `read_party_sheets` (summaries) in the pack's vocabulary, with summaries built as the full view minus its private fields |
| P0.9 Canon store | ✅ | `kernel/canon.py` | Records in folded state; derived alias table, relation graph, and per-scope indexes (secrets absent from the player index); append-only supersede with history; reveal; scene bundles; digest stub |
| P0.10 Spatial engine | ✅ | `kernel/spatial.py`, `kernel/tactics.py` | `SpatialBackend` interface with ZoneGraph and RangeBands; pack movement allowance (`spatial.movement.steps_per_move`), provoke rules (`spatial.provokes`, logged as `move_provoked`), and region cover/terrain/elevation readable in rule expressions. ZoneGraph: scene regions with undirected adjacency, adjacency-checked moves, GM placement, per-observer `visible_to`, `scene_view`. Scenes without regions keep plain zone labels. Candidate generator (`kernel/tactics.py`): ranked, mastery-tiered `enumerate_moves`, `enumerate_action_candidates`, and `preview`, scored by kernel features weighted by the pack's tactical profile. RangeBands: pack-declared bands, one band per pair of participants, a move shifts one pair by one band; `tidewrack` uses it. Both backends pass the 10,000-enumeration legality sweep |
| P0.11 Clocks and time | ✅ | `kernel/clocks.py`, `kernel/timekeeping.py` | Create, advance, and pause clocks; off-air advancement on a per-clock schedule at each session start; prepped stages written as canon whenever a clock crosses them. In-world calendar from pack-declared units (watches, days, and so on), `advance_time`, time passing between sessions, and clocks scheduled on in-world time; rounds and turns are the turn controller's |
| P0.12 Scripted harness | ✅ | `harness/scripted.py` | Pack-agnostic smoke campaigns with coverage sweep, YAML scenarios, verification, double-run determinism, soak runner |
| P0.13 Sectioned rules text | ✅ | `kernel/rules.py` | Inline or sectioned rules text; deterministic section index; key-first `query_rules` (id, ref, alias, partial) with suggestions and a logged lookup; lint for digest budget, section cap, alias uniqueness, parents, refs, and coverage. The data-only fixture `lanternlight_sectioned` runs in every gate and matches its parent event for event |
| P0.15 Progression | ⬜ | — | XP, milestones, mark-on-failure, use-based; advancement as an enumerated choice (T0.27) |
| P0.14 Excluded terms | ✅ | `kernel/terms.py` | `meta.excluded_terms` inherited and merged by term; one whole-word, case-insensitive matcher on canon's normalisation; every canon write path refuses them; lint against the pack's own names; `excluded_in()` ready for the validation pass (P3.3). Fixture `tidewrack_excluded` uses invented terms |

## Later phases

| Step | Status | Notes |
|---|---|---|
| P1.1 Adapters | ⬜ | Interface in `adapters/base.py`; first provider is Anthropic (D-013) |
| P1.2 Tool API surface | 🟡 | Schemas generated per pack, role, and settings; dispatch from tool calls to engine commands still to write |
| P1.3 Context assembler | ⬜ | |
| P2 Scheduler, watchdog, traits, metrics | ⬜ | |
| P3 Session 0, prep, validation | ⬜ | |
| P4.4 Rule cards | 🟡 | Text renderer is the reference implementation (`broadcast/cards.py`); graphical renderer to come |
| P4.0 Broadcast pack (SRD 5.1) | ⬜ | Written as late as possible; sectioned; CC-BY 4.0; excluded terms for non-SRD names (D-012, D-015) |
| P4 Renderer, TTS, overlay, stream | ⬜ | Host encode path checked by `tob remote HOST encode-test` |
| P5 Board, break time, hardening | ⬜ | |
| Deployment tooling | ✅ | Bootstrap, gated atomic deploys, rollback, doctor, encode test, soak, verified backups |

## Suggested order from here

1. Owner decisions on the 1.6 draft (D-036): `scene_closed` (T0.24), condition stacking (T0.25), weight inventory (T0.26), progression (T0.27, BUILD_PLAN P0.15); harm is pending.
2. Gate P0 sign-off (T0.13): the agent refreshes the evidence, and the owner signs off.
3. Then start P1 with the Anthropic adapter.
4. The broadcast pack (SRD 5.1) waits until P4.0.

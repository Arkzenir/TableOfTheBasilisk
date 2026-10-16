# Roadmap

Status of each `docs/BUILD_PLAN.md` step in this repository.
✅ done and tested · 🟡 partial · ⬜ not started

Work is broken into agent-sized tasks in [`docs/dev/TASKS.md`](docs/dev/TASKS.md); this file tracks build-plan steps.

## Phase 0 — Rules kernel and deterministic core

| Step | Status | Where | Notes |
|---|---|---|---|
| P0.1 Event store | ✅ | `kernel/events.py` | Hash chain, append-only triggers, transactions, snapshots, fork, online backup, pinning checks |
| P0.2 Randomizer | 🟡 | `kernel/rng.py`, `kernel/dice.py` | Seeded dice, full grammar (keep, explode, count, fate), lookup tables, weighted draws, seed commitment. **Todo:** deck state and draw commands (shuffle primitive exists); `peek_roll` command and the rank-based direction-of-drama constraint (schema presence is already gated) |
| P0.3 Entity model, expressions | ✅ | `kernel/engine.py`, `kernel/expr.py` | Stats, derived, resources, tracks, conditions, tags, currencies; inventory is a simple list. Noun lint in the gate |
| P0.4 Effects, resolution, turns | 🟡 | `kernel/engine.py` | All primitives except `trigger_procedure` (reserved); roll-over and banded resolution; ruling slots; fiction triggers; determinism settings with mid-campaign changes. **Todo:** turn-order strategies and action economy for encounter mode |
| P0.5 Pack loader | 🟡 | `kernel/packs.py`, `kernel/tools.py` | Inheritance, merge rules, removals, hashing, kernel compatibility, tool-schema generation. **Todo:** sandboxed hook runtime (the registry currently refuses every hook, as required until it exists) |
| P0.6 Baselines and packs | 🟡 | `packs/` | `core`, `core.roll_over`, `core.banded`, two demo games from different families, one data-only derived pack. **Todo:** data-only sectioned variant (T0.15). The broadcast pack (SRD 5.1) is P4.0 |
| P0.7 Conformance and authoring | 🟡 | `kernel/packlint.py`, `tob pack new` | Scaffold, static lint, strict-readiness, defect-class tests. **Todo:** generated property tests per action and outcome band; golden fixtures per pack |
| P0.8 Sheets and chargen | 🟡 | `kernel/engine.py` | Roll, choice, and table steps; `unique_per_table`. **Todo:** full/summary read views (`read_sheet`, `read_party_sheets`) |
| P0.9 Canon store | ✅ | `kernel/canon.py` | Records in folded state; derived alias table, relation graph, and per-scope indexes (secrets absent from the player index); append-only supersede with history; reveal; scene bundles; digest stub |
| P0.10 Spatial engine | ⬜ | — | Zones are plain labels today (`move` effect). ZoneGraph, RangeBands, candidate generator, mastery tiering |
| P0.11 Clocks and time | 🟡 | `kernel/engine.py` | Create and advance clocks. **Todo:** off-air advancement scheduler, calendar |
| P0.12 Scripted harness | ✅ | `harness/scripted.py` | Pack-agnostic smoke campaigns with coverage sweep, YAML scenarios, verification, double-run determinism, soak runner |
| P0.13 Sectioned rules text | ⬜ | — | Section schema, key-first `query_rules`, section lint (T0.14) |
| P0.14 Excluded terms | ⬜ | — | Pack-declared unlicensed names, refused in canon, linted; matcher for the validation pass (T0.16) |

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

1. P0.10 spatial (ZoneGraph first), then turn order (P0.4).
2. P0.13 sectioned rules text, then its fixture variant; P0.14 excluded terms.
3. `peek_roll` and decks (P0.2), read views (P0.8), golden fixtures and property tests (P0.7), off-air clocks (P0.11).
4. Pass Gate P0 with `tob check`, then start P1 with the Anthropic adapter.
5. The broadcast pack (SRD 5.1) waits until P4.0.

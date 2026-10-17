# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** done are the event store, randomizer and dice (P0.2), expression language, pack system, engine (P0.4), scripted harness, deploy tooling, canon store (P0.9), spatial engine (P0.10), sheet views (P0.8), and now **off-air clock advancement (T0.11)**. See `ROADMAP.md`.
- **Not started:** golden fixtures and property tests (T0.10), sectioned rules text (T0.14, then T0.15), excluded terms (T0.16), calendar tracking (no task), and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.11)

- New `src/basilisk/kernel/clocks.py` (`ClockCommands` mixin). `create_clock` (moved out of `engine.py`) now takes an optional `schedule` and `stages`. `advance_clock` is unchanged, and there is a new `pause_clock`.
- Off-air advancement runs at `start_session` before play resumes. Stages write prepped canon whenever a clock crosses them, once each.
- New events `clock_stage_reached` and `clock_paused`. `clock_created` gains optional fields. All documented in EVENTS.md.
- The harness smoke clock now has a schedule and stages, and there is a scenario step `pause_clock`. The GM gets a `pause_clock` tool.
- `tests/test_clocks.py`: 16 tests. Clocks advance across sessions with no interference and write canon for each world change before play resumes. Also covered: every-N schedules, clocks created mid-campaign, pausing, stages firing once however the clock moves, atomic validation, secret stages staying player-invisible, and replay. Design choices are recorded in D-023.
- Earlier this session: T0.3 to T0.9 (D-016 to D-022), the engine split, and seven pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.10 (golden fixtures), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Suggested next: T0.14 and T0.15 sectioned rules text, then T0.16 excluded terms. Do T0.10 golden fixtures last, so the fixtures capture the finished kernel, then prepare the Gate P0 evidence (T0.13).
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, `fudging.py`, `sheets.py`, and `clocks.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

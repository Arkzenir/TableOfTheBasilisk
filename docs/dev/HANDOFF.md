# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** done are the event store, randomizer and dice, expression language, pack system, engine (effects, resolution, rulings, determinism settings), scripted harness, deploy tooling, canon store (T0.2), the whole spatial engine (P0.10), turn order and action economy (T0.6, completing P0.4), seeded decks (T0.8), and now **`peek_roll` and fudging (T0.7)**, which completes P0.2. See `ROADMAP.md`.
- **Not started:** read views, golden fixtures, off-air clocks, sectioned rules text, excluded terms, and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.7)

- New `src/basilisk/kernel/fudging.py` (`FudgeCommands` mixin):
  - `peek_roll(keep | reroll)`, `pending_peek()`, `peeks_left()`, and `peek_cap(trait)`
  - the direction-of-drama check by party-side rank
- `resolution.py` was refactored into `_scale`, `_interpret`, and `_resolved`. `_run_procedure` pauses on `peek` and returns `(None, None, None)`. `commit_action` and `resolve_unmodelled` return `pending` while paused, and blocked commands refuse until the GM settles.
- `campaign_started` records `gm_fudging` (from `gm_traits.fudging`, default 50).
- New events `roll_peeked`, `roll_fudged`, and `peek_settled`, documented in EVENTS.md.
- Tools: `rule_on_action.peek`, `resolve_unmodelled.peek`, and `peek_roll {decision}`, only where fudging is available.
- Harness: a `commit_action` step can carry `then: keep | reroll`, and there is a `peek_roll` step.
- `tests/test_fudging.py`: 12 tests (15 cases). The property test covers both scales and both sides, plus caps, refusals, tools, and live cards showing only the final roll. Design choices are recorded in D-021.
- Earlier this session: T0.3 to T0.6 and T0.8 (D-016 to D-020), the engine split, and five pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.9 (read views), T0.10 (golden fixtures), T0.11 (off-air clocks), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Suggested next: T0.9 read views (`read_sheet` full and `read_party_sheets` summary, in the pack's vocabulary). It is small and closes P0.8. Then T0.11 off-air clocks, T0.14 sectioned rules text, T0.16 excluded terms, and T0.10 golden fixtures last, so the fixtures capture the finished kernel.
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, and `fudging.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

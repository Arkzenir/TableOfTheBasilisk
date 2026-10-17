# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** done are the event store, randomizer and dice (P0.2), expression language, pack system, engine (P0.4), scripted harness, deploy tooling, canon store (T0.2), the whole spatial engine (P0.10), seeded decks (T0.8), fudging (T0.7), and now **sheet read views (T0.9)**, which completes P0.8. See `ROADMAP.md`.
- **Not started:** golden fixtures and property tests (T0.10), off-air clocks (T0.11), sectioned rules text (T0.14, then T0.15), excluded terms (T0.16), and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.9)

- New `src/basilisk/kernel/sheets.py` (`SheetCommands` mixin):
  - `full_sheet(entity)`, `read_sheet(seat, entity_id=None)`, `read_party_sheets(seat)`
  - the pure `summarise(full)`
  - lint class `sheet`
- Every field carries the pack's label and a `private` flag. Public fields are conditions, nameplate resources, and `presentation.sheet.public`.
- Packs: Lanternlight makes `guard` public, Tidewrack makes `harm` public.
- Tools: `read_sheet` (GM: `entity_id`) and `read_party_sheets`.
- `tests/test_sheets.py`: 10 tests, including the no-private-field property over full smoke campaigns on three packs. Design choices are recorded in D-022.
- Earlier this session: T0.3 to T0.8 (D-016 to D-021), the engine split, and six pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.10 (golden fixtures), T0.11 (off-air clocks), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Suggested next: T0.11 off-air clocks, then T0.14 and T0.15 sectioned rules text, then T0.16 excluded terms. Do T0.10 golden fixtures last, so the fixtures capture the finished kernel, then prepare the Gate P0 evidence (T0.13).
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, `fudging.py`, and `sheets.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

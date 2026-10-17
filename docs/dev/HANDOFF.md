# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** done are the event store, randomizer and dice (P0.2), expression language, pack system, engine (P0.4), scripted harness, deploy tooling, canon store (P0.9), spatial engine (P0.10), sheet views (P0.8), off-air clocks (T0.11), and now **sectioned rules text with `query_rules` (T0.14)**. See `ROADMAP.md`.
- **Not started:** the sectioned fixture pack (T0.15, now ready), excluded terms (T0.16), golden fixtures and property tests (T0.10), calendar tracking (no task), and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.14)

- New `src/basilisk/kernel/rules.py`:
  - `SectionIndex`, built once from the pinned pack using canon's key normalisation
  - the `RulesCommands` mixin, with `query_rules(seat, query)` (logs the passive `rules_queried`) and `rules_layer()` (context layer 2)
  - `lint_rules`
- The `rules-text` lint now covers digest, caps, ids, refs, name collisions, parents and loops, and coverage. The inline budget check moved there.
- New passive event `rules_queried`, documented in EVENTS.md. Tool `query_rules {query}` for every role.
- `tests/test_rules.py`: 18 tests covering P0.13's test (every section by id and alias, every catalogue id to a covering section, misses with suggestions, deterministic index, inline packs with sections), one defect per lint class (10), logging, and schemas. Design choices are recorded in D-024.
- Earlier this session: T0.3 to T0.11 (D-016 to D-023), the engine split, and eight pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.15 (sectioned fixture pack), T0.16 (excluded terms), and T0.10 (golden fixtures).
- Suggested next: T0.15. Make `packs/lanternlight_sectioned/` extend `lanternlight` and change only `rules_text`; `sectioned_data()` in `tests/test_rules.py` is a ready template. Then T0.16 excluded terms. Do T0.10 golden fixtures last, then prepare the Gate P0 evidence (T0.13).
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, `fudging.py`, `sheets.py`, `clocks.py`, and `rules.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

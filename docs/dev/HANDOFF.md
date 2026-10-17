# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** done are everything through P0.13 except the items below: the event store, randomizer and dice, expressions, pack system, engine, harness, deploy tooling, canon, spatial, sheets, off-air clocks, and now **sectioned rules text with its shipped fixture pack (T0.14, T0.15)**. See `ROADMAP.md`.
- **Not started:** excluded terms (T0.16), golden fixtures and property tests (T0.10), calendar tracking (no task), the Gate P0 sign-off (T0.13), and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.15)

- New `packs/lanternlight_sectioned/pack.yaml`: Lanternlight with only `rules_text` changed (sectioned, digest, 12 sections). It lints clean and is strict-ready like its parent, with no kernel change.
- Smoke campaigns make one `query_rules` per scene, and there is a scenario step `query_rules`.
- `tests/test_sectioned_pack.py`: 4 tests. Only `rules_text` differs; it conforms; its campaign matches the parent's event for event apart from pack identity and the answers to rule lookups; every section is reachable by id and alias. `test_packs` lists the new pack. Design choices are recorded in D-025.
- Earlier this session: T0.3 to T0.14 (D-016 to D-024), the engine split, and nine pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.16 (excluded terms) and T0.10 (golden fixtures).
- Suggested next: T0.16 excluded terms (fixture terms must be invented, never real IP). Then T0.10 golden fixtures, then the Gate P0 evidence (T0.13).
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, `fudging.py`, `sheets.py`, `clocks.py`, and `rules.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

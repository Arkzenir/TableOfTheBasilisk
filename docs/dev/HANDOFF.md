# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** every build step is done or nearly done. The last kernel feature, **excluded terms (T0.16, P0.14)**, has landed. What remains for Gate P0 is golden fixtures and generated property tests (T0.10), then the evidence for sign-off (T0.13). Calendar tracking has no task. See `ROADMAP.md`.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.16)

- New `src/basilisk/kernel/terms.py`:
  - `find` (the matcher), `merge`, and `lint_terms`
  - the `TermCommands` mixin, with `excluded_in(text)` and the canon refusal
- The pack loader merges `meta.excluded_terms` along the extends chain. `_canon_record` refuses excluded terms in names, aliases, and bodies.
- New lint class `excluded-term`.
- New fixture pack `packs/tidewrack_excluded/` with invented names. It runs in the gate.
- `tests/test_terms.py`: 25 tests matching P0.14's test (refusals for terms, aliases, and case; near misses accepted; colliding terms fail lint; deterministic), plus inheritance, every canon path, and spoken-line checks. Design choices are recorded in D-026.
- Earlier this session: T0.3 to T0.15 (D-016 to D-025), the engine split, and ten pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.10 (property tests and golden fixtures). After it, T0.13 (Gate P0 sign-off) needs the owner.
- Suggested next: T0.10. Generate property tests per pack (every action resolvable from sampled states; every outcome band reachable, with exact dice distributions where possible; no effect sequence yields an invalid sheet). Add golden fixtures in `packs/<id>/fixtures/` as `(seed, script) -> expected log head hash`, regenerated only with `TOB_UPDATE_GOLDEN=1`. Then prepare the Gate P0 evidence for T0.13.
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, `fudging.py`, `sheets.py`, `clocks.py`, `rules.py`, and `terms.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

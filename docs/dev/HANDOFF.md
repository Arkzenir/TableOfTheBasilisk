# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** every build step P0.1 to P0.14 is done. The exceptions are calendar tracking in P0.11 (no task; rounds are in the turn controller) and the hook sandbox (T0.12, deferred by design: no pack uses hooks, and the loader refuses them). **Track 0 is complete apart from T0.13, the Gate P0 sign-off, which needs the owner.** See `ROADMAP.md`.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.10)

- `dice.distribution()`: exact outcome probabilities as `Fraction`s; None for exploding dice.
- New `src/basilisk/kernel/conformance.py`: `outcome_reachability` and `outcome_probabilities` per procedure.
- `sheets.py` gained `sheet_problems(entity)`.
- `tests/test_properties.py`: generated per playable pack (22 cases). It checks exact distributions, every outcome band reachable, every action resolvable from seeded sampled states, and no invalid sheet after seeded walks of commits and extreme effects.
- `tests/test_golden.py` and `packs/<id>/fixtures/golden.yaml` for all five playable packs (smoke runs, plus the Lanternlight demo scenario). Regenerate only with `TOB_UPDATE_GOLDEN=1`.
- TESTING.md documents both.
- Timings: full gate about 20 s, `--quick` about 1.5 s. Design choices are recorded in D-027.
- Earlier this session: T0.3 to T0.16 (D-016 to D-026), the engine split, and eleven pushes.

## Next step

- **Track 0:** only T0.13 (Gate P0 sign-off, `human`) remains. The agent prepares evidence for every Gate P0 item (BUILD_PLAN, Gate P0) as the commands run and their results; the owner signs off. Track 1 starts after that (D-014).
- Suggested next: write the Gate P0 evidence into this file, item by item, with the exact command or test that demonstrates it. Flag any item not covered, for example "fork at any seq" and "10k-roll distribution", which should be checked against existing tests first.
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, `fudging.py`, `sheets.py`, `clocks.py`, `rules.py`, `terms.py`, and the pure `conformance.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-16)

- **P0:** done are the event store, randomizer, dice, expression language, pack system, engine (effects, resolution, rulings, determinism settings), scripted harness, deploy tooling, canon store (T0.2), and the **whole spatial engine (P0.10)**: ZoneGraph (T0.3), the candidate generator and mastery tiering (T0.4), and now **RangeBands (T0.5)**. See `ROADMAP.md`.
- **Not started:** turn order, `peek_roll`, decks, read views, golden fixtures, sectioned rules text, excluded terms, and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.5)

- `src/basilisk/kernel/spatial.py` now has one backend interface implemented by both `ZoneGraph` and the new `RangeBands`. A position is a region id, or `band:entity` in a band scene.
- `set_scene(participants=, ranges=)` opens a band scene. Every pair of participants has a band, and unset pairs start furthest. A move shifts one pair by one band. `place_entity` and `spawn_entity(zone=…)` set any band and add newcomers.
- New engine queries: `position_of` and `steps_from`. `reachable(entity, at=)` now accepts a hypothetical position.
- `tactics.py` works on positions and steps, so its features mean the same under both backends. Move candidates carry `position_id` (zone ones also keep `region_id`).
- `tidewrack` permits only `range_bands` (`close / near / far`). Smoke campaigns on band packs open band scenes.
- Tools: `place_entity` takes `position_id`. `set_scene` gains `participants` / `ranges` on band packs.
- Lint checks `spatial.bands`, and `square_grid` is reported as planned for v2.
- Tests:
  - new `tests/test_bands.py` with 19 tests, including Lanternlight run unchanged under RangeBands
  - the 10,000-enumeration sweep in `tests/test_tactics.py` now runs once per backend (about 3.4 s plus 1.7 s)
  - Tidewrack cases in `tests/test_tactics.py` use band scenes
- Zone-pack smoke and demo logs are byte-identical to the previous commit. Design choices are recorded in D-018.
- Earlier this session: T0.3 (D-016), the engine split into mixins, T0.4 (D-017), and two pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.6 (turn order), T0.7 (`peek_roll`), T0.8 (decks), T0.9 (read views), T0.10 (golden fixtures), T0.11 (off-air clocks), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Suggested next: T0.6 turn order and action economy (§2.4). It completes P0.4, and the scheduler's Stage 1 bid needs `current_turn`.
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, and `tactics.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

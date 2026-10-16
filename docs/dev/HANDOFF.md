# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-16)

- **P0:** done are the event store, randomizer, dice, expression language, pack system, engine (effects, resolution, rulings, determinism settings), scripted harness, deploy tooling, canon store (T0.2), and now **ZoneGraph (T0.3)**. See `ROADMAP.md`.
- **Not started:** RangeBands, candidate generator, turn order, `peek_roll`, decks, read views, golden fixtures, sectioned rules text, excluded terms, and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` with one commit per step; nothing is pushed. Hooks are installed (`core.hooksPath tools/githooks`).

## What changed this session (T0.3 ZoneGraph)

- New `src/basilisk/kernel/spatial.py`:
  - the `SpatialBackend` interface and `ZoneGraph`: region normalisation, undirected adjacency, `neighbours`, `distance` (steps), `check_move`
  - the `SpatialCommands` mixin on `Engine`: `place_entity`, `set_visibility`, and the queries `scene_view(seat)`, `visible(seat, entity)`, `reachable(entity)`, `distance(a, b)`
- `set_scene(..., regions=, placements=)`: a scene is spatial only when given regions. In a non-spatial scene, zones stay plain labels and older logs fold unchanged, so there is no kernel bump.
- `move` effects are checked against adjacency in spatial scenes. A player can't target an entity it can't see; the error lists only visible entities. `spawn_entity` checks the zone it is given.
- New event `visibility_set`, and an optional `spatial` field on `scene_set`. Both are documented in `docs/dev/EVENTS.md`.
- Pack lint checks `spatial.backends` names and duplicate `spatial.terrain` / `spatial.cover` ids. Tool schemas gain `look`, `set_scene.regions/placements`, `place_entity`, and `set_visibility`; strict schemas still carry no free values.
- The harness's smoke campaigns now run spatial scenes (a three-region line, one NPC hidden from one seat in encounters). The lanternlight demo scenario has a spatial scene with deliberate refusals. Scenario steps `place_entity` and `set_visibility` were added.
- `tests/test_spatial.py`: 21 tests covering the T0.3 acceptance criteria. Design choices are recorded in D-016.

## Next step

- **Track 0 only (D-014).** Ready: T0.4 (candidate generator and mastery tiering, now unblocked), T0.5 (RangeBands, now unblocked), T0.6 (turn order), T0.7 (`peek_roll`), T0.8 (decks), T0.9 (read views), T0.10 (golden fixtures), T0.11 (off-air clocks), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Suggested next: T0.4. It builds directly on `reachable` and `distance` and closes the Gate P0 spatial items.
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- `src/basilisk/kernel/engine.py` is about 920 lines, past AGENTS.md's ~800 guideline. Split it along a § boundary, for example resolution (§2.5) and effects (§2.6) into mixins like `canon.py` and `spatial.py`, before it grows further.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

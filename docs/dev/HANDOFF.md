# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-16)

- **P0:** done are the event store, randomizer, dice, expression language, pack system, engine (effects, resolution, rulings, determinism settings), scripted harness, deploy tooling, canon store (T0.2), ZoneGraph (T0.3), and now the **candidate generator and mastery tiering (T0.4)**. See `ROADMAP.md`.
- **Not started:** RangeBands, turn order, `peek_roll`, decks, read views, golden fixtures, sectioned rules text, excluded terms, and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.4)

- New `src/basilisk/kernel/tactics.py` (`TacticalCommands` mixin, read-only):
  - `enumerate_moves(entity, mastery)`
  - `enumerate_action_candidates(entity, mastery, position_id=None)`, which is what the `enumerate_actions` tool maps to
  - `preview(entity, action, mastery, target=None)`
  - `tier_of(mastery)`
- Ranking uses kernel features (threat and ally counts, `closer`, `elevation_change`, `target_threat` / `target_ally`). They count only entities the seat can see, and are weighted by the pack's `spatial.tactical_profile`: categories, weights, factors, annotation templates. The tiers are prefixes of one ranked list, capped at 12.
- `Engine.enumerate_actions` was renamed `available_actions`, because the agent-facing name now returns candidates. Logged options are unchanged, so logs are identical.
- Both demo packs have tactical profiles. Actions declare `annotation_categories`, and `lanternlight_house` overrides an inherited factor that named the removed Inspire action.
- Pack lint gained the `tactical-profile` class. Tools gained `enumerate_moves`, `enumerate_actions.position_id`, and `preview`.
- `tests/test_tactics.py`: 15 tests, including the 10,000-enumeration legality sweep (about 2.6 s), strict tier subsets, the cap, no numbers or coordinates, hidden-entity non-leakage, real commits of every candidate on both packs, and lint defects. Design choices are recorded in D-017.
- Earlier this session: T0.3 ZoneGraph (D-016), the engine split into mixins, and the first push to GitHub.

## Next step

- **Track 0 only (D-014).** Ready: T0.5 (RangeBands), T0.6 (turn order), T0.7 (`peek_roll`), T0.8 (decks), T0.9 (read views), T0.10 (golden fixtures), T0.11 (off-air clocks), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Suggested next: T0.5 RangeBands. It needs a `SpatialBackend` for bands and must join the 10,000-enumeration volume test in `tests/test_tactics.py`. `tidewrack` should declare and use it.
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, and `tactics.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

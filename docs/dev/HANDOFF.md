# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** done are the event store, randomizer, dice, expression language, pack system, engine (effects, resolution, rulings, determinism settings), scripted harness, deploy tooling, canon store (T0.2), the whole spatial engine (P0.10: T0.3 to T0.5), turn order and action economy (T0.6, completing P0.4), and now **seeded decks (T0.8)**. See `ROADMAP.md`.
- **Not started:** `peek_roll`, read views, golden fixtures, off-air clocks, sectioned rules text, excluded terms, and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.8)

- New `src/basilisk/kernel/decks.py` (`DeckCommands` mixin):
  - `draw_card(deck, by, to)`, `reshuffle_deck`, `discard_card`, and `deck_view(deck, seat)`
  - the reshuffle rules `when_empty`, `every_draw`, `scene`, `session`, and `manual`
  - lint class `deck`
- New events `deck_shuffled` (records `counter`, `cards`, and the resulting `order`), `card_drawn`, and `card_discarded`, documented in EVENTS.md.
- The harness's `verify --seed` now re-derives every deck shuffle.
- Tidewrack has an `omens` deck, and its rules text mentions it. Smoke campaigns draw from every deck each scene. Scenario steps were added for draw, reshuffle, and discard.
- Tools: `draw_card` and `discard_card` (GM; also players on `players_draw` decks), and `reshuffle_deck` (GM).
- `tests/test_decks.py`: 14 tests covering replay, seed re-derivation, the shared roll counter, each reshuffle rule, hands and hidden pile order, permissions, lint, and tools. Design choices are recorded in D-020.
- Earlier this session: T0.3 to T0.6 (D-016 to D-019), the engine split, and four pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.7 (`peek_roll`), T0.9 (read views), T0.10 (golden fixtures), T0.11 (off-air clocks), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Suggested next: T0.7 `peek_roll` and fudging (§5.5, §2.5, §2.13), which closes P0.2. Lanternlight's GM rolls; give it `gm.fudgeable_procedures` and test that rerolls never worsen the party-side rank on either pack's scale.
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, and `decks.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

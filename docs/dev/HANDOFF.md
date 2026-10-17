# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-17)

- **P0:** done are the event store, randomizer, dice, expression language, pack system, engine (effects, resolution, rulings, determinism settings), scripted harness, deploy tooling, canon store (T0.2), the whole spatial engine (P0.10: T0.3, T0.4, T0.5), and now **turn order and action economy (T0.6)**, which completes P0.4. See `ROADMAP.md`.
- **Not started:** `peek_roll`, decks, read views, golden fixtures, off-air clocks, sectioned rules text, excluded terms, and everything in P1 and later.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.6)

- New `src/basilisk/kernel/turns.py` (`TurnCommands` mixin):
  - `start_encounter(participants, first)`, `end_turn(by, next)`, `next_round`, `end_encounter`, and `current_turn()`
  - all six orders and three economies from `turn_structure.encounter`
  - lint class `turn-structure`
- `commit_action` enforces turn and budget during an encounter, and `available_actions` filters by them. Encounters end at scene and session boundaries.
- New events `encounter_started`, `round_started`, `turn_started`, `economy_spent`, and `encounter_ended`, documented in EVENTS.md. Old logs fold unchanged.
- Lanternlight: `initiative` (`1d20 + {grace}`) with `action` and `minor` slots. Recall uses the minor slot, and the rules text says so. Tidewrack stays `spotlight`.
- Harness: smoke encounter scenes start an encounter and play it turn by turn. Scenario steps `start_encounter`, `end_turn`, `next_round`, and `end_encounter` were added.
- Tools: `end_turn` (`next` under handoff); for the GM, `start_encounter`, `end_encounter`, and `next_round` (spotlight).
- `tests/test_turns.py`: 23 tests. Every order cycles through a scripted encounter, the economy is enforced atomically (slots, points, reactions), deck draws re-derive from the seed, and lifecycle, lint, and tools are covered. Design choices are recorded in D-019.
- Earlier this session: T0.3 (D-016), the engine split, T0.4 (D-017), T0.5 (D-018), and three pushes.

## Next step

- **Track 0 only (D-014).** Ready: T0.7 (`peek_roll`), T0.8 (decks), T0.9 (read views), T0.10 (golden fixtures), T0.11 (off-air clocks), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Suggested next: T0.8 decks (P0.2). `turns.py` already draws a deck order with equal-weight logged draws; generalise that into pack-declared decks. Then T0.7 `peek_roll`, which needs fudgeable procedures in a pack.
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, and `turns.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-16)

- **P0:** done are the event store, randomizer, dice, expression language, pack system, engine (effects, resolution, rulings, determinism settings), scripted harness, deploy tooling, and the canon store (T0.2). See `ROADMAP.md`.
- **Not started:** spatial engine, turn order, `peek_roll`, decks, read views, golden fixtures, sectioned rules text, and everything in P1 and later.
- **Git:** the folder is now a git repository, but it has **no commits** and every file is untracked. The first commit should hold everything to date, including T0.2 and this design revision.

## What changed this session (design revision, no code)

- Owner decisions recorded in `docs/dev/DECISIONS.md`:
  - **D-012:** the broadcast pack is the SRD 5.1 (CC-BY 4.0 release), with sectioned rules text in v1. Rules handling is agnostic by construction. The broadcast pack is written as late as possible (P4.0). No grid in v1.
  - **D-013:** the first provider adapter is Anthropic. The owner supplies the key from a dedicated account when live work starts.
  - **D-014:** Track 0 is finished before any Track 1 work.
- **ARCHITECTURE → 1.5:** §0 overview, §1.1, §1.2 (source pin and trademark caution), §2.3 schema, §2.8, §2.10 lint, §2.11 rewritten, §7.1 `query_rules`, §11.4.
- **BUILD_PLAN → 1.4:** P0.6 names the test packs, new P0.13 (sectioned rules text), two new Gate P0 items, new P4.0 (broadcast pack), and a new Gate P4 item.
- `TASKS.md`: T0.1 is deferred to P4.0. New T0.14 (sectioned rules text, `ready`) and T0.15 (sectioned fixture variant, blocked on T0.14). Track 1 waits for Gate P0.
- `ROADMAP.md` is updated to match. `docs/dev/proposals/REV-ARCH-1.5.md` is the review draft, kept as a record.

## Next step

- **Track 0 only (D-014).** Ready: T0.3 (ZoneGraph, the largest), T0.6 (turn order), T0.7 (`peek_roll`), T0.8 (decks), T0.9 (read views), T0.10 (golden fixtures), T0.11 (off-air clocks), and T0.14 (sectioned rules text).
- Keep everything system-agnostic. Develop and test against `lanternlight`, `tidewrack`, and the baselines only. Nothing 5e-specific goes in before P4.0.

## Open questions for the owner

None blocking. The SRD source document is needed only at P4.0.

## Notes for the next session

- Run `git config core.hooksPath tools/githooks` now that the folder is a git repository.
- Kernel comments are noun-linted too. Avoid words such as "down", "rest", and "recall" in `src/basilisk/kernel/` (see `tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

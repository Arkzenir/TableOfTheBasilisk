# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-16)

- **P0:** done are the event store, randomizer, dice, expression language, pack system, engine (effects, resolution, rulings, determinism settings), scripted harness, deploy tooling, and the canon store (T0.2). See `ROADMAP.md`.
- **Not started:** spatial engine, turn order, `peek_roll`, decks, read views, golden fixtures, sectioned rules text, and everything in P1 and later.
- **Git:** initial commit `3a73a0e` on `main`, plus a housekeeping commit for LF line endings and the licence note. Hooks are installed (`core.hooksPath tools/githooks`). Nothing is pushed.

## What changed this session (design revision, no code)

- Owner decisions recorded in `docs/dev/DECISIONS.md`:
  - **D-012:** the broadcast pack is the SRD 5.1, with sectioned rules text in v1. Rules handling is agnostic by construction. The broadcast pack is written as late as possible (P4.0). No grid in v1.
  - **D-013:** the first provider adapter is Anthropic. The owner supplies the key from a dedicated account when live work starts.
  - **D-014:** Track 0 is finished before any Track 1 work.
  - **D-015:** the SRD 5.1 is used under CC-BY 4.0, not the OGL 1.0a, after research (sources are in DECISIONS). Packs now declare `meta.excluded_terms` for unlicensed names. New task T0.16 and build step P0.14 cover it.
- **ARCHITECTURE → 1.5:** §0 overview, §1.1, §1.2 (source pin and trademark caution), §2.3 schema, §2.8, §2.10 lint, §2.11 rewritten, §7.1 `query_rules`, §11.4.
- **BUILD_PLAN → 1.4:** P0.6 names the test packs, new P0.13 (sectioned rules text), two new Gate P0 items, new P4.0 (broadcast pack), and a new Gate P4 item.
- `TASKS.md`: T0.1 is deferred to P4.0. New T0.14 (sectioned rules text, `ready`) and T0.15 (sectioned fixture variant, blocked on T0.14). Track 1 waits for Gate P0.
- `ROADMAP.md` is updated to match.
- `.gitattributes` forces LF on every OS. Shell scripts and hooks are committed as executable.

## Next step

- **Track 0 only (D-014).** Ready: T0.3 (ZoneGraph, the largest), T0.6 (turn order), T0.7 (`peek_roll`), T0.8 (decks), T0.9 (read views), T0.10 (golden fixtures), T0.11 (off-air clocks), T0.14 (sectioned rules text), and T0.16 (excluded terms).
- Keep everything system-agnostic. Develop and test against `lanternlight`, `tidewrack`, and the baselines only. Nothing 5e-specific goes in before P4.0.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3. Research suggests a lawyer confirm the CC-BY 4.0 rule on technological measures for DRM streaming platforms.

## Notes for the next session

- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words such as "down", "rest", and "recall" in `src/basilisk/kernel/` (see `tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

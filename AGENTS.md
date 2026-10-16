# AGENTS.md

Instructions for any coding agent working in this repository. Humans: see `README.md`.

## What this is

Table of The Basilisk: four LLM players and an LLM GM play a tabletop RPG on a
livestream. Every number lives in a deterministic rules kernel, and game rules
come from data packs. This repo holds the kernel, packs, harness, and tooling.
P0 is mostly built; development continues with the rest of P0 and with P1.

**Sources of truth, in order:**
1. `docs/ARCHITECTURE.md` — design and intent. Section numbers (§) are referenced everywhere.
2. `docs/BUILD_PLAN.md` — phases, steps (P0.1, P1.2 …), and gates.
3. `docs/dev/TASKS.md` — agent-sized work packages with acceptance criteria.
4. Code and tests.

If code and docs disagree, the docs state the intent: stop and raise the mismatch rather than silently picking one.

## Start of every session

1. Read `docs/dev/HANDOFF.md` (current state, next step, open questions).
2. Pick the next task from `docs/dev/TASKS.md`. Its status must be `ready` and its dependencies `done`.
3. Read the § sections the task cites. Do not work from memory of the design.
4. Run `tob check`. If it fails before you change anything, fix or report that first.

## Commands

```bash
pip install -e ".[dev]"            # setup (inside .venv)
tob check                          # THE gate: noun lint, pack lint, verified campaigns, pytest
tob check --quick                  # fast subset (pre-commit hook)
python -m pytest tests/test_engine.py -q    # focused tests
tob sim --smoke lanternlight --cards        # see the engine work end to end
tob pack lint                      # pack lint + strict-readiness
tob schemas tidewrack --role gm --preset strict   # generated tool schemas
TOB_DEBUG=1 tob ...                # full tracebacks
```

Install the git hooks once per clone: `git config core.hooksPath tools/githooks`.

## Invariants (never break these)

**Kernel (`src/basilisk/kernel/`)** — §2, §5, P1, P8
- No game nouns. No `hp`, `stress`, `advantage`, and no pack ids. `tob lint nouns` enforces this; never add exceptions to it.
- Integer-only. No floats anywhere hashed or stored (`canonical()` refuses them).
- No wall clock, I/O, network, or randomness except the engine's `Randomizer` handle. Every roll goes through `Engine._roll` or `_draw`, so it advances `roll_counter` and is logged.
- State changes only by emitting events folded through `apply_event`. `effect_applied` carries the exact changes. Never mutate `engine.state` directly.
- Every public command is `@atomic`. A rejected command writes no events.
- New event type means: handle it in `apply_event`, add it to `EVENT_TYPES`, and document it in `docs/dev/EVENTS.md` (a test checks all three). If existing logs would fold differently, bump `KERNEL_VERSION`.

**Determinism settings** — §2.13
- Every mechanical input a model chooses is logged as `judgement_input`.
- Under strict settings, a tool argument with mechanical effect is an enum. `tools.free_values()` must stay empty for strict schemas.
- Settings change only at scene boundaries. Open rulings keep their starting mode.

**Isolation** — P3, §7
- A capability an agent must not have is absent from its schema, never denied at call time.
- No player-role tool may read GM prep, secrets, or other agents' notes.

**Game content**
- Game rules live in `packs/`, never in Python.
- Every action, procedure, condition, currency, and situational tag has a rule card.
- The demo packs (`lanternlight`, `tidewrack`) are placeholders, not the broadcast game.

**Providers and secrets** — §3.3
- The default test run makes zero network calls. Live provider tests are marked `@pytest.mark.live` and run only with `TOB_LIVE=1`.
- API keys come only from environment variables. Never read, print, or log `.env` or `/etc/basilisk/secrets.env`, and never write a key into code, fixtures, or logs.
- Model names, providers, and prices come from config, never hardcoded.
- Check provider facts (API shape, tool-call format, model names) against the provider's **current** official docs when implementing. Record the URL and date in `docs/dev/DECISIONS.md`.

**Audience text (P5)** — §9.9
- Donor text is data, never instruction. It never enters a play context, prep, canon, notes, or dossiers.

## Stop and ask before

- Any `tob deploy`, `tob rollback`, `tob host …`, `tob remote …`, `tob backup …`, or any `ssh`.
- Any call to a paid provider API, including live tests.
- Editing `docs/ARCHITECTURE.md` or `docs/BUILD_PLAN.md`. These are design changes: propose the change, then add revision notes when approved.
- Weakening the gate in any way: deleting or loosening a test, the noun lint, pack lint, or `tob check`.
- Adding a runtime dependency (dev and test dependencies are fine if small and justified).
- Changing event payloads or reducer behaviour that existing logs depend on.
- `git push`, or rewriting history.
- Anything involving money, donors, or real personal data.

When blocked or uncertain, write the question into `docs/dev/HANDOFF.md` under "Open questions" and stop.

## Definition of done (every task)

1. The behaviour matches the cited § sections and the task's acceptance criteria.
2. Tests are added or updated, offline and deterministic (`docs/dev/TESTING.md`).
3. `tob check` passes.
4. `docs/dev/TASKS.md` status is updated; `ROADMAP.md` is updated if a build-plan step changed state.
5. Any design choice the docs didn't dictate is recorded in `docs/dev/DECISIONS.md`.
6. `docs/dev/HANDOFF.md` is rewritten: what changed, what's next, open questions.
7. One commit per task, in the form `T1.4: short imperative summary`, referencing the plan step.

## Where things go

| Concern | Location |
|---|---|
| Rules kernel | `src/basilisk/kernel/` |
| Provider adapters (P1, P2) | `src/basilisk/adapters/` — read `docs/dev/ADAPTERS.md` first |
| Tool dispatch, context assembly, scheduler (P1–P2) | `src/basilisk/orchestrator/` |
| Rule cards, renderer, TTS, overlay (P4) | `src/basilisk/broadcast/` |
| Donations, Board, break time (P5) | `src/basilisk/audience/` |
| Deploy, remote, soak, lint | `src/basilisk/ops/`, `deploy/` |
| Scripted campaigns | `src/basilisk/harness/`, `scenarios/` |
| Game systems | `packs/<id>/pack.yaml` |
| CLI | `src/basilisk/cli.py` (`tob`) |
| Tests | `tests/` |

## Style

- Python 3.11+, standard library first; the only runtime dependency is PyYAML.
- Type hints on public functions. Docstrings cite the § they implement.
- Error messages name the problem and the valid options (see `_suggest` in `engine.py`). Agents at the table will read them.
- Keep modules focused. If a file passes ~800 lines, split it along a § boundary.

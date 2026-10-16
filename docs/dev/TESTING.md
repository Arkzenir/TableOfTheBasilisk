# Testing

`tob check` is the gate. It runs, in order:

1. kernel noun lint
2. pack lint for every pack
3. a verified three-session campaign on every playable pack (hash chain, replay, snapshot consistency, seed re-derivation, byte-identical second run, full action coverage)
4. `pytest`

The git hooks run `tob check --quick` on commit and the full `tob check` on push.

## Rules for every test

- **Offline.** The default run makes no network calls. Provider tests use the mock adapter or recorded cassettes.
- **Deterministic.** Seeds are explicit. The engine uses a logical clock (`clock=lambda: None`), never wall time. No `sleep`, and no retry-until-pass.
- **Isolated.** Use `tmp_path` for files, `EventStore(":memory:")` for logs, and copies of `packs/` when a test mutates a pack (see `tests/test_packs.py`).
- **Behaviour, not implementation.** Assert on events, state, and returned errors, not on private attributes, wherever possible.
- **Never weaken an existing assertion to make a change pass.** If a test is wrong, explain why in the commit and in `DECISIONS.md`. Changing the gate requires approval (`AGENTS.md`).

## Layers

| Layer | Where | Examples |
|---|---|---|
| Unit | `tests/test_*.py` | dice grammar, expressions, merge rules, schema validator |
| Engine | `tests/test_engine.py` | atomicity, settings changes, rulings, pinning |
| Pack conformance | `tests/test_packs.py`, `tob pack lint` | one test per lint defect class |
| Campaign | `tests/test_harness.py`, `tob check` | smoke campaigns, scenario files, replay, seed verification |
| Golden (T0.10) | `packs/<id>/fixtures/` | `(seed, script) → expected log head hash` |
| Adapter (P1) | `tests/test_adapters_*.py` | mock transport, cassettes |
| Live (P1+) | marked `@pytest.mark.live` | real provider calls; opt-in only |
| Docs consistency | `tests/test_docs.py` | event registry vs `docs/dev/EVENTS.md` |

## Live tests

```python
import pytest

@pytest.mark.live
def test_provider_round_trip():
    ...
```

Skipped unless `TOB_LIVE=1` is set. They cost money: ask the owner before running them (`AGENTS.md`). Live runs should record cassettes so the same coverage runs offline afterwards.

## Golden fixtures

When an intentional change alters event logs (a new event, a payload change), the golden hashes change. Regenerate them deliberately with `TOB_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py`, and explain in the commit why logs changed. If existing campaigns would fold differently, bump `KERNEL_VERSION` (§2.9).

## Time budget

The full `tob check` should stay under about 60 seconds on the development desktop, and `--quick` under about 10 seconds. If a new suite threatens that, mark the slow part `@pytest.mark.slow`, run it in `tob check` but not `--quick`, and say so in `HANDOFF.md`.

## Adding a scenario

Write `scenarios/<name>.yaml` in the format of `scenarios/lanternlight_demo.yaml`. Mark steps the engine must refuse with `expect_error: true`. Then run:

```bash
tob sim scenarios/<name>.yaml --cards
```

Add a test that runs it if it guards a behaviour.

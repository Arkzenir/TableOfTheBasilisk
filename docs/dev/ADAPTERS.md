# Provider adapters

The contract every provider adapter must meet (ARCHITECTURE §3.3, §4.2, §7.5; BUILD_PLAN P1.1, P2.1). The interface is defined in `src/basilisk/adapters/base.py`.

## Principle

The scheduler and the kernel never know which model they are talking to. Everything provider-specific — wire format, tool-call shape, stop reasons, usage fields, error types — stops inside the adapter. Anything that crosses the boundary is one of the types in `adapters/base.py`, or an event.

## The interface

| Method | Used for | Budget |
|---|---|---|
| `bid(context, timeout_ms=800)` | Stage 2 discretionary bid (§4.1) on the seat's cheap model | Hard timeout. Return `None` on timeout; never raise |
| `act(context, tools, token_budget)` | The awarded generation, with tools | `token_budget` from the scheduler, which enforces `verbosity` |
| `recap(context)` | Per-agent session recap (§6.3) | Off-air |
| `prep(context, tools)` | GM prep passes (§7.6) | Off-air |

## Responsibilities, in order, for every `act`

1. **Translate tool schemas.** Input is the kernel's dialect from `kernel/tools.generate()`:
   - `enum`; `oneOf` (rung id *or* bounded integer under standard settings)
   - `type: integer` with `minimum`/`maximum`
   - `type: array` with `items` and `maxItems`
   - `format: id` (a string the engine validates)
   - `x-narrative: true` (free text with no mechanical effect)

   Map these faithfully. **Never widen a type.** If the provider can't express a constraint, keep it in the description and rely on step 3.
2. **Call the provider.** This goes through the transport (`adapters/transport.py`, T1.4), so tests can record and replay.
3. **Validate every tool call before it reaches the engine.** Use `orchestrator/validate.py` (T1.1). The checks are: unknown tool, malformed arguments, a free value where the role's settings require an enum, and out-of-bounds values.
4. **Repair once.** Feed back a structured error naming what was wrong and what is valid, and allow one correction. ID errors include the engine's suggestion ("Did you mean …?").
5. **Degrade.** On a second failure, return an `ActResult` that the dispatcher resolves as `pass`. A broken call must never become dead air.
6. **Detect refusals.** Use the provider's structured signals first (stop or finish reasons, safety flags), then a conservative text check. Set `refused=True`; the scheduler re-awards the floor. A refusal is a technical failure, not content (§9.10).
7. **Account usage.** Record input, output, and cached tokens, latency, and model id, together with the seat. The metrics report (T1.8) and cost control (§4.7) depend on this.

## Events adapters cause

These are passive events: the reducer accepts them and they don't change game state.

| Event | When |
|---|---|
| `bid_submitted` / `bid_timeout` | Every Stage 2 bid (P2) |
| `tool_call` | Every call the model attempts, valid or not |
| `tool_error` | Every rejected call, with the error returned to the model |
| `refusal_detected` | Every detected refusal |
| `model_usage` | Every provider call: tokens, cached tokens, latency, model |

Add each one to `EVENT_TYPES` and `docs/dev/EVENTS.md` when you first emit it. Payloads must never contain credentials. Prompts may be logged in full only in the archive store (§8.5), never in the overlay path.

## Configuration, not code

Providers, model ids, cheap-tier model ids, prices, and per-seat voices come from the agent roster in config (ARCHITECTURE Appendix C). Nothing provider-specific is hardcoded outside the adapter, and model ids are not hardcoded inside it either.

```yaml
agent_roster:
  - agent_id: ash
    provider: <provider>
    model: <model id from the provider's current docs>
    cheap_model: <cheap-tier model id>
    voice_id: ...
```

## Secrets

- Keys are read from environment variables only. Use `.env` locally (gitignored) and `/etc/basilisk/secrets.env` on the host.
- Never log, print, or serialise a key. The transport's record mode strips auth headers and any value matching a key pattern; a test enforces this over every cassette.

## Dependencies

Each provider SDK goes in its own optional dependency group in `pyproject.toml` (e.g. `[project.optional-dependencies] <provider> = ["<sdk>==<pinned version>"]`). The core install stays dependency-light. Adding one requires approval (`AGENTS.md`). Pin exact versions, and prefer releases at least two weeks old.

## Verify provider facts at implementation time

APIs, tool-calling formats, model names, caching behaviour, and pricing change. When implementing or updating an adapter:

1. Read the provider's current official API docs for tool use, streaming, caching, and stop reasons.
2. Record the URLs and the date in `docs/dev/DECISIONS.md`, under a decision named for the adapter.
3. Check terms of service for this use case (ARCHITECTURE §3.3 action item); flag concerns in `HANDOFF.md`.

## Testing an adapter

- **Unit:** `MockTransport` responses covering valid calls, malformed calls, unknown tools, invented ids, refusals, timeouts, and provider errors.
- **Cassettes:** realistic recorded exchanges replayed offline. This is how the malformed-call suite (BUILD_PLAN P1.1: 200 malformed calls, zero reaching the engine) runs in `tob check`.
- **Live:** `@pytest.mark.live`, run only with `TOB_LIVE=1` and with approval. Live runs record new cassettes; they never gate CI.
- **The five-adapter diff (P2.1):** the same scripted scenario through every adapter, comparing tool-failure rate, refusal rate, and latency. Results feed seating decisions (§3.3).

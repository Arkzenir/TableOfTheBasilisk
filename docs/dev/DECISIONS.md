# Decisions

Implementation choices the design docs didn't dictate. Append new entries at the bottom; never edit an accepted entry. Supersede it with a new one instead.

Template:

```
## D-NNN Title
- Date: YYYY-MM-DD · Status: accepted | superseded by D-NNN
- Context: what forced a choice
- Decision: what we chose
- Consequences: what this commits us to; what to revisit
- Sources: URLs consulted (with access date) when external facts were involved
```

---

## D-001 Python and SQLite for the kernel and harness
- Date: 2026-10-15 · Status: accepted
- Context: a solo developer, fast iteration, and good LLM SDK coverage. The event log must be durable and portable.
- Decision: Python 3.11+, standard library first, PyYAML as the only runtime dependency. Event store on SQLite in WAL mode, with append-only triggers.
- Consequences: integer-only arithmetic is enforced by `canonical()`. Performance is ample for one table; revisit only if soak runs show otherwise.

## D-002 HMAC-SHA256 randomizer instead of Python `random`
- Date: 2026-10-15 · Status: accepted
- Context: rolls must be identical on any machine and any Python version, and verifiable after the seed is published (§5.5).
- Decision: each integer is HMAC-SHA256(seed, "counter:sub:attempt") with rejection sampling. The log stores a commitment to the seed, never the seed itself.
- Consequences: `tob verify --seed` can re-derive every roll. The seed must be kept secret until the campaign ends.

## D-003 `effect_applied` events carry exact state changes
- Date: 2026-10-15 · Status: accepted
- Context: replay must not depend on re-running rules, which may later change.
- Decision: the engine computes changes; the reducer only applies `{path, value|delete}`.
- Consequences: the reducer is pack-agnostic and trivially replayable. Event payloads are slightly larger.

## D-004 Engine commands are atomic
- Date: 2026-10-15 · Status: accepted
- Context: a command can fail midway (bad GM input, an effect precondition).
- Decision: the `@atomic` decorator wraps each command in an SQLite transaction plus an in-memory state restore.
- Consequences: rejected commands leave no events. Harnesses can attempt and recover freely.

## D-005 Demo packs are kernel fixtures, not the broadcast game
- Date: 2026-10-15 · Status: accepted
- Decision: `lanternlight` (roll-over) and `tidewrack` (banded) are tiny original CC0 games that exist to prove two-family support. The broadcast system is T0.1.

## D-006 Hooks refused until the sandbox exists
- Date: 2026-10-15 · Status: accepted
- Decision: `HOOK_REGISTRY` is empty, so any pack declaring a hook fails to load. This satisfies §2.7's refusal requirement until T0.12.

## D-007 Determinism defaults: players strict, GM standard
- Date: 2026-10-15 · Status: accepted
- Decision: per ARCHITECTURE §2.13.2 (v1.3). Settings are stored fully expanded in the log, so code defaults can change without affecting replay.

## D-008 AGENTS.md is canonical; tool-specific files import it
- Date: 2026-10-15 · Status: accepted
- Context: the project is developed with a desktop coding agent (currently Claude Code) and must stay agent-agnostic.
- Decision: `AGENTS.md` holds all agent instructions. `CLAUDE.md` imports it with `@AGENTS.md`, because Claude Code reads CLAUDE.md, not AGENTS.md. `.claude/settings.json` enforces part of the approval list for Claude Code. Git hooks enforce the gate for every agent and human.
- Sources: Claude Code memory docs, https://code.claude.com/docs/en/memory (accessed 2026-10-15).

## D-009 `docs/dev/EVENTS.md` is the exact event registry
- Date: 2026-10-15 · Status: accepted
- Context: ARCHITECTURE §5.7 is an abbreviated design list; the code has more types (e.g. `chargen_started`, `gm_resolution`).
- Decision: EVENTS.md mirrors `EVENT_TYPES` exactly, with a test enforcing it. ARCHITECTURE §5.7 stays a summary and is updated at the next design revision.

## D-010 Canon store: records in state, indexes derived per scope
- Date: 2026-10-16 · Status: accepted
- Context: T0.2 (§1.3, §6.2, §6.5). The docs fix the record shape and the rules but not the index mechanics.
- Decision:
  - Records live under `state["canon"]`, keyed by id. The key is created by the first canon event, so logs written before the store existed fold to the same state hash. No `KERNEL_VERSION` bump.
  - `CanonIndex` (alias table, word table, relation graph) is rebuilt from state per scope: `gm`, or `players`. A seat id maps to its role's scope. The player index is built from a record set with every `secret` removed. Player-visible records also lose `discovery_paths`, lose `depends_on` ids the scope cannot see, and show the first visible successor as `superseded_by`. If every successor is secret, they show none, because the table still holds the old belief.
  - Indexes are cached on the engine by a fingerprint of `(id, superseded_by, knowledge)`, the only mutable fields. `atomic` clears the cache on rollback, because a rolled-back id and seq can be reused.
  - Name keys: lowercase words, possessives and punctuation stripped, plus a second key without filler words (`the`, `that`, `a`, …). Resolution order: exact id, then alias key, then partial (every query word appears in the record's names). An exact key clash with any current record, secrets included, is rejected. A difflib ratio ≥ 0.85 is flagged in the `canon_written` payload.
  - `knowledge` and `origin` are required, with no defaults. A `secret` needs at least one discovery path (§7.6.2 axioms 3 and 10). Discovery paths may name canon records or entities.
  - Scene bundle: breadth-first, 2 hops over `depends_on` and `discovery_paths` edges (both directions), with superseded ids redirected to their successors.
  - `supersede_canon` is an engine command but not a model tool. Corrections belong to the post-session pass (§7.6.3), which the orchestrator will drive.
  - `atomic`, `EngineError`, and `_suggest` moved to `kernel/command.py` so that command mixins can use them. `engine.py` re-exports them, and it was already past ~800 lines.
- Consequences: player-scoped queries cannot reach a secret through any phrasing. The per-character knowledge tier (§6.2) is not modelled yet: every player seat shares one table-knowledge index.

## D-011 Shared player canon; personal, fallible copies in notes; no mid-session retcons
- Date: 2026-10-16 · Status: accepted (owner, answering HANDOFF questions 4 and 5)
- Decision:
  - **Character knowledge.** Every player seat queries the same canon (the `players` index, secrets excluded). The kernel has no per-character canon scope. Each agent keeps its own copy of what it learned in its notes (§6.4). Those copies are free text and never validated or corrected against canon, so an agent can recall things incorrectly. Per-agent recaps add controlled error through `memory_fidelity` (§6.3). The validation pass (§1.3.3) checks GM narration, not a player's misremembering.
  - **No retcons mid-session.** `supersede_canon` is refused between `session_started` and `session_ended`. During play the GM may still `write_canon` new records and `reveal` secrets. Supersede stays allowed before the first session (Session 0 prep) and between sessions (the post-session pass).
  - The open/closed check reads the event log instead of a folded flag. Adding a flag to state would change the folded state of every existing log and force a `KERNEL_VERSION` bump. The check scans the log, which is acceptable because supersede is rare and off-air.
- Consequences: ARCHITECTURE §6.2 was revised to match this decision (version 1.4, approved by the owner on 2026-10-16). Note tools are task T1.10.


## D-012 Broadcast system: SRD 5.1, sectioned rules text in v1
- Date: 2026-10-16 · Status: accepted (owner). ARCHITECTURE 1.5, BUILD_PLAN 1.4.
- Context: the owner chose the D&D 5e SRD (2014 rules) because more viewers know them. The design said v1 ships one inline rules-light pack, with sectioned text deferred to v2. §1.2 does not list the OGL 1.0a.
- Decision:
  - The source is the **SRD 5.1**. Its licence is chosen separately (D-015). The required notice is copied verbatim from the source. The stream uses no D&D trademarks.
  - **Sectioned rules text is v1** (§2.11). `query_rules` resolves by key: section ID, then catalogue ref, then alias, then partial match, with key normalisation shared with canon. Vector search over rules stays in v2.
  - **Rules handling is system-agnostic by construction.** The kernel has no section taxonomy, and sections are opaque text. Structure (`parent`, `refs`) is pack data. Inline packs may declare sections too.
  - **The broadcast pack is written as late as possible** (BUILD_PLAN P4.0, gating Phase 4). Gate P0 and Phases 1–3 develop against `lanternlight` and `tidewrack`, plus a data-only sectioned variant. The owner supplies the source document at P4.0.
  - No grid in v1. SRD distances map to range bands. `SquareGrid` stays in v2, to be added when appropriate.
- Consequences: new tasks T0.14 (sectioned rules text) and T0.15 (sectioned fixture variant). T0.1 is deferred to P4.0.

## D-013 First provider adapter: Anthropic (Claude)
- Date: 2026-10-16 · Status: accepted (owner, answering HANDOFF question 2)
- Decision: T1.5 targets the Anthropic Messages API. The owner will create a dedicated account and supply its API key through an environment variable when live work begins. No key is needed before then. All tests stay offline, using cassettes and the mock adapter.
- Note: check the API shape, tool-call format, and model names against Anthropic's current docs when T1.5 starts, and record the URL and date here.

## D-014 Finish Track 0 before Track 1
- Date: 2026-10-16 · Status: accepted (owner, answering HANDOFF question 3)
- Decision: complete the Track 0 tasks (Gate P0) before starting any Track 1 task, including the parallel-safe ones.

## D-015 SRD 5.1 licence: CC-BY 4.0 or OGL 1.0a (open)
- Date: 2026-10-16 · Status: open. Decide before P4.0.
- Context: the owner noted that SRD 5.1 is dual-released: under the OGL 1.0a (since 2016) and under CC-BY 4.0 (since January 2023), with the same text. A user may pick either licence. The owner thinks the OGL may suit the project better. The design text first assumed CC-BY only.
- What each requires, to verify against the current source and licences at P4.0:
  - **CC-BY 4.0:** an attribution statement, and nothing else. It is irrevocable and is already on the §1.2 permitted list.
  - **OGL 1.0a:** the full licence text distributed with the work, a Section 15 copyright notice, an explicit designation of Open Game Content and Product Identity, and no use of trademarks or claims of compatibility beyond what the licence allows. Content derived from Open Game Content becomes Open Game Content itself, a share-alike effect that §1.2 already flags as a caveat for generated content. Choosing it adds the OGL 1.0a to the §1.2 permitted list in an ARCHITECTURE revision note.
- Until decided: the kernel, packs, and harness are unaffected. `meta.license` and `meta.attribution_text` already hold either licence. Not legal advice.


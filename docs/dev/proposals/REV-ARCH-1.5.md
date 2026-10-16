# Draft revision: ARCHITECTURE 1.5 / BUILD_PLAN 1.4

**Status:** applied on 2026-10-16, with changes. The owner chose SRD 5.1 and no grid, and asked for the broadcast pack as late as possible, so it moved from P3.0 to **P4.0**. The applied text also adds `parent` nesting and the no-taxonomy rule to §2.11. The design docs are authoritative; this file is kept only as a record.
**Implements:** D-012 (approved by the owner on 2026-10-16). Sectioned rules text moves into v1. The SRD 5.1, in its CC-BY 4.0 release, becomes the broadcast pack.
**Owner constraint:** development stays system-agnostic. Nothing in the kernel, harness, or orchestrator is tuned to 5e.

Each change gives the location, the current text, and the proposed text. Points that need a decision from you are marked **⚑ Decide**.

---

## A. ARCHITECTURE.md

### A1. Header: version and revision note

**Current:** `**Version:** 1.4 (revised design freeze for v1)`

**Proposed:** `**Version:** 1.5 (revised design freeze for v1)`, plus a new note after the 1.4 notes:

> **Revision notes (1.5):**
> - The v1 broadcast system is the **System Reference Document 5.1**, used under its **CC-BY 4.0** release (§1.1, §1.2).
> - **Sectioned rules text** (§2.11) moves from v2 into v1. A sectioned pack inlines a compact rules digest and serves the full text through `query_rules`, which resolves by key first. Vector search over rules stays v2.
> - Gate P0 is proven on the kernel fixture packs. The broadcast pack is a content step and gates Phase 3 (BUILD_PLAN 1.4).

### A2. §0 overview, line 37

**Current:** "…so the table can play a rules-light indie game one season and a dice-pool or 2d6-move system the next."

**Proposed:** "…so the table can play a large d20 system one season and a rules-light dice-pool or 2d6-move game the next."

### A3. §1.1 Game systems: rewrite the decision and the first paragraph

**Current:**
> **Decision:** the engine is a system-agnostic rules kernel and each game is a system pack (§2). v1 ships one rules-light pack, loaded whole into context.
>
> The decisive property of a rules-light system (roughly 20 pages) is that it **fits entirely in every agent's context**. This deletes the entire rules-retrieval subsystem for v1: no chunking, no index, no RAG quality failures, no agent failing to look something up.

**Proposed:**
> **Decision:** the engine is a system-agnostic rules kernel and each game is a system pack (§2). The v1 broadcast pack is the **SRD 5.1** (§1.2). It is too large to inline, so it uses sectioned rules text (§2.11). The kernel test packs stay rules-light and inline. v1 therefore supports both modes, and neither mode is the special case.
>
> An inline pack (roughly 20 pages) **fits entirely in every agent's context**, so it needs no rules retrieval. A sectioned pack inlines a compact digest and looks up the rest **by key**: section IDs, aliases, and catalogue IDs, using the same Layer 0 mechanism as canon (§6.5). There is no chunking and no embedding index in v1. A rules question that cannot be answered by key fails with suggestions, and the miss is logged.

**Keep, lightly edited:** the "contaminated prior" paragraph. It now describes the v1 game directly. Proposed last sentence:
> v1 plays a famous game, so this is a live risk rather than a hypothetical. The digest states which edition is in force. The validation pass (§1.3.3) checks narrated mechanics against the pack, not against what the model remembers. `query_rules` is the sanctioned way to settle a doubt.

**Current (line 127):** "Adding another rules-light system is a new pack. Adding a large system such as the 5.1 SRD is a new pack plus sectioned rules text (§2.11). Neither is a kernel change."

**Proposed:** "Adding another system, rules-light or large, is a new pack. Choosing inline or sectioned text is a field in the pack. Neither is a kernel change."

### A4. §1.2 Licensing: pin the source and add a trademark caution

§1.2 already permits CC-BY 4.0 and names the 5.1 SRD. **Proposed addition** after the permitted-sources list:

> **v1 broadcast source:** SRD 5.1, CC-BY 4.0 release, with no OGL material. The pack's `meta.license` is `CC-BY-4.0`, and `meta.attribution_text` carries the attribution statement that Wizards of the Coast publishes with that release, copied verbatim from the source document when the pack is written (T0.1). The attribution appears in the VOD description and the stream's about panel.
>
> The licence covers the text, not the trademarks. The stream never uses "Dungeons & Dragons", D&D logos, or trade dress, and describes the game only as "compatible with fifth edition" or "using the SRD 5.1." Product-identity material (named settings, named creatures, and characters outside the SRD) is excluded.

**⚑ Decide:** do you want the SRD **5.1** (2014 rules) as approved, or the **5.2** SRD (2024 rules, also CC-BY 4.0)? This draft assumes 5.1.

### A5. §2.3 pack schema, line 310

**Current:** `mode: inline | sectioned        # sectioned is v2 (§2.11)`

**Proposed:**
```
  rules_text:
    mode: inline | sectioned        # §2.11
    full_text                       # inline
    digest                          # sectioned: always-loaded summary
    sections: [{ id, title, aliases, body, refs }]   # sectioned
```
`refs` are the catalogue IDs a section governs (actions, conditions, procedures). They let the kernel map an ID to its section (A6).

### A6. §2.11 Rules text at scale: rewrite

**Current:**
> - **Inline** — the full text is layer 2 of every context (§6.1). The v1 design, and the reason rules retrieval does not exist in v1.
> - **Sectioned** — for systems too large to inline. The text is split into sections with IDs and aliases; a compact rules digest is inlined instead; `query_rules` resolves section IDs and aliases by key first, consistent with §6.5 Layer 0, with vector search last.
>
> **v1 ships inline only.** The sectioned interface is defined now so that a heavy system is a content project in v2, not a kernel change.

**Proposed:**
> - **Inline:** the full text is layer 2 of every context (§6.1). `query_rules` still works and searches the same sections, if the pack declares any.
> - **Sectioned:** for systems too large to inline. Layer 2 carries the pack's `digest`. The full text is split into sections with stable IDs, aliases, and `refs`.
>
> **Resolution (v1):** `query_rules(query)` resolves in this order: exact section ID, catalogue ID (through `refs`), alias key, then partial match (every query word appears in a section's title or aliases). Key normalisation matches canon (D-010), so the two indexes cannot drift apart. The section index is built once from the pinned pack, so it is deterministic and hashed with the pack. A miss returns the three closest section titles and is logged. **Vector search over rules is v2.** The Layer-3 hit-rate rule (§6.5) applies here too: frequent misses mean the aliases are weak, so fix the pack.
>
> **Returned text:** a hit returns the section body, capped at the pack's `max_section_tokens`. A longer section must be split by the author, and the linter enforces this.
>
> **Rule cards (§8.6)** never show section text, only titles (unchanged).
>
> **Lint (§2.10):** an inline pack's `full_text` must fit the context budget. A sectioned pack's `digest` must fit the budget, every section must fit `max_section_tokens`, every alias key must be unique across sections, and every action, procedure, and condition must be covered by at least one section's `refs`.

### A7. §2.8 shipped packs, line 503

**Current:** "v1 ships `core`, the family baseline for the playable pack, the playable rules-light pack, and a second complete pack in a different family (§2.10)."

**Proposed:** "v1 ships `core`, the family baselines, the two kernel test packs from different families (`lanternlight`, roll-over; `tidewrack`, banded), a data-only sectioned variant of one of them, and the broadcast pack, the SRD 5.1 on the roll-over baseline (§2.10)."

### A8. §2.10 static lint, line 526

**Current:** `- inline rules text fits the context budget (§6.1)`

**Proposed:** `- rules text fits the context budget: inline full text, or a sectioned digest plus per-section caps, alias uniqueness, and catalogue coverage (§2.11)`

### A9. §6.1 context layer 2

No change. The table already reads "Full rules text (inline packs) or rules digest (sectioned packs, §2.11)".

### A10. §7.1 world tools, line 1279

**Current:** `query_rules(query)                 → rarely needed when rules are inline`

**Proposed:** `query_rules(section_id | query)    → key-first lookup per §2.11; the main path for sectioned packs`

### A11. §11.4 Deferred to v2

**Current:** `- Sectioned rules text for large systems (§2.11)`

**Proposed:** `- Vector search over rules text (§2.11). Key-first sectioned lookup is in v1.`

**⚑ Decide (spatial, no change proposed):** 5e combat assumes a grid, but `SquareGrid` is v2 (§2.4, §11.4). This draft keeps v1 on ZoneGraph and RangeBands, which maps to theatre-of-the-mind 5e: SRD distances become range bands in the pack. If you want grid combat on stream in v1, that is a separate revision.

---

## B. BUILD_PLAN.md

### B1. Revision note

> **Revision notes (1.4):** The broadcast pack is the SRD 5.1 (CC-BY 4.0) with sectioned rules text, now in v1 (ARCHITECTURE §1.1, §2.11). Gate P0 is proven on the kernel test packs, so kernel work is never tuned to the broadcast game. The broadcast pack is built as content in P3.0 and gates Phase 3.

### B2. P0.6 Baselines and first packs

**Current:**
> - The family baseline for the playable pack
> - **The playable rules-light pack**, extending it. Measure `full_text` token count against the context budget with room for all other layers
> - **A second complete pack from a different resolution family** — …

**Proposed:**
> - Family baselines: `core.roll_over` and `core.banded`
> - **Two complete kernel test packs from different resolution families** (`lanternlight`, `tidewrack`), each complete enough to play a scripted campaign. **Not stubs.** Measure each `full_text` token count against the context budget, leaving room for all other layers.
> - **A data-only sectioned variant** of one test pack. It switches `rules_text` to sectioned with a digest and changes nothing else. It proves that sectioned mode is a pack field, not a kernel change.

Test line: append "The sectioned variant passes conformance and runs the same scripted campaign as its parent, with an identical event stream apart from rules-lookup events."

### B3. New step P0.13 Sectioned rules text

> ### P0.13 Sectioned rules text
> - Section schema, digest, `refs`, and `max_section_tokens` in the pack loader (§2.3, §2.11)
> - Deterministic section index built from the resolved pack (ID, catalogue ref, alias, partial), sharing key normalisation with canon
> - `query_rules` engine query: key-first, with suggestions on a miss and a logged lookup
> - Lint: digest budget, section caps, alias uniqueness, catalogue coverage
>
> **Test:** every section is reachable by its ID and by each alias. Every catalogue ID resolves to a covering section. Misses return suggestions. One defect of each new lint class is caught. Index construction is byte-identical across runs.

### B4. Gate P0 additions

> - [ ] Sectioned and inline modes both pass conformance; the sectioned variant runs with zero kernel changes made for it
> - [ ] `query_rules` resolves 100% of section IDs, aliases, and catalogue refs in every shipped pack

The existing items "Both shipped packs are strict-ready …" and "on both packs" now refer to the two kernel test packs.

### B5. New step P3.0 Broadcast pack (before Session 0)

> ### P3.0 Broadcast pack: SRD 5.1
> - `packs/srd51/` extending `core.roll_over`, sectioned, CC-BY 4.0 attribution in `meta`
> - Digest that names the edition in force (§1.1), within budget
> - Rule-card data for every action, procedure, condition, currency, and tag; strict-ready on every control
> - Golden fixtures and the derived house-rules check, as in P0.7
> - **Zero kernel code changes made for it.** Any kernel change it seems to need is raised as a defect against the kernel, fixed generically, and proven on the test packs first.
>
> **Test:** the pack passes conformance, the smoke campaign covers every action, and `query_rules` reaches every section.

Gate P3 gains: `- [ ] The broadcast pack (P3.0) passes conformance and was built with zero kernel changes made for it`.

**⚑ Decide:** this moves the broadcast pack out of Gate P0. Phases 1 and 2 would then play on `lanternlight` and `tidewrack`. That fits your goal of not tuning development to one ruleset, and it lets the PDF arrive later. The alternative is to keep the SRD pack in P0.6, which makes Gate P0 wait for the PDF.

---

## C. Follow-up edits once approved (not design docs)

- `docs/dev/TASKS.md`: T0.1 becomes the P3.0 content task. Add **T0.14 Sectioned rules text** (P0.13) and **T0.15 Sectioned fixture variant** (P0.6) as `ready` in Track 0.
- `docs/dev/DECISIONS.md`: D-012 status becomes `accepted`, pointing at ARCHITECTURE 1.5.
- `ROADMAP.md`: P0.6 notes, a new P0.13 row, and a P3.0 row.

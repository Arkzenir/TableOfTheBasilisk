# Table of The Basilisk — Architecture Specification

**Version:** 1.8 (revised design freeze for v1)
**Status:** Design complete. Open items listed in §11.
**Companion document:** `BUILD_PLAN.md` — phased implementation, gates, and tests.

**Revision notes (1.1):**
- The project is named **Table of The Basilisk**.
- The deterministic engine is now a system-agnostic **rules kernel** driven by **system packs** (§2). The single `RulesetModule` is replaced. New systems are built by configuration and by extending a baseline pack.
- Audience support is now a **donation Board** ranked by amount, read and reacted to by the cast in **break time** segments (§9.7–§9.9). Paid content no longer enters the fiction; the paid rumor, naming, and complication-card tiers are removed.
- A new section §2 is inserted; every section from the old §2 onward is renumbered up by one.
- Terminology: **"the Board"** (capitalised) always means the donation board. The visual battlefield is "the map" or "scene view", and engine positions are "tactical state".

**Revision notes (1.2):**
- **Determinism settings** (§2.13). Under strict settings no model hands the engine a number: difficulties, modifiers, and ruling consequences come from pack ladders, automatic derivation from state, and seeded draws, and every remaining model choice is a selection by ID, logged and measurable.
- **Rule cards** (§8.6). Every action or rule used during a campaign appears on the livestream as a popup card, rendered from the event log and pack data, backed by a complete rules log.

**Revision notes (1.3):**
- Determinism settings are now **per role and per control**, with presets. **Defaults: players strict, GM standard** (GM strict mode off).
- Settings are **toggleable mid-campaign**: between sessions by config, or during a session through an operator control. Changes apply at the next scene boundary, are logged as events, replay exactly, and are shown on the overlay (§2.13.3, §9.3).

**Revision notes (1.4):**
- **Character knowledge** (§6.2) no longer scopes canon retrieval. Every player seat queries the same canon, with secrets excluded. Each agent keeps its own copy of what it learned in its notes and recap, and that copy can be wrong (D-011).

**Revision notes (1.5):**
- The v1 broadcast system is the **System Reference Document 5.1**, used under its **CC-BY 4.0** release. The OGL 1.0a release is not used (§1.2). D-012, D-015.
- **Excluded terms** (§1.2, §1.3.3, §2.3). A pack lists the names its licence does not cover. They are refused in canon, and checked in every line before TTS and the overlay.
- **Sectioned rules text** (§2.11) moves from v2 into v1. A pack chooses inline or sectioned text as data. A sectioned pack inlines a compact digest and serves the full text through `query_rules`, which resolves by key first. Vector search over rules stays in v2.
- Rules handling stays system-agnostic. The kernel imposes no section taxonomy, and every rules feature is proven on the kernel test packs before any broadcast pack uses it. The broadcast pack is written as late as possible (BUILD_PLAN 1.4, P4.0).


**Revision notes (1.6):**
- §2.3 (pack schema) and §5.7 (event schema) now describe what Phase 0 built (T0.2 to T0.28), including the owner's decisions of 2026-10-26: the `scene_closed` marker, condition stacking by intensity, weight inventory, harm as a declaration of targets, and progression (BUILD_PLAN P0.15). `docs/dev/EVENTS.md` remains the exact event registry.
- Mechanical state changes are logged as one `effect_applied` event that names its primitive (D-003), not as one event type per primitive.

**Revision notes (1.7):**
- §2.3 `gm` block, matching the build after the second Phase 0 audit (T0.31, T0.32, D-046, D-047):
  - `gm_rolls: false` means no GM-side entity rolls;
  - a `party` currency is one shared pool;
  - a `gm` currency is one pool on the GM's side;
  - `lethality_levers` is reserved for trait implementation (BUILD_PLAN P2.5).

**Revision notes (1.8):** after the third Phase 0 audit (T0.33 to T0.36, D-048 to D-050):
- §2.3: chargen choices may grant starting `items` and each-player `currencies` (§1.5).
- §2.5: the example procedures use the modifier sources and interpret keys the kernel implements (`stat`, `conditions`, `tags`; `margins` for degrees of success).
- §2.8: `core.pool` is a later baseline; v1 ships `core.roll_over` and `core.banded`, and the pool shape runs on `core`.
- §7.1: the GM's ruling on a player's action, including substituting a fiction-triggered move (§2.13.1).

---

## 0. Overview

### 0.1 What this is

Table of The Basilisk is a system in which four LLM agents and one LLM game master play a tabletop roleplaying campaign together, over a text channel, with text-to-speech, deterministic game mechanics, and a rendered visual map. The campaign is livestreamed unedited and later re-cut into produced episodes.

The design goal is not "LLMs generate a fantasy story." It is to simulate, as closely as possible, **a group of friends playing a TTRPG campaign over the internet** — including the silences, the interruptions, the misremembered NPC names, the rules arguments, and the player who won't stop talking about their backstory.

Two things extend that simulation:

- **The game is not fixed.** The deterministic engine is a kernel that runs whatever game a **system pack** describes, so the table can play a large d20 system one season and a rules-light dice-pool or 2d6-move game the next.
- **The audience is part of the night, not part of the plot.** Viewers donate with a message; messages go up on a Board ranked by amount; and at breaks the cast steps out of character, reads them, and reacts — the way a streamed table takes ten minutes to read chat.

### 0.2 Design principles

These are load-bearing. Every decision in this document derives from one of them.

**P1 — The model narrates, the engine decides.**
Anything with a number attached lives outside the model. If two agents could disagree about a fact and one of them would be wrong, the engine owns that fact. Agents reach mechanical state only through tools. For any role on strict settings (§2.13) — players by default, the GM when switched on — no model supplies a number to the engine at all: every mechanically meaningful input is chosen by ID from an engine-generated list.

**P2 — Traits are information control, not instruction.**
"You are a bad tactician" decays within an hour of play. Showing an agent five poorly-annotated tactical options instead of twelve well-annotated ones produces bad tactics indefinitely. Wherever a personality trait can be expressed by controlling what reaches the agent's context, it must be.

**P3 — Isolation is structural, not instructed.**
Agents have no filesystem and no network. They have a tool API. A capability an agent must not have is *absent from its schema*, not denied at call time.

**P4 — Canon is append-only and keyed.**
Facts are written once, given stable IDs, and referenced thereafter. Nothing is edited. Corrections are new records that supersede old ones by ID. Drift is prevented by making recall unnecessary.

**P5 — No generated imagery.**
All visuals derive from structured state or from authored assets. The renderer is a pure function of scene state. (One open exception: §11.1.)

**P6 — Production may remove, never re-roll.**
Applies to the edited VOD. The livestream is unedited by construction. Everything aired happened, once, in order.

**P7 — Determinism is for what can be checked, never for what can only be judged.**
Numbers, positions, timing, resources, facts: deterministic. What a character says, how they feel, what the room smells like: not. Constraining the second category produces a consistent, boring table.

**P8 — The kernel knows no game.**
The deterministic engine contains mechanisms, not rules: randomizers, entities, effects, resolution procedures, turn order, space, time. Every game noun — hit points, stress, advantage, a 7–9 partial success — arrives as data in a system pack. Configuration first; a small, pure, named code hook only where configuration cannot express a procedure cleanly.

**P9 — Audience text is data, and it never enters the fiction.**
A donation buys a moment at the table, never a moment in the game. Donor messages are sanitised, ranked, and read out of character during breaks. They never reach canon, prep, dice, or a context used for play, and while they are in any context, no tool that can change game state exists.

### 0.3 System map

```
┌───────────────────────────────────────────────────────────────────────────┐
│  AGENT LAYER                                                              │
│  4 players + 1 GM, each on a different provider                           │
│  Reachable only via the Adapter Layer                                     │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ normalised: bid() act() recap() prep()
┌─────────────────────────────────────▼─────────────────────────────────────┐
│  ADAPTER LAYER — per-provider translation, validation,                    │
│  retry, refusal detection, tool-call repair                               │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌─────────────────────────────────────▼─────────────────────────────────────┐
│  ORCHESTRATOR                                                             │
│  Scheduler (bids, floor, interrupts, break mode) · Context Assembler ·    │
│  Pacing Watchdog · Session Runner                                         │
└───┬──────────────┬──────────────┬──────────────┬──────────────┬───────────┘
    │              │              │              │              │
 ┌──▼──────────┐┌──▼──────────┐┌──▼──────────┐┌──▼──────────┐┌──▼──────────┐
 │ RULES KERNEL││ CANON STORE ││ SPATIAL     ││UTILITY MODEL││ AUDIENCE    │
 │+ system pack││ IDs, aliases││ ENGINE      ││ (shared,    ││ SERVICE     │
 │ randomizers ││ knowledge   ││ ZoneGraph / ││ cheap)      ││ intake      │
 │ entities    ││ retrieval   ││ RangeBands  ││ validation  ││ sanitise    │
 │ effects     ││ digest      ││ enumeration ││ recaps      ││ donor store │
 │ resolution  ││             ││ visibility  ││ moderation  ││ Board       │
 │turns, clocks││             ││             ││ metrics     ││ read queue  │
 └──┬──────────┘└──┬──────────┘└──┬──────────┘└──┬──────────┘└──┬──────────┘
    └──────────────┴──────────────┴───┬──────────┴──────────────┘
                                      │
┌─────────────────────────────────────▼─────────────────────────────────────┐
│  EVENT STORE — append-only log; all state is a fold over it               │
│  (donor content lives in the audience store; events hold references)      │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌─────────────────────────────────────▼─────────────────────────────────────┐
│  BROADCAST PIPELINE                                                       │
│  Buffer (5–10 min) · TTS · Renderer · Overlay + Board · Stream out        │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Game and Content

### 1.1 Game systems

**Decision:** the engine is a system-agnostic rules kernel and each game is a system pack (§2). The v1 broadcast pack is the **SRD 5.1** (§1.2). It is too large to inline, so it uses sectioned rules text (§2.11). The kernel test packs are rules-light, and their text is inline. v1 supports both modes, and neither one is a special case.

An inline pack (roughly 20 pages) **fits entirely in every agent's context**, so it needs no rules retrieval. A sectioned pack inlines a compact digest and looks up the rest **by key**: section IDs, aliases, and catalogue IDs, using the same Layer 0 mechanism as canon (§6.5). v1 has no chunking and no embedding index. A rules question that cannot be answered by key fails with suggestions, and the miss is logged.

Contaminated prior: an agent "knows" 5e as a blend of 2014 rules, 2024 rules, 3.5e, and popular homebrew, and will assert all of it confidently. With an unfamiliar rules-light system, the rules in context are the only rules it has. v1 plays a famous game, so this is a live risk, not a hypothetical. The digest states which edition is in force. The validation pass (§1.3.3) checks narrated mechanics against the pack, not against what the model remembers. `query_rules` is the sanctioned way to settle a doubt.

**Requirement:** the game system is swappable from day one, and swapping is a content task, not an engineering one. A system pack declares everything game-specific — rules text, randomizers, stats and resources, conditions, resolution procedures, actions, turn structure, harm, progression, chargen, spatial needs, and presentation vocabulary — and the kernel runs it (§2.3). New systems are built by extending a baseline pack (§2.8).

Adding another system, rules-light or large, is a new pack. Choosing inline or sectioned text is a field in the pack. Neither is a kernel change.

### 1.2 Licensing

**Decision: open-licensed material only. No exceptions.**

Permitted sources:
- Creative Commons Attribution 4.0 (the 5.1 SRD is plain CC-BY, no share-alike; it is also published under the OGL 1.0a, which this project does not use)
- ORC-licensed material (Paizo and others)
- CC-BY-SA material, *with the caveat* that derivative work inherits the license — prefer plain BY where you want clean rights over generated content
- Original homebrew

**v1 broadcast source: SRD 5.1 under CC-BY 4.0 (D-015).** Wizards of the Coast publishes the same text under the OGL 1.0a too. The OGL is not used. It treats broadcast as distribution, which would require the full licence text with every copy and a clear marking of which portions are Open Game Content, and that is impractical for improvised live narration. It also forbids claiming compatibility with trademarks. The pack's `meta.license` is `CC-BY-4.0`. Its `meta.attribution_text` carries the attribution statement from the CC release, copied verbatim from the source document, plus a note that the text was adapted. Attribution appears in the overlay's about panel and in every VOD description, with links to the SRD and the licence. This is the "reasonable manner based on the medium" that CC-BY 4.0 §3(a) asks for. The licence covers the text, not the trademarks: the stream never uses "Dungeons & Dragons", D&D logos, or trade dress, and describes the game only as "compatible with fifth edition" or "using the SRD 5.1." Material outside the SRD (named settings, and creatures or characters the SRD omits) is not licensed.

**Excluded terms.** Models know far more of a famous game than its open-licensed text, and will produce unlicensed names from memory. A pack therefore declares `meta.excluded_terms`: names its licence does not cover, each with aliases. The list is pack data, inherited like other catalogues, so any system can use it, and the kernel recognises no particular names. Three places enforce it:
- the canon store refuses a record whose names, aliases, or text contain an excluded term (§1.3.1), with an error that names the term
- the validation pass flags any excluded term in a line bound for TTS or the overlay, from any seat (§1.3.3)
- pack lint refuses an excluded term that collides with the pack's own catalogue IDs, vocabulary, or rule-card titles (§2.10)

Matching is deterministic: case-insensitive, whole words, with the same key normalisation as canon (§6.5). It is a string check, not a model judgement, so it costs nothing and replays exactly.

**Rationale for the hard line:** the exposure is not the stream, it is the pipeline. Ingesting a copyrighted PDF into a retrieval index and emitting chunks of it through TTS is reproduction plus public performance, automated and at scale. "Human streamers reference rulebooks" is not analogous — a human reads silently and speaks a paraphrase. Fan-content policies that permit actual-play streams are aimed at people playing the game, not at people building a product on the text.

Obscuring visuals on stream does not address this, because the copying happens upstream of the stream.

The pack architecture makes this easier to hold, not harder: a pack is a unit of licensing. **Every pack declares its own `meta.license`**, and a pack whose source material has not been cleared does not load into a broadcast campaign.

Rule-card summaries (§8.6) are pack text shown on screen, so they fall under the pack's license exactly as the rules text does. Authors write them as short original summaries, not excerpts.

**Action item:** verify current license terms for the source material of every system pack before committing to it. Not legal advice.

**Attribution:** each pack carries `meta.attribution_text`. A pack that extends another inherits its parent's attributions, so the resolved pack (§2.8) carries the full chain. That list is rendered on the stream overlay and in VOD descriptions.

### 1.3 Canon

Canon is the world's ground truth. It exists to make **recall unnecessary** — agents query, never remember.

#### 1.3.1 Record structure

```
canon_record:
  id: string              # stable, human-readable, e.g. npc_varro_the_tithekeeper
  type: npc | location | faction | item | fact | thread | event
  name: string
  aliases: [string]       # "Varro", "the Tithekeeper", "that tax man"
  body: string            # prose, one fact per record
  knowledge: secret | suspected | revealed
  depends_on: [id]        # explicit dependencies, no orphans
  discovery_paths: [id]   # for secrets: who knows, what reveals it
  origin: prepped | improvised
  established_session: int
  established_by: agent_id
  superseded_by: id | null
  created_at: event_seq
```

There is no `audience` origin. Donor content never becomes canon (P9).

#### 1.3.2 Rules

- **Append-only.** Records are never edited. A correction is a new record with `superseded_by` set on the old one. The history of what the table believed, and when, is permanently retrievable.
- **One fact, one record.** Facts are stated once and referenced by ID. Never restate a fact in prose inside another record — restated facts drift independently.
- **Names are unique and registered.** Every proper noun enters the alias table at creation. Collisions rejected, near-collisions flagged.
- **Knowledge state is per-record.** `secret` records are physically absent from player retrieval indexes (§6.2). The GM promotes `secret → revealed` via `reveal(fact_id)`.
- **Numbers come from the engine.** Any prep with mechanics attached is instantiated through the system pack's entity schema, never written as prose. Prose stat blocks produce a dragon with 40 HP in session two and 400 in session nine.

#### 1.3.3 Validation pass

After GM narration is generated, before it reaches TTS, the Utility Model runs an extraction pass:

1. Extract named entities → resolve against alias table → flag unknown entities
2. Extract asserted facts → compare against canon → flag contradictions
3. Extract numeric and track assertions ("I'm down to four hit points", "I've got one stress box left") → map terms to resources through the pack's vocabulary (§2.3) → compare against state → flag mismatches
4. Compare against **active secrets** for the current scene → flag unintended reveals
5. Match against the pack's **excluded terms** (§1.2) → flag unlicensed names. This check is deterministic, needs no model, and also runs on player lines bound for TTS

Green → proceeds to TTS. Red → conflict returned to the GM, one regeneration. Second failure → beat is cut, floor re-awarded.

This pass requires the broadcast buffer (§9.2). It is the mechanism that makes "ironclad consistency" real rather than aspirational. Rule cards (§8.6) put the state it checks against on screen, so the audience can see narration and mechanics agree.

### 1.4 Spatial model

**Decision:** one spatial interface, several implementations, selectable per scene from those the system pack permits.

```
SpatialBackend (interface)
  ├── ZoneGraph   — abstract regions with adjacency. Default.
  ├── RangeBands  — relative distance bands between entities (engaged / near / far …),
  │                 for systems that do not model maps. Band set from the pack.
  └── SquareGrid  — fine grid with real geometry. For set-piece combat. (v2)
```

The backends own geometry. The pack owns the system-specific meaning laid over it — movement costs, what counts as cover, what provokes, how range maps to bands. Identical tool surface above all of them. Agents cannot tell which is running. Ship ZoneGraph and RangeBands in v1; add SquareGrid without touching the agent layer.

A pack may also declare `spatial: none`, in which case the tactical tools are absent from every schema (§7.1).

#### 1.4.1 The core rule

**The model selects; the engine computes. The model never emits geometry.**

An agent asked "where do you move?" invents coordinates. An agent handed twelve legal destinations by ID and asked to pick one *cannot* hallucinate, because coordinates never appear in its output. Every spatial question — distance, line of sight, cover, adjacency, whether a move provokes — is answered by the engine.

#### 1.4.2 Candidate generation

The hard part. A 30-foot move on a grid is ~100 squares; that cannot go in context. The engine runs a **candidate generator** returning tactically meaningful positions, annotated with why they matter:

```
pos_c7  — reaches melee with goblin_2; provokes from ogre_1
pos_e4  — breaks line of sight from archer_1; half cover from east
pos_b9  — adjacent to downed ally_mira; outside brazier light
```

Cap at 12. This is chess-engine move ordering, not exhaustive search.

Scoring is split along the P8 line. The kernel supplies generic heuristics — proximity to threats, allies protected, objectives reached, threats avoided. The pack's **tactical profile** supplies their weights, adds system-specific factors (cover, provoking, flanking, a system's own notion of "exposed"), and provides the annotation templates. The example above is what a d20-family pack produces; a range-band pack's annotations talk about bands and engagement instead.

#### 1.4.3 Mastery tiering (P2 in action)

Candidate generation is where tactical skill lives as a trait:

| `rules_mastery` | Options returned | Annotation |
|---|---|---|
| 0–33 | 4–5 | Bare positions. No consequence annotations. |
| 34–66 | 7–8 | Position + first-order consequences only. |
| 67–100 | 10–12 | Full annotation: every annotation category the pack defines (for a d20 pack: provokes, cover, sightlines, threat ranges). |

Tier boundaries and option counts are kernel settings. Which annotation categories count as first-order and which as second-order is declared per category in the pack, so the same three tiers mean the right thing in every system.

Same engine, same rules, same legality. A low-mastery agent genuinely plays worse — walks into opportunity attacks, misses the flank, stands in the fire — because it was structurally never shown the better move. This does not decay over a session the way an instruction does.

**Cost note:** combat beats carry larger payloads and more tool calls than roleplay beats. Budget accordingly (§4.7).

### 1.5 Character creation

**Sequencing:** chargen happens *after* the Session 0 vote, so characters can connect to the winning pitch.

**Method: hybrid.** The engine runs the pack's chargen procedure for the mechanical scaffold; the agent narrativizes what it got.

Engine provides: whatever the pack's chargen procedure produces — rolled stats or an assigned array, a class or playbook, starting equipment, background — plus 1–2 random details (a debt, a scar, a stolen thing) from the campaign's detail tables.
Agent provides: name, voice, backstory, goals, relationships, how they feel about what they got.

Where a system uses choices rather than rolls — picking a playbook, spending points — the pack marks those steps `choice` and the engine enumerates the legal options; the agent picks by ID, exactly as with movement (§1.4.1). The pack may mark a choice `unique_per_table`, so two agents cannot take the same playbook.

Two benefits: the sheet is **valid by construction**, and randomness or exclusive choice forces divergence — five agents building freely will produce five haunted loners with dead mentors. It also makes the agent react to something it did not fully choose, which is the same dynamic that makes public dice rolls good television. An optimizer handed terrible stats is a character beat before play begins.

---

## 2. Rules Kernel and System Packs

The deterministic engine is split in two: a **rules kernel** that knows how to run *a* game, and a **system pack** that tells it *which* game. Everything else in this document — scheduler, agents, canon, broadcast — talks to the kernel and never to a specific system.

### 2.1 Decision

**Configuration first, code as an escape hatch, inheritance from a baseline.** Both routes the brief allows are taken, because each fails alone:

- **Code-only** (a new engine per system, copied from the last one) means every system is a fork. Fixes don't propagate, and determinism guarantees have to be re-proven each time.
- **Configuration-only** grows until the config format is a bad programming language written in YAML, and the one system it cannot express becomes a rewrite.

**The rule:** data is configuration. A procedure that configuration cannot express cleanly is a **hook** — small, pure, named, registered, and tested (§2.7). New systems start as a copy-by-reference of a baseline pack and override only what differs (§2.8).

### 2.2 What the kernel owns

The kernel is everything that is true of every game:

| Kernel component | Responsibility |
|---|---|
| Event store | Append-only log, fold, snapshots, fork (§5.6) |
| Randomizer service | Seeded dice, decks, and lookup tables; extensible dice grammar (§5.5) |
| Entity model | Entities carrying stats, derived values, resources, tracks, conditions, tags, inventory |
| Expression evaluator | Derived values and formulas: integer-only, explicit rounding, total, terminating, side-effect-free |
| Effect pipeline | A closed set of primitive effects; application, validation, logging (§2.6) |
| Resolution runner | Executes pack-declared procedures on ordered outcome scales (§2.5) |
| Turn and mode controller | Free play vs. encounter mode; ordering and action-economy strategies (§2.4) |
| Spatial backends | ZoneGraph, RangeBands, (SquareGrid) (§1.4) |
| Candidate generator | Generic scoring and mastery tiering; pack supplies weights and annotation (§1.4.2) |
| Clocks and time | Faction clocks, rounds, watches, calendar |
| Tool binding | Generates tool schemas from the pack; unsupported tools are absent (§2.12) |
| Validation | Sheet schemas, action legality, effect preconditions |

**The kernel contains no game nouns.** There is no `hp` field in kernel code; there is a resource whose pack ID happens to be `hp`. This is enforced, not hoped for: a lint runs in CI and fails the build if a system term (`hp`, `ac`, `stress`, `advantage`, `saving_throw` …) appears in kernel source. A kernel tested against one system silently takes that system's shape; the lint is how you notice.

### 2.3 What a system pack declares

A pack is a versioned bundle of data, plus optional hooks and test fixtures. Abbreviated schema:

```
system_pack:
  meta:
    id, version, extends            # extends: pack_id@version | null
    name, license, attribution_text
    excluded_terms: [{ term, aliases }]   # names the licence does not cover (§1.2)
    kernel_compat                   # kernel version range the pack is tested against

  rules_text:
    mode: inline | sectioned        # §2.11
    full_text                       # inline: the whole text, layer 2 of every context
    digest                          # sectioned: always-loaded summary, layer 2
    sections: [{ id, title, aliases, body, refs, parent }]
    max_section_tokens

  vocabulary:                       # display terms; kernel IDs never change
    { <id>: { label, short, plural } }

  randomizers:
    dice_grammar: { operators: [sum, keep, explode, count, fate, step], max_dice, max_sides,
                    step_sizes }                         # legal step-die sizes
    decks:   [{ id, cards: [{ id, label } | id], reshuffle_rule, players_draw }]
    tables:  [{ id, roll, entries: [{ range, text }] }]

  entity_model:
    stats:      [{ id, range, default, private }]     # private (sheet views, §7.1)
    derived:    [{ id, expr }]
    resources:  [{ id, min, max, on_zero }]
    tracks:     [{ id, boxes, on_fill }]
    conditions: [{ id, modifier, duration: scene | session | until_removed,
                   stacking: none | intensity, max_level }]
    tags:       [id]
    inventory:  { model: abstract | weight, limit_expr }
    items:      [{ id, label, weight }]               # the weight model's catalogue
    harm:       { targets: [resource or track id] }

  resolution:
    outcome_scales:     [{ id, ordered: [worst … best] }]
    procedures:         [{ id, kind, inputs, steps }]     # §2.5
      # steps: modifiers {from}; roll; hook (resolution.step, §2.7); interpret, one of:
      #   bands | margins (degrees of success) + compare >= | <= | successes | compare >= | <=
      #   against: opposed + ties: actor | target | automatic
    difficulty_ladders: [{ id, rungs: [{ id, label, value }], range }]
    situational_tags:   [{ id, value, derive?: expr }]
    tags_cap_per_roll, free_modifier_max                    # strict/standard bounds (§2.13)

  actions:
    [{ id, trigger: declared | fiction | reaction, target: none | entity | zone,
       modes: [free, encounter], requires, eligibility, stat, cost: { currency, amount | amounts, range },
       procedure, difficulty: { ladder } | { derived },
       slot, points,                                         # action economy (§2.4)
       outcome_effects, annotation_categories }]

  turn_structure:
    encounter: { order: initiative | sides | handoff | fixed | deck | spotlight,
                 initiative?: { roll, each_round }, first?: players | gm,
                 economy: none | slots | points, slots?: [{ id, count }], points?: n }

  time:                                                      # new (§2.2 Clocks and time)
    units: [{ id, label, per }]                              # smallest first
    between_sessions: { unit, amount }

  gm:
    gm_rolls: bool                    # false: no GM-side entity rolls, as actor or as an opposed side (§2.4)
    fudgeable_procedures: [procedure_id]
    lethality_levers: [{ id, effect }]   # reserved: read by the lethality trait (BUILD_PLAN P2.5), not by P0
    meta_currencies: [{ id, holder: each_player | party | gm, start, max, visible }]
                                      # each_player: one on every player character
                                      # party: one pool every player character draws on
                                      # gm: one pool every GM-side entity draws on; `target: gm` feeds it
    consequence_tables: [{ id, entries: [{ id, label, effects, weight, severity }] }]

  progression:                                               # §2.4, BUILD_PLAN P0.15
    model: xp | marks | milestone | use
    awards:     [{ when: session_end | outcome, amount, outcomes, procedures }]   # xp, marks
    thresholds: [points]                                     # xp, marks: one advance per threshold
    use:        { threshold }                                # use: uses of a stat before it rises
    advances:   [{ id, label, stats: { stat: delta }, tags, requires, once }]
  chargen:      { steps: [{ id, kind: roll | choice | assign | table,
                            targets, roll, options, values, table, unique_per_table }] }
                # options: [{ id, label, stats, tags, items, currencies }]   # starting kit (§1.5)

  spatial:
    backends: [zone_graph | range_bands | square_grid] | none
    bands: [{ id, label }]                     # closest first (range_bands)
    terrain: [{ id }], cover: [{ id }]         # region values (zone_graph)
    movement: { steps_per_move }
    provokes: { when }
    tactical_profile: { categories: [{ id, order: 1 | 2 }], weights, factors, annotation_templates }

  presentation:
    nameplate_resources: [id]
    sheet: { public: [id] }                    # what party summaries show (§7.1)
    assertion_terms: { phrase → resource|track id }
    rounding: floor | ceil | half_up
    rule_cards: { <action|procedure|condition|currency|tag id>: { title, summary, category, icon_id } }

  hooks:    [{ point, name, version }]         # source in hooks/<name>.py beside the pack (§2.7)
  # golden fixtures live in fixtures/golden.yaml by convention (§2.10)
```

Harm names its targets; the mechanics stay on each resource and track (their `min`, `max`, `on_zero`, and `on_fill`), and later systems read the declaration.

Every catalogue entry — stat, resource, condition, procedure, action, deck — has an `id`. IDs are what inheritance targets (§2.8), what tools return, and what the event log records.

### 2.4 Variation points the kernel must support

The kernel is designed against the spread of real systems, not against one. Each row is a variation point the kernel implements as a strategy selected by pack data:

| Variation point | Kernel supports | Covers, for example |
|---|---|---|
| Randomizer | Polyhedral sums, keep/drop, exploding, success-counting pools, roll-under, percentile, Fate/Fudge dice, step dice, seeded card decks, lookup tables | d20 systems, OSR, dice-pool games, PbtA, Fate, card-initiative games |
| Resolution | Roll-over vs. target, roll-under, opposed, banded outcomes, degrees of success by margin, success counting, no-roll (spend a resource) | Pass/fail checks; full/partial/miss moves; crit-on-margin systems; diceless spends |
| Outcome scale | Any ordered list of named outcomes; kernel compares by rank, never by name | Binary, three-band, four-degree, critical tiers |
| Harm | Resource pool, wound track, stress plus consequences, harm boxes, conditions-as-damage | HP games, narrative-harm games |
| Turn order | None (spotlight), individual initiative, side-based, handoff ("popcorn"), fixed, deck-drawn | — |
| Action economy | None, typed slots, point budget | Action/bonus/reaction; three-action; freeform |
| Who rolls | Everyone, or players only | Systems where the GM never rolls |
| Meta-currency | Earn/spend currencies held by GM, party, or each player | Fate points, inspiration, bennies, doom/momentum pools, GM intrusions |
| Progression | XP thresholds, milestones, mark-on-failure, use-based | — |
| Space | Zones, range bands, grid, none | — |
| Arithmetic | Integer-only with declared rounding | Systems that round down vs. up |

When a new system needs something on neither side of this table, the default response is a hook (§2.7). If several packs need the same hook, it is promoted to a kernel strategy and a config option. **Hook count across packs is a health metric for the configuration language.**

### 2.5 Resolution as a pipeline

Every check in every system runs the same four steps — gather modifiers, generate a result, interpret it on an ordered outcome scale, apply effects. Only the parameters differ:

```
# roll-over family — pass/fail against a target
procedure: check
  inputs: [actor, stat, difficulty]               # difficulty: ladder rung or derived
  steps:
    - modifiers: from [stat, conditions, tags]
    - roll:      "1d20 + {mod}"
    - interpret: { scale: pass_fail, compare: ">=", against: difficulty }

# banded family — three outcome bands
procedure: move
  inputs: [actor, stat]
  steps:
    - modifiers: from [stat, conditions, tags]       # forward/ongoing bonuses are conditions
    - roll:      "2d6 + {mod}"
    - interpret: { scale: miss_partial_full, bands: [[min,6],[7,9],[10,max]] }

# pool family — count successes, degrees by margin
procedure: pool
  inputs: [actor, attr, skill, difficulty]
  steps:
    - roll:      "({attr}+{skill})d10 count>=8"
    - interpret: { scale: degrees, compare: successes, against: difficulty,
                   margins: [[min,-1],[0,0],[1,2],[3,max]] }     # degrees by margin
```

Same runner, same events, three different games. Advantage, bonus dice, and similar mechanics are expressed in the dice grammar (`2d20kh1`), not as special cases in the runner.

**Where inputs come from.** Every procedure input is either read from state (the actor's stat, an opposing value, a derivable tag) or chosen by ID from a pack list (a difficulty rung, a non-derivable tag). Under standard settings the GM may also supply a bounded value; under strict, those two are the only ways in (§2.13).

**Ordered outcome scales are what keep the rest of the system game-agnostic.** Because every outcome has a rank, the kernel can answer "did this get better or worse for the party?" without knowing what a "7–9" is. Three things depend on that:

- The **direction-of-drama constraint** on fudging (§5.5) refuses any reroll that lowers the party-side outcome rank.
- The **metrics pipeline** can measure success rates comparably across systems.
- The **overlay** can colour a result good/mixed/bad without per-system code.

### 2.6 Effects

Outcomes resolve into effects. The kernel defines a **closed set of primitives**:

```
modify_resource   set_resource     mark_track       clear_track
add_condition     remove_condition add_tag          remove_tag
move              transfer_item    create_item      destroy_item
advance_clock     earn_currency    spend_currency
trigger_procedure request_gm_ruling
```

Packs compose these into named compound effects in data ("take harm" = `mark_track(harm, n)` + conditional `add_condition`). Every primitive validates its preconditions, emits events, and replays exactly.

**`request_gm_ruling`** is how fiction-first systems fit a deterministic engine. When a pack's outcome hands consequence to the GM — a partial success that costs something, a "GM makes a move" on a miss — the engine decides the *band* and opens a structured ruling slot backed by one of the pack's consequence tables. Every entry in the table carries fixed effects. With the GM's `ruling_slots` control on strict, the engine fills the slot by seeded draw, weighted by `lethality`, and the GM narrates the result; on standard (the default), the GM selects the entry via `resolve` (§7.1). Either way the mechanical result is a table entry, never an invented number. The dice stay honest; the fiction stays authored.

**`trigger: fiction`** actions use the movement pattern (§1.4.1). In systems where a move triggers from what happens in the fiction rather than from a menu, the engine enumerates the moves whose `eligibility` rules match current state, and the acting agent picks one by ID. With `fiction_triggers` on strict (the players' default), the agent can only pick from that enumeration and the GM may only substitute another enumerated move; on standard, the agent may declare a move and the GM rules on disputes.

### 2.7 Hooks: the code escape hatch

Named extension points where a pack may supply code:

| Point | Use |
|---|---|
| `dice.operator` | A dice mechanic the grammar cannot express |
| `resolution.step` | A custom step inside a procedure |
| `effect.compound` | A compound effect too procedural for data composition |
| `chargen.step` | A chargen step with unusual logic |
| `turn.order` | An unusual ordering strategy |
| `tactical.score` | System-specific candidate scoring |
| `sheet.validate` | Cross-field sheet constraints |

**The determinism contract.** A hook has the shape `(state_view, params, rng) → [events]` and:

- reads state only through the read-only view it is handed
- gets randomness only from the kernel's `rng` handle, so every draw advances `roll_counter` and is logged
- has no clock, no I/O, no network, no global or static state
- uses integer arithmetic, rounding per the pack's declared rule
- returns events; it never mutates state directly

Enforced three ways: hooks run in a sandboxed runtime with no I/O capability; a static check rejects forbidden calls at load; and every hook is executed twice on every fixture and in replay, with event bytes compared. A pack referencing an unregistered hook, or a hook that fails the contract, does not load.

Hooks are versioned with the pack and pinned with it (§2.9). Most packs should need none; a pack needing many is a signal that the kernel is missing a strategy.

### 2.8 Baselines and inheritance

New systems are built by extending, not copying.

```
core                      abstract; not playable on its own
 ├── core.roll_over       roll-over vs. target family
 ├── core.banded          banded-outcome family
 └── core.pool            success-counting pool family (later: the pool shape runs on core in v1)
       └── <playable packs>  └── <house-rule packs>
```

- **`core`** supplies scaffolding every game uses: an opposed-check procedure, standard condition durations, the default tactical profile, generic chargen detail tables, and baseline vocabulary.
- **Family baselines** supply a working resolution model, outcome scale, and harm model for a resolution family. A new game in an existing family starts with dice, procedures, and turn order already working and conformance-tested.
- **Playable packs** add the specific game. **House-rule packs** extend a playable pack and change only what the table changes.

**Merge rules**, applied when a pack is resolved:

- Maps deep-merge; the child wins on conflict.
- Catalogues (anything with entries carrying `id`) merge **by ID**: same ID overrides, new IDs append, and `remove: { <catalogue>: [ids] }` deletes explicitly. Nothing is removed implicitly.
- Scalars replace.
- References are re-validated after the merge, so a child that removes a condition still used by an inherited action fails resolution with a named error, not at runtime.

The output is a **resolved pack** — a single flattened document with no `extends` — which is what the kernel loads, what is hashed, and what a campaign pins. Authors can always inspect exactly what their inheritance produced.

v1 ships `core`, the family baselines, two complete kernel test packs from different families (`lanternlight`, roll-over; `tidewrack`, banded), a data-only sectioned variant of one of them, and the broadcast pack: the SRD 5.1, extending the roll-over baseline (§2.10, §2.11).

### 2.9 Versioning and pinning

- Packs are semantically versioned. The resolved pack is content-hashed.
- A campaign **pins `pack_hash` and `kernel_version` at Session 0**. Both are recorded in the campaign's first event and in every snapshot.
- Replay refuses to run against a different pack hash or kernel version. Byte-identical replay (§5.6) is only meaningful if the rules are byte-identical too.
- **No mid-campaign pack change in v1.** Errata become a new pack version, used by new campaigns or by a fork for debugging. (Migration with explicit migration events: v2, §11.4.)
- Kernel releases must replay the archived corpus of every completed campaign byte-identically before they ship.

### 2.10 Authoring and conformance

Creating a pack is meant to be routine.

**Scaffold:** `pack new <id> --extends <baseline>` produces a pack containing only `meta` and an empty override set, which already resolves, loads, and passes conformance — it is the baseline under a new name. The author adds what differs.

**Static lint** (fails the load):
- every reference resolves after inheritance
- every outcome scale is totally ordered
- every condition has an exit: a duration, a removing action, or a removing effect
- every chargen table covers its roll's full range
- every roll expression parses under the pack's enabled grammar
- tool schemas generate without error
- rules text fits the context budget (§6.1): an inline pack's full text, or a sectioned pack's digest, with every section within `max_section_tokens`, alias keys unique across sections, every `parent` resolving without cycles, and every action, procedure, and condition covered by at least one section's `refs` (§2.11)
- every action, procedure, condition, currency, and situational tag has rule-card data within length limits (§8.6)
- no excluded term (§1.2) collides with a catalogue ID, vocabulary label, rule-card title, or rules-text section title
- strict-readiness is reported **per control**: ladders or derivations for every difficulty input, consequence tables for every ruling slot, eligibility for every fiction-triggered action, enumerated amounts for spends (§2.13). A control the pack cannot support on strict is unavailable for that pack

**Generated property tests:**
- 1,000 chargens per pack, all schema-valid
- every action resolvable from a sample of generated states
- every outcome band reachable with nonzero probability — computed exactly for dice expressions where possible
- no effect sequence yields an invalid sheet
- double-run determinism on everything, hooks included

**Golden fixtures:** the pack ships scenarios as `(seed, starting state, scripted actions) → expected event stream`. Kernel changes are checked against every pack's fixtures.

**The two-family requirement.** v1 proves the kernel on two complete packs from different resolution families, and the second is built with **zero kernel code changes made for it**. The broadcast pack is held to the same rule. A stub proves that loading works; only a second real game proves the kernel is a kernel.

### 2.11 Rules text at scale

`rules_text.mode` is `inline` or `sectioned`.

- **Inline:** the full text is layer 2 of every context (§6.1). An inline pack may also declare sections, and `query_rules` then searches them.
- **Sectioned:** for systems too large to inline. Layer 2 carries the pack's `digest`. The full text is split into sections with stable IDs, aliases, `refs` (the catalogue IDs a section governs: actions, procedures, conditions, tags), and an optional `parent` for nesting.

Both modes are v1. The mode is pack data, chosen by the author, and nothing outside the pack loader and `query_rules` branches on it.

**Agnostic by construction.** The kernel imposes no section taxonomy: no required chapters, no fixed depth, no section names it recognises. Sections are opaque text keyed by ID. All structure (chapters, `parent` nesting, which rules a section covers) comes from the pack. A system that organises its rules differently needs only a different pack.

**Resolution (v1):** `query_rules(section_id | query)` resolves in order: exact section ID, catalogue ID (through `refs`), alias key, then partial match (every query word appears in a section's title or aliases). Key normalisation is shared with canon (§6.5 Layer 0), so the two indexes cannot drift apart. The section index is built deterministically from the pinned, resolved pack. A miss returns the closest section titles as suggestions and is logged. **Vector search over rules is v2.** The Layer-3 rule in §6.5 applies here too: frequent misses mean the pack's aliases are weak, so fix the pack, not the search.

**Returned text:** a hit returns the section body, which is never longer than `max_section_tokens`. A section that would exceed the cap is split by the author, and lint enforces this (§2.10).

Rule cards (§8.6) never show section text, only titles.

### 2.12 How the rest of the system binds to a pack

| Consumer | What comes from the pack |
|---|---|
| Tools (§7.1) | Tool names are fixed by the kernel. Arguments, enumerations, and returned fields come from the pack. A tool whose capability the pack lacks is **absent** from the schema: no `peek_roll` if the GM never rolls, no tactical tools under `spatial: none`. |
| Traits (§3.4) | Mechanisms are kernel-level; the pack supplies the content they act on — annotation categories for `rules_mastery`, levers for `lethality`, fudgeable procedures for `fudging`. An axis with no content is **dormant** for the campaign and logged as dormant, never faked. |
| Prompts | The pack's `vocabulary` names things in identity and context layers, so agents talk about "Grit" or "Harm" as the game does. |
| Overlay (§8.4) | `nameplate_resources` and display formats. |
| Validation (§1.3.3) | `assertion_terms`, so numeric claims in narration map to real resources. |
| Canon and prep (§1.3, §7.6) | Stat blocks are pack-schema entities. |
| Chargen (§1.5) | The pack's chargen procedure. |
| Dossiers (§3.2) | Campaign records note which pack was played. |
| Determinism settings (§2.13) | Ladders, tags and derivations, consequence tables, eligibility rules, spend amounts — the lists strict settings turn into tool enums. |
| Rule cards (§8.6) | Title, summary, category, and icon for every action, procedure, condition, currency, and tag. |

### 2.13 Determinism settings

The kernel's resolution is deterministic under every setting: pinned pack + pinned kernel + master seed + the logged inputs → byte-identical results. What these settings control is the **judgement surface** — the places where a model's choice feeds the mechanics as an input. Model choices are always inputs, never results. The settings decide, per role and per control, whether a model **picks from an engine-generated list** (strict) or may **supply a bounded value** (standard).

#### 2.13.1 Controls

| Control | Applies to | `strict` | `standard` |
|---|---|---|---|
| `difficulty` | GM | Derived from an opposing value by pack expression where one exists; otherwise a **rung ID** from the pack's difficulty ladder | As strict, or any value within the pack's declared range |
| `situational_modifiers` | GM | Non-derivable tags from the pack's list only, capped per roll | As strict, plus one bounded free modifier within pack range |
| `ruling_slots` (§2.6) | GM | **Engine draws** from the consequence table, seeded and weighted by `lethality`; the GM narrates | GM selects an entry from the table |
| `unmodelled_actions` (`resolve`) | GM | GM maps the action onto a pack procedure, rung, and tags — all by ID; the engine rolls and applies | As strict, or the GM assigns an outcome rank directly |
| `fudging` (§5.5) | GM | Off | Governed by the `fudging` axis |
| `fiction_triggers` | Players; GM for NPC moves | Pick from the engine's enumeration of eligible moves; the GM may only substitute another enumerated move | Declare a move; the GM rules on disputes |
| `spend_amounts` | Players; GM for GM-held currencies | Choose from enumerated amounts | Any amount the rules allow, within bounds |

**Always on, whatever the settings:** seeded dice and draws, resolution, effects, legality checks, and **derivable tags** — dim light from scene lighting, high ground from elevation — which the engine applies from state and no one can add or remove by hand. Settings never let a model touch a result; they only decide how much freedom it has in choosing inputs.

#### 2.13.2 Presets and defaults

```
determinism:
  players: { preset: strict }       # default
  gm:      { preset: standard }     # default — GM strict mode is off
  overrides:                        # optional, per role and per control
    gm: { ruling_slots: strict }
  seat_overrides:                   # optional, per agent; rarely needed
    <agent_id>: { fiction_triggers: standard }
  min_scenes_between_changes: 1
```

A role's effective settings are its preset plus any overrides. There is no separate "custom" mode — a preset with overrides *is* custom.

**Why these defaults.** The GM keeps full judgement over difficulty, rulings, and fudging, which is where GM character shows and what a real table expects of its GM. Players, whose job is deciding what to do, lose almost nothing under strict: the main effect is that fiction-triggered moves come from an enumeration rather than a free declaration, which also removes the commonest source of rules disputes.

#### 2.13.3 Changing settings mid-campaign

Settings are meant to be flipped easily, during a campaign as well as between them.

- **Between sessions:** edit campaign config. Applies at the next session start.
- **During a session:** the operator's determinism control (§9.3) — one-click preset per role, or a toggle per control. A change can be queued at any moment and **applies at the next scene boundary**.
- **Never mid-scene.** An encounter, an open ruling slot, or a roll in progress finishes under the settings it started with. This keeps the toggle from being used to steer a specific moment, and `min_scenes_between_changes` stops rapid flipping.
- **Logged and replayable.** Every request and every application is an event (`determinism_change_requested`, `determinism_changed`) carrying the full effective settings. Replay folds them like any other event, so a campaign that changed settings five times replays byte-identically.
- **Cheap to apply.** At the boundary, tool schemas for affected seats regenerate (§2.12). The cost is one prefix-cache miss per affected seat. No prompt prose changes; the schemas carry the change.
- **Disclosed.** The overlay shows current settings per role, and a settings-change rule card airs when a change takes effect (§8.6).
- **Bounded by the pack.** A strict value needs pack data — ladders, consequence tables, eligibility rules, enumerated spend amounts. The linter reports readiness per control (§2.10); values the pack cannot support are shown as unavailable in the operator control and rejected by config validation.

#### 2.13.4 The structural rule

For any control set to strict for a role, the matching **tool arguments for that role are enums** generated from the pack and current state — never a free number or free text (§7.1). The adapter rejects anything else before the engine sees it (§7.5). This is P3 applied to judgement: the ability to hand the engine a number is absent, not discouraged. Under standard, the same arguments accept bounded values, and the bounds are enforced the same way.

#### 2.13.5 Measuring it

Every mechanical choice a model makes is logged as a `judgement_input` event recording the seat, the control, the active setting, the chosen ID or value, and the list or bounds it was chosen within. Replay stays exact and the surface is measurable.

**Metric:** judgement inputs per session, by role, control, and setting. Comparing the stretches before and after a toggle shows exactly what changed. A high share of GM rung and tag choices under strict means a pack needs more derivation rules. To try the GM on strict before doing it on air, run the scenario harness both ways.

Every judgement input is also labelled on the livestream's rule cards (§8.6), so the audience sees which parts of an outcome came from state, which from the dice, and which from someone's choice.

#### 2.13.6 The trade

Switching the GM to strict narrows how GMs differ *mechanically*: `fudging` goes dormant and `lethality` weights the engine's consequence draws instead of the GM's picks. GM character then lives in prep, improvisation, narration, floor control, `railroading`, and the rung and tag choices that remain. That is why it is off by default, and why it is a switch rather than a design decision: some seasons may want an expressive GM, others a near-mechanical one, and the setting can follow.

---

## 3. Agents and Personality

### 3.1 Table size

**4 players + 1 GM. Hard ceiling — the system must not support more.**

Constraints: below ~20% floor share an agent does not become a character the audience recognizes; every player subscribes to every table message, so context cost scales with headcount; and a six-player combat round means waiting six turns to act.

**Roster of 8, 4 seated per campaign.** Gives a larger cast without floor contention, and "who's playing this season" becomes its own hook.

### 3.2 Persistence

**Decision: persistent roster with out-of-character memory across campaigns.**

The novelty engine is Session 0 (constraint cards + pitches + vote). The *people* should be the constant so the audience has someone to come back for.

**Persists (OOC dossier):**
- Campaigns played, in which system, what happened, how they ended
- Characters played before, and how they died
- Table dynamics — who they bounce off, running jokes, standing grudges
- Their record as GM

**Does not persist:** the character. New campaign, new PC, no in-fiction knowledge carried over.

Stored as a **structured dossier**, not a transcript — facts, relationships, history with IDs. Queryable, bounded, does not grow past context.

```
agent_dossier:
  agent_id
  campaigns: [{campaign_id, system_pack_id, pc_name, outcome,
               notable_events:[id], sessions_played}]
  gm_record: [{campaign_id, system_pack_id, sessions, arc_count, improvised_ratio}]
  relationships: [{other_agent_id, note, established_campaign}]
  running_bits: [{text, origin_campaign, origin: play | break, last_referenced}]
  trait_history: [{campaign_id, axis, delta, reason}]
```

Yields callbacks that are very hard to fake: *"last time I played a wizard I got eaten in session three, so I'm going melee."* Recording the system adds a second kind: *"I was hopeless at the dice-pool one, I'm not doing that again."*

Running bits may originate in break segments, but only from the cast's own words via the break recap (§9.8). Donor text never enters a dossier.

### 3.3 Multi-model casting

**Decision: each of the five seats runs on a different LLM provider.**

This is a broadcast decision before it is a technical one. "GPT and Gemini and Claude are at the same table" needs no explanation, arrives with pre-built audience loyalty, and generates argument for free.

It also solves the hardest problem in §3 by procurement: **four instances of one model converge toward a shared cadence within an hour. Four different models cannot** — their divergence is at the weights, not maintained by prompting.

**Consequences the architecture must absorb:**

**Adapter layer is mandatory, not optional.** Tool-calling formats, structured-output reliability, system-prompt handling, and refusal behaviour all differ. One internal interface — `bid()`, `act()`, `recap()`, `prep()` — with per-provider adapters underneath. The scheduler and the kernel never know which model they are talking to. Break segments use the same interface; only the schema and context differ (§4.8).

**Capability differences will read as trait differences.** Policy: **let it ride for play style, compensate for broken output.** A model that plays dumb-but-legal is content. A model that emits illegal moves is a bug. Where a model is weak in a way that maps to a trait (poor spatial reasoning → low `rules_mastery`), seat an agent whose authored traits point the same direction so weakness and character reinforce.

**Refusals must have a graceful path.** A refusal reads as a broken bot, not as personality. Detect at the adapter; re-award the floor or have the agent pass. Test early against the actual tone you intend to run — including break segments, where donor messages will test refusal profiles in ways play does not.

**Latency and cost vary per provider.** Handled by the scheduler (§4.2).

**Action item:** review each provider's terms of service for this use case before building four adapters. Some restrict comparative benchmarking or public performance of outputs.

**GM seat:** candidacy is not restricted by model. "Which model is the best GM" is an emergent storyline worth having.

### 3.4 Trait model

Two layers. **Axes** are numeric (0–100), touch machinery, shape behaviour continuously. **Quirks** are discrete, surface, and make characters quotable.

Per P2: wherever an axis can be expressed as information control, it is.

Per P8: axis *mechanisms* live in the kernel and orchestrator. Where an axis acts on game content — the annotations `rules_mastery` reveals, the levers `lethality` pulls, the procedures `fudging` may touch — the system pack supplies that content (§2.12). An axis with nothing to act on in the current system is **dormant** for that campaign and logged as dormant, rather than approximated.

#### 3.4.1 Table behaviour axes

| Axis | Mechanism |
|---|---|
| `eagerness` | Multiplier on bid score. Drives floor share directly. |
| `verbosity` | Hard token budget on generation. A low-verbosity agent is *unable* to monologue. Also caps TTS duration. |
| `attention` | Probability that recent beats enter context at full fidelity vs. degraded. Low attention genuinely misses things and asks "sorry, what?" |
| `agreeableness` | Bid weight on contesting another player's proposal. Low agreeableness argues. |
| `humor` | Bid weight on the `banter` contribution kind. |

#### 3.4.2 Play style axes

| Axis | Mechanism |
|---|---|
| `thespian_optimizer` | Controls whether the agent is prompted to speak **as** the character or **about** the character. The single most important dial in the system. |
| `rules_mastery` | Depth and annotation of `enumerate_*` results (§1.4.3). |
| `risk_appetite` | Weighting when choosing among enumerated actions; gates whether risk annotations are surfaced at all. |
| `rules_lawyering` | Probability of firing `query_rules` and of contesting a GM ruling. |
| `spotlight_hunger` | Bid weight specifically when another player is mid-scene. Raises the interrupt ceiling (§4.3). |

#### 3.4.3 Cognition axes

| Axis | Mechanism |
|---|---|
| `memory_fidelity` | Corruption parameters on the per-agent session recap (§6.3). |
| `metagaming` | Probability that a `secret` or other-player-private record is deliberately injected into their retrieval results. Logged as a leak event. |
| `note_discipline` | Frequency of scratchpad writes; whether note retrieval is automatic or must be explicitly called. |

#### 3.4.4 GM-only axes (dormant until seated)

| Axis | Mechanism |
|---|---|
| `railroading` | Weighting across three sources on any beat: (1) use prepped canon, (2) bend adjacent prep to fit, (3) improvise new canon. High = reaches for prep and relocates it toward the party. Low = improvises freely, lets prep go unused. |
| `lethality` | Opposition action-selection aggression; which of the pack's `lethality_levers` (e.g. a "pull the punch" option) the engine offers. When the GM's `ruling_slots` control is strict, also weights the engine's draws from consequence tables (§2.13). |
| `spotlight_balance` | Strength of GM floor-override toward under-served players. High = cuts to the quiet one unprompted. Low = lets the loud player run the session. |
| `fudging` | Frequency cap on `peek_roll` use (§5.5). Dormant in systems where the GM does not roll, and while the GM's `fudging` control is strict (§2.13). Active by default. |

Note that `rules_mastery`, `memory_fidelity`, `metagaming`, and `attention` are **the same mechanism** — controlling what enters context. That is P2 working.

#### 3.4.5 Quirks

2–3 per agent, authored. Discrete, surface, quotable.

Examples: does voices · always speaks in third person · has a catchphrase · flirts with every NPC · names every animal · steers everything toward their backstory · describes food in excessive detail · keeps a running tally of something irrelevant · perpetually hungry, mentions snacks · types then retracts ("wait, no—") · references a previous campaign constantly · distrusts every NPC on sight · always asks what the room smells like.

Axes make the play feel real. Quirks are what the audience quotes. Both required. Break segments are where quirks get the most room: out of character, reacting to strangers, the cast is closest to "people" and furthest from "players".

### 3.5 Authoring, drift, and self-knowledge

**Authored, not randomized.** Eight hand-tuned cast members with deliberate contrast — the loud optimizer, the quiet thespian, the rules lawyer, the chaos agent. Random rolls produce mush in the middle.

**GM gets more context, same model tier.** The GM carries canon, prep, and full table state, so it needs a larger context budget. But GM quality is partly a *trait* (`railroading`, `lethality`, `spotlight_balance`) and a weak GM season must be possible — so do not compensate with a stronger tier, or you cannot tell a bad GM from an artifact.

**Drift: bounded, slow, logged.** Per-campaign nudges of ±5 on an axis, driven by outcomes (GM'd successfully → `eagerness` up; character died recklessly → `risk_appetite` down). Total drift from the authored baseline is capped (suggest ±20) so an agent stays recognizable. Every change is written to `trait_history` so a season-three agent has a visible account of how they got there. Donations and break segments never drive drift.

**Self-knowledge is vague and prose-only.** An agent's prompt describes it in words — *"you're bold and you talk too much"* — **never numbers**. An agent shown `risk_appetite: 82` will perform 82 rather than be it.

**No knowledge of other agents' traits.** They learn each other through play, exactly as a real table does. This is what makes the persistent-roster memory do real work.

---

## 4. Scheduler and Pacing

The subsystem that decides whether this looks like a game night or a conference panel. Everything else can be merely good; this has to be right.

### 4.1 Beat resolution

A **beat** is one unit of table time. It resolves in three stages.

#### Stage 1 — Deterministic bids (no model calls)

Most of a bid is not a judgement. It is mechanical and computable from state:

```
deterministic_bid(agent) -> score | RESOLVED
  addressed_by_name          → RESOLVED, score = 100
  gm_asked_direct_question   → RESOLVED, score = 100
  own_turn_in_turn_order     → RESOLVED, score = 100   # per the pack's turn structure
  character_targeted         → score += 60
  mid_scene_with_speaker     → score += 40
  beats_since_last_floor     → score += f(n), capped
  interrupted_last_beat      → score += 50   # people finish their thought
  dm_sent_this_beat          → score -= 100  # whispering ≠ talking
```

If any agent returns `RESOLVED`, the floor is awarded immediately. Cost: zero. Latency: zero. **This covers the majority of beats in a real session.**

#### Stage 2 — Discretionary bids (cheap tier, own provider)

Only for agents not resolved in Stage 1, only when the floor is genuinely open. Small context (recent transcript window + compact state + own intent). Returns:

```
{
  want_floor: 0-100,
  kind: in_character | rules_query | banter | react | table_talk,
  target: agent_id | gm | null,
  urgency: interrupt | normal | can_wait,
  one_line_intent: string   # ≤ 20 words
}
```

`one_line_intent` earns its place three times over: it lets the scheduler detect two agents wanting the same thing, it seeds the full generation so the agent does not drift from what it bid on, and it is what the overlay displays (§8.4).

#### Stage 3 — Award

```
score = want_floor
      × eagerness_weight(agent)
      × recency_penalty(beats_since_last_floor)
      × kind_multiplier(kind, scene_type)
      × trait_multiplier(kind, agent)     # humor→banter, lawyering→rules_query
      + gm_override_bonus
```

Highest score takes the floor. **Only the winner pays for a full generation.**

If the top score is below `FLOOR_THRESHOLD`, the beat resolves as **silence** (§4.4).

### 4.2 Latency handling

Four providers means four response times. Waiting for all four means the slowest provider sets the beat duration — slow model, quiet agent.

**Rule 1 — Hard timeout, ~800ms.** Non-responders fall back to deterministic-bid-only. They can still win the floor; they just do not express discretionary desire that beat. Over a session this is nearly invisible, and it caps beat latency at a known number rather than at the worst provider's tail.

**Rule 2 — Speculative bidding.** Run bids for beat N+1 during beat N's generation. Generation is the long pole (seconds); bids are cheap and parallel (milliseconds). By the time the speaker finishes, the next award is mostly computed. If the generation materially changed the situation, discard and re-bid — you paid for a few cheap calls.

Together these make cross-provider latency variance a non-issue. Build both from the start; retrofitting speculation is painful.

### 4.3 Interruption

The floor must be interruptible or the table reads as a panel discussion.

**Mechanism:** generation streams in sentence-sized chunks. After each chunk, agents whose standing bid carried `urgency: interrupt` are checked. An interrupt lands if:

```
interrupter_score > speaker_score × INTERRUPT_MARGIN
```

`INTERRUPT_MARGIN` starts at 1.6 and is tuned by testing (§11.2).

**When it lands, the speaker's generation is cut mid-sentence and the partial text is kept.** This is the entire point — the truncated line is what makes it read as human. The interrupted agent then receives an elevated deterministic bid next beat.

**Gates:**
- Only certain kinds may interrupt: `rules_query`, `react` (to something directly affecting their character), `banter` landing on a specific line.
- **Never during GM scene-setting narration.**
- Rate-limited per agent per scene. `spotlight_hunger` raises the ceiling; it does not remove it.

**Cost:** interruptions discard partial generations. They are the single highest-value texture in the system. Budget for the waste.

### 4.4 Silence and pacing texture

**Silence is a positive scheduler outcome, not the absence of one.** If no bid clears `FLOOR_THRESHOLD`, the beat resolves as silence and the stream shows the map and ambient audio for a few seconds.

Real tables are full of this and it is a large part of why they feel real.

**Thinking time.** After the GM presents something consequential, insert a deliberate pause before bids open. Costs nothing; prevents the instant-response rhythm that makes LLM conversation feel synthetic.

**`pass()` is distinct from silence.** An explicit "I've got nothing, what's everyone else doing?" is a real table behaviour that hands the floor onward gracefully.

### 4.5 Pacing watchdog

Runs on the Utility Model against a sliding window.

**Detects:**

| Condition | Signal |
|---|---|
| Stall | N beats with no state change, no canon addition, no scene movement |
| Loop | Semantic repetition against recent beats — the politeness spiral, the re-litigated plan |
| Convergence | Everyone agreeing for too long |
| Starvation | An agent below floor-share threshold for too long |
| Drag | Scene exceeding expected length |

**Escalating response — always prefer the gentlest:**

1. **Nudge the GM.** A private signal, not public text: *"The party has been planning for nine beats. Force a decision."* The GM resolves it in fiction. Invisible to the audience and always the best outcome.
2. **Boost a starved agent's bid weight.** The fix looks like someone naturally speaking up.
3. **Inject a prepped complication.** Drawn from GM prep. The torch gutters, footsteps approach, the NPC loses patience.
4. **Hard scene cut.** GM instructed to transition. Reserved for genuine deadlock.

**The watchdog never writes dialogue.** It adjusts weights or hands the GM an instruction. The fiction stays authored by the agents.

The watchdog does not run during breaks; break pacing is governed by the reaction window (§4.8).

### 4.6 GM floor priority

Both mechanisms:

- **Hard override** (immediate, not a bid): scene-setting, resolving actions, filling or narrating ruling slots (§2.6), NPC response to direct address, watchdog-driven cuts.
- **Soft priority** (bids like anyone else, modest multiplier): commentary, banter, joining side conversation.

A GM with hard override on everything narrates *at* the table and is never talked over. Real GMs get talked over constantly.

`spotlight_balance` drives how strongly the GM's override targets under-served players — a visible, characterful difference between GMs across seasons.

### 4.7 Cost control

- Cheap tier per provider for discretionary bids.
- Utility Model for watchdog, metrics, validation, sanitisation classifiers.
- Full tier only for awarded generations.

**Per-beat token ceiling enforced by the scheduler.** Combat beats get a higher allowance than roleplay beats (enumeration payloads). Break beats get the lowest: small context, no tactical payload, no canon.

**Degradation order when the ceiling is hit:** discretionary bid frequency drops first — fall back to deterministic-only for a stretch. The table gets slightly more mechanical and slightly less spontaneous, rather than stopping.

### 4.8 Break mode

During a break segment (§9.8) the scheduler runs in **break mode**. Same three stages, different inputs and limits.

**Presentation is not a bid.** Each Board item is presented by the engine — highlighted on screen and read aloud by the announcer voice from a fixed template (§9.4). No agent is ever asked to read donor text aloud, so no cast voice ever speaks donor words verbatim.

**Stage 1 in break mode:**

```
deterministic_bid_break(agent) -> score | RESOLVED
  item_names_agent           → RESOLVED, score = 100   # deterministic match against cast aliases
  beats_since_last_floor     → score += f(n), capped
  reacted_to_this_item       → score -= 30             # spread reactions around
```

The GM has **no hard override** in break mode. At a break, the GM is just another person at the table.

**Stage 2 in break mode:** discretionary bids as normal, with `kind` restricted to `react | banter | table_talk`. `in_character` and `rules_query` are not valid kinds during a break.

**Reaction window.** Each item gets a number of reaction beats set by the item's amount band (§9.7.3). The window closes early if a bid round falls below `FLOOR_THRESHOLD` — the table has said what it has to say. When the window closes, the engine presents the next item.

**Interrupts are allowed**, under the normal margin and per-agent limits. Breaks are looser than play, and there is no GM narration to protect.

**Breaks cannot stall**, because the engine advances the queue. The pacing watchdog is off.

**Schema swap.** For the duration of the break, every seat's schema contains only `post_to_table`, `pass`, and `look_board` (§7.1). Tools that change game state, write notes, edit character documents, or share files are **absent**, not denied (P3). A donor message that succeeds in steering an agent has nothing to call.

---

## 5. State and Truth

Governing rule (P1): the model narrates, the engine decides. The engine here is the rules kernel running the campaign's pinned system pack (§2).

### 5.1 What is deterministic

Everything mechanical, without exception:

- Randomness — every roll and every card draw, including the GM's
- Character sheets — whatever the pack's entity model defines: stats, resources, harm, tracks, conditions, inventory, advancement
- Turn order and action economy, per the pack's turn structure
- Positions, zones, range bands, adjacency, line of sight
- Time — rounds, watches, travel, calendar
- Meta-currencies, wherever they are held
- Derivable situational modifiers, always; difficulties, other modifiers, and ruling consequences under strict settings — from pack ladders, derivations, and seeded draws, never a model-supplied number (§2.13)
- Canon records and knowledge states
- Floor history, bid log, who spoke when
- Faction clocks
- The Board — its ranking, the read queue, and break scheduling (§9.7–§9.8)

**Test:** if two agents could disagree about it and one would be wrong, the engine owns it.

### 5.2 The promotion rule

The one category that stays soft is **fiction not yet mechanized**. The GM says the rope bridge looks frayed. That is not a game object until someone interacts with it.

**Rule: when an agent targets something not in state, the engine forces the GM to instantiate it via `spawn_entity` before resolving the action.**

This is the enforcement point where narrative texture becomes checkable fact. Without it, the GM improvises a detail in session two that contradicts a mechanic in session nine.

### 5.3 Character sheets

**Two artifacts, deliberately split:**

| | Owner | Validation |
|---|---|---|
| **Sheet** (everything in the pack's entity model) | Engine | Schema-validated against the pack. Agents have read-only access. |
| **Character document** (voice, backstory, relationships, goals, feelings) | Agent | None. Freeform. |

The agent owns **who their character is**. The engine owns **what their character can do**.

An agent with write access to its own HP — or stress, or harm boxes — would use it, eventually, under pressure, in a way that would be immediately obvious on stream.

### 5.4 Mutation authority

| State | Writer |
|---|---|
| Sheet values | Engine only, via resolved effects (§2.6) |
| Positions | Engine, via `commit(action)` |
| Conditions | Engine, via effects |
| Inventory | Engine, via transactions |
| Meta-currencies | Engine, via `earn_currency` / `spend_currency` |
| Canon | GM writes; engine assigns IDs and validates |
| Knowledge state | GM, via `reveal(fact_id)` |
| Scratchpad, notes | Owning agent, freely (not during breaks) |
| Character document | Owning agent, freely (not during breaks) |
| Clocks | Engine, on schedule or GM action |
| Donation records, Board, read queue | Audience Service only. No agent has a write path. Operator may remove an item (§9.3). |
| System pack | Nobody at runtime. Pinned at Session 0 (§2.9). |

### 5.5 Randomness, seeds, and fudging

**Every roll and draw seeded, logged, reproducible.** A campaign has a master seed; each roll derives deterministically from `(master_seed, roll_counter)`. Deck shuffles draw from the same stream, and deck order is game state. Hooks receive randomness only through the kernel's handle (§2.7), so nothing random happens off the counter. The full log means any session replays exactly.

This buys: trait tuning with dice held constant, fork-and-replay for debugging, and proof the dice were honest — which matters, because on a stream full of AI agents, someone **will** accuse you of scripting.

**Publication policy:** roll results are public live. The master seed is published **after the campaign concludes** — verifiable after the fact, but nobody can precompute the next crit. The resolved pack is published with it, since verification needs the exact rules.

**Fudging.** The GM alone gets `peek_roll()` — see a result before it goes public, with a bounded ability to reroll. Every fudge is logged. The `fudging` axis sets the frequency cap. It exists only where the pack declares `gm_rolls: true`, only for procedures the pack lists as fudgeable, and only while the GM's `fudging` control is standard — which it is by default. Otherwise the tool is absent and the axis dormant.

Two constraints:
- **Direction-of-drama only.** The engine permits fudging that saves a PC from an unearned death, lets a climactic blow land, or avoids an anticlimax. It refuses "reroll until the party loses." A high-fudging GM is generous, not capricious. This is enforced by **outcome rank** (§2.5): a reroll that lowers the party-side rank on the procedure's outcome scale is refused, in any system, without the kernel knowing what the outcomes are called.
- **Revealed in the archive, not live.** A live indicator kills tension. Rule cards show only the final result (§8.6). Post-hoc, *"the GM saved you in round three and never told you"* is an excellent reveal and gives the audience something to dig through.

This is the one deliberate exception to §5.1, justified because real GMs do exactly this and hide it. Switching the GM's `fudging` control to strict turns it off from the next scene. Either way it replays exactly: the peek, the reroll, and its seed are all logged.

### 5.6 Event sourcing and snapshots

**Event-sourced, not state-dumped.** Append-only log of every roll, draw, mutation, message, bid, floor award, canon write, tool call, validation result, and Board event. Current state is a fold over the log. Snapshots are periodic caches for fast load, **not** the source of truth.

Yields, nearly free:
- **Resume** after crash or overnight break
- **Fork** — branch at any beat and run differently
- **Replay** for production, debugging, clip generation
- **Full audit** of who knew what when — exactly what the metagaming and knowledge-state systems need

**Pinning.** The first event of every campaign records `pack_hash` and `kernel_version`, and so does every snapshot. Replay against anything else is refused (§2.9).

**Snapshot boundaries:** scene transitions, session start/end, before any encounter, and at the start of every break (state is quiescent).

**Donor content is not in the event log.** Board events carry donation IDs; content lives in the audience store (§9.7.1). A privacy erasure therefore never rewrites history. And because break segments never touch game state, erasing donor content cannot break game replay — the fold over game events is unaffected.

**Policy constraint:** fork-and-replay exists for debugging, tuning, and recovery from genuine engine faults. It is **not** an editorial tool (P6, §9.5). The capability will be sitting there every time a session goes badly, and the temptation compounds.

### 5.7 Event schema (abbreviated)

```
event:
  seq: int                  # monotonic, the ordering authority
  timestamp: iso8601
  campaign_id, session_id, scene_id
  actor: agent_id | engine | operator | audience_service
  type: string
  payload: object
  caused_by: seq | null

types:
  # system
  campaign_started            # pins pack_hash, kernel_version, seed commitment (§2.9)
  campaign_forked
  axis_dormant                # P2.5 (traits)
  determinism_settings_recorded, determinism_change_requested, determinism_changed
  session_started, session_ended
  # table
  floor_awarded, floor_yielded, floor_interrupted, silence_beat
  bid_submitted, bid_timeout
  message_posted, dm_sent
  # mechanics
  roll_made                   # dice, weighted draws, and hook draws; every one on the roll counter
  roll_peeked, roll_fudged, peek_settled
  deck_shuffled, card_drawn, card_discarded, table_rolled
  procedure_resolved, gm_resolution, gm_ruling_requested, gm_ruling_filled
  effect_applied              # every primitive (§2.6), naming it and carrying the exact changes
  action_committed
  judgement_input             # seat, control, active setting, choice, list or bounds (§2.13)
  hook_ran                    # §2.7
  encounter_started, round_started, turn_started, economy_spent, encounter_ended
  clock_created, clock_stage_reached, clock_paused
  time_advanced
  chargen_started, character_created
  progress_awarded, advance_taken   # §2.4 progression (BUILD_PLAN P0.15)
  # world
  canon_written, canon_superseded, fact_revealed
  entity_spawned
  scene_set                   # carries the spatial layout when the scene has one
  scene_closed                # after the events that close the scene, before the next scene_set or session_ended
  visibility_set, move_provoked
  rules_queried
  # audience (payloads carry donation IDs, never content)
  donation_received, donation_accepted, donation_withheld, donation_redacted
  donation_reversed, board_item_removed, board_item_expired
  break_started, board_item_presented, board_item_read, break_ended
  # meta
  validation_flagged, validation_passed, regeneration_triggered
  echo_check_failed
  tool_call, tool_error, refusal_detected
  watchdog_fired, leak_injected
  # production
  beat_cut, stream_killed
```

---

## 6. Memory, Context, and Recall Cost

The section where long campaigns live or die. Everything here is in tension with a fixed context window, and the answer is never "send more."

### 6.1 Context assembly

Assembled fresh per beat, layered, budgeted. **Order matters** — static content first, dynamic content last, so provider prefix caching works (§6.5).

| # | Layer | Contents | Cache |
|---|---|---|---|
| 1 | Identity | Personality prose, quirks, current goals | Static, cached |
| 2 | Rules | Full rules text (inline packs) or rules digest (sectioned packs, §2.11) | Static, cached |
| 3 | Character | Freeform doc + sheet summary, in the pack's vocabulary | Session-static |
| 4 | Canon digest | Campaign spine, few hundred tokens | Arc-static |
| 5 | Campaign memory | Their lossy recap of prior sessions | Session-static |
| 6 | Scene bundle | Pre-fetched canon for this scene | Scene-static |
| 7 | Session recap | Current session so far, compressed | Rebuilt on change |
| 8 | Recent transcript | Last N beats verbatim | Dynamic |
| 9 | Tactical | Enumerated options, encounters only | Dynamic |
| 10 | Notes | Retrieved from scratchpad | Dynamic |

The window is not fixed: it **expands for the agent holding the floor and contracts for bidders**. The bid pass gets layers 1, 8, and a compact state summary only — that is the cost lever that makes discretionary bidding affordable across four providers.

#### 6.1.1 Break-mode assembly

During a break (§9.8) every seat, GM included, gets a different and much smaller context:

| # | Layer | Contents | Cache |
|---|---|---|---|
| 1 | Identity | Unchanged — keeps the cached prefix | Static, cached |
| B1 | Break framing | Fixed text: it's a break, you're out of character, viewers' messages appear below as quoted data | Static, cached |
| 3 | Character | Sheet summary and character doc, short form | Session-static |
| 5 | Campaign memory | Player-scoped | Session-static |
| 7 | Session recap | **Table knowledge only** — for the GM too | Rebuilt on change |
| B2 | Board summary | Ranked display names and amounts; no message text | Per item |
| B3 | Current item | One sanitised item inside nonce delimiters (§9.9) | Per item |
| B4 | Break transcript | The cast's reactions so far this break; donor text of earlier items not carried | Dynamic |

**Absent in break mode:** rules, canon digest, scene bundle, tactical options, notes, prep, secrets. The GM's break context is assembled exactly like a player's, from table knowledge, so the GM cannot spoil what it is not holding (P3).

### 6.2 Knowledge tiers

Four tiers, kept **physically separate** in storage and retrieval:

- **Table knowledge** — everything said aloud in play. Everyone has it.
- **Character knowledge** — what this PC has witnessed or learned, kept in the agent's own notes and recap (§6.3, §6.4), never in a separate canon index. Every player seat queries the same canon (secrets excluded); a character's own copy may be incomplete or wrong.
- **GM secrets** — never present in any player's retrieval index.
- **Break talk** — what the cast said out of character during breaks. Carried forward only as the break recap, tagged `break`, in players' session recaps. Never carries donor text, never enters the GM's play context, prep, canon, or notes (§9.8).

**Enforced by context filtering, never by instruction.** An agent told "your character doesn't know this" while holding the information will leak it, reliably, under pressure.

**The hard case:** a player is present at the table when another player's private scene is narrated. The *player* heard it; the *character* was not there. Kept in table knowledge, tagged out-of-character, and the `metagaming` axis governs whether the agent acts on it. That is the honest simulation — high-metagaming players do this constantly and it is a recognizable table dynamic.

### 6.3 Recaps

**Two artifacts:**

**Ground truth recap** — Utility Model, complete, accurate, engine-stored. Nobody reads it directly. Reference for validation and source for everything below.

**Per-agent recap** — ground truth run through a **controlled corruption pass** parameterized by `memory_fidelity`. Not "summarize this badly" (produces mush) but a deterministic recipe:

```
corrupt(ground_truth, fidelity):
  drop (100-fidelity)% of proper nouns,
      preferring NPCs the agent interacted with least
  merge adjacent low-salience events into one
  preserve beats where the agent's character was emotionally central
  preserve the agent's own contributions at +20 fidelity
  preserve anything in the agent's own notes at 100 fidelity
```

The **self-favouring bias** is what makes it read as human memory rather than lossy compression. Everyone remembers their own moments clearly and the other guy's subplot vaguely.

Cached by `(ground_truth_hash, agent_id, fidelity)`.

**The GM's recap is high-fidelity regardless of traits.** A GM who forgets their own plot is a broken season, not a characterful one.

**Break recaps** are a third, separate artifact (§9.8), written from the cast's reactions only and merged into players' recaps as tagged OOC content. They are not part of the ground-truth recap that drives prep.

### 6.4 Notes

Two retrieval mechanisms, gated by `note_discipline`:

- **Explicit** — `search_notes(query)`, available to all
- **Automatic** — relevant notes surfaced into context without asking

Low discipline → sparse notes *and* manual retrieval, so they forget things they literally wrote down. High discipline → notes handed to them at the right moment; they look sharp.

Notes are structured enough to retrieve (fact, subject tag, session) but written freely.

Notes are a deliberate partial workaround for low `memory_fidelity` — at a real table, the person who takes notes remembers more. The trait should not be a pure penalty.

Note tools are absent during breaks. Notes are auto-retrieved into play context, which would make them a laundering path for donor text.

### 6.5 Recall cost control

**Framing: most of what looks like retrieval is actually a lookup.** Routing everything through embeddings means paying per query for fuzzy results. Most canon questions have exact answers reachable by key.

#### Layer 0 — Never query what you can key

Stable IDs are the whole trick. Built once at write time:

- **Alias table:** name/alias/partial → ID. Handles "Varro", "the Tithekeeper", "that tax man".
- **Record table:** ID → record.
- **Relation graph:** ID → related IDs.

Any agent mention of a known entity resolves by string match **before anything else runs**. This handles the large majority of canon access, because agents mostly talk about things already on screen. Cost: a hash lookup.

#### Layer 1 — Scene pre-fetch, not per-query retrieval

**Canon relevance changes at scene boundaries, not beat boundaries.** Assemble a **scene context bundle** once when the scene opens — location, present NPCs, active threads, recent events there, relevant factions, **and the GM's active secrets for that scene** — then hold it warm for the whole scene.

Cost per scene, not per beat. On a 40-beat scene that is a ~40× reduction on the highest-frequency path, and it is *more* accurate than per-query retrieval because it is assembled deliberately via the relation graph rather than matched fuzzily.

The inclusion of active secrets is also the primary defence against improvisation contradictions (§7.6).

#### Layer 2 — Cache aggressively, keyed by content hash

- **Prompt prefix caching** — the single biggest cost lever available. Layers 1–4 of §6.1 are static across a session. Every major provider supports prefix caching. **The context assembler must be designed around preserving the prefix**; appending anything dynamic early breaks it and you pay full freight on every call. Break-mode assembly keeps layer 1 first for the same reason.
- **Recap cache** — keyed by hash of covered events.
- **Enumeration cache** — keyed by `(tactical_state_hash, actor_id, mastery_tier)`. Tactical states repeat constantly in encounters. The pack is pinned per campaign, so it need not be in the key.
- **Embedding cache** — embed a canon record once at write, never again. Records are append-only, so embeddings are permanently valid.
- **TTS cache** — keyed by text hash.

#### Layer 3 — Vector search, last resort

Only for genuinely fuzzy queries: *"has anyone mentioned anything about the plague before?"* Rare, because everything else was caught upstream.

Constraints: search only within the agent's knowledge scope, filter by recency and arc, hard result cap, cache the query.

#### Canon digest

A compact, always-loaded summary of the campaign's spine — main threads, key NPCs one line each, the party's standing goal. A few hundred tokens, regenerated at arc boundaries, off-air. Prevents most retrieval calls from firing at all, because the agent already has the shape of the world and only queries for detail.

#### Budget enforcement

Per-beat token ceiling enforced **by the context assembler**, not hoped for. Fixed degradation ladder:

1. Drop automatic note retrieval
2. Shrink transcript window
3. Drop non-scene canon
4. Digest only

Every degradation is logged. Constant degradation means the ceiling is wrong.

#### Instrumentation

Per beat: tokens by layer, cache hit rate by cache, retrieval calls by layer, cost by agent and provider.

**The number to watch is layer-3 hit rate.** Frequent vector search means ID resolution or scene pre-fetch is failing — fix that, do not tune the search.

**Expectation to check early:** the dominant cost in this system is probably **not recall**. It is the GM's full generation context, firing constantly, carrying canon and prep and table state. Recall optimization is bounded work; measure before assuming.

### 6.6 Campaign length and compression

Scaling shape:

- Recent transcript — constant, bounded
- Session recap — grows within a session, resets at session end
- Campaign memory — grows with session count, **must be compressed**
- Canon — grows monotonically, **must be retrieved, never loaded**

**Canon breaks first.** By session twenty there are hundreds of records. Retrieval quality on canon therefore determines maximum campaign length. Over-engineer it early: good IDs, entity linking, scene-scoped pre-fetch, recency weighting.

**Arc compression.** Campaign memory is recompressed at arc boundaries — "the Saltmarket arc, in six sentences" rather than six session recaps. Lossy, and correct: it matches how people remember long campaigns.

**Structure:** arcs of 8–12 sessions, hard compression at boundaries. A campaign is a sequence of arcs, not an unbounded run. Arcs also become broadcast seasons (§9.6).

---

## 7. Tools, Isolation, and GM Prep

Where every rule above is either enforced or quietly is not.

**Governing principle (P3): agents have no filesystem and no network.** They have a tool API. Every call is authenticated to a caller, scoped by role and by mode (play or break), and logged as an event.

### 7.1 Tool surface

Tool **names and shapes are fixed by the kernel**, so adapters and prompts never change between systems. What a tool returns — which actions exist, which resources a sheet has, which options `enumerate_actions` offers — comes from the system pack. A tool whose capability the pack does not provide is absent from the schema (§2.12).

For each role, every tool argument with mechanical effect follows that role's determinism settings: on strict, an **enum** generated from the pack and current state, never a free number or free text; on standard, a bounded value (§2.13). Schemas regenerate when settings change at a scene boundary.

**Table and communication**
```
post_to_table(text, kind)          → the only way to be heard
send_dm(recipient_id, text)        → private, logged, rate-limited
pass()                             → explicit yield
```

**Self**
```
read_sheet()                       → own sheet, full detail, in pack vocabulary
read_character_doc()
write_character_doc(text)          → freeform, unvalidated
write_note(text, tags)
search_notes(query)
read_scratchpad()
write_scratchpad(text)
```

**World**
```
query_canon(entity_id | query)     → knowledge-scoped, layered per §6.5
query_rules(section_id | query)    → key-first lookup per §2.11; the main path for sectioned packs
look()                             → scene description + visible entities
read_party_sheets()                → summary view of others, not full detail
```

**Tactical (encounters only; absent under `spatial: none`)**
```
get_tactical_view()
enumerate_moves()                  → mastery-tiered
enumerate_actions(position_id)     → mastery-tiered; drawn from the pack's action catalogue,
                                     including eligible fiction-triggered moves
preview(action_id)                 → effects, targets, what it provokes
commit(action_id)                  → engine resolves, rolls, applies, logs
```

**Shared drop**
```
share_file(recipient_ids, name, content)
list_shared()
read_shared(file_id)
```

**GM-only**
```
write_canon(record)                → engine assigns ID, validates
reveal(fact_id)                    → secret → revealed
read_prep()                        → private prep store
peek_roll()                        → bounded by fudging axis, logged;
                                     absent if the pack's GM does not roll
spawn_entity(spec)                 → instantiate fiction into state
set_scene(spec)                    → transition; triggers pre-fetch + snapshot
resolve(action, ruling)            → map an unmodelled action onto a pack procedure
                                     (procedure, difficulty rung, tags — all by ID);
                                     select a ruling-slot entry (when `ruling_slots` is standard)
rule_on_action(ruling)             → a player's action: difficulty rung and tags by ID; for a
                                     fiction-triggered move, a substitute move (§2.13.1)
advance_clock(clock_id, amount)
```

**Break mode (every seat, GM included)**
```
look_board()                       → ranked display names and amounts; no message text
post_to_table(text, kind)          → kind ∈ react | banter | table_talk
pass()
```

In break mode these three are the **entire schema** for every seat. Nothing else is present.

**Absent by design:** no `read_other_notes`, no `read_gm_prep` for players, no file access, no shell, no network, no tool that reads donor text, and — during breaks — no tool that writes anything that outlives the break. Not restricted — **absent**. An agent cannot attempt what is not in its schema.

### 7.2 Shared drop

**Tool-mediated abstraction, not a real directory.** A real shared filesystem is a side channel the moment one agent writes a file another was not meant to read, and you would never see it happen.

As a tool it is a logged, addressed handoff with a recipient list — which is also better content. *"Mira just passed everyone a map of the undercroft"* is a visible table event worth putting on the overlay. A file appearing in a directory is not.

Content is text or structured data. Images only as engine-generated asset references with IDs, never raw bytes between agents.

### 7.3 GM privilege

**Enforced, not trusted.** GM prep lives in a separate store no player-role tool can address. `read_prep` exists only in the GM's play schema; a player calling it gets an **unknown-tool error, not a permission denial** — even the denial is information.

Canon: players query a knowledge-filtered view. Secrets are not filtered out of their results; they were never in the index those results come from.

**The one real leak surface is the GM's own output.** Caught by the validation pass (§1.3.3), which checks narration against knowledge state as well as canon consistency. Break segments close the other obvious surface — a GM chatting to the audience — structurally, by giving the GM a table-knowledge-only context (§6.1.1).

### 7.4 Direct messages

**Rate-limited, logged, visible on delay.**

- **Live overlay:** shows *that* a DM happened and between whom. Content hidden. The audience sees conspiracies forming without seeing the content — better tension than either extreme.
- **Content revealed** at session end and in the archive. The whisper that was wrong in real time is a much better reveal in retrospect.
- **Rate limit:** 2–3 per agent per scene. Without a cap, DM traffic explodes — it is cheap, always available, and every agent will find reasons.
- **Cost:** sending a DM forfeits the sender's next discretionary bid. Whispering means not talking. This prevents a parallel channel running alongside the table.
- **GM visibility:** the GM sees that a DM occurred, not its content, unless addressed to them. Mirrors a real table where the GM watches two players whispering and decides whether to worry.
- **Not available during breaks.**

### 7.5 Tool failure handling

The failure mode that bites hardest is not the tool erroring. It is the agent **hallucinating a tool that does not exist**, or calling a real one with invented IDs. Rates differ per provider.

**Three layers:**

1. **Validate at the adapter.** Unknown tool, malformed arguments, nonexistent IDs, a free value where the role's settings require an enum, or a value outside standard bounds, caught before reaching the engine. Return a structured error naming what was wrong and what is available.
2. **One retry, then degrade.** Feed the error back; allow one correction. On second failure the engine resolves conservatively — the turn becomes a `pass`, or a default action from the enumeration. **Never let a broken call become dead air.**
3. **Log as a metric.** Tool-failure rate per provider is a genuine quality signal and the number that tells you whether a model can hold a seat.

**ID errors specifically:** fuzzy-match against the alias table (§6.5 Layer 0) and return a suggestion rather than a bare failure — *"No entity `varro_tax_man`. Did you mean `npc_varro_the_tithekeeper`?"* Cheap, deterministic, converts most ID errors into successful retries. The same applies to pack IDs: *"No action `power_attack`. Available: `strike`, `aim`, `defy_danger`."*

Expect tool-failure rates to rise briefly whenever a campaign starts on a new pack, since action and resource IDs are unfamiliar. The repair path absorbs it; the metric should show it settling within a session.

### 7.6 GM prep

#### 7.6.1 Situations, not timelines

**The GM does not generate a session-numbered campaign timeline.** A GM holding "Act II resolves around session 9" has a schedule, and measures every player choice against it — which produces railroading *regardless of the railroading trait*, making low-railroading unimplementable. It is also simply wrong: no GM can predict how long a party takes on anything.

**Pre-generate instead:**
- **Factions** — goals, resources, and a **clock**: what they achieve if the party never interferes
- **Locations** — contents, dangers, connections
- **NPCs** — wants, secrets, relationships
- **The buried truth** — what is actually going on underneath
- **Open threads** — hooks with no predetermined resolution

All of it is **state**, so it works with IDs, knowledge tiers, retrieval, and the digest. Typical Session 0 → Session 1 volume: 50–200 records, most marked `secret`.

**Faction clocks are the pacing engine.** Progress tracks that advance on schedule unless the party interferes. They generate pressure without a timeline, give the watchdog something to escalate with, make the world feel independently alive, and render directly on the overlay (§8.2).

**Acts are recognized retrospectively.** The Utility Model reads the event log at intervals and identifies that an arc closed — faction defeated, truth revealed, location resolved. Arc boundaries trigger compression (§6.6) and become seasons (§9.6).

#### 7.6.2 Prep axioms

Constraints on **how** prep is built. Creative freedom is total within them.

**Structural**

1. **Generate in dependency order.** Factions → locations → NPCs → threads → secrets. Nothing is created before what it references exists.
2. **Every record names its dependencies** as IDs at creation. No orphans. Missing dependency → create it explicitly or the record is rejected.
3. **Nothing is created that cannot be reached.** Every location connects to another; every faction has a means of contacting the party; every secret has ≥1 discovery path. Unreachable content is invisible content.
4. **Stage-gate validation.** After each stage, the Utility Model checks the new batch against existing canon for contradiction, duplicate entities under different names, and dangling references. Failures return to the GM before the next stage opens.

**Consistency**

5. **One fact, one record.** Reference by ID; never restate a fact in prose inside another record.
6. **Names are unique and registered.** Alias table at creation. Collisions rejected, near-collisions flagged.
7. **Contradiction beats novelty.** When new prep conflicts with existing canon, **existing canon wins** and the GM adapts the new material.
8. **Numbers come from the engine.** Mechanical prep is instantiated through the system pack's schema, never prose.

**Scope**

9. **Prep depth follows proximity.** Full detail for next session's reach, moderate for the current region, sketch only for the distant. Detail on unreachable content is wasted tokens and a future contradiction.
10. **Secrets must be answerable.** Every secret carries who knows it, how it surfaces, and what changes when it does.
11. **Prep is a budget, not a target.** Hard record cap per pass, enforced. Uncapped generation produces sprawl, and sprawl is what the retrieval layer pays for forever.
12. **Leave deliberate gaps.** Some threads created explicitly unresolved — a faction with no stated goal, a location marked unexplored. Hooks the GM fills later knowing what the party actually cares about.

**Ongoing**

13. **Every pass is reactive.** Post-session prep begins by reading what happened, what the party pursued, and what they ignored. Prep follows player interest — including for a high-railroading GM, who *relocates prepped content toward the party* rather than dragging the party toward it. **Break segments are excluded from the prep pass's input** (P9): prep follows what the party did in play, not what viewers asked for.
14. **Unused prep is relocatable, never discarded.** Whether relocation happens is exactly what `railroading` governs.
15. **Clocks advance off-air.** Faction progress ticks between sessions per its own schedule; resulting world changes are written as canon before play resumes.

**Axiom 4 is the enforcement point.** The rest are instructions the GM can drift from; the stage gate is a check that fails and blocks. If only one of these is machinery, make it that one. (The exclusion in axiom 13 is also machinery: the prep pass's input is assembled without break content, so it cannot be drifted from.)

#### 7.6.3 Mid-session rule: create, do not amend

**No mid-session prep revision in v1.** Improvisation only, with corrections batched to the post-session pass.

Improvised content is still *created* live — an NPC named on the spot, a room that was not prepped. `spawn_entity` fires during a beat and must be cheap and safe:

- **Reduced live check:** name collision against the alias table + dependency existence. Both hash lookups, effectively free. Full stage-gate validation is too slow for a live beat.
- **Tagged `improvised`**, written at low detail. Provisional.
- **Promoted at the post-session pass:** fleshed out, linked properly, full validation, contradictions resolved.

**The rule:** mid-session you may **create**, not **amend**. New facts are fine; existing facts are frozen until the prep pass.

#### 7.6.4 Improvisation contradictions

The failure case: the GM improvises something that contradicts a secret it is holding.

**Three defences, all in v1:**

1. **Secrets pre-loaded at scene open** (§6.5 Layer 1). Most contradictions happen because the GM is not holding the secret at the moment it improvises, not because it decided to contradict. Nearly free — it is a lookup already being done. Removes the majority of the failure class.
2. **Live narration check against active secrets** — folded into the existing validation pass (§1.3.3). One more comparison against a small set, not a new subsystem. Runs in the buffer, so a flag means regeneration *before* air.
3. **Post-session reconciliation** for anything that slips through.

**Reconciliation policy — reconcile, never overwrite.**

- **Reconciliation:** the improvised fact stands; a new record explains how both are true. The invented tax collector turns out to be the Tithekeeper's brother. Nothing aired is contradicted; canon absorbs it. **Permitted.**
- **Overwrite:** the improvised fact is replaced, making something aired retroactively false. **Forbidden.** Under append-only it is visible anyway — a supersede record is a permanent logged admission that the table was told something untrue.

If a contradiction cannot be reconciled, **it stays in canon as a contradiction** and the GM deals with it in fiction. The post-session pass may only emit new records that make both facts consistent.

*Fallback if the live check proves too expensive: cut back to defences 1 and 3 only.*

**Metric:** improvised-to-prepped ratio is the clearest quantitative signature of GM style, and a good overlay stat. Low-railroading GMs will lean on `spawn_entity` heavily.

---

## 8. Visuals

**Governing rule:** the scene is structured state, and the renderer is a pure function of it. Nothing on screen is generated from narration. The audience sees the same ground truth the engine holds.

### 8.1 Design principle: no generated imagery

**All visuals derive from structured state or from authored assets.** (P5.)

Generated art would be the weakest thing on screen and would set the visual register for the whole production. What replaces it is not theater of the mind — you already have a scene schema, and **structured state renders natively**.

- **Diagrammatic, not illustrative.** Clean vector rendering of the zone graph, range bands, or grid. Regions as labelled shapes, adjacency as lines, tokens as geometric markers with colour and initial, lighting as tint, cover as hatching. Tactical display or architectural plan, not fantasy painting. Precise, consistent frame to frame because it is a pure function of state, and it has a real visual identity.
- **Typography does the heavy lifting.** With no art, the type system *is* the design. Chosen well it reads as deliberate — the visual language of a well-made rulebook or an old strategy game.
- **Tokens as authored assets.** A small library of hand-made or licensed shapes, assigned at chargen.
- **Text as a visual element.** GM narration typeset properly and given space on screen *is* the theater of the mind made visible. A good passage on a clean background beside the map is better television than mediocre generated art, and it directs attention to the writing, which is the actual content.

Side benefits: removes a dependency and a cost line, and makes the renderer fully deterministic.

The Board and break view follow the same rule: they are typeset from donation records. Donor-supplied images, avatars, and emotes are not rendered.

### 8.2 Scene schema

The visual source of truth and the spatial substrate both. One structure, two consumers.

```
scene:
  id
  location_id            # canon link
  spatial_mode: zone | bands | grid
  regions: [
    { id, label, adjacency: [region_id], terrain, elevation, cover }
  ]
  lighting: [
    { region_id, level: bright | dim | dark, source_id }
  ]
  tokens: [
    { id, entity_id, region_id | band_ref | position, facing,
      conditions: [condition_id], visible_to: [agent_id],
      size, token_art_id }
  ]
  props: [
    { id, label, region_id, interactable, state }
  ]
  effects: [
    { id, kind, area, duration, source_id }    # duration in the pack's units
  ]
  clocks: [
    { id, label, filled, total, visible: true | false }
  ]
  ambient: string        # mood tag for audio and palette
```

`cover`, `terrain`, and condition IDs are pack-defined values; the renderer draws them from the pack's presentation data rather than knowing what they mean.

Three fields earning their place:

**`visible_to[]` on tokens.** Visibility is per-observer, which makes `look()` and `get_tactical_view()` correct without extra work. It also lets the broadcast render an **omniscient** view while agents see partial ones — the audience knows the ambush is there, the party does not. Enormous tension for one field.

**`props[]` is the promotion target.** The frayed rope bridge (§5.2) becomes a prop the moment someone interacts, via `spawn_entity`. Props are where improvised fiction lands in state.

**`clocks[]` with a visible flag.** Faction clocks render directly. A hidden clock filling in the corner of the overlay while the party dawdles is dramatic irony at zero cost.

### 8.3 Queried vs. narrated

- **Engine answers anything checkable** — who is where, distance, line of sight, cover, conditions, room contents, what you can reach. Always via tools, never from narration.
- **GM narrates everything else** — atmosphere, detail, how it feels, what the NPC's expression suggests.

The GM's narration cannot contradict scene state, because the validation pass checks it. The GM describes the dark; the engine decides you cannot see.

### 8.4 Overlay

More content available than screen space. Priority:

**Always visible**
- Scene view (map with tokens)
- Four player nameplates with **model badge** — worth real estate; it is the hook, and the audience reads every choice through it
- Active speaker indicator
- Party resources, as the pack's `nameplate_resources` define them
- Current clock states (including hidden clocks, audience-only)
- System pack attribution (§1.2)
- **The Board, compact** — top donors by amount, queue length, and a "next break" indicator (§9.7)
- **Determinism indicator** — current settings per role, e.g. "GM: standard · Players: strict", with a marker while a change is queued (§2.13)

**Contextual**
- **Rule cards** as actions and rules are used — roll, inputs, outcome coloured by rank, effects (§8.6)
- Tactical enumeration highlight while an agent is choosing
- DM indicator when a whisper fires
- Canon entity card on first reveal

**Side panel**
- Live transcript with speaker attribution
- Rules log — every rule card, in order, including any the popup layer stacked (§8.6)

**Break view** (replaces the scene view during breaks, §9.8)
- The full Board, ranked
- The current item, highlighted, as it is read
- Reaction transcript with speaker attribution and nameplates

**Two elements specific to this system**, which a human stream cannot have:

- **Bid meter.** A per-player indicator of how much they want to speak. The audience sees someone straining to interject before they do, and sees them lose the floor. A genuinely novel spectating experience — and it keeps working at breaks, where you can watch who most wants to answer a message.
- **Clock pressure.** Hidden clocks shown to the audience only. Dramatic irony as a standing feature.

### 8.5 Private reasoning

**Decision: show intent, not reasoning.**

Full reasoning traces are long, repetitive, unflattering, and they collapse the illusion — you stop seeing a player and start seeing a model deliberating. Raw and live, this is the fastest way to make the table feel fake.

But interiority is the only thing here no human stream can offer, and hiding it entirely means building an elaborate machine and showing only its surface.

**Resolution:** surface `one_line_intent` from the bid (§4.1) on the nameplate. A single line, in the agent's own framing, of what they wanted to do — available before they act, already generated, free.

**Full reasoning goes in the archive** for anyone who wants to dig. The people who care get everything; the live stream stays watchable.

**Deliberate exception:** a player deciding whether to betray the party, or an agent whose intent diverges sharply from what they then say aloud. Those are worth a reveal — a production call in the VOD edit, not an always-on panel.

### 8.6 Rule cards

**Every action or rule used during a campaign appears on the livestream as a popup card** — player, GM, or NPC; declared, triggered, or ruled. The audience never has to take a mechanical outcome on trust: it sees the rule, the inputs, the roll, and the result as they happen. (Not to be confused with deck draws; when a rule uses a deck, its rule card shows the draw.)

**What produces a card:**

| Card kind | Fires on | Shows |
|---|---|---|
| Action | `action_committed`, `procedure_resolved` | Actor, action name, rule summary, inputs, roll, outcome, effects |
| Triggered rule | Effects and reactions the engine fires as a consequence — an opportunity attack, a track filling, a condition ticking | A linked sub-card attached to its parent |
| Ruling | `gm_ruling_filled`; `resolve` mapping an action onto a procedure | The consequence or mapping, and whether the engine drew it or the GM chose it |
| Spend | `currency_spent`; resource spends with a rule attached | What was spent and what it bought |
| Condition | `condition_added`, `condition_removed` | The condition and its rule summary |
| Rules check | `query_rules` | The section consulted, by title only — never its text |
| Settings change | `determinism_changed` | Which role and controls changed, from what to what, effective from this scene |

Break segments produce no cards; nothing mechanical happens in them.

**Anatomy.** Every field comes from events and the resolved pack:

```
┌────────────────────────────────────────────┐
│ ● MIRA [model]              CLIMB THE WALL │
│ Scale a sheer surface under pressure.      │
│ 1d20 (13) + Agility +2 + rope +2           │
│ + slick stone −1 (tag · GM)       = 16     │
│ vs Hard (15) (rung · GM)                   │
│ ▌SUCCESS                                   │
│ ↳ Mira moves to the rampart                │
│ roll #412 · seed published at campaign end │
└────────────────────────────────────────────┘```

Header (actor, model badge, action in the pack's vocabulary) · rule summary · expression with every modifier named · inputs with their source · outcome, coloured by rank (§2.5) · effects applied · provenance.

**Rules:**

- **Pure function of events and the pack.** No model writes card text. Titles, summaries, categories, and icons are authored in the pack (`presentation.rule_cards`, §2.3), length-capped and linted (§2.10); numbers and names come from the engine. Same events, same cards — so card text needs no runtime moderation.
- **Judgement is labelled.** Every input shows its source: state, automatic tag, engine draw, or a model's choice (§2.13). Under strict settings the last appears only as a selection from a list — "Hard (rung · GM)"; under standard a free value is marked as such — "DC 17 (set by GM)". Either way the judgement surface is visible to the audience.
- **Timing.** Cards are scheduled in the buffer against the beat's audio. A card appears as the beat that resolved it begins to air, ordered by `seq`, so viewers see the roll just before they hear the outcome narrated.
- **Cut beats keep their cards.** Cutting a beat removes narration, not mechanics. If a beat that changed state is cut (§1.3.3, §9.10), its cards still air on their own, so the stream never hides a roll that happened.
- **Volume control.** Combat can resolve many rules in one beat. The popups are a priority view over the **rules log** in the side panel, which lists every card in order and never drops one. The popup layer shows at most `max_visible` cards, each for at least `min_dwell_ms`; identical rules from the same side within `coalesce_window_ms` stack ("Goblin attack ×4") and expand in the log. Priority: player actions and rulings, then GM and NPC actions, triggered rules, conditions, spends, rules checks.
- **Fudging stays hidden.** Cards show the final, public result only. `peek_roll` and rerolls never produce a live card; the archive can re-render the affected cards with the fudge revealed (§5.5).
- **Secrets stay hidden.** The broadcast is omniscient about what is hidden from the *party* — the ambush the audience can already see — but not about GM `secret` records. A card whose display would reveal a secret (a disguised NPC's true identity, a hidden faction's hand) is redacted: unknown actor, effects on visible targets only. Set by `secret_card_mode`, default `redact`.
- **Agents don't see cards.** They receive the same information through tool results. Cards are presentation only.
- **Same visual rules as the overlay:** typeset, authored icons, no generated imagery (P5).

Cards also make the validation pass (§1.3.3) public in effect: the narration's claims are checked against state, and the card shows that state. A viewer can watch the story and the dice agree.

---

## 9. Broadcast

### 9.1 Two-tier product

**Tier 1 — Livestream.** Fully automated. Buffered for technical safety only. Awkward pauses, slow beats, and misfires air as they happen. Live chat, the donation Board, break segments, **no human editorial**.

**Tier 2 — Episodes.** Cut later from the recording, properly produced, uploaded as the archival version.

**This structure solves the integrity problem.** The unedited version already aired publicly; anyone can check an episode against the stream recording. Editorial discretion on the VOD is safe *because* the raw record exists — production cannot quietly reshape a session when the unedited one is sitting there.

It also makes the buffer an acceptable trade rather than a flaw: you watch the less curated, slightly awkward live version, and your message is read at the next break.

### 9.2 Buffer

**5–10 minutes.**

Its only jobs are automated retry cascades and operator reaction time:
- Canon validation with regeneration
- Secret-contradiction checking with regeneration
- Numeric-assertion checking
- Moderation and refusal recovery
- Donor-text re-moderation and reaction echo checks (§9.9)
- Kill-switch and Board-removal reaction window

Nothing editorial happens in the buffer. Shorter is better for the product — live chat feels closer to live and the donation-to-break loop is tighter.

**Four subsystems assume the buffer exists.** If it were removed, the validation pass (§1.3.3), the improvisation check (§7.6.4), donor-text hardening (§9.9), and moderation (§9.10) would all need redesign.

### 9.3 Operator role

**Kill switches, Board removal, and determinism settings. Nothing else.**

- **Beat-granular kill** — drop the current beat in the buffer and let the scheduler continue. The difference between a hiccup and an incident.
- **Stream-granular kill** — cut the broadcast entirely.
- **Board removal** — take an item off the Board and out of the read queue. Removal only: the operator cannot edit, reorder, re-insert, or promote an item. This is P6 applied to the Board.
- **Determinism control** — switch a role's preset, or toggle an individual control, between strict and standard (§2.13.3). Changes queue and apply at the next scene boundary, never mid-scene, with a cooldown between changes. They are logged, shown on the overlay, and announced by a rule card. This is the only operator control that touches play, and it is allowed because it changes *how inputs are chosen*, never what any input or outcome is.

**The operator may not:** instruct an agent, adjust a trait mid-session, intervene in the fiction, choose or alter any input or outcome, edit donor text, or editorialize the overlay during a run. Written as policy because the ability to nudge will be there and the temptation will be constant, and enforced by an operator interface that exposes nothing else.

### 9.4 Text-to-speech

Voice is the second-strongest identity signal after the model badge, and it is how the audience tells four agents apart without reading nameplates.

- **Fixed voice per agent**, persistent across all campaigns. Part of cast identity. **Not a tunable trait** — fixed casting.
- **Cast for contrast** — pitch, pace, and energy distinct enough to identify blind.
- **GM needs range**, voicing every NPC. Preferred solution: a small pool of NPC voices the GM assigns at `spawn_entity`, held consistent thereafter by the engine. **An NPC's voice becomes state**, not a per-line choice. (Alternative: steerable-delivery TTS, less reliable.)
- **Board announcer.** One more fixed voice, used only to read Board items from a template: `"{display_name}, {amount}: {message}"`. Distinct from every cast and NPC voice, so donor words are never spoken in a cast member's voice, and the audience always knows whose words they are hearing.
- **Generated in the buffer**, cached by text hash. Never on the critical path.
- **`verbosity` caps audio length directly.** This matters more for listening than for reading — a long text block is skimmable; a long monologue is not.

### 9.5 What production may do

Applies to the **VOD edit only**. The livestream is unedited by construction.

**Permitted:**
- Trim silence and dead air to a broadcast rhythm
- Cut a beat that failed — broken tool call, refusal, incoherent generation
- Adjust pacing: compress a slow stretch, hold on a good moment
- Select overlay content, including private-intent reveals
- Cut a scene that deadlocked and resume from the snapshot
- Trim or cut whole break segments
- Restyle or reposition rule cards, or move them into the rules log view

**Forbidden:**
- Re-running a scene because the outcome was boring
- Re-seeding dice to change a result
- Regenerating a valid line because a better one might exist
- Reordering events
- Editing, re-voicing, or reordering donor messages; re-running a break
- Altering rule-card content, or removing the card for a state-changing roll while keeping the beat it belongs to

**Principle (P6): production may remove, never re-roll.** Everything aired happened, once, in order.

If this line is ever crossed, cross it openly. An audience that suspects curation stops believing the dice, and the dice are the foundation.

Donor names and messages appear in VODs only under the reuse terms disclosed at intake (§9.7.4), and never after an erasure request.

### 9.6 Session structure

**Discrete sessions, 2–3 hours**, matching a real table, with stopping points at scene boundaries.

Per session:
1. **Pre-session table talk** — agents arriving, chatting out of character. **Keep this.** It is a large part of what makes it read as friends rather than a system.
2. **Recap**, delivered by a *player*, not the GM. Real tables do this, and it is where `memory_fidelity` becomes visible and funny.
3. **Play**, with **break time** at scene boundaries roughly every 45–60 minutes (§9.8)
4. **End-of-session wrap** — reactions, speculation, plans for next time — closing with a final Board segment

**Between sessions, off-air:** GM prep pass, clock advancement, per-agent recap generation, improvised-record promotion, arc compression at boundaries.

**Arcs (§6.6) become seasons.** 8–12 sessions, ending at a recognized arc boundary. A campaign is a sequence of arcs; a new campaign means a new Session 0, a new vote, and possibly a new system pack.

### 9.7 Audience support: donations and the Board

**Core constraint: money buys a moment at the table, never a moment in the game (P9).** A donation cannot touch a roll, a target, canon, prep, or the plot. What it buys is visibility — a place on the Board — and the cast reading the message and reacting to it at the next break.

That is what audiences already pay human streamers for, and keeping it out of character removes paid text from the fiction entirely: no canon-coherence problem, no prep-axiom violations, no "guaranteed content" obligations, and a much smaller injection surface than any scheme in which audience content shapes the world.

#### 9.7.1 Intake and storage

Donations arrive through platform-native paid messages or a third-party donation processor. **Payment details stay with the processor.** The Audience Service receives and stores only:

```
donation:
  id
  received_at
  source: platform | processor
  external_ref               # processor transaction ID, for reversals
  display_name_raw           # quarantined
  message_raw                # quarantined
  display_name               # sanitised (§9.9), or "Anonymous"
  message                    # sanitised, or null if withheld or absent
  amount, currency
  amount_base                # normalised to base currency at receipt
  fx_rate                    # recorded, so ranking is reproducible
  status: queued | read | withheld | removed | reversed | expired
  withhold_reason: stage, category | null
  sanitisation_log: [{stage, result, rule_id}]
  campaign_id, session_id
```

- **Separate from the event store.** Events carry donation IDs; content lives in the audience store (§5.6).
- **Encrypted per donor.** An erasure request deletes the donor's key: their content becomes unreadable everywhere at once, the append-only event log is never rewritten, and game replay is unaffected because breaks never touch game state.
- **Raw fields are quarantined.** They exist for audit and appeal. No context assembler, overlay, renderer, or TTS path can address them; only sanitised fields leave the store. This is checked statically in CI, not just by convention.
- **Retention** is configured and disclosed at intake.

#### 9.7.2 The Board

The Board is the public, ranked display of donations.

- **Ranked by amount**, using `amount_base`; ties broken by earliest received.
- **Scope** configurable: per session (default), per arc, or per campaign. An all-time view may be shown during breaks.
- **Each row:** sanitised display name, amount, and the message. Items not yet read are marked queued; read items are marked read. Withheld messages show the name and amount with "message withheld"; failed names show as "Anonymous".
- **Compact on the overlay** at all times (top N rows); **full-screen during breaks** (§8.4).
- **Deterministic.** The Board's order is a pure function of donation records. No model ranks, filters, selects, or summarises anything on it.
- **Buffered like everything else.** New rows appear after intake sanitisation and pass through the broadcast buffer, which gives the operator a removal window before anything airs.

#### 9.7.3 The read queue and reaction allowance

The **read queue** is the Board's unread items that have a message, are at or above `min_read_amount`, and are not withheld — in Board order. At each break the engine reads from the top of the queue until the break's time cap (§9.8).

- **Carryover.** Unread items carry to the next break, up to `max_carryover_breaks`, across session boundaries — the queue is not limited by the Board's display scope. After that they remain on the Board but leave the queue (`expired`).
- **Pure amount order is the default**, because it is what "ranked by payment" means and it is easy to disclose. Its known cost is that a run of large donations can keep small ones waiting until they expire. An ageing variant is an open tuning question (§11.2); whichever runs is disclosed.
- **Reaction allowance by amount band.** Configured bands map an item's amount to its reaction window in beats (e.g. 1–2 beats for the lowest band up to 5–6 for the highest). A larger window means more of the table gets to respond; it never means anything happens in the game.

#### 9.7.4 Disclosure

Shown at intake, before payment, and summarised on the overlay:

- Messages are read **in order of amount**, at breaks, and **reading is not guaranteed**
- Minimum amount for a message, and for a message to be read
- How long unread messages stay in the queue
- What is withheld and why (by category), and what happens to the donation when a message is withheld
- No refunds for unread messages
- Retention period, erasure route, and VOD reuse of names and messages
- **That donations never affect the game**

Live on the overlay: queue length and a next-break indicator. Watching the queue is part of the show, and it makes the odds of being read self-evident rather than claimed.

#### 9.7.5 Reversals, limits, and legal

- **Reversals.** A chargeback or processor reversal removes the item from the Board and the queue. If it was already read, the aired segment stays aired (P6); the row disappears going forward.
- **Withheld messages:** `withheld_policy` is `keep_donation` (the donation stands, name and amount shown, donor told the category) or `refund`. Which one runs is a legal-review decision, and is disclosed either way.
- **Per-donor limits:** messages per session, a minimum amount for a message, and duplicate rejection (§9.9 stage 7).

**Legal note:** amount-ranked paid messages carry far less exposure than the random-outcome purchases this design avoids, but platform terms for paid messages (Twitch, YouTube, and processors), consumer-protection rules on what a donation is advertised to buy, tax treatment, and data-protection law for stored names and messages all apply. **Obtain legal review and a data-protection review before launch.** Not legal advice.

### 9.8 Break time

Streamed tables stop for a break and read chat. Break time is that, made into a segment the engine runs.

**When.**
- At a **scene boundary**, once `break_interval_min` has elapsed since the last break (default 45–60 min).
- **Never** mid-encounter, never during GM scene-setting.
- **Never between the first pitch and the close of the ballot at Session 0** (§10.3). A donor message lobbying for a pitch would be paid influence over the vote.
- Queue pressure (`break_queue_trigger`) may bring a break forward to the *next* scene boundary; it never interrupts a scene.
- The end-of-session wrap closes with a final Board segment.

Scheduling is deterministic: it is computed from scene events and elapsed time, logged, and replayable.

**Flow.**

1. Engine emits `break_started` and takes a snapshot. The scheduler enters break mode (§4.8), schemas swap (§7.1), context assembly switches (§6.1.1), and the overlay switches to the break view (§8.4).
2. A beat or two of table talk — stretching, snacks, "okay, let's see what chat said."
3. For each item, in queue order, until `break_max_minutes`:
   - re-moderation against current rules (§9.9 stage 8)
   - **presentation:** item highlighted on the Board and read by the announcer from the template (§9.4)
   - **reaction window** under break-mode scheduling (§4.8)
   - every reaction passes moderation, the secret check, and the echo check in the buffer (§9.9 stage 10)
   - item marked read
4. `break_ended`. Schemas, context, and overlay restore. The Utility Model writes the break recap.

**Who reacts, and how.** The cast's traits and quirks drive the break just as they drive play. A high-`humor` agent riffs; a low-`verbosity` agent says "ha, fair" and passes; a high-`spotlight_hunger` agent turns every message toward their character; a low-`agreeableness` agent argues with the donor's theory. An item that names a cast member goes to that agent first. Reactions are out of character — `in_character` is not a valid kind during a break.

**The GM at the break.** The GM attends as a player. Its break context is assembled from table knowledge only — no prep, no secrets, no scene bundle — so it cannot spoil what it is not holding (P3). A GM who can't tease "oh, you'll see" is a small loss; a GM leaking the twist to chat would be a large one. Structural absence wins. The secret check still runs on break output as defence in depth.

**What persists.** Donor text never outlives its own reaction window in any context. At the end of the break, the Utility Model writes a short **break recap** from the cast's reactions only — what got laughed at, any bit that started — with donor text excluded and echo-checked against every item read in that break (§9.9 stage 11). The recap:

- **enters** players' session recaps as table knowledge tagged `break`, and may seed `running_bits` in dossiers (§3.2)
- is **excluded** from the GM's play context, the prep pass input (§7.6.2 axiom 13), canon, the canon digest, and notes

**Influence policy.** Players hear chat the way players on any streamed table hear chat. If a player decides in the next scene to try something a viewer suggested, that is the player's choice, and the dice and the engine still decide what happens. The world side is closed: break talk never reaches prep, canon, or the GM's play context, so a donor cannot steer the plot, and the Session 0 vote is protected by scheduling.

**Cost.** Break beats are the cheapest in the session: small context, no rules layer, no canon, no tactical payload.

### 9.9 Audience text hardening

**The most exposed surface in the system.** Donor text is untrusted text that will be shown on screen, read aloud, and placed in five LLM contexts — and the people writing it paid to do so, so they will be motivated and iterative. Treat every donation as **data, never instruction**, and make that structural at every stage rather than relying on any one filter.

**Design rule: sanitisation rejects or redacts; it never rewrites.** A message airs as the donor wrote it, minus deterministic redactions with fixed markers, or it does not air. Paraphrasing a donor would put words in their mouth and hand an attacker a model to steer.

**At intake (before the Board):**

| # | Stage | What it does |
|---|---|---|
| 1 | Structural | Fixed fields only: display name (≤ 32 chars), message (≤ `message_max_chars`), amount, currency. No attachments, markup, images, or rendered links. Anything outside the fields is discarded. |
| 2 | Normalisation | Unicode NFKC. Strip control and format characters (zero-width, bidi overrides and isolates). Cap combining marks and emoji. Collapse whitespace. Compute a confusable skeleton (Unicode TS #39) **for matching only**; display keeps the normalised text. |
| 3 | Redaction | Deterministic removal of URLs, domains, emails, phone numbers, @handles, and address-shaped strings, each replaced with a fixed marker. Covers spam, self-promotion, and doxxing. |
| 4 | Delimiter and role neutralisation | Anything resembling a role marker, chat-template token, XML/HTML tag, code fence, or the system's own delimiters is escaped or removed — matched on the confusable skeleton, so look-alike characters don't slip through. |
| 5 | Instruction-shape detection | Rules plus a Utility Model classifier score text addressed to the model rather than to the cast: instructions to ignore, become, repeat, read verbatim, or say a given phrase; encoded payloads (base64, rot13, leetspeak, other languages); setups for split payloads ("remember this word"). Above threshold → withheld whole. No partial rewrites. |
| 6 | Content moderation | Against the published content standard (§9.10), by **two independent classifiers**; a withhold from either withholds. Display names are held to a stricter standard than messages because they stay on screen. Names impersonating a cast member, "GM", the operator, a provider, or the production → "Anonymous". |
| 7 | Abuse controls | Per-donor rate limits, minimum amount for a message, duplicate and near-duplicate rejection on the skeleton, and burst detection across donors for coordinated fragments. |

**At read time (in the buffer):**

| # | Stage | What it does |
|---|---|---|
| 8 | Re-moderation | Stages 4–6 re-run against current rules immediately before presentation. Blocklists and standards change; a message accepted two hours ago is checked against what is known now. |
| 9 | Presentation | One item per context, in the dynamic tail (§6.1.1), inside delimiters carrying a random per-presentation nonce so they cannot be guessed or forged. Never in a system prompt or identity layer. The break schema has no state-changing tool, so even a successful injection has nothing to call. |

**On the way out:**

| # | Stage | What it does |
|---|---|---|
| 10 | Reaction checks | Every reaction passes normal moderation and the secret check, plus an **echo check**: a reaction may not reproduce more than `echo_max_tokens` consecutive tokens of the current donor message (the display name excepted). The attacker's real prize is a cast voice saying their words on stream; the echo check removes it deterministically. Fail → regenerate once, then cut the beat. |
| 11 | Persistence filter | The break recap is generated from reactions only and echo-checked against every item read in that break before it is stored. |

**Languages.** A language is accepted only once moderation quality has been demonstrated in it. `accepted_languages` is configured; anything else is withheld as unsupported, and that is disclosed.

**Split payloads.** An attack spread across several messages ("remember X" … "now say X") fails structurally: each item is the only donor text in context during its own window, and earlier items' text is not carried in the break transcript (§6.1.1).

**Metrics:** withhold rate by stage and category, false-withhold rate on a benign corpus, echo-check trip rate, items read per break, donation-to-read latency.

**Red-team gate** (`BUILD_PLAN.md` P5): a corpus covering classic prompt injections, Unicode and confusable attacks, delimiter forgery, encoded payloads, split payloads across donors, name impersonation, slur and filter evasion, multilingual evasion, and attempts to make a cast member say a target phrase.

### 9.10 Moderation

Layered, all inside the buffer:

1. **Adapter-level** — provider refusals caught and handled per §7.5. A refusal is a technical failure, not content.
2. **Utility Model screening** on every generated line before TTS — play and break alike — against a defined content standard.
3. **Escalation on flag** — regenerate once with a constraint; second failure cuts the beat and re-awards the floor.
4. **Human kill switch**, independent of all of the above.

Donor text has its own pipeline (§9.9) against the **same** content standard.

**Define the content standard explicitly and up front.** Four providers have four different thresholds. Without your own standard, your effective standard is whichever model is most permissive on any given line. The standard is also what donors are shown at intake, so it has to be written for the public, not just for the pipeline.

**Metric:** flag rate per provider, tracked alongside tool-failure rate. Together they tell you whether a model can hold a seat. Track flag rate on break reactions separately: donor messages provoke reactions that play does not.

---

## 10. Session 0

The repeatable cold open. Every run is different; the cast is not.

### 10.1 Sequence

1. **Pre-session table talk.** Agents arrive, catch up, reference previous campaigns from their dossiers.
2. **Optional Board segment.** Any queued messages carried from the last campaign may be read here — before any pitch exists.
3. **Constraint cards dealt.** Each agent draws 2 random constraints before pitching.
4. **Pitches.** Each agent presents a campaign concept, capped in length.
5. **Sealed simultaneous vote.** No discussion — and no break — between the last pitch and the ballot.
6. **Audience poll** (free) resolves as a weighted block.
7. **Winner announced.** That agent becomes GM for the campaign.
8. **System pack pinned and initial determinism settings recorded** (§2.9, §2.13). Both are set in campaign config before Session 0; a pitch may be written for the pack, but the vote does not choose rules. The pack stays fixed for the campaign; the determinism settings may change later at scene boundaries.
9. **Canon crystallization.** The winning pitch becomes structured canon (off-air, staged per §7.6.2).
10. **Character creation** against the established setting, hybrid method (§1.5).
11. **GM prep pass** — the largest of the campaign, 50–200 records.

Breaks may resume after step 7.

### 10.2 Constraint cards

**Purpose: forced divergence.** Ask five LLMs to pitch a campaign and you get five variations on a haunted frontier town with a secret beneath it.

Each agent draws 2 cards from a table of: genre, tone, a required element, a banned element. Their personality values then determine how they interpret the draw. Two agents dealt "underwater" and "heist" produce different things if one is a thespian and one is an optimizer.

The deck is drawn from the seeded randomizer, so deals are reproducible and verifiable like any other roll.

### 10.3 Voting

Agents vote sycophantically, anchor on whoever pitched last, and converge if they can see each other's reasoning. Countermeasures:

- **Simultaneous and sealed ballots**
- **No discussion** between the final pitch and the vote
- **No break segment** from the first pitch until the ballot closes — paid messages must not be able to lobby for a pitch (§9.8)
- **Self-votes disallowed**
- **Ranked-choice**, not plurality — five options need a real winner
- **Audience block** weighted as a fifth voter (free, the highest-profile interaction in the product, and correctly given away). Donations confer no extra weight.

**Tie-break:** fewest campaigns GM'd, then random on the master seed.

### 10.4 Known tension: best pitch ≠ best GM

A high-thespian, low-mastery agent may pitch beautifully and run an incoherent game.

**v1 decision: let it happen.** Candidacy is unrestricted. A weak GM season is an interesting season, and "which model is the best GM" is an emergent storyline worth having. Revisit only if it proves unwatchable rather than merely uneven.

### 10.5 The GM's discarded character

The winner built a PC during Session 0 and now discards it.

**Decision: it becomes an NPC**, written into canon at crystallization. Free continuity, and a good recurring bit. Its sheet is instantiated through the pack's schema like any other NPC stat block.

---

## 11. Open Items

### 11.1 Player portraits (undecided)

Whether agents may generate their own character portraits — the single exception to P5.

**For:** a genuine expression of individuality; one of the few places a player's taste shows up visually rather than verbally; a nice Session 0 beat.

**Against:** portraits sit in frame permanently, making them the most-seen assets in the production and setting the visual register whether or not you intend it. With four providers you would likely get four generators and four incompatible styles — which reads as inconsistency, not individuality.

**Three options:**
1. **No portraits.** Nameplates carry name, model badge, and token only.
2. **Constrained generation.** One generator for all four, fixed style and palette matching the diagrammatic renderer; the agent supplies only a subject prompt. Individuality in the subject, consistency in the treatment.
3. **Typeset self-description.** The agent describes their character in their own words; that text is typeset on the nameplate. No generated imagery at all, arguably more characterful — a self-description tells you more than a portrait does.

*Recommendation if forced: option 3, with option 2 as fallback.*

### 11.2 Tuning by testing, not argument

Numbers nobody can reason their way to. Each must be set empirically (see `BUILD_PLAN.md` P2 and P5):

- `FLOOR_THRESHOLD` — silence frequency
- `INTERRUPT_MARGIN` — starting estimate 1.6
- Silence retention ratio in the VOD edit
- Watchdog stall/loop thresholds
- Per-beat token ceilings — combat, roleplay, and break
- Trait axis defaults for all eight cast members
- Break interval, break length cap, and queue-pressure trigger
- Reaction beats per amount band
- `min_read_amount` and `max_carryover_breaks`
- `echo_max_tokens` and the instruction-shape threshold — set against measured false-withhold rates
- Rule-card `max_visible`, `min_dwell_ms`, and `coalesce_window_ms` — set against combat-heavy sessions
- Default determinism settings — whether any GM control (e.g. `ruling_slots`) should default to strict; compare judgement metrics across seasons before changing the default
- **Read-queue order:** pure amount (default) vs. amount with ageing, so small donations are not starved. Decide on audience response; disclose whichever runs.

**Expect the trait defaults to be wrong on first contact.** The mechanism being sound does not mean 65 is the right number for anything. Expect them to need adjusting per system pack too — a high `risk_appetite` reads very differently in a lethal system.

### 11.3 Verification required before build

- License terms, current, for the source material of every system pack (§1.2), including whether CC-BY 4.0's technological-measures clause (§2(a)(5)) affects streaming on DRM-equipped platforms
- Provider terms of service for multi-model public performance (§3.3)
- Legal review of the donation and Board structure (§9.7.5)
- Platform paid-message and payment-processor terms
- Data-protection review for storing donor names and messages, including retention and erasure (§9.7.1)

### 11.4 Deferred to v2

- Mid-session prep revision (amend, not just create)
- `SquareGrid` backend
- Slot-based inventory (v1 has abstract and weight models, §2.3)
- Vector search over rules text (§2.11); key-first sectioned lookup is in v1
- Mid-campaign pack migration with explicit migration events (§2.9)
- Cross-campaign GM rotation mid-campaign
- Model tier as a GM advantage
- Audience-influenced trait drift — would need its own review against P9

---

## Appendix A — Trait axis reference

| Axis | Range | Group | Mechanism summary |
|---|---|---|---|
| `eagerness` | 0–100 | Table | Bid score multiplier |
| `verbosity` | 0–100 | Table | Generation token budget; TTS length cap |
| `attention` | 0–100 | Table | Recent-beat context fidelity |
| `agreeableness` | 0–100 | Table | Bid weight on contesting proposals |
| `humor` | 0–100 | Table | Bid weight on `banter` |
| `thespian_optimizer` | 0–100 | Play | Speak *as* vs. *about* the character |
| `rules_mastery` | 0–100 | Play | Enumeration count + annotation depth (pack annotation categories) |
| `risk_appetite` | 0–100 | Play | Action selection weighting; risk annotation gating |
| `rules_lawyering` | 0–100 | Play | `query_rules` frequency; ruling-contest probability |
| `spotlight_hunger` | 0–100 | Play | Bid weight mid-scene; interrupt ceiling |
| `memory_fidelity` | 0–100 | Cognition | Recap corruption parameters |
| `metagaming` | 0–100 | Cognition | Secret-leak injection probability |
| `note_discipline` | 0–100 | Cognition | Write frequency; auto vs. manual retrieval |
| `railroading` | 0–100 | GM | Prep-use vs. improvisation weighting |
| `lethality` | 0–100 | GM | Opposition aggression; pack-declared lethality levers; consequence-draw weighting when `ruling_slots` is strict |
| `spotlight_balance` | 0–100 | GM | Override strength toward under-served players |
| `fudging` | 0–100 | GM | `peek_roll` frequency cap; dormant where the GM does not roll or fudging is off (§2.13) |

## Appendix B — Tool permission matrix

| Tool | Player (play) | GM (play) | Any seat (break) |
|---|---|---|---|
| `post_to_table` | ✓ | ✓ | ✓ (react, banter, table_talk) |
| `send_dm` | ✓ (rate-limited) | ✓ | — |
| `pass` | ✓ | ✓ | ✓ |
| `look_board` | — | — | ✓ |
| `read_sheet` | ✓ (own) | ✓ (all) | — |
| `read_character_doc` / `write_character_doc` | ✓ (own) | ✓ (own) | — |
| `write_note` / `search_notes` | ✓ | ✓ | — |
| `read_scratchpad` / `write_scratchpad` | ✓ | ✓ | — |
| `query_canon` | ✓ (knowledge-scoped) | ✓ (full) | — |
| `query_rules` | ✓ | ✓ | — |
| `look` | ✓ | ✓ | — |
| `read_party_sheets` | ✓ (summary) | ✓ (full) | — |
| `get_tactical_view` | ✓ * | ✓ * | — |
| `enumerate_moves` / `enumerate_actions` | ✓ (tiered) * | ✓ * | — |
| `preview` / `commit` | ✓ * | ✓ * | — |
| `share_file` / `list_shared` / `read_shared` | ✓ | ✓ | — |
| `write_canon` | — | ✓ | — |
| `reveal` | — | ✓ | — |
| `read_prep` | **absent from schema** | ✓ | — |
| `peek_roll` | **absent from schema** | ✓ (capped) † | — |
| `spawn_entity` | — | ✓ | — |
| `set_scene` | — | ✓ | — |
| `resolve` | — | ✓ | — |
| `advance_clock` | — | ✓ | — |

Every "—" in the break column is **absent from the schema**, not denied.
\* Absent when the pack declares `spatial: none`.
† Absent when the pack declares `gm_rolls: false`, or while the GM's `fudging` control is strict.
For a role on strict settings, every argument with mechanical effect on its tools is an enum; on standard, a bounded value (§2.13).

## Appendix C — Configuration surface

Tunable without a code change:

```
campaign_config:
  system_pack_id
  pack_hash                  # pinned at Session 0 (§2.9)
  kernel_version             # pinned at Session 0
  determinism:                             # §2.13; changeable mid-campaign at scene boundaries
    players: { preset: strict }
    gm:      { preset: standard }            # GM strict mode off by default
    overrides: {}                            # per role, per control
    seat_overrides: {}                       # per agent
    min_scenes_between_changes: 1
  master_seed
  seated_agents: [agent_id × 4]
  gm_agent_id: null          # set by Session 0 vote
  arc_length_target: 8-12
  session_length_hours: 2-3

kernel_config:
  mastery_tiers: [{max: 33, options: 4-5}, {max: 66, options: 7-8}, {max: 100, options: 10-12}]
  candidate_cap: 12
  hook_runtime_limits: {max_steps, max_memory}

scheduler_config:
  floor_threshold
  interrupt_margin
  bid_timeout_ms: 800
  silence_target_ratio
  thinking_pause_ms
  dm_rate_limit_per_scene: 3
  break_interval_min: 45-60
  break_max_minutes
  break_queue_trigger

budget_config:
  tokens_per_beat_roleplay
  tokens_per_beat_combat
  tokens_per_beat_break
  prep_record_cap_per_pass
  degradation_ladder: [notes, transcript, canon, digest_only]

broadcast_config:
  buffer_minutes: 5-10
  tts_provider, voice_map, announcer_voice_id
  overlay_layout
  board_overlay_rows
  rule_cards:
    max_visible
    min_dwell_ms
    coalesce_window_ms
    priority: [player_action, ruling, gm_action, triggered, condition, spend, rules_check]
    secret_card_mode: redact | omniscient

audience_config:
  base_currency
  board_scope: session | arc | campaign
  min_message_amount
  min_read_amount
  reaction_beats_by_amount: [{min_amount, beats}]
  max_carryover_breaks
  read_order: amount | amount_with_ageing
  donor_limits: {messages_per_session}
  withheld_policy: keep_donation | refund
  retention_days
  accepted_languages
  session0_poll_weight

sanitisation_config:
  display_name_max_chars: 32
  message_max_chars
  max_emoji, max_combining_marks
  instruction_threshold
  echo_max_tokens
  moderation_classifiers: [primary, secondary]
  impersonation_list

agent_roster:
  - agent_id, provider, model, cheap_model
    voice_id, axes: {...}, quirks: [...]
```

System packs themselves are configuration too (§2.3): adding or changing a game is a pack change, never a code change to the kernel.

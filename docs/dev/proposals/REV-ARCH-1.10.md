# Draft revision: ARCHITECTURE 1.10 (Phase 0 completeness)

**Status:** approved by the owner on 2026-10-30 as recommended in every section, applied to `docs/ARCHITECTURE.md` as 1.10, and built as T0.40 (A, E, F), T0.41 (B, C, D), and T0.42 (G, H), split as in section I. Kept as the record of the review.

**Why:** the fifth Phase 0 audit (2026-10-30) found that the gate passes and every test BUILD_PLAN names for P0.1 to P0.15 exists. It also found eight places where the P0 design promises something the kernel cannot yet do, or where the text and the build disagree. The owner asked for all eight in one proposal, so P0 is complete against its own design.

| # | Gap | Where the design promises it | Section |
|---|---|---|---|
| 1 | Lookup tables roll only during chargen | §2.2, §2.3 `randomizers.tables`, §2.4, P0.2 | A |
| 2 | A promoted prop becomes an NPC that takes turns | §5.2, §8.2 `props[]` | B |
| 3 | A spawned entity can only set stats and position, and the GM's tool can set neither stats nor kit | §1.3.2 "numbers come from the engine", §7.1 `spawn_entity(spec)` | C |
| 4 | `get_tactical_view` is listed but does not exist | §7.1 (tool list and table), §8.2 | D |
| 5 | Time-advance limits are fixed in the kernel, unlike clock limits | §2.3 `time` (and 1.9's clock limits) | E |
| 6 | The master seed cannot be revealed in the log | §5.5 publication policy; BUILD_PLAN P5.7 | F |
| 7 | Point-buy chargen has no step kind | §1.5 ("spending points") | G |
| 8 | Lighting is scene-wide; §8.2 has it per region | §8.2 `lighting[]`, §2.13.1 "dim light from scene lighting" | H |

Each section gives the problem, the options, a recommendation (⚑ marks the decision), the proposed text, and what the build would add. **None of these changes the fold of an existing log:** every new field is written only when used, and every new event is new. So no shipped campaign's state hash moves, and `KERNEL_VERSION` stays as D-045 decides.

---

## Header: version and revision note

**Current:** `**Version:** 1.9 (revised design freeze for v1)`
**Proposed:** `**Version:** 1.10 (revised design freeze for v1)`, plus:

> **Revision notes (1.10):** after the fifth Phase 0 audit (T0.40, D-057):
> - §2.3, §7.1: lookup tables roll in play (`roll_table`), for the GM and, where the pack allows, players.
> - §2.3, §5.2, §8.2: an entity is an `npc` or a `prop`; props never take turns unless joined.
> - §2.3, §7.1: pack-declared entity templates; the GM spawns from a template by ID.
> - §7.1: `get_tactical_view` is the encounter view of positions, ranges, cover, and whose turn it is.
> - §2.3: in-world time advances within per-unit limits the pack sets, with kernel defaults.
> - §5.5, §5.7: `conclude_campaign` reveals the master seed into the log once the campaign is over.
> - §1.5, §2.3: a `points` chargen step for point-buy systems.
> - §2.3, §8.2: lighting is a region value the pack declares, readable by rules.

---

## A. Lookup tables in play

**Problem:** `randomizers.tables` rolls only in a chargen `table` step. Nothing in play can roll one, so random-encounter, oracle, weather, or loot tables are unusable, though §2.2 lists lookup tables beside dice and decks on the seeded stream.

**Options:**
1. **(Recommended) A `roll_table(table_id)` command and tool.** The engine rolls the table's `roll` through the logged randomizer and emits the existing `table_rolled` event with the entry. The GM always has the tool. A table may declare `players_roll: true` (as decks have `players_draw`), which gives players the tool too. Entries stay text, and the result is narrated. Mechanical consequences already have consequence tables (§2.6), so a lookup table carries no effects.
2. **An effect primitive `roll_table`,** so a pack outcome can roll a table. This changes §2.6's closed set of seventeen primitives, and since entries are text the effect would change nothing mechanical. Not recommended now; it can be added if a pack needs an outcome to roll a table.

**⚑ Decide:** option 1. Also decide whether players may ever roll (recommended: only where the pack sets `players_roll`).

**Proposed §2.3 text** (`randomizers` block):
```
    tables:  [{ id, roll, entries: [{ range, text }], players_roll }]   # rolled in play by roll_table (§7.1), or by a chargen table step
```
**Proposed §7.1 text** (GM-only block): `roll_table(table_id) → a seeded roll on a pack lookup table; the entry is narrated`. Table row: `| roll_table | ✓ ‡ | ✓ | — |`, with `‡ only for tables the pack marks players_roll`.

**Build:**
- `table_rolled` gains `by` and `purpose: play` when it comes from `roll_table`. The field is optional, so chargen events read the same.
- `roll_table` is `@atomic`, and `@gm_call` for the GM. The roll is the event's cause.
- Lint: `players_roll` is a boolean.
- The smoke harness rolls `core`'s detail table once per scene.

---

## B. Props

**Problem:** §5.2 promotes "the frayed rope bridge" to a game object through `spawn_entity`, and §8.2 calls such objects props. Today every spawn is an NPC on the GM's side:
- a bridge joins every encounter by default and is given turns;
- it counts as a GM-side roller under `gm_rolls: false`;
- §8.2's `interactable` has no counterpart.

**Options:**
1. **(Recommended) An entity `kind`: `npc` (default) or `prop`.** A prop:
   - is never a default encounter participant. `join_encounter` can still add one that acts, such as an animated statue.
   - never rolls: an opposed check against a prop is refused, with "use a derived difficulty".
   - takes `interactable: false` to refuse being an action's target, for scenery.

   It keeps everything else an entity has: resources, tracks, conditions, and tags. A bridge can be damaged, and its state ("frayed", "cut") is pack tags.
2. **A separate prop store outside `entities`.** Then actions and effects cannot target a prop without a second targeting path, which defeats §5.2's point that the prop becomes checkable state.

**⚑ Decide:** option 1, including that a prop's state is pack tags rather than a free `state` string. A free string is unvalidated text, and strict settings need ids.

**Proposed §8.2 text:** keep `props[]` in the scene schema, and add under it: "A prop is an entity of kind `prop` (§2.3): it can be targeted, damaged, and tagged like any entity, but it never takes a turn unless the GM joins it to an encounter, and it never rolls. `state` is its pack tags; `interactable: false` makes it scenery no action can target."
**Proposed §7.1 text:** `spawn_entity(spec) → instantiate fiction into state; spec.kind: npc | prop`.

**Build:**
- `entity_spawned`'s entity carries `kind: prop` and, when false, `interactable`. Older entities are all `npc`, so nothing re-folds.
- `start_encounter`'s default roster skips props.
- `_roll_refusal` treats a prop as a non-roller.
- Action targeting refuses a non-interactable prop.
- The smoke harness spawns a prop and targets it once.

---

## C. Entity templates (richer spawns)

**Problem:** `spawn_entity` takes stats and a position only, and the GM's tool takes neither: it is `{entity_id, name}`, so every NPC the GM spawns in play has default stats. A prepped stat block cannot carry tags (undead), starting items, conditions, or a wounded start. §1.3.2 says prepped mechanics go "through the system pack's entity schema, never written as prose". Under strict GM settings, a free stats mapping in the tool would also break the structural rule (§2.13.4).

**Options:**
1. **(Recommended) Pack-declared templates, plus a full spec for the engine command.**
   - `entity_model.templates: [{id, label, kind, stats, resources, tags, items, conditions}]`, validated by lint against the entity model, like chargen options.
   - **Strict-safe:** the GM's `spawn_entity` tool offers `template` as an enum, so under both presets the GM picks a template by id, and no free number crosses.
   - **Full spec:** the engine command also accepts the fields directly (`stats`, `resources`, `tags`, `items`, `conditions`, `kind`), each checked against the pack. This is for prep (P3, written by the prep pass and validated there) and for scripted harnesses. It is never a model tool argument.
   - Spawn fields given beside a template override it.
2. **Free spec fields in the GM tool under standard settings.** This gives the GM the most range, but stat blocks become model-supplied numbers in play, which §1.3.2 exists to prevent. Not recommended.

**⚑ Decide:** option 1, and whether a campaign's prep may add its own templates in P3. Recommended: yes, as canon-linked stat blocks validated by the same lint, decided when P3.5 is built.

**Proposed §2.3 text** (`entity_model`): `templates: [{ id, label, kind, stats, resources, tags, items, conditions }]   # stat blocks the GM spawns by id (§7.1)`.
**Proposed §7.1 text:** `spawn_entity(spec) → instantiate fiction into state from a pack template (by id) and a name; kind npc | prop`.

**Build:**
- Lint per template:
  - stats are in range;
  - resources sit within min and max;
  - tags, items, and conditions exist;
  - under the weight model, the kit fits the carry limit.
- The spawned entity carries the result, so `entity_spawned` is unchanged in shape.
- Lanternlight and Tidewrack each gain one or two templates, which changes their hashes. Golden fixtures are regenerated deliberately.

---

## D. `get_tactical_view`

**Problem:** §7.1 lists `get_tactical_view()` (absent under `spatial: none`), and §8.2 says per-observer visibility makes it correct. No engine view or tool exists. `look` returns the scene, and the enumeration tools return ranked options without the board they rank.

**Options:**
1. **(Recommended) Build it as a composition of existing reads.** One call returns, for the caller's seat and only what it can see:
   - each visible entity's position;
   - range or steps from the caller's entity;
   - cover and terrain where it stands;
   - the caller's reachable positions;
   - `current_turn(seat)`.

   It is encounter-only and absent under `spatial: none`. It writes nothing and needs no new event.
2. **Fold it into `look` and remove it from §7.1.** This is less to maintain, but `look` is for every scene, and the enumeration tools need a compact board to be read against.

**⚑ Decide:** option 1.

**Proposed §7.1 text:** `get_tactical_view() → positions, ranges, and cover of what you can see, your reach, and whose turn it is`.

**Build:**
- `tactical_view(seat)` in `kernel/tactics.py` and the tool. Both are generated only where a spatial backend is declared.
- Tests that a hidden entity is absent from it, as in the T0.37 leak sweep.

---

## E. Time-advance limits as pack data

**Problem:** T0.39 made clock limits pack data, but `advance_time` still accepts 1 to 1000 of any unit, while its GM tool offers 1 to 12. One range across units is also odd: twelve watches and twelve moons are very different jumps.

**Options:**
1. **(Recommended) Per unit:** `time.units[].advance: [min, max]`, with the kernel default `[1, 12]`. It is read by `advance_time` and its tool, and linted like `clocks`. The engine's ceiling therefore drops from 1000 to the unit's max. No shipped campaign or test advances more than 12, which the build must confirm.
2. **One `time.advance` range for all units:** simpler, but it has the mismatch above.

**⚑ Decide:** option 1, and the default `[1, 12]`.

**Proposed §2.3 text:** `units: [{ id, label, per, advance }]   # smallest first; advance: [min, max] per GM call (default [1, 12])`.

---

## F. Revealing the master seed

**Problem:** §5.5 publishes the master seed and the resolved pack after the campaign concludes. The commitment is logged and `tob verify --seed` re-derives every roll. But nothing marks a campaign as concluded, refuses play after that, or records the seed where the log itself can be verified. BUILD_PLAN P5.7 already plans "master-seed and resolved-pack publication at campaign end", so this is the kernel half of a planned item, not a new feature.

**Options:**
1. **(Recommended) Kernel event now, publishing later.**
   - **P0:** `conclude_campaign(seed)` (operator only) checks the seed against the commitment and logs `campaign_concluded {seed}`.
   - **After it:** every command is refused, and a fork can be taken only at a seq before it.
   - **Verify:** `tob verify` uses a logged seed automatically.
   - **P5.7:** the publishing pipeline: exporting the log, the seed, and the resolved pack, and where they go.
2. **All of it in P5.7.** This needs no P0 change, but the kernel has no concluded state until then, and a published log cannot verify itself.

**⚑ Decide:** option 1. Also decide whether `conclude_campaign` needs an open session to be ended first (recommended: yes).

**Proposed §5.5 text** (after the publication policy): "The operator ends a campaign with `conclude_campaign`, which checks the seed against the commitment in the first event and logs it as `campaign_concluded`. Nothing can be played after it, and the log then verifies itself."
**Proposed §5.7 text** (system events): `campaign_started, campaign_concluded, campaign_forked`.

---

## G. Point-buy chargen

**Problem:** §1.5 says choices like "spending points" are `choice` steps, but a `choice` picks one listed option, and enumerating every allocation of a point pool is impossible. Point-buy systems cannot be expressed.

**Options:**
1. **(Recommended) A `points` step kind.**
   - **Shape:** `{id, kind: points, targets, pool, range: [min, max], cost}`.
   - **`cost`:** a cost per point (default 1), or a table `{value: cost}` for rising costs. *As built (D-059): a list of costs, one per value from the range's low end up, since the canonical pack hash takes only string keys.*
   - **The agent's choice:** it supplies `{stat: value}` for every target.
   - **Checks:** each value is in range, and the total cost equals `pool`. `exact: false` allows spending less.
   - **Logging:** the allocation is a `judgement_input`.
   - **Strict-safe:** like `assign`, every value is chosen from a bounded, enumerable range per stat, and the tool schema carries each stat's range as an enum.
2. **Packages as `choice` options** (the pack lists a few builds). This works today but removes the freedom point-buy exists for.

**⚑ Decide:** option 1, and whether the cost table is enough without a hook. Recommended: yes; anything stranger is the `chargen.step` hook point (§2.7).

**Proposed §1.5 text:** "…picking a playbook is a `choice` step, spending points a `points` step; the engine enumerates or bounds the legal options and the agent picks…"
**Proposed §2.3 text:** `chargen: { steps: [{ id, kind: roll | choice | assign | table | points, targets, roll, options, values, table, pool, range, cost, exact, unique_per_table }] }`.

**Build:**
- Chargen runner and lint:
  - the pool is reachable within the ranges;
  - the cost table covers the range.
- `tob pack new` and conformance's 1,000-chargen property test handle the new kind.
- `lanternlight_house` gains a `points` step instead of, or beside, its `assign` step. Its hash and golden fixture change.

---

## H. Lighting per region

**Problem:** §8.2 gives each region a lighting level, and §2.13.1's example derivable tag is "dim light from scene lighting". The kernel has only scene-wide flags (`scene.dim`), so a lit doorway and a dark corner of one scene cannot differ, and a rule cannot read the light where an actor stands.

**Options:**
1. **(Recommended) Lighting as a region value, like terrain and cover.**
   - **Pack:** declares `spatial.lighting: [{id, label}]` (for example bright, dim, dark).
   - **Regions:** `set_scene` sets `lighting` per region.
   - **Rules:** read `actor.region.lighting.<id>` and `target.region.lighting.<id>`, so a tag can derive from it.
   - **Scenes without regions:** keep scene flags.
   - **Light sources:** §8.2's `source_id` is presentation (P4) and stays out of the kernel.
   - **Mid-scene changes** (a torch goes out) are a later GM command, if a pack needs one. The next scene can always relight.
2. **Leave lighting to P4's renderer.** The overlay would show light that rules cannot read, so narration and mechanics could disagree, which §8.3 forbids.

**⚑ Decide:** option 1, and whether a mid-scene `set_lighting` belongs in P0. Recommended: not yet.

**Proposed §2.3 text** (`spatial`): `terrain: [{ id }], cover: [{ id }], lighting: [{ id }]   # region values (zone_graph)`.
**Proposed §2.13.1 text:** unchanged ("dim light from scene lighting" then holds per region).

**Build:**
- The region field is written only when a scene sets it, so older scene payloads fold unchanged.
- Lint and tool enum as for terrain.
- Lanternlight's `dim_light` tag derives from the region where a region says, and from the scene flag otherwise. That changes its hash and golden fixture.

---

## I. Suggested build split

All eight fit one task. If smaller commits are preferred:

| Task | Gaps | Why together |
|---|---|---|
| T0.40 | A, E, F | Randomizer and time: no pack hash changes |
| T0.41 | B, C, D | Entities and the tactical surface: templates change both demo packs |
| T0.42 | G, H | Chargen and spatial values: `lanternlight` and `lanternlight_house` change |

Each task ends with `tob check`, regenerated golden fixtures where a pack changed (explained in the commit), DECISIONS entries, and EVENTS rows for `campaign_concluded` and the optional fields.

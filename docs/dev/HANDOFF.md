# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-18)

- **P0:** every build step P0.1 to P0.14 is done. The exceptions are calendar tracking in P0.11 (no task; rounds are in the turn controller) and the hook sandbox (T0.12, deferred by design: no pack uses hooks, and the loader refuses them). **Track 0 is complete apart from T0.13, the Gate P0 sign-off, which needs the owner.** See `ROADMAP.md`.
- **Design:** ARCHITECTURE 1.5 and BUILD_PLAN 1.4. The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (T0.13 preparation)

- New `tests/test_gate_p0.py` (19 tests) closes the Gate P0 items that the existing tests covered only partly:
  - fork at every seq, with diverging branches
  - 10,000-roll chi-square tests of every rolled expression against its exact distribution
  - an all-strict `judgement_input` audit on every playable pack
  - excluded terms across a scripted campaign
  - a refused replay under another kernel version
- The harness gained a `write_canon` scenario step.
- Evidence for every gate item is below. T0.13 stays `human` until you sign off.
- Earlier this session: T0.3 to T0.16 and T0.10 (D-016 to D-027), the engine split, and twelve pushes.

## Gate P0 evidence (T0.13, for the owner's sign-off)

Prepared 2026-10-18 at the commit that adds `tests/test_gate_p0.py`. Every item below was run on the development desktop:

- `tob check`: **GATE: PASS** in about 20 s. It runs the noun lint, pack lint for 8 packs, verified smoke campaigns on the 5 playable packs, and pytest with **308 tests passed**.
- `tob pack lint`: 0 errors and 0 warnings on every pack.

"Both packs" means the two kernel test games from different families, `lanternlight` (roll-over) and `tidewrack` (banded) (BUILD_PLAN P0.6). The three data-only derivatives are also run.

| # | Gate item | Status | Evidence |
|---|---|---|---|
| 1 | Full campaign replay is byte-identical from the event log, on both packs | ✅ | `tob check` "scripted campaigns" (replay, snapshot + tail, seed re-derivation, byte-identical second run) on all 5 playable packs; `tests/test_harness.py::test_smoke_campaigns_all_packs`; `tests/test_golden.py` pins the log head of each pack's seeded runs |
| 2 | Fork at any `seq` produces correct divergent branches | ✅ | `tests/test_gate_p0.py::test_fork_at_every_seq_gives_a_correct_divergent_branch` (both packs). Forks at **every** seq; each fork's chain verifies and folds to the source's state at that seq. Two forks then play on differently, both verify with the seed, and the source is untouched. Store level: `tests/test_events.py::test_fork_and_snapshot` |
| 3 | 10k-roll distribution passes for every operator and die type in use | ✅ | `tests/test_gate_p0.py::test_10k_rolls_match_the_exact_distribution`. 10,000 seeded rolls of **every rolled expression in every playable pack**, plus keep-high, keep-low, fate, and count, are chi-square tested against the exact distribution (`dice.distribution`). `tests/test_rng_dice.py::test_distribution_10k` covers d4 to d100. Exploding dice have no exact distribution; the termination test covers them. No shipped pack uses explode. |
| 4 | Zero `secret` leakage across 1,000 player-scoped canon queries | ✅ | `tests/test_canon.py::test_player_scope_never_sees_secrets` (200 records, 1,000 queries); also `test_secret_successor_hides_correction_from_players`, and `tests/test_clocks.py::test_secret_stages_with_discovery_paths` |
| 5 | Zero illegal moves across 10,000 enumerated candidates, per backend | ✅ | `tests/test_tactics.py::test_ten_thousand_enumerations_are_all_legal[zone_graph]` and `[range_bands]`. 10,000+ enumerations each; every move passes the backend's own `check_move`, and every action candidate is legal; `test_enumerated_actions_are_accepted_by_the_engine` commits every candidate for real on both packs |
| 6 | Mastery tiers produce measurably different option sets on identical tactical states | ✅ | `tests/test_tactics.py::test_lower_tiers_are_strict_information_subsets` (prefix lists, annotation subsets, strictly more information low → mid → high); `test_candidate_cap_holds` (4–5 / 7–8 / 10–12 options) |
| 7 | Scripted 3-session campaign completes on each pack with no LLM involvement | ✅ | `tob check` (3 sessions per pack, every action covered, zero network); `tests/test_harness.py::test_smoke_campaigns_all_packs` |
| 8 | **The second pack runs with zero kernel code changes made for it** | ⚠️ owner's call | **Structural evidence only.** `tidewrack` was written alongside the kernel before this repository had history, so no commit can show "no change was made for it." What can be shown: the kernel contains no pack's catalogue ids (noun lint, which checks every pack on disk, is clean); both families run on one kernel build; `tidewrack` switched backends (zone to RangeBands, T0.5) as pack data; and the later data-only derivative `lanternlight_sectioned` landed in commit `5b0400a` with **zero `src/basilisk/kernel` changes** (`git show --stat 5b0400a`). |
| 9 | Kernel noun lint is clean | ✅ | `tob check`: "kernel noun lint: clean"; `tests/test_harness.py::test_kernel_noun_lint_clean`, plus the pollution-detection test |
| 10 | Every hook in every shipped pack passes the determinism contract | ✅ (vacuous) | No pack declares a hook (`hooks: []` in `core`, inherited by all). The loader refuses any unregistered hook (`tests/test_packs.py::test_unregistered_hook_refused`, D-006). The sandbox itself (T0.12) is deferred until a pack needs one. |
| 11 | Replay against a mismatched pack hash or kernel version is refused | ✅ | Pack hash and seed: `tests/test_engine.py::test_pinning_refuses_mismatch`. Kernel version: `tests/test_gate_p0.py::test_replay_against_another_kernel_version_is_refused` (added for this sign-off; the earlier test checked only the pack hash and seed) |
| 12 | A derived house-rules pack is built as data only and passes conformance | ✅ | `packs/lanternlight_house` (changed resource, new condition, removed action, overridden tactical factor); `tests/test_packs.py::test_house_rules_merge`; pack lint clean; it plays in `tob check` |
| 13 | Both shipped packs are strict-ready on every control and carry rule-card data for everything | ✅ | `tob pack lint`: `strict-ready: … all yes` for `lanternlight` and `tidewrack` (and all derivatives). The rule-card lint class fails any action, procedure, condition, currency, or tag without a card (`tests/test_packs.py::test_linter_catches_each_defect_class`) |
| 14 | Under strict, zero model-supplied numbers reach resolution: enforced by schema, confirmed by auditing `judgement_input` | ✅ | Schema: `tests/test_packs.py::test_strict_schemas_have_no_free_values`, and the same assertion for every new tool in the T0.3 to T0.16 tests. Audit: `tests/test_gate_p0.py::test_strict_roles_supply_no_numbers_audited_from_judgement_input`, an all-strict campaign on every playable pack in which every strict `judgement_input` choice is one of its logged options, no free modifier is used, and no `gm-value` difficulty reaches `procedure_resolved` |
| 15 | Mid-campaign settings changes apply only at scene boundaries and replay byte-identically | ✅ | `tests/test_engine.py::test_settings_change_applies_only_at_scene_boundary`, `test_cooldown`, `test_open_ruling_keeps_its_starting_mode`; the smoke campaigns make 2 mid-campaign changes and replay byte-identically |
| 16 | Inline and sectioned rules text both pass conformance; the sectioned variant runs with zero kernel changes | ✅ | `tests/test_sectioned_pack.py` (only `rules_text` differs; lint clean; its campaign matches `lanternlight` event for event apart from pack identity and rule-lookup answers); commit `5b0400a` touched no kernel file |
| 17 | `query_rules` resolves 100% of section ids, aliases, and catalogue refs in every shipped pack | ✅ | `tests/test_sectioned_pack.py::test_every_section_is_reachable_by_id_and_alias`, plus the coverage lint (every action, procedure, and condition is in some section's refs). Only `lanternlight_sectioned` declares sections; inline packs have none to resolve. |
| 18 | Zero canon records containing an excluded term are accepted, across scripted campaigns on a pack that declares them | ✅ | `tests/test_gate_p0.py::test_no_excluded_term_reaches_canon_in_a_scripted_campaign` (a 3-session campaign on `tidewrack_excluded` with injected write attempts: 3 refused, and no stored record contains a term); `tests/test_terms.py` (every canon path) |

**Not gate items, but open in P0:** calendar and watch tracking (P0.11, no task) and the hook sandbox (T0.12, deferred).

**To sign off:** check items 8 and 10, which rest on your judgement rather than a test. Then tick Gate P0 in `docs/BUILD_PLAN.md` (a design-doc edit, so it needs your approval) and set T0.13 to `done`. Track 1 starts after that (D-014).

## Next step

- **Track 0:** only T0.13 (Gate P0 sign-off, `human`) remains. The agent prepares evidence for every Gate P0 item (BUILD_PLAN, Gate P0) as the commands run and their results; the owner signs off. Track 1 starts after that (D-014).
- Suggested next: the owner reviews the evidence above and signs off Gate P0. After that comes Track 1, starting with T1.1 (schema validator), then T1.3 (mock adapter) and T1.4 (recording transport), then T1.5 (Anthropic adapter, D-013).
- Keep everything system-agnostic: develop against `lanternlight`, `tidewrack`, and the baselines only.

## Open questions for the owner

None blocking. Before P4.0: the SRD source document. Before launch: the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- The engine is split along § boundaries. `engine.py` holds the reducer, lifecycle, entities, and actions (about 580 lines). Mixins: `resolution.py` (§2.5 procedures, `resolve_unmodelled`), `effects.py` (§2.6 primitive registry, effect application, ruling slots), `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, `fudging.py`, `sheets.py`, `clocks.py`, `rules.py`, `terms.py`, and the pure `conformance.py`. Add new command groups as mixins too.
- The pre-commit hook needs `tob` on PATH, so activate the venv first.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel comments are noun-linted too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared" (`tools/kernel_nouns.txt` plus every pack's catalogue ids).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

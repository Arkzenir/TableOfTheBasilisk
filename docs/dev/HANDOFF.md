# Handoff

Rewritten at the end of every work session, so the next session — any agent or human — can start cold.

## Current state (2026-10-27)

- **Phase 0 is closed. Gate P0 was signed off by the owner on 2026-10-26** (T0.13, D-042). Every build step P0.1 to P0.15 is done, and every gate item is ticked here and in BUILD_PLAN. A second audit of Phase 0 (2026-10-27) found gaps: T0.31 fixed them, and T0.32 built the owner-approved GM pool and applied ARCHITECTURE 1.7. **Track 1 is next.** See `ROADMAP.md`.
- **Design:** ARCHITECTURE 1.7 (§2.3 and §5.7 as built; 1.7 corrected the `gm` block) and BUILD_PLAN 1.6 (Gate P0 signed off). The broadcast pack is the SRD 5.1 under CC-BY 4.0, written last (P4.0). Track 0 is finished before Track 1. Anthropic is the first provider. See D-012 to D-015.
- **Git:** `main` tracks `origin/main` (github.com/Arkzenir/TableOfTheBasilisk). Hooks are installed: pre-commit runs `tob check --quick`, pre-push runs the full gate.

## What changed this session (owner decisions on the 1.6 draft, sign-off, two audits)

- **T0.32** (D-047): `holder: gm` is one pool on the GM's side, fed from anyone's effect with `target: gm`; currencies take a `visible` flag; `lethality_levers` is a reserved warning. ARCHITECTURE 1.7 applied (REV-ARCH-1.7 approved as proposed).
- **T0.31** (D-046), from the second audit:
  - `gm_rolls: false` is enforced: no GM-side entity rolls (Tidewrack's NPCs could).
  - `holder: party` is one shared pool, and an unknown holder fails lint.
  - The loader refuses an id declared twice in one pack file; the merge used to fold it unseen.
  - Every lint class now has a defect test, as does removing a condition an inherited action uses.
  - The verifier checks the kernel pin and snapshot pins.
  - `tob pack lint` prints rules-text size against its budget.

- **T0.30** (D-044): every GM call is logged as a `judgement_input` (`@gm_call`), with a test that every GM tool is covered. **D-045:** `KERNEL_VERSION` stays `0.1.0` until every Phase 0 audit returns complete.

- **T0.29** (D-043): fixes from the audit after sign-off: rangeless stats no longer crash progression, advance lint, a private `progress` field on the own sheet, wider `sheet_problems`, UTF-8 CLI output on Windows, and cached, libyaml-backed pack parsing (gate about 30 s).

- **Sign-off** (D-042): the owner ticked every Gate P0 item and approved the 1.6 draft. Gate P0 is ticked in BUILD_PLAN, ARCHITECTURE 1.6 is applied, and T0.13 is done.

- **T0.28** (D-037): harm is a declaration of targets only (`entity_model.harm.targets`), read through `harm_state(entity)`. Tidewrack's track was renamed `strain` (label still "Harm").
- **T0.24** (D-038): the `scene_closed` marker, after the events that close a scene.
- **T0.25** (D-039): condition stacking by intensity (`stacking: intensity`, `max_level`); modifiers scale with the level.
- **T0.26** (D-040): weight inventory (`inventory: {model: weight, limit_expr}`, `entity_model.items`); no slots.
- **T0.27** (D-041): progression (`kernel/progression.py`): `xp`, `marks`, `milestone`, and `use`; new events `progress_awarded` and `advance_taken`; `advance_options`, `take_advance` (a logged `judgement_input`), `award_milestone`; tools `take_advance` and `award_milestone`. Lanternlight uses XP and Tidewrack marks, and the smoke harness takes every advance due, so every gated campaign progresses.
- **The 1.6 draft** (`docs/dev/proposals/REV-ARCH-1.6.md`) was revised to match the build, then applied.
- Golden fixtures were regenerated deliberately for T0.24, T0.26, T0.27, and T0.28.

## Gate P0 evidence (T0.13, signed off 2026-10-26)

Refreshed 2026-10-26 after T0.24 to T0.28. Every item below was run on the development desktop:

- `tob check`: **GATE: PASS** in about 30 s (budget 60 s). It runs the noun lint, pack lint for 9 packs, verified smoke campaigns on the 6 playable packs, and pytest with **542 tests passed** (after T0.32).
- `tob pack lint`: 0 errors and 0 warnings on every pack, every pack strict-ready on every control. Hook counts: 2 in `lanternlight_hooked`, 0 elsewhere. Rules text (P0.6): Lanternlight inline ~167 of 30,000 tokens, Tidewrack ~103, the sectioned variant's digest ~69 of 6,000 with 12 sections.

"Both packs" means the two kernel test games from different families, `lanternlight` (roll-over) and `tidewrack` (banded) (BUILD_PLAN P0.6). The four derivatives are also run.

| # | Gate item | Status | Evidence |
|---|---|---|---|
| 1 | Full campaign replay is byte-identical from the event log, on both packs | ✅ | `tob check` scripted campaigns (replay, snapshot + tail, seed re-derivation, byte-identical second run) on all 6 playable packs; `tests/test_phase0_gaps.py::test_three_session_campaign_under_every_preset` (18 runs); `tests/test_golden.py` |
| 2 | Fork at any `seq` produces correct divergent branches | ✅ | `tests/test_gate_p0.py::test_fork_at_every_seq_gives_a_correct_divergent_branch` (every seq, both packs) |
| 3 | 10k-roll distribution passes for every operator and die type in use | ✅ | `tests/test_gate_p0.py::test_10k_rolls_match_the_exact_distribution` (every rolled expression in every playable pack, plus every grammar operator); step dice in `tests/test_step_dice.py`; `tests/test_rng_dice.py::test_distribution_10k` (d4 to d100) |
| 4 | Zero `secret` leakage across 1,000 player-scoped canon queries | ✅ | `tests/test_canon.py::test_player_scope_never_sees_secrets` |
| 5 | Zero illegal moves across 10,000 enumerated candidates, per backend | ✅ | `tests/test_tactics.py::test_ten_thousand_enumerations_are_all_legal[zone_graph]` and `[range_bands]`; `test_enumerated_actions_are_accepted_by_the_engine` |
| 6 | Mastery tiers produce measurably different option sets on identical tactical states | ✅ | `tests/test_tactics.py::test_lower_tiers_are_strict_information_subsets`, `test_candidate_cap_holds` |
| 7 | Scripted 3-session campaign completes on each pack with no LLM involvement | ✅ | `tob check`; `tests/test_phase0_gaps.py` (every pack, every preset) |
| 8 | **The second pack runs with zero kernel code changes made for it** | ✅ | **Structural evidence only.** `tidewrack` was written alongside the kernel before the repository had history. What can be shown: no pack's ids are in the kernel (noun lint over every pack); both families run on one kernel build; `tidewrack` switched backends as pack data (T0.5); and the data-only derivative `lanternlight_sectioned` landed in `5b0400a` with zero `src/basilisk/kernel` changes (`git show --stat 5b0400a`) |
| 9 | Kernel noun lint is clean | ✅ | `tob check`; `tests/test_harness.py::test_kernel_noun_lint_clean` and the pollution test |
| 10 | Every hook in every shipped pack passes the determinism contract | ✅ | **Now a real test:** `tests/test_gate_p0.py::test_every_shipped_hook_passes_the_contract` (static check at load, every call run twice and agreeing, seed re-derivation of hook draws); `tests/test_hooks.py` (22 tests, including a clock read, I/O, private randomness, and runaway loops all refused) |
| 11 | Replay against a mismatched pack hash or kernel version is refused | ✅ | `tests/test_engine.py::test_pinning_refuses_mismatch`; `tests/test_gate_p0.py::test_replay_against_another_kernel_version_is_refused` |
| 12 | A derived house-rules pack is built as data only and passes conformance | ✅ | `packs/lanternlight_house` (changed resource, new condition, removed action, a standard stat array via `assign`); `tests/test_packs.py::test_house_rules_merge` |
| 13 | Both shipped packs are strict-ready on every control and carry rule-card data for everything | ✅ | `tob pack lint` strict-ready lines; the rule-card lint class (`tests/test_packs.py::test_linter_catches_each_defect_class`) |
| 14 | Under strict, zero model-supplied numbers reach resolution (schema, plus a `judgement_input` audit) | ✅ | `tests/test_packs.py::test_strict_schemas_have_no_free_values`; `tests/test_gate_p0.py::test_strict_roles_supply_no_numbers_audited_from_judgement_input` |
| 15 | Mid-campaign settings changes apply only at scene boundaries and replay byte-identically | ✅ | `tests/test_engine.py::test_settings_change_applies_only_at_scene_boundary`, `test_cooldown`, `test_open_ruling_keeps_its_starting_mode`; every-preset campaigns |
| 16 | Inline and sectioned rules text both pass conformance; the sectioned variant needs zero kernel changes | ✅ | `tests/test_sectioned_pack.py`; commit `5b0400a` |
| 17 | `query_rules` resolves 100% of section ids, aliases, and catalogue refs in every shipped pack | ✅ | `tests/test_sectioned_pack.py::test_every_section_is_reachable_by_id_and_alias` plus the coverage lint (only `lanternlight_sectioned` declares sections) |
| 18 | Zero canon records containing an excluded term are accepted, across scripted campaigns on a pack that declares them | ✅ | `tests/test_gate_p0.py::test_no_excluded_term_reaches_canon_in_a_scripted_campaign`; `tests/test_terms.py` |
| 19 | Every progression model awards and advances through a scripted campaign, only by options the pack offers, and replays byte-identically | ✅ | `tests/test_progression.py::test_a_scripted_campaign_advances_and_replays` (xp on `lanternlight`, marks on `tidewrack`) and `test_milestone_and_use_campaigns_advance_and_replay`, each verified and run twice; `test_no_advance_the_pack_does_not_offer`, `test_once_advances_are_taken_once`; every gated smoke campaign now takes advances |

## Next step

- **Track 1** (D-014): T1.1 (schema validator), T1.3 (mock adapter) and T1.4 (recording transport), then T1.5, the Anthropic adapter (D-013). T1.5's live tests need the owner's API key and approval before any paid call.

## Open questions for the owner

1. **D-045:** whether the second Phase 0 audit now counts as complete (its items 1 to 9 are fixed by T0.31 and T0.32; item 10, BUILD_PLAN §0.4's pre-build checklist, is the owner's).
2. **Re-audit when the P0 architecture is finalised:** Gate item 8 (structural evidence only) and the hook return shape (D-033: point-specific results rather than `[events]`).
3. **When `KERNEL_VERSION` moves:** decided to wait (D-045). It stays `0.1.0` until every Phase 0 audit returns complete; then the owner sets the bump and the policy.
4. Before T1.5's live tests, the Anthropic API key, set as an environment variable.
5. Before P4.0, the SRD source document. Before launch, the legal review in ARCHITECTURE §11.3.

## Notes for the next session

- Engine mixins: `resolution.py`, `effects.py`, `canon.py`, `spatial.py`, `tactics.py`, `turns.py`, `decks.py`, `fudging.py`, `sheets.py`, `clocks.py`, `timekeeping.py`, `rules.py`, `terms.py`, `progression.py`. Also the pure `conformance.py` and the hook runtime `hooks.py`. Add new command groups as mixins.
- Golden fixtures change whenever a pack or kernel behaviour changes. Regenerate deliberately with `TOB_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py` and say why in the commit.
- The pre-commit hook runs `tob check --quick`, which skips pytest. Run the full `tob check` (or let pre-push run it) before trusting a change.
- When writing files with Python on Windows, pass `newline` set to LF, or write bytes. Text mode writes CRLF.
- Kernel source is noun-linted, comments too. Avoid words that are pack catalogue ids, such as "down", "rest", "recall", "might", "guard", "hope", and "prepared".
- In pack YAML, never use a bare `on:` key: YAML 1.1 reads it as the boolean true (hence `when:` in progression awards).
- A local venv exists at `.venv/` (Python 3.14); activate it with `.venv\Scripts\activate`.

import shutil

import pytest
import yaml

from basilisk.kernel.determinism import expand
from basilisk.kernel.packlint import errors, lint, readiness
from basilisk.kernel.packs import PackError, resolve, scaffold
from basilisk.kernel.tools import free_values, generate


def test_resolution_and_hash_stability(packs_dir):
    a, b = resolve("lanternlight", packs_dir), resolve("lanternlight", packs_dir)
    assert a.hash == b.hash
    assert a.lineage == ["core@0.1.0", "core.roll_over@0.1.0", "lanternlight@0.1.0"]
    assert "check" in a.by_id("resolution.procedures") and "automatic" in a.by_id("resolution.procedures")


def test_house_rules_merge(packs_dir):
    house = resolve("lanternlight_house", packs_dir)
    assert house.by_id("entity_model.resources")["vigor"]["max"] == "10 + might * 2"
    assert house.by_id("entity_model.resources")["vigor"]["on_zero"]  # deep-merged, not replaced
    assert "inspire" not in house.by_id("actions")
    assert "inspired" in house.by_id("entity_model.conditions")
    assert len(house.data["meta"]["attributions"]) == 2
    assert errors(lint(house)) == []


def test_all_shipped_packs_lint_clean(packs_dir):
    for pid in ("core", "core.roll_over", "core.banded", "lanternlight", "tidewrack", "lanternlight_house",
                "lanternlight_sectioned", "tidewrack_excluded", "lanternlight_hooked", "lanternlight_pointbuy"):
        assert errors(lint(resolve(pid, packs_dir))) == [], pid


def _copy(packs_dir, tmp_path):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    return dst


def _edit(path, fn):
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


DEFECTS = {
    "reference": lambda d: d["actions"][0].__setitem__("procedure", "nope"),
    "condition-exit": lambda d: d["entity_model"]["conditions"].append({"id": "stuck", "modifier": -1, "duration": "until_removed"}),
    "roll": lambda d: d["actions"][0]["outcome_effects"]["pass"][0].__setitem__("amount", "-1d6!"),
    "rule-card": lambda d: d["presentation"]["rule_cards"].pop("strike"),
    "table-coverage": lambda d: d.setdefault("randomizers", {}).__setitem__("tables", [{"id": "detail_table", "entries": [{"range": [1, 3], "text": "x"}]}]),
    "effect": lambda d: d["actions"][0]["outcome_effects"]["pass"].append({"primitive": "teleport", "target": "actor"}),
}


@pytest.mark.parametrize("code", sorted(DEFECTS))
def test_linter_catches_each_defect_class(packs_dir, tmp_path, code):
    pd = _copy(packs_dir, tmp_path)
    _edit(pd / "lanternlight" / "pack.yaml", DEFECTS[code])
    found = {f.code for f in errors(lint(resolve("lanternlight", pd)))}
    assert code in found, found


def test_unregistered_hook_refused(packs_dir, tmp_path):
    pd = _copy(packs_dir, tmp_path)
    _edit(pd / "tidewrack" / "pack.yaml", lambda d: d.__setitem__("hooks", [{"point": "dice.operator", "name": "custom"}]))
    with pytest.raises(PackError, match="unregistered hook"):
        resolve("tidewrack", pd)


def test_remove_requires_known_ids(packs_dir, tmp_path):
    pd = _copy(packs_dir, tmp_path)
    _edit(pd / "lanternlight_house" / "pack.yaml", lambda d: d.__setitem__("remove", {"actions": ["missing"]}))
    with pytest.raises(PackError):
        resolve("lanternlight_house", pd)


def test_scaffold_resolves_as_its_baseline(packs_dir, tmp_path):
    pd = _copy(packs_dir, tmp_path)
    scaffold("mygame", "lanternlight", pd)
    mine, base = resolve("mygame", pd), resolve("lanternlight", pd)
    assert mine.by_id("actions") == base.by_id("actions")
    assert errors(lint(mine)) == []


def test_abstract_pack_not_playable(packs_dir):
    with pytest.raises(PackError):
        resolve("core", packs_dir, allow_abstract=False)


def test_strict_schemas_have_no_free_values(lantern, tide):
    strict = expand({"players": {"preset": "strict"}, "gm": {"preset": "strict"}})
    standard = expand({"players": {"preset": "standard"}, "gm": {"preset": "standard"}})
    for pack in (lantern, tide):
        for role in ("players", "gm"):
            assert free_values(generate(pack, strict, role)) == [], (pack.id, role)
    assert free_values(generate(lantern, standard, "gm"))  # standard allows bounded values


def test_capability_absence(lantern, tide):
    gm_std = expand({"gm": {"preset": "standard"}})
    gm_strict = expand({"gm": {"preset": "strict"}})
    assert "peek_roll" in generate(lantern, gm_std, "gm")
    assert "peek_roll" not in generate(lantern, gm_strict, "gm")      # fudging off under strict
    assert "peek_roll" not in generate(tide, gm_std, "gm")            # GM never rolls in this pack
    assert "fill_ruling" in generate(tide, gm_std, "gm")
    assert "fill_ruling" not in generate(tide, gm_strict, "gm")       # engine draws instead
    assert "rule_on_action" not in generate(lantern, gm_std, "players")
    assert all(readiness(lantern).values()) and all(readiness(tide).values())


# ---------------------------------------------------------------- every lint class (P0.7; T0.31)

def _assign(**step):
    return lambda d: d["chargen"]["steps"].append({"id": "array", "kind": "assign", **step})


MORE_DEFECTS = [
    ("outcome-scale", lambda d: d["resolution"].setdefault("outcome_scales", []).append(
        {"id": "flat", "ordered": ["meh", "meh"]}), "flat: needs at least two unique, ordered outcomes"),
    ("chargen", lambda d: d["chargen"]["steps"][0]["targets"].append("nerve"), "step stats: unknown stat 'nerve'"),
    ("chargen", lambda d: d["chargen"]["steps"][1]["options"][0]["stats"].__setitem__("nerve", 1),
     "step background.soldier: unknown stat 'nerve'"),
    ("chargen", lambda d: d["chargen"]["steps"][2].__setitem__("table", "nowhere"),
     "step detail: unknown table 'nowhere'"),
    ("chargen", _assign(targets=["might", "nerve"], values=[0, 1]), "step array: unknown stat 'nerve'"),
    ("chargen", _assign(targets=["might", "grace"], values=[1]), "needs one value per target (1 values, 2 targets)"),
    ("chargen", _assign(targets=["might"], values=[99]), "value 99 is outside might's range"),
    ("chargen", lambda d: d["chargen"]["steps"].append({"id": "dance", "kind": "dance"}),
     "kind must be roll, choice, assign, table or points"),
    ("rules-text", lambda d: d["rules_text"].__setitem__("full_text", "word " * 30_000),
     "inline rules text is ~37500 tokens; budget 30000"),
]


@pytest.mark.parametrize("code, defect, fragment", MORE_DEFECTS, ids=[m[2][:40] for m in MORE_DEFECTS])
def test_every_lint_class_catches_its_defect(packs_dir, tmp_path, code, defect, fragment):
    pd = _copy(packs_dir, tmp_path)
    _edit(pd / "lanternlight" / "pack.yaml", defect)
    found = [(f.code, f.message) for f in errors(lint(resolve("lanternlight", pd)))]
    assert any(c == code and fragment in m for c, m in found), found


def test_a_missing_section_is_a_schema_error(lantern):
    from basilisk.kernel.packs import ResolvedPack
    data = {k: v for k, v in lantern.data.items() if k != "presentation"}
    found = [(f.code, f.message) for f in lint(ResolvedPack(data=data, hash="x", lineage=[]))]
    assert found == [("schema", "missing section 'presentation'")]


def test_a_schema_that_cannot_generate_is_a_lint_error(lantern, monkeypatch):
    from basilisk.kernel import packlint

    def broken(pack, effective, role, seat=None):
        raise ValueError("no enum for spend")
    monkeypatch.setattr(packlint, "generate", broken)
    found = [(f.code, f.message) for f in errors(lint(lantern))]
    assert ("tool-schema", "players/strict: no enum for spend") in found and len(found) == 4  # 2 roles x 2 presets


@pytest.mark.parametrize("edit, where", [
    (lambda d: d["actions"].append(dict(d["actions"][0])), "actions: strike"),
    (lambda d: d["entity_model"]["conditions"].append({"id": "shaken", "modifier": -2, "duration": "scene"}),
     "entity_model.conditions: shaken"),
    (lambda d: d["chargen"]["steps"][1]["options"].append({"id": "soldier", "label": "Soldier again"}),
     "chargen.steps[background].options: soldier"),  # nested catalogues too
])
def test_an_id_declared_twice_in_one_pack_is_refused(packs_dir, tmp_path, edit, where):
    """Within one file a second entry would merge into the first unseen (T0.31)."""
    pd = _copy(packs_dir, tmp_path)
    _edit(pd / "lanternlight" / "pack.yaml", edit)
    with pytest.raises(PackError, match="declares an id twice in one catalogue: " + where.replace("[", r"\[")
                       .replace("]", r"\]")):
        resolve("lanternlight", pd)


def test_removing_a_condition_an_inherited_action_uses_names_it(packs_dir, tmp_path):
    """P0.5: the child removes `shaken`, which Lanternlight's `strike` still adds."""
    pd = _copy(packs_dir, tmp_path)
    _edit(pd / "lanternlight_house" / "pack.yaml",
          lambda d: d.setdefault("remove", {}).__setitem__("entity_model.conditions", ["shaken"]))
    found = [(f.code, f.message) for f in errors(lint(resolve("lanternlight_house", pd)))]
    assert ("reference", "action strike [fail]: unknown condition 'shaken'") in found, found


# ---------------------------------------------------------------- keys, names, consistency (T0.34)

SCHEMA_DEFECTS = [
    ("schema", lambda d: d["actions"][0].__setitem__("outcome_efects", d["actions"][0].pop("outcome_effects")),
     "actions[strike]: unknown key 'outcome_efects'"),
    ("schema", lambda d: d.__setitem__("actoins", []), "pack: unknown key 'actoins'"),
    ("schema", lambda d: d["entity_model"]["stats"][0].__setitem__("rnage", [0, 3]),
     "entity_model.stats[might]: unknown key 'rnage'"),
    ("schema", lambda d: d["presentation"]["rule_cards"]["strike"].__setitem__("icon", "x"),
     "rule card strike: unknown key 'icon'"),
    ("schema", lambda d: d["vocabulary"].__setitem__("might", {"lable": "Might"}), "vocabulary.might: entries are"),
    ("expression", lambda d: d["entity_model"].setdefault("derived", []).append({"id": "dodge", "expr": "mana * 2"}),
     "derived dodge: unknown name 'mana'"),
    ("expression", lambda d: d["actions"][0].__setitem__("requires", "actor.mana > 1"),
     "action strike requires: unknown name 'actor.mana'"),
    ("expression", lambda d: d["actions"][0].__setitem__("eligibility", "actor.conditions.shaken + mood"),
     "action strike eligibility: unknown name 'mood'"),
    ("expression", lambda d: d["progression"]["advances"][0].__setitem__("requires", "target.wit >= 1"),
     "requires: unknown name 'target.wit'"),
    ("expression", lambda d: d["entity_model"]["resources"][0].__setitem__("max", "10 + actor.mana"),
     "resource vigor max: unknown name 'actor.mana'"),
    ("consistency", lambda d: d["presentation"].__setitem__("rounding", "round"),
     "presentation.rounding 'round' is not one of ceil, floor, half_up"),
    ("consistency", lambda d: d["presentation"].__setitem__("assertion_terms", {"mana points": "mana"}),
     "assertion term 'mana points' names 'mana'"),
    ("consistency", lambda d: d["vocabulary"].__setitem__("mana", {"label": "Mana"}),
     "vocabulary 'mana' names nothing the pack declares"),
    ("consistency", lambda d: d["gm"].__setitem__("fudgeable_procedures", ["nope"]),
     "gm.fudgeable_procedures: unknown procedure 'nope'"),
    ("consistency", lambda d: d["entity_model"]["stats"][0].__setitem__("default", 99),
     "stat might: default 99 is outside its range"),
    ("consistency", lambda d: d["gm"]["meta_currencies"][0].update({"start": 9, "max": 3}),
     "currency luck: start 9 must be an integer from 0 to its max 3"),
    ("consistency", lambda d: d["actions"][-1]["cost"].update({"amounts": [1, 5], "range": [1, 2]}),
     "spend amounts [5] are outside its range 1..2"),
    ("consistency", lambda d: d["actions"][0].__setitem__("modes", ["combat"]), "modes are a list of free and encounter"),
    ("consistency", lambda d: d["actions"][0].__setitem__("target", "everyone"), "target must be none, entity or zone"),
]


@pytest.mark.parametrize("code, defect, fragment", SCHEMA_DEFECTS, ids=[m[2][:40] for m in SCHEMA_DEFECTS])
def test_misspelt_keys_unknown_names_and_contradictions_fail_lint(packs_dir, tmp_path, code, defect, fragment):
    pd = _copy(packs_dir, tmp_path)
    _edit(pd / "lanternlight" / "pack.yaml", defect)
    found = [(f.code, f.message) for f in errors(lint(resolve("lanternlight", pd)))]
    assert any(c == code and fragment in m for c, m in found), found


def test_tactical_and_scene_names_are_known(packs_dir, tmp_path):
    """Tactical rules may read their features; scene flags are open (the GM sets them)."""
    pd = _copy(packs_dir, tmp_path)
    _edit(pd / "lanternlight" / "pack.yaml", lambda d: d["actions"][0].__setitem__(
        "requires", "scene.anything + actor.tags.marked + actor.region.cover.light + target.conditions.shaken"))
    assert errors(lint(resolve("lanternlight", pd))) == []


def test_a_currency_an_entity_does_not_hold_reads_zero(lantern):
    """NPCs hold no personal currencies; a rule reading one sees 0, not an error."""
    from conftest import new_campaign
    eng = new_campaign(lantern)
    eng.spawn_entity("foe", "Foe")
    assert eng.view(eng.state["entities"]["foe"])["luck"] == 0

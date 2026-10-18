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
                "lanternlight_sectioned", "tidewrack_excluded"):
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

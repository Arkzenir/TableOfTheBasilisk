"""Sectioned rules text and key-first query_rules (T0.14; ARCHITECTURE §2.11, BUILD_PLAN P0.13)."""

import pickle
import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.rules import SectionIndex
from basilisk.kernel.tools import generate


def sectioned_data(base):
    """Sections for Lanternlight: a chapter, one section per action, and the
    procedures and conditions. Structure is pack data, not kernel knowledge."""
    actions = [a["id"] for a in base.catalogue("actions")]
    secs = [{"id": "doing_things", "title": "Doing things", "aliases": ["actions", "what you can do"],
             "body": "Every action is a Check unless it says otherwise."}]
    for aid in actions:
        secs.append({"id": f"act_{aid}", "title": f"The {aid.title()} action", "aliases": [f"how to {aid}"],
                     "body": f"Rules for {aid}.", "refs": [aid], "parent": "doing_things"})
    secs.append({"id": "checks", "title": "Checks and automatic results", "aliases": ["rolling dice"],
                 "body": "Roll d20 + stat against the difficulty.",
                 "refs": [p["id"] for p in base.catalogue("resolution.procedures")]})
    secs.append({"id": "conditions", "title": "Conditions", "aliases": ["status effects"],
                 "body": "What each condition does and how it ends.",
                 "refs": [c["id"] for c in base.catalogue("entity_model.conditions")]})
    return {"mode": "sectioned", "digest": "LANTERNLIGHT digest: d20 + stat vs difficulty; see sections.",
            "max_section_tokens": 200, "sections": secs}


@pytest.fixture(scope="module")
def packs_with_sections(packs_dir, lantern, tmp_path_factory):
    dst = tmp_path_factory.mktemp("rules") / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["rules_text"] = sectioned_data(lantern)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return dst


@pytest.fixture(scope="module")
def sectioned(packs_with_sections):
    pack = resolve("lanternlight", packs_with_sections)
    assert errors(lint(pack)) == []
    return pack


def table(pack):
    eng = Engine.start_campaign(pack, "rules-seed", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    return eng


def edited(packs_with_sections, tmp_path, fn):
    dst = tmp_path / "packs"
    shutil.copytree(packs_with_sections, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data["rules_text"])
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return [f.message for f in errors(lint(resolve("lanternlight", dst))) if f.code == "rules-text"]


# ---------------------------------------------------------------- resolution order (§2.11)

def test_every_section_is_reachable_by_id_and_each_alias(sectioned):
    eng = table(sectioned)
    for s in sectioned.get("rules_text.sections"):
        assert eng.query_rules("ash", s["id"])["via"] == "id"
        for name in [s["title"], *s.get("aliases", [])]:
            hit = eng.query_rules("ash", name)
            assert hit["via"] == "alias" and s["id"] in [x["id"] for x in hit["sections"]], name


def test_every_catalogue_id_resolves_to_a_covering_section(sectioned):
    eng = table(sectioned)
    for dotted in ("actions", "resolution.procedures", "entity_model.conditions"):
        for item in sectioned.catalogue(dotted):
            hit = eng.query_rules("ash", item["id"])
            assert hit["via"] in ("ref", "id"), item["id"]
            assert any(item["id"] in (sec.get("refs") or [])
                       for sec in sectioned.get("rules_text.sections") if sec["id"] in [x["id"] for x in hit["sections"]])


def test_partial_matches_and_misses(sectioned):
    eng = table(sectioned)
    hit = eng.query_rules("ash", "action climb")
    assert hit["via"] == "partial" and [s["id"] for s in hit["sections"]] == ["act_climb"]
    miss = eng.query_rules("ash", "Condishuns")
    assert miss["via"] is None and miss["sections"] == [] and "Conditions" in miss["suggestions"]
    logged = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "rules_queried"]
    assert logged[-1]["via"] is None and logged[-1]["suggestions"] == miss["suggestions"]
    assert "body" not in logged[-2] and logged[-2]["sections"] == ["act_climb"]  # ids only, never text


def test_returned_text_and_layer_two(sectioned, lantern):
    eng = table(sectioned)
    hit = eng.query_rules("gm", "act_strike")
    assert hit["sections"] == [{"id": "act_strike", "title": "The Strike action", "parent": "doing_things",
                                "body": "Rules for strike."}]
    assert eng.rules_layer().startswith("LANTERNLIGHT digest")
    assert table(lantern).rules_layer().startswith("LANTERNLIGHT (demo)")  # inline: the full text


def test_inline_packs_with_and_without_sections(lantern, packs_dir, tmp_path):
    out = table(lantern).query_rules("ash", "strike")
    assert out["sections"] == [] and "inline" in out["note"]
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["rules_text"]["sections"] = [{"id": "luck", "title": "Luck", "body": "Spend it to Inspire.", "refs": ["inspire"]}]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    pack = resolve("lanternlight", dst)
    assert errors(lint(pack)) == []  # inline packs need no coverage
    assert table(pack).query_rules("ash", "inspire")["via"] == "ref"


def test_queries_are_validated_logged_and_replay(sectioned):
    eng = table(sectioned)
    with pytest.raises(EngineError, match="No seat"):
        eng.query_rules("nobody", "checks")
    with pytest.raises(EngineError, match="needs a section id"):
        eng.query_rules("ash", "  ")
    eng.query_rules("ash", "checks")
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()  # passive: state unchanged


def test_index_construction_is_deterministic(packs_with_sections):
    a = SectionIndex(resolve("lanternlight", packs_with_sections))
    b = SectionIndex(resolve("lanternlight", packs_with_sections))
    assert pickle.dumps((a.order, a.refs, a.keys, sorted((k, sorted(v)) for k, v in a.words.items()))) == \
           pickle.dumps((b.order, b.refs, b.keys, sorted((k, sorted(v)) for k, v in b.words.items())))


# ---------------------------------------------------------------- lint classes (§2.10)

@pytest.mark.parametrize("edit, fragment", [
    (lambda rt: rt.update({"mode": "chapters"}), "No rules_text mode 'chapters'"),
    (lambda rt: rt.update({"digest": ""}), "needs a digest"),
    (lambda rt: rt.update({"digest": "x" * 30_000}), "the digest is ~7500 tokens"),
    (lambda rt: rt["sections"][1].update({"body": "y" * 1_000}), "max_section_tokens is 200"),
    (lambda rt: rt["sections"][2].update({"aliases": ["actions"]}), "collides with section doing_things"),
    (lambda rt: rt["sections"][1].update({"parent": "nowhere"}), "No parent section 'nowhere'"),
    (lambda rt: rt["sections"][0].update({"parent": "act_strike"}), "loops back"),
    (lambda rt: rt["sections"][1].update({"refs": []}), "no section lists it in refs"),
    (lambda rt: rt["sections"][1].update({"refs": ["strike", "flying"]}), "No catalogue id for refs 'flying'"),
    (lambda rt: rt["sections"][1].update({"page": 4}), "unknown field"),
])
def test_each_lint_class_catches_its_defect(packs_with_sections, tmp_path, edit, fragment):
    found = edited(packs_with_sections, tmp_path, edit)
    assert any(fragment in m for m in found), found


def test_query_rules_is_in_every_schema(lantern, tide, sectioned):
    for pack in (lantern, tide, sectioned):
        eff = table(lantern).state["determinism"]["effective"]
        for role in ("players", "gm"):
            assert generate(pack, eff, role)["query_rules"] == {"query": {"type": "string", "x-narrative": True}}

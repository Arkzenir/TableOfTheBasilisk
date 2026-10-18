"""Excluded terms (T0.16; ARCHITECTURE §1.2, §1.3.3, §2.10; BUILD_PLAN P0.14).

The fixture terms are invented and belong to no real work."""

import shutil

import pytest
import yaml

from basilisk.kernel import terms
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve


@pytest.fixture(scope="module")
def marked(packs_dir):
    return resolve("tidewrack_excluded", packs_dir)


def table(pack, seed="terms-seed"):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    return eng


def rec(name, body="One fact.", aliases=None):
    return {"type": "npc", "name": name, "aliases": aliases or [], "body": body, "knowledge": "revealed",
            "origin": "improvised"}


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


# ---------------------------------------------------------------- the matcher

@pytest.mark.parametrize("text, expected", [
    ("Morrowgaunt rises", ["Morrowgaunt"]),
    ("they whisper of MORROWGAUNT.", ["Morrowgaunt"]),          # case and punctuation
    ("Morrowgaunt's hounds", ["Morrowgaunt"]),                   # possessive
    ("the gaunt one stirs", ["Morrowgaunt"]),                    # alias, whole words
    ("Morrow  Gaunt", ["Morrowgaunt"]),                          # spacing
    ("Ysolde and the Compact", ["Saltmother Ysolde", "Brinehold Compact"]),
    ("a gauntlet and a compactor", []),                          # near misses: not whole words
    ("Saltmother is a title", []),                               # half of a two-word term
    ("", []),
])
def test_whole_word_case_insensitive_matching(marked, text, expected):
    assert terms.find(marked, text) == expected


def test_packs_without_terms_match_nothing_and_keep_their_shape(tide):
    assert terms.find(tide, "Morrowgaunt") == []
    assert "excluded_terms" not in tide.data["meta"]  # no key, so existing pack hashes are unchanged


# ---------------------------------------------------------------- canon refuses them

@pytest.mark.parametrize("record", [
    rec("Morrowgaunt"),
    rec("MORROWGAUNT the Old"),
    rec("A harbour pilot", aliases=["Ysolde"]),
    rec("A harbour pilot", body="She serves the Brinehold Compact."),
])
def test_canon_writes_with_excluded_terms_are_refused_atomically(marked, record):
    eng = table(marked)
    before = frozen(eng)
    with pytest.raises(EngineError, match="licence does not cover it"):
        eng.write_canon(record)
    assert frozen(eng) == before


def test_the_error_names_the_term(marked):
    eng = table(marked)
    with pytest.raises(EngineError, match="'Saltmother Ysolde'"):
        eng.write_canon(rec("Ysolde of the Tides"))


def test_near_misses_are_accepted(marked):
    eng = table(marked)
    eng.write_canon(rec("A gauntleted pilot", body="She keeps a compactor and a morrow-light."))
    assert len(eng.state["canon"]) == 1


def test_every_canon_path_is_checked(marked):
    eng = table(marked)
    with pytest.raises(EngineError, match="licence"):
        eng.create_clock("plot", "Plot", 2, stages=[{"at": 1, "record": {
            "type": "event", "name": "The Compact moves", "body": "x", "knowledge": "revealed"}}])
    first = eng.write_canon(rec("A harbour pilot"))["id"]
    with pytest.raises(EngineError, match="licence"):
        eng.supersede_canon(first, rec("A harbour pilot", body="Sworn to Morrowgaunt."))


def test_excluded_in_checks_spoken_lines(marked, tide):
    eng = table(marked)
    assert eng.excluded_in("The GM says: Ysolde waits at the quay.") == ["Saltmother Ysolde"]
    assert table(tide).excluded_in("The GM says: Ysolde waits at the quay.") == []


def test_matching_and_replay_are_deterministic(marked):
    a, b = table(marked), table(marked)
    for eng in (a, b):
        eng.write_canon(rec("A harbour pilot"))
        with pytest.raises(EngineError):
            eng.write_canon(rec("Morrowgaunt"))
    assert a.store.head(a.campaign_id) == b.store.head(b.campaign_id)
    assert hash_obj(fold(a.store.read(a.campaign_id))) == a.state_hash()


# ---------------------------------------------------------------- packs

def test_terms_inherit_and_merge_by_term(packs_dir, tmp_path):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    child = dst / "tidewrack_excluded_child"
    child.mkdir()
    (child / "pack.yaml").write_text(yaml.safe_dump({
        "meta": {"id": "tidewrack_excluded_child", "version": "0.1.0", "extends": "tidewrack_excluded@0.1.0",
                 "name": "child", "license": "CC0-1.0", "attribution_text": "child",
                 "excluded_terms": [{"term": "Morrowgaunt", "aliases": ["the Old Hound"]},
                                    {"term": "Glasswake", "aliases": []}]}}, sort_keys=False))
    pack = resolve("tidewrack_excluded_child", dst)
    declared = {e["term"]: e["aliases"] for e in pack.get("meta.excluded_terms")}
    assert declared["Morrowgaunt"] == ["the Old Hound"] and "Glasswake" in declared and "Saltmother Ysolde" in declared
    assert terms.find(pack, "the gaunt") == [] and terms.find(pack, "the old hound") == ["Morrowgaunt"]
    assert errors(lint(pack)) == []


@pytest.mark.parametrize("term, where", [
    ({"term": "Grit"}, "resource"),                     # a catalogue id
    ({"term": "Read the Waters"}, "rule card"),         # a rule-card title
    ({"term": "Iron"}, "vocabulary"),                   # a vocabulary label
    ({"term": "!!!"}, "needs a term"),
])
def test_terms_colliding_with_the_packs_own_names_fail_lint(packs_dir, tmp_path, term, where):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "tidewrack_excluded" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["meta"]["excluded_terms"].append(term)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f.message for f in errors(lint(resolve("tidewrack_excluded", dst))) if f.code == "excluded-term"]
    assert any(where in m for m in found), found


def test_the_fixture_pack_is_clean_and_plays(marked, packs_dir):
    assert errors(lint(marked)) == []
    from basilisk.harness.scripted import run_script, smoke_script
    _, report = run_script(smoke_script(marked), packs_dir)
    assert not report.actions_never_taken

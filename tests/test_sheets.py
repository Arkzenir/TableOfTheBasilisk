"""Sheet read views (T0.9; ARCHITECTURE §7.1, BUILD_PLAN P0.8)."""

import shutil

import pytest
import yaml

from basilisk.harness.scripted import run_script, smoke_script
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.sheets import summarise
from basilisk.kernel.tools import generate


def table(pack):
    eng = Engine.start_campaign(pack, "sheet-seed", {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.spawn_entity("foe", "Foe")
    return eng


def by_id(sheet):
    return {f["id"]: f for f in sheet["fields"]}


def test_own_sheet_is_full_and_in_the_packs_vocabulary(lantern):
    eng = table(lantern)
    sheet = eng.read_sheet("ash")
    fields = by_id(sheet)
    ent = eng.state["entities"]["ash"]
    assert sheet["entity"] == "ash" and sheet["name"] == "Ash"
    assert fields["might"]["label"] == "Might" and fields["might"]["short"] == "MGT"
    assert fields["might"]["value"] == ent["stats"]["might"] and fields["might"]["private"]
    assert fields["vigor"]["value"] == ent["resources"]["vigor"] and fields["vigor"]["max"] == 12
    assert fields["guard"]["section"] == "derived" and fields["guard"]["value"] == 10 + ent["stats"]["grace"]
    assert fields["fatigue"]["max"] == 3 and fields["luck"]["section"] == "currency"
    assert {"inventory", "details"} <= set(fields)


def test_only_your_own_sheet_in_full(lantern):
    eng = table(lantern)
    with pytest.raises(EngineError, match="read_party_sheets"):
        eng.read_sheet("ash", "bram")
    with pytest.raises(EngineError, match="name the entity"):
        eng.read_sheet("gm")
    assert eng.read_sheet("gm", "foe")["kind"] == "npc"
    with pytest.raises(EngineError, match="No seat"):
        eng.read_sheet("nobody")


def test_party_summaries_show_only_public_fields(lantern):
    eng = table(lantern)
    eng._apply_effect({"primitive": "add_condition", "target": "bram", "condition": "shaken"},
                      {"actor": None, "target": None, "self": None}, None, {})
    [bram] = eng.read_party_sheets("ash")
    assert bram["entity"] == "bram" and {f["id"] for f in bram["fields"]} == {"vigor", "guard", "shaken"}
    assert all(not f["private"] for f in bram["fields"])
    gm = eng.read_party_sheets("gm")
    assert [s["entity"] for s in gm] == ["ash", "bram"] and any(f["private"] for f in gm[0]["fields"])


@pytest.mark.parametrize("pack_id", ["lanternlight", "lanternlight_house", "tidewrack"])
def test_summaries_never_include_private_fields(packs_dir, pack_id):
    """Acceptance: across a whole smoke campaign's worth of state, for every seat."""
    pack = resolve(pack_id, packs_dir)
    engine, _ = run_script(smoke_script(pack), packs_dir)
    seats = [s for s, r in engine.seats.items() if r == "player"]
    checked = 0
    for seat in seats:
        for summary in engine.read_party_sheets(seat):
            full = engine.full_sheet(summary["entity"])
            private = {f["id"] for f in full["fields"] if f["private"]}
            shown = {f["id"] for f in summary["fields"]}
            assert not shown & private, (seat, summary["entity"])
            assert summary == summarise(full)
            assert summary["entity"] != engine.state["entities"].get(seat, {}).get("id")
            checked += 1
    assert checked == len(seats) * (len(seats) - 1)


def test_reads_are_pure(lantern):
    eng = table(lantern)
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    eng.read_sheet("ash")
    eng.read_party_sheets("bram")
    eng.read_party_sheets("gm")
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before


@pytest.mark.parametrize("edit, fragment", [
    (lambda d: d["presentation"].update({"sheet": {"public": ["charm"]}}), "No sheet field 'charm'"),
    (lambda d: d["entity_model"]["stats"][0].update({"private": True}) or
               d["presentation"].update({"sheet": {"public": ["might"]}}), "might is marked private"),
])
def test_bad_sheet_presentation_fails_lint(packs_dir, tmp_path, edit, fragment):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    edit(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f.message for f in errors(lint(resolve("lanternlight", dst))) if f.code == "sheet"]
    assert any(fragment in m for m in found), found


def test_sheet_tools(lantern, tide):
    for pack in (lantern, tide):
        eff = table(lantern).state["determinism"]["effective"]
        gm, players = generate(pack, eff, "gm"), generate(pack, eff, "players")
        assert players["read_sheet"] == {} and "read_party_sheets" in players
        assert gm["read_sheet"] == {"entity_id": {"type": "string", "format": "id"}}

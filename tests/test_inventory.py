"""Weight-based inventory (T0.26; ARCHITECTURE §2.3)."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve

IDS = {"actor": "ash", "target": "foe", "self": "ash"}


def table(pack):
    eng = Engine.start_campaign(pack, "inv", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})  # Might 2: carries 10 + 2 * 2 = 14
    eng.spawn_entity("foe", "Foe")                                   # Might 0: carries 10
    eng.start_session()
    return eng


def give(eng, item, who="actor"):
    eng._apply_effect({"primitive": "create_item", "target": who, "item": item}, IDS, None, {})


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


def test_weight_and_capacity(lantern):
    eng = table(lantern)
    ash = eng.state["entities"]["ash"]
    assert eng.capacity(ash) == 14 and eng.carried(ash) == 0
    for item in ("crowbar", "rope", "lantern", "lantern", "ration", "ration"):  # 4+3+2+2+1+1 = 13
        give(eng, item)
    assert eng.carried(ash) == 13
    assert eng.view(ash)["carried"] == 13 and eng.view(ash)["capacity"] == 14
    inv = next(f for f in eng.full_sheet("ash")["fields"] if f["id"] == "inventory")
    assert inv["carried"] == 13 and inv["max"] == 14


def test_overloading_is_refused_atomically(lantern):
    eng = table(lantern)
    for item in ("crowbar", "crowbar", "rope"):  # 11 of 14
        give(eng, item)
    before = frozen(eng)
    with pytest.raises(EngineError, match="cannot carry crowbar: that would be 15 of 14"):
        give(eng, "crowbar")
    assert frozen(eng) == before
    give(eng, "rope")  # exactly 14 is fine
    assert eng.carried(eng.state["entities"]["ash"]) == 14


def test_transfers_respect_the_receivers_limit(lantern):
    eng = table(lantern)
    for item in ("crowbar", "crowbar"):  # Ash carries 8 of 14
        give(eng, item)
    give(eng, "crowbar", who="target")
    give(eng, "crowbar", who="target")  # the foe carries 8 of 10
    before = frozen(eng)
    with pytest.raises(EngineError, match="foe cannot carry crowbar"):
        eng._apply_effect({"primitive": "transfer_item", "from": "actor", "to": "target", "item": "crowbar"}, IDS, None, {})
    assert frozen(eng) == before
    eng._apply_effect({"primitive": "transfer_item", "from": "target", "to": "actor", "item": "crowbar"}, IDS, None, {})
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_only_known_items_exist_under_weight(lantern, tide):
    with pytest.raises(EngineError, match="No item 'anvil'"):
        give(table(lantern), "anvil")
    t = Engine.start_campaign(tide, "t", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    t.create_character("ash", "Ash", {"playbook": "warden"})
    t._apply_effect({"primitive": "create_item", "target": "actor", "item": "anything"},
                    {"actor": "ash", "target": None, "self": "ash"}, None, {})  # abstract: any item id
    assert t.state["entities"]["ash"]["inventory"] == ["anything"]


@pytest.mark.parametrize("inventory, items, fragment", [
    ({"model": "slots"}, None, "slots is not built yet"),
    ({"model": "weight"}, [], "needs entity_model.items"),
    ({"model": "weight", "limit_expr": "import os"}, None, "limit_expr"),
    ({"model": "weight"}, [{"id": "rock", "weight": -1}], "non-negative"),
])
def test_bad_inventories_fail_lint(packs_dir, tmp_path, inventory, items, fragment):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["entity_model"]["inventory"] = inventory
    if items is not None:
        data["entity_model"]["items"] = items
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [f.message for f in errors(lint(resolve("lanternlight", dst))) if f.code == "inventory"]
    assert any(fragment in m for m in found), found

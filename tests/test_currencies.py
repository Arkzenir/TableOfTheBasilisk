"""Meta-currency holders: each player, the party's pool, and the GM's pool (T0.31, T0.32;
ARCHITECTURE §2.3 `gm.meta_currencies`, §2.4 meta-currency; BUILD_PLAN P0.4)."""

import shutil

import pytest
import yaml

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve

IDS = {"actor": "ash", "target": None, "self": "ash"}


def _variant(packs_dir, tmp_path, fn):
    dst = tmp_path / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "lanternlight" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve("lanternlight", dst)


@pytest.fixture
def pooled(packs_dir, tmp_path):
    """Lanternlight with a shared Resolve the whole party spends from."""
    def add(d):
        d["gm"]["meta_currencies"].append({"id": "resolve", "holder": "party", "start": 2, "max": 4})
        d["actions"].append({"id": "muster", "trigger": "declared", "procedure": "automatic",
                             "cost": {"currency": "resolve", "amount": 1}, "outcome_effects": {}})
        cards = d["presentation"]["rule_cards"]
        cards["resolve"] = {"title": "Resolve", "summary": "The party's shared nerve.", "category": "currency",
                            "icon_id": "coin"}
        cards["muster"] = {"title": "Muster", "summary": "Spend 1 shared Resolve.", "category": "action",
                          "icon_id": "flag"}
    return _variant(packs_dir, tmp_path, add)


def table(pack):
    eng = Engine.start_campaign(pack, "pool", {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"background": "soldier"})
    eng.create_character("bram", "Bram", {"background": "scholar"})
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("hall")
    return eng


def test_the_pool_is_lint_clean(pooled):
    assert errors(lint(pooled)) == []


def test_the_party_shares_one_pool(pooled):
    eng = table(pooled)
    assert eng.currency("ash", "resolve") == eng.currency("bram", "resolve") == 2  # its start, before any change
    assert "currencies" not in eng.state and "resolve" not in eng.state["entities"]["ash"]["currencies"]
    eng.commit_action("ash", "muster")
    assert eng.currency("ash", "resolve") == eng.currency("bram", "resolve") == 1
    spent = [e["payload"] for e in eng.store.read(eng.campaign_id)
             if e["type"] == "effect_applied" and e["payload"]["primitive"] == "spend_currency"][-1]
    assert spent["changes"] == [{"path": ["currencies", "party", "resolve"], "value": 1}]
    eng.commit_action("bram", "muster")
    assert "muster" not in eng.available_actions("ash")  # the pool is empty for everyone
    with pytest.raises(EngineError, match="cannot afford"):
        eng.commit_action("ash", "muster")
    assert eng.currency("ash", "luck") == 1  # a personal currency stays personal
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_earning_fills_the_pool_to_its_max(pooled):
    eng = table(pooled)
    eng._apply_effect({"primitive": "earn_currency", "target": "actor", "currency": "resolve", "amount": 9},
                      IDS, None, {})
    assert eng.currency("bram", "resolve") == 4
    assert eng.view(eng.state["entities"]["bram"])["resolve"] == 4  # expressions read the shared value
    assert eng.sheet_problems("bram") == []


def test_only_the_party_holds_the_pool(pooled):
    eng = table(pooled)
    assert eng.currency("foe", "resolve") == 0
    with pytest.raises(EngineError, match="resolve belongs to the party, and foe is not a player character"):
        eng._apply_effect({"primitive": "earn_currency", "target": "actor", "currency": "resolve", "amount": 1},
                          {"actor": "foe", "target": None, "self": "foe"}, None, {})


def test_an_unknown_holder_fails_lint(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path,
                    lambda d: d["gm"]["meta_currencies"][0].__setitem__("holder", "everyone"))
    found = [f.message for f in errors(lint(pack))]
    assert any("No holder 'everyone'" in m and "each_player, gm, party" in m for m in found), found


# ---------------------------------------------------------------- the GM's pool (T0.32, REV-ARCH-1.7)

@pytest.fixture
def doom(packs_dir, tmp_path):
    """Lanternlight with a Doom pool on the GM's side: a player's gamble feeds
    it, and any NPC spends it."""
    def add(d):
        d["gm"]["meta_currencies"].append({"id": "doom", "holder": "gm", "start": 0, "max": 3, "visible": True})
        d["actions"] += [
            {"id": "gamble", "trigger": "declared", "procedure": "automatic",
             "outcome_effects": {"pass": [{"primitive": "earn_currency", "target": "gm", "currency": "doom",
                                           "amount": 1}]}},
            {"id": "loom", "trigger": "declared", "procedure": "automatic",
             "cost": {"currency": "doom", "amount": 1}, "outcome_effects": {}}]
        cards = d["presentation"]["rule_cards"]
        cards["doom"] = {"title": "Doom", "summary": "The GM's pool.", "category": "currency", "icon_id": "skull"}
        cards["gamble"] = {"title": "Gamble", "summary": "Push on; the GM gains 1 Doom.", "category": "action",
                           "icon_id": "dice"}
        cards["loom"] = {"title": "Loom", "summary": "An NPC spends 1 Doom.", "category": "action",
                         "icon_id": "shadow"}
    return _variant(packs_dir, tmp_path, add)


def test_the_gm_pool_is_lint_clean(doom):
    assert errors(lint(doom)) == []


def test_players_feed_the_gm_pool_and_every_npc_draws_on_it(doom):
    eng = table(doom)
    eng.spawn_entity("foe2", "Second Foe")
    assert "doom" not in eng.state["entities"]["foe"]["currencies"]  # no copy per NPC
    assert eng.currency("foe", "doom") == eng.currency("foe2", "doom") == 0
    assert "loom" not in eng.available_actions("foe")
    eng.commit_action("ash", "gamble")
    eng.commit_action("bram", "gamble")
    fed = [e["payload"] for e in eng.store.read(eng.campaign_id)
           if e["type"] == "effect_applied" and e["payload"]["primitive"] == "earn_currency"][-1]
    assert fed["target"] is None and fed["changes"] == [{"path": ["currencies", "gm", "doom"], "value": 2}]
    assert eng.currency("foe", "doom") == eng.currency("foe2", "doom") == 2
    assert eng.currency("ash", "doom") == 0 and "loom" not in eng.available_actions("ash")
    eng.commit_action("foe", "loom", by="gm")
    eng.commit_action("foe2", "loom", by="gm")
    with pytest.raises(EngineError, match="cannot afford"):
        eng.commit_action("foe", "loom", by="gm")
    assert eng.currency("foe2", "doom") == 0
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()


def test_the_gm_pool_caps_and_refuses_overspending(doom):
    eng = table(doom)
    for _ in range(5):
        eng.commit_action("ash", "gamble")
    assert eng.currency("foe", "doom") == 3
    with pytest.raises(EngineError, match="the GM has only 3 doom"):
        eng._apply_effect({"primitive": "spend_currency", "target": "gm", "currency": "doom", "amount": 4},
                          IDS, None, {})


def test_only_the_gm_side_holds_the_gm_pool(doom):
    eng = table(doom)
    with pytest.raises(EngineError, match="doom belongs to the GM's side, and ash is not GM-controlled"):
        eng._apply_effect({"primitive": "earn_currency", "target": "actor", "currency": "doom", "amount": 1},
                          IDS, None, {})
    with pytest.raises(EngineError, match="target gm needs a GM-held currency; luck is held by each_player"):
        eng._apply_effect({"primitive": "earn_currency", "target": "gm", "currency": "luck", "amount": 1},
                          IDS, None, {})


@pytest.mark.parametrize("edit, fragment", [
    (lambda d: d["actions"][0]["outcome_effects"]["pass"].append(
        {"primitive": "earn_currency", "target": "gm", "currency": "luck", "amount": 1}),
     "target gm is only for earn_currency or spend_currency on a GM-held currency"),
    (lambda d: d["actions"][0]["outcome_effects"]["pass"].append(
        {"primitive": "add_tag", "target": "gm", "tag": "marked"}),
     "target gm is only for earn_currency or spend_currency"),
    (lambda d: d["gm"]["meta_currencies"][0].__setitem__("visible", "yes"), "visible must be true or false"),
])
def test_bad_gm_pool_declarations_fail_lint(packs_dir, tmp_path, edit, fragment):
    found = [f.message for f in errors(lint(_variant(packs_dir, tmp_path, edit)))]
    assert any(fragment in m for m in found), found


def test_lethality_levers_are_reserved(packs_dir, tmp_path):
    pack = _variant(packs_dir, tmp_path, lambda d: d["gm"].__setitem__("lethality_levers",
                                                                         [{"id": "pull_punch", "effect": "x"}]))
    found = lint(pack)
    assert errors(found) == []
    assert [f.message for f in found if f.code == "reserved"] == [
        "gm.lethality_levers is reserved for the lethality trait (BUILD_PLAN P2.5); nothing reads it yet"]

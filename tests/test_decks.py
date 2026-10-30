"""Seeded decks (T0.8; ARCHITECTURE §2.4, §5.5)."""

import shutil

import pytest
import yaml

from basilisk.harness.scripted import verify
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packlint import errors, lint
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import free_values, generate

OMENS = ["gull", "squall", "flat_calm", "wreckage", "beacon"]
_PACKS: dict = {}


@pytest.fixture
def variant(packs_dir, tmp_path_factory):
    """Tidewrack with its omen deck's rule (and flags) changed."""
    def make(**deck):
        key = repr(sorted(deck.items()))
        if key not in _PACKS:
            dst = tmp_path_factory.mktemp("decks") / "packs"
            shutil.copytree(packs_dir, dst)
            path = dst / "tidewrack" / "pack.yaml"
            data = yaml.safe_load(path.read_text())
            data["randomizers"]["decks"][0].update(deck)
            path.write_text(yaml.safe_dump(data, sort_keys=False))
            _PACKS[key] = resolve("tidewrack", dst)
        return _PACKS[key]
    return make


def table(pack, seed="deck-seed"):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player", "bram": "player"}},
                                clock=lambda: None)
    eng.create_character("ash", "Ash", {"playbook": "warden"})
    eng.start_session()
    eng.set_scene("harbour")
    return eng


def events(eng, kind):
    return [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


# ---------------------------------------------------------------- shuffles are seeded state

def test_first_draw_shuffles_and_draws_replay_exactly(tide):
    eng = table(tide)
    assert "decks" not in eng.state  # untouched decks leave older logs unchanged
    drawn = [eng.draw_card("omens") for _ in range(3)]
    shuffle = events(eng, "deck_shuffled")
    assert len(shuffle) == 1 and shuffle[0]["reason"] == "first_draw"
    assert sorted(shuffle[0]["order"]) == sorted(OMENS) and drawn == shuffle[0]["order"][:3]
    assert eng.state["decks"]["omens"]["discard"] == drawn
    assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()
    assert verify(eng.store, eng.campaign_id, tide, "deck-seed") == []  # the shuffle re-derives from the seed
    assert [table(tide).draw_card("omens") for _ in range(1)] == drawn[:1]  # same seed, same deck


def test_shuffles_share_the_roll_counter(tide):
    eng = table(tide)
    before = eng.state["roll_counter"]
    eng.draw_card("omens")
    assert eng.state["roll_counter"] == before + 1
    assert events(eng, "deck_shuffled")[0]["counter"] == before


# ---------------------------------------------------------------- reshuffle rules

def test_when_empty_reshuffles_the_discards_back_in(tide):
    eng = table(tide)  # Tidewrack's omens use when_empty
    first = [eng.draw_card("omens") for _ in range(5)]
    sixth = eng.draw_card("omens")
    reasons = [s["reason"] for s in events(eng, "deck_shuffled")]
    assert reasons == ["first_draw", "when_empty"] and sorted(first) == sorted(OMENS)
    assert sixth == events(eng, "deck_shuffled")[1]["order"][0]


def test_manual_decks_refuse_when_empty_until_the_gm_reshuffles(variant):
    eng = table(variant(reshuffle_rule="manual"))
    for _ in range(5):
        eng.draw_card("omens")
    before = frozen(eng)
    with pytest.raises(EngineError, match="empty; its reshuffle rule is manual"):
        eng.draw_card("omens")
    assert frozen(eng) == before
    with pytest.raises(EngineError, match="only the GM reshuffles"):
        eng.reshuffle_deck("omens", by="ash")
    eng.reshuffle_deck("omens")
    eng.draw_card("omens")


def test_every_draw_shuffles_before_each_draw(variant):
    eng = table(variant(reshuffle_rule="every_draw"))
    for _ in range(7):
        eng.draw_card("omens")
    assert len(events(eng, "deck_shuffled")) == 7


@pytest.mark.parametrize("rule, boundary", [("scene", "set_scene"), ("session", "start_session")])
def test_boundary_rules_reshuffle_used_decks_only(variant, rule, boundary):
    eng = table(variant(reshuffle_rule=rule))
    eng.set_scene("unused")
    assert events(eng, "deck_shuffled") == []  # never drawn: no state, nothing to reshuffle
    eng.draw_card("omens")
    if boundary == "start_session":
        eng.end_session()
        eng.start_session()
    else:
        eng.set_scene("next")
    assert [s["reason"] for s in events(eng, "deck_shuffled")] == ["first_draw", rule]
    assert eng.state["decks"]["omens"]["discard"] == [] and len(eng.state["decks"]["omens"]["draw"]) == 5


# ---------------------------------------------------------------- hands and views

def test_hands_are_kept_out_of_reshuffles_and_views(variant):
    eng = table(variant(reshuffle_rule="manual"))
    mine = eng.draw_card("omens", to="ash")
    eng.draw_card("omens", to="bram")
    eng.draw_card("omens")
    eng.reshuffle_deck("omens")
    assert mine not in eng.state["decks"]["omens"]["draw"] and len(eng.state["decks"]["omens"]["draw"]) == 3
    view = eng.deck_view("omens", "ash")
    assert view == {"deck": "omens", "in_pile": 3, "discard": [], "hands": {"ash": [mine]}}
    assert set(eng.deck_view("omens", "gm")["hands"]) == {"ash", "bram"}
    assert "draw" not in view and "order" not in view  # pile order is never shown
    with pytest.raises(EngineError, match="only bram.s controller or the GM"):
        eng.discard_card("omens", eng.state["decks"]["omens"]["held"]["bram"][0], "bram", by="ash")
    eng.discard_card("omens", mine, "ash", by="ash")
    assert eng.deck_view("omens", "ash")["hands"] == {} and mine in eng.deck_view("omens", "ash")["discard"]
    with pytest.raises(EngineError, match="No card in ash's hand"):
        eng.discard_card("omens", mine, "ash")


def test_who_may_draw(tide, variant):
    eng = table(tide)
    with pytest.raises(EngineError, match="only the GM draws"):
        eng.draw_card("omens", by="ash")
    with pytest.raises(EngineError, match="No deck 'tarot'"):
        eng.draw_card("tarot")
    with pytest.raises(EngineError, match="No holder 'nobody'"):
        eng.draw_card("omens", to="nobody")
    open_deck = table(variant(players_draw=True))
    open_deck.draw_card("omens", by="ash", to="ash")


# ---------------------------------------------------------------- packs and tools

@pytest.mark.parametrize("deck, fragment", [
    ({"reshuffle_rule": "sometimes"}, "No reshuffle rule 'sometimes'"),
    ({"cards": []}, "at least one card"),
    ({"cards": ["gull", "gull"]}, "duplicate card ids"),
    ({"cards": ["Big Gull"]}, "card id 'Big Gull'"),
])
def test_bad_decks_fail_lint(variant, deck, fragment):
    found = [f.message for f in errors(lint(variant(**deck))) if f.code == "deck"]
    assert any(fragment in m for m in found), found


def test_deck_tools(tide, lantern, variant):
    eff = table(tide).state["determinism"]["effective"]
    gm, players = generate(tide, eff, "gm"), generate(tide, eff, "players")
    assert gm["draw_card"]["deck_id"] == {"enum": ["omens"]} and "reshuffle_deck" in gm
    assert "draw_card" not in players and "reshuffle_deck" not in players
    assert not free_values(gm["draw_card"]) and not free_values(gm["reshuffle_deck"])
    assert "draw_card" in generate(variant(players_draw=True), eff, "players")
    assert "draw_card" not in generate(lantern, eff, "gm")  # no decks, no deck tools

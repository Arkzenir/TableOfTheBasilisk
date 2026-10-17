"""`peek_roll` and fudging (T0.7; ARCHITECTURE §5.5, §2.5, §2.13, §8.6)."""

import shutil

import pytest
import yaml

from basilisk.broadcast.cards import CardRenderer
from basilisk.harness.scripted import verify
from basilisk.kernel import dice, fudging
from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.packs import resolve
from basilisk.kernel.tools import generate


@pytest.fixture(scope="module")
def tide_rolls(packs_dir, tmp_path_factory):
    """Tidewrack with a GM who rolls and a fudgeable banded procedure: the
    second outcome scale for the direction-of-drama check."""
    dst = tmp_path_factory.mktemp("fudge") / "packs"
    shutil.copytree(packs_dir, dst)
    path = dst / "tidewrack" / "pack.yaml"
    data = yaml.safe_load(path.read_text())
    data["gm"]["gm_rolls"] = True
    data["gm"]["fudgeable_procedures"] = ["banded_roll"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return resolve("tidewrack", dst)


def table(pack, seed="fudge-seed", fudging_trait=100, gm=None):
    eng = Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", "ash": "player"},
                                             "gm_traits": {"fudging": fudging_trait},
                                             "determinism": {"gm": gm or {"preset": "standard"}}}, clock=lambda: None)
    choice = {s["id"]: s["options"][0]["id"] for s in pack.get("chargen.steps") or [] if s["kind"] == "choice"}
    eng.create_character("ash", "Ash", choice)
    eng.spawn_entity("foe", "Foe")
    eng.start_session()
    eng.set_scene("fight", flags={"danger": 1}, encounter=True)
    return eng


def act(eng, actor, peek=True):
    """One fudgeable roll per pack: Lanternlight climbs (check); Tidewrack defies danger (banded)."""
    gm = {"peek": peek}
    if eng.pack.id == "lanternlight":
        return eng.commit_action(actor, "climb", target="ledge", gm={**gm, "difficulty": "moderate"},
                                 by="gm" if actor == "foe" else None)
    return eng.commit_action(actor, "defy_danger", gm=gm, by="gm" if actor == "foe" else None)


def frozen(eng):
    return eng.store.head(eng.campaign_id), hash_obj(eng.state)


def events(eng, kind):
    return [e for e in eng.store.read(eng.campaign_id) if e["type"] == kind]


# ---------------------------------------------------------------- the pause

def test_a_peek_pauses_the_action_until_the_gm_settles(lantern):
    eng = table(lantern)
    out = act(eng, "ash")
    assert out["pending"]["procedure"] == "check" and "outcome" not in out
    assert events(eng, "procedure_resolved") == [] and len(events(eng, "roll_peeked")) == 1
    before = frozen(eng)
    for blocked in (lambda: act(eng, "ash", peek=False), lambda: eng.set_scene("next"), lambda: eng.end_session()):
        with pytest.raises(EngineError, match="waiting for the GM"):
            blocked()
        assert frozen(eng) == before
    with pytest.raises(EngineError, match="only the GM"):
        eng.peek_roll("keep", by="ash")
    settled = eng.peek_roll("keep")
    assert settled["outcome"] == out["pending"]["outcome"]
    resolved = events(eng, "procedure_resolved")[0]["payload"]
    assert resolved["roll_seq"] == events(eng, "roll_peeked")[0]["payload"]["roll_seq"]
    with pytest.raises(EngineError, match="no peeked roll"):
        eng.peek_roll("keep")


def test_keeping_a_peek_matches_not_peeking(lantern):
    peeked, plain = table(lantern), table(lantern)
    act(peeked, "ash")
    peeked.peek_roll("keep")
    act(plain, "ash", peek=False)
    strip = lambda e: {k: v for k, v in e.items() if k not in ("fudging",)}  # noqa: E731
    assert strip(peeked.state)["entities"] == strip(plain.state)["entities"]


# ---------------------------------------------------------------- direction of drama (§5.5)

def _reroll_rank(eng):
    """The outcome rank a reroll would produce, derived independently from the seed."""
    p = eng.state["fudging"]["pending"]
    counter = eng.state["roll_counter"]
    total = dice.evaluate(p["expression"], p["variables"], lambda sub, lo, hi: eng.rng.integer(counter, sub, lo, hi)).total
    return eng._scale(p["procedure"]).index(eng._interpret(p["procedure"], total, p["difficulty"]))


@pytest.mark.parametrize("pack_name", ["lantern", "tide_rolls"])
@pytest.mark.parametrize("actor", ["ash", "foe"])
def test_rerolls_never_lower_the_party_side_rank(request, pack_name, actor):
    pack = request.getfixturevalue(pack_name)
    allowed = refused = 0
    for i in range(40):
        eng = table(pack, f"seed-{i}")
        act(eng, actor)
        p = eng.state["fudging"]["pending"]
        new_rank = _reroll_rank(eng)
        lowers = eng._party_rank(actor, new_rank, p["ranks"]) < p["party_rank"]
        before = frozen(eng)
        if lowers:
            with pytest.raises(EngineError, match="direction of drama"):
                eng.peek_roll("reroll")
            assert frozen(eng) == before
            refused += 1
            eng.peek_roll("keep")
        else:
            eng.peek_roll("reroll")
            fudged = events(eng, "roll_fudged")[0]["payload"]
            assert fudged["to_rank"] == new_rank
            assert events(eng, "procedure_resolved")[0]["payload"]["roll_seq"] == fudged["to_roll_seq"]
            allowed += 1
        assert verify(eng.store, eng.campaign_id, pack, f"seed-{i}") == []  # every roll re-derives
        assert hash_obj(fold(eng.store.read(eng.campaign_id))) == eng.state_hash()
    assert allowed and refused  # both branches exercised on this scale and side


def test_the_party_side_mirrors_for_gm_entities(lantern):
    eng = table(lantern)
    assert eng._party_rank("ash", 1, 2) == 1 and eng._party_rank("foe", 1, 2) == 0  # a foe's success is bad news


# ---------------------------------------------------------------- availability

def test_the_fudging_trait_caps_peeks_per_session(lantern):
    assert [fudging.peek_cap(t) for t in (0, 24, 25, 50, 100)] == [0, 0, 1, 2, 4]
    eng = table(lantern, fudging_trait=25)
    act(eng, "ash")
    eng.peek_roll("keep")
    with pytest.raises(EngineError, match="no peeks left"):
        act(eng, "ash")
    eng.end_session()
    eng.start_session()
    eng.set_scene("again", encounter=True)
    assert eng.peeks_left() == 1
    with pytest.raises(EngineError, match="no peeks left"):
        act(table(lantern, fudging_trait=0), "ash")


def test_peeks_are_refused_where_fudging_does_not_exist(lantern, tide):
    with pytest.raises(EngineError, match="strict"):
        act(table(lantern, gm={"preset": "strict"}), "ash")
    with pytest.raises(EngineError, match="never rolls"):
        act(table(tide), "ash")
    eng = table(lantern)
    with pytest.raises(EngineError, match="no roll to peek at"):
        eng.resolve_unmodelled("ash", "automatic", peek=True)
    with pytest.raises(EngineError, match="not fudgeable"):
        eng._open_peek({"procedure": "automatic"}, None)


def test_unmodelled_resolutions_can_be_peeked(lantern):
    eng = table(lantern)
    out = eng.resolve_unmodelled("ash", "check", stat="wits", difficulty="easy", peek=True)
    assert out["pending"]["procedure"] == "check"
    assert eng.peek_roll("keep")["outcome"] in ("pass", "fail")


def test_the_tool_is_absent_where_fudging_is_off(lantern, tide, tide_rolls):
    std = table(lantern).state["determinism"]["effective"]
    strict = table(lantern, gm={"preset": "strict"}).state["determinism"]["effective"]
    assert generate(lantern, std, "gm")["peek_roll"] == {"decision": {"enum": ["keep", "reroll"]}}
    assert generate(lantern, std, "gm")["rule_on_action"]["peek"] == {"type": "boolean"}
    assert "peek_roll" not in generate(lantern, strict, "gm")
    assert "peek" not in generate(lantern, strict, "gm")["rule_on_action"]
    assert "peek_roll" not in generate(tide, std, "gm")  # the GM never rolls
    assert "peek_roll" in generate(tide_rolls, std, "gm")
    assert "peek_roll" not in generate(lantern, std, "players")


# ---------------------------------------------------------------- live cards stay quiet (§8.6)

def test_live_cards_show_only_the_final_roll(lantern):
    for i in range(40):  # find a seed whose reroll is allowed and changes the total
        eng = table(lantern, f"card-{i}")
        act(eng, "ash")
        p = eng.state["fudging"]["pending"]
        if eng._party_rank("ash", _reroll_rank(eng), p["ranks"]) >= p["party_rank"]:
            eng.peek_roll("reroll")
            fudged = events(eng, "roll_fudged")[0]["payload"]
            if fudged["from_total"] != fudged["to_total"]:
                break
    else:
        raise AssertionError("no suitable seed")
    card = CardRenderer(list(eng.store.read(eng.campaign_id)), lantern).all_cards()[-1]
    assert f"= {fudged['to_total']}" in card and f"= {fudged['from_total']}" not in card
    assert not any(word in card.lower() for word in ("peek", "fudge", "reroll"))

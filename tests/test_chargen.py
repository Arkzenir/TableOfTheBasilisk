"""Chargen and sheet guarantees (T0.19; ARCHITECTURE §1.5, §5.4; BUILD_PLAN P0.8, P0.7)."""

import copy
import random

import pytest

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError
from basilisk.kernel.entities import allocate_points
from basilisk.kernel.packs import discover, resolve
from conftest import PACKS

PLAYABLE = sorted(p for p in discover(PACKS) if not resolve(p, PACKS).data["meta"]["abstract"])
SEATS = ("p1", "p2", "p3", "p4")


def table(pack, seed):
    return Engine.start_campaign(pack, seed, {"seats": {"gm": "gm", **{s: "player" for s in SEATS}}},
                                 clock=lambda: None)


def random_choices(pack, rng, taken):
    out = {}
    for step in pack.get("chargen.steps") or []:
        if step["kind"] == "choice":
            opts = [o["id"] for o in step["options"] if not step.get("unique_per_table") or o["id"] not in taken]
            out[step["id"]] = rng.choice(opts)
            if step.get("unique_per_table"):
                taken.add(out[step["id"]])
        elif step["kind"] == "points":  # raise the stats in a random order
            order = list(step["targets"])
            rng.shuffle(order)
            out[step["id"]] = allocate_points(step, order)
        elif step["kind"] == "assign":
            values = list(step["values"])
            rng.shuffle(values)
            out[step["id"]] = dict(zip(step["targets"], values))
    return out


# ---------------------------------------------------------------- assign steps (§1.5)

def test_assign_places_the_array_and_logs_the_choice(packs_dir):
    pack = resolve("lanternlight_house", packs_dir)
    eng = table(pack, "assign")
    arrangement = {"might": -1, "grace": 2, "wits": 1, "heart": 0}
    eng.create_character("p1", "One", {"stats": arrangement, "background": "acolyte"})
    stats = eng.state["entities"]["p1"]["stats"]
    assert stats == {**arrangement, "heart": 2}  # the background choice then sets Heart, as the pack says
    judged = [e["payload"] for e in eng.store.read(eng.campaign_id) if e["type"] == "judgement_input"
              and e["payload"]["control"] == "chargen_assign"]
    assert judged[0]["choice"] == arrangement and judged[0]["options"] == [2, 1, 0, -1]
    assert not [e for e in eng.store.read(eng.campaign_id) if e["type"] == "roll_made"
                and e["payload"]["purpose"].startswith("chargen:stats")]  # nothing rolled for stats


@pytest.mark.parametrize("bad, message", [
    ({"might": 2, "grace": 1, "wits": 0}, "assign each of"),                     # a stat left out
    ({"might": 2, "grace": 2, "wits": 0, "heart": -1}, "each used once"),        # a value used twice
    ({"might": 3, "grace": 1, "wits": 0, "heart": -1}, "each used once"),        # a value not in the array
    ([2, 1, 0, -1], "assign each of"),                                           # not a mapping
])
def test_bad_assignments_are_refused_atomically(packs_dir, bad, message):
    pack = resolve("lanternlight_house", packs_dir)
    eng = table(pack, "assign-bad")
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    with pytest.raises(EngineError, match=message):
        eng.create_character("p1", "One", {"stats": bad, "background": "acolyte"})
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before


# ---------------------------------------------------------------- 1,000 characters per pack (P0.8)

@pytest.mark.parametrize("pack_id", PLAYABLE)
def test_a_thousand_generated_characters_are_all_valid(pack_id):
    pack = resolve(pack_id, PACKS)
    rng = random.Random(pack_id)
    made = 0
    for table_no in range(250):  # four characters per table: unique-per-table choices stay satisfiable
        eng = table(pack, f"{pack_id}-{table_no}")
        taken: set = set()
        for seat in SEATS:
            eng.create_character(seat, seat.upper(), random_choices(pack, rng, taken))
            assert eng.sheet_problems(seat) == [], (pack_id, table_no, seat)
            made += 1
    assert made == 1000


def test_unique_per_table_cannot_be_taken_twice(lantern):
    eng = table(lantern, "unique")
    eng.create_character("p1", "One", {"background": "soldier"})
    with pytest.raises(EngineError, match="already taken"):
        eng.create_character("p2", "Two", {"background": "soldier"})


# ---------------------------------------------------------------- read views cannot mutate (§5.4)

def _scramble(obj):
    """Mutate everything reachable in a returned value."""
    if isinstance(obj, dict):
        for k in list(obj):
            _scramble(obj[k])
            obj[k] = "tampered"
        obj["injected"] = 1
    elif isinstance(obj, list):
        for item in obj:
            _scramble(item)
        obj.append("injected")
        obj.reverse()


def test_read_views_cannot_change_state(lantern):
    eng = table(lantern, "reads")
    eng.create_character("p1", "One", {"background": "soldier"})
    eng.create_character("p2", "Two", {"background": "scholar"})
    eng.start_session()
    eng.set_scene("z", regions=[{"id": "a", "adjacency": ["b"]}, {"id": "b"}], placements={"p1": "a", "p2": "b"})
    eng.write_canon({"type": "fact", "name": "The bell", "body": "It rings.", "knowledge": "revealed",
                     "origin": "improvised"})
    before = (eng.store.head(eng.campaign_id), hash_obj(eng.state))
    snapshot = copy.deepcopy(eng.state)
    for read in (lambda: eng.read_sheet("p1"), lambda: eng.read_party_sheets("p1"),
                 lambda: eng.read_party_sheets("gm"), lambda: eng.full_sheet("p2"), lambda: eng.scene_view("p1"),
                 lambda: eng.query_canon("p1", "bell"), lambda: eng.enumerate_moves("p1", 100),
                 lambda: eng.enumerate_action_candidates("p1", 100), lambda: eng.preview("p1", "strike", 100)):
        _scramble(read())
    assert (eng.store.head(eng.campaign_id), hash_obj(eng.state)) == before
    assert eng.state == snapshot

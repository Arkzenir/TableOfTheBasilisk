"""Canon store (T0.2 · §1.3, §6.2, §6.5 Layers 0–1)."""

import random

import pytest

from basilisk.kernel.canonical import hash_obj
from basilisk.kernel.engine import Engine, EngineError, fold
from basilisk.kernel.tools import free_values, generate
from conftest import new_campaign


def rec(type_, name, knowledge="revealed", origin="prepped", **extra):
    return {"type": type_, "name": name, "body": f"{name}: one fact.", "knowledge": knowledge,
            "origin": origin, **extra}


def tithe_world(eng):
    eng.start_session()
    eng.write_canon(rec("faction", "The Counting Order"))
    eng.write_canon(rec("location", "The Tithe House", depends_on=["faction_counting_order"]))
    eng.write_canon(rec("npc", "Varro the Tithekeeper", aliases=["the Tithekeeper", "that tax man"],
                        depends_on=["location_tithe_house", "faction_counting_order"]))
    eng.write_canon(rec("fact", "Varro skims the tithe", "secret", depends_on=["npc_varro_tithekeeper"],
                        discovery_paths=["npc_varro_tithekeeper"]))
    eng.write_canon(rec("location", "Gull Quay", depends_on=["location_tithe_house"]))
    return eng


SYLLABLES = ["ka", "lo", "mir", "ven", "tha", "dru", "sel", "gor", "pim", "zu", "ash", "rel", "on", "qua", "bex"]


def made_up_name(rng, used):
    while True:
        name = " ".join("".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3))).capitalize()
                        for _ in range(2))
        if name.lower() not in used:
            used.add(name.lower())
            return name


def no_trace(eng, fn):
    head, state = eng.store.head(eng.campaign_id), hash_obj(eng.state)
    with pytest.raises(EngineError) as err:
        fn()
    assert eng.store.head(eng.campaign_id) == head and hash_obj(eng.state) == state
    return str(err.value)


def test_player_scope_never_sees_secrets(lantern):
    """200 records, 1,000 player-scoped queries, zero secret records returned."""
    eng = new_campaign(lantern)
    eng.start_session()
    rng = random.Random(20261016)
    ids, names, aliases, used = [], [], [], set()
    for i in range(200):
        knowledge = ("revealed", "suspected", "secret")[i % 3]
        deps = rng.sample(ids, k=min(2, len(ids)))
        extra = {"discovery_paths": deps} if knowledge == "secret" else {}
        name, alias = made_up_name(rng, used), made_up_name(rng, used)
        out = eng.write_canon(rec(("npc", "location", "faction", "item", "fact", "thread", "event")[i % 7],
                                  name, knowledge, aliases=[alias], depends_on=deps, **extra))
        ids.append(out["id"])
        names.append(name)
        aliases.append(alias)
    secret_ids = {r for r, v in eng.state["canon"].items() if v["knowledge"] == "secret"}
    assert len(secret_ids) == 66

    # ids, names, aliases, single words (partials), and near-miss spellings
    probes = ids + names + aliases + [n.split()[0] for n in names] + [n[:-1] for n in names]
    leaked = 0
    for n in range(1000):
        result = eng.query_canon(("players", "ash", "bram")[n % 3], rng.choice(probes))
        for r in result["records"]:
            leaked += r["id"] in secret_ids or r["knowledge"] == "secret"
            assert "discovery_paths" not in r
            assert not set(r["depends_on"]) & secret_ids
        assert not set(result.get("suggestions", [])) & secret_ids
    assert leaked == 0
    loc = next(i for i in ids if i.startswith("location_") and i not in secret_ids)
    bundle = eng.scene_bundle(loc, [], scope="ash")
    assert not set(bundle["records"]) & secret_ids and "secrets" not in bundle
    # the GM scope does see them
    assert eng.query_canon("gm", sorted(secret_ids)[0])["records"]


def test_aliases_resolve_partial_and_colloquial_names(lantern):
    eng = tithe_world(new_campaign(lantern))
    for query in ("Varro", "varro", "Varro's", "the Tithekeeper", "Tithekeeper", "that tax man",
                  "the tax man", "tax man", "npc_varro_tithekeeper"):
        found = eng.query_canon("players", query)
        assert [r["id"] for r in found["records"]] == ["npc_varro_tithekeeper"], query
    assert eng.query_canon("ash", "Varro")["via"] == "partial"
    assert eng.query_canon("ash", "that tax man")["via"] == "alias"
    miss = eng.query_canon("ash", "Varo")
    assert miss["records"] == [] and miss["suggestions"] == ["npc_varro_tithekeeper"]
    # the secret about Varro is not even a partial match for players
    assert [r["id"] for r in eng.query_canon("ash", "skims")["records"]] == []
    assert [r["id"] for r in eng.query_canon("gm", "skims")["records"]] == ["fact_varro_skims_tithe"]


def test_collisions_rejected_and_near_collisions_flagged(lantern):
    eng = tithe_world(new_campaign(lantern))
    msg = no_trace(eng, lambda: eng.write_canon(rec("npc", "The Tax Man", origin="improvised")))
    assert "collides with canon record 'npc_varro_tithekeeper'" in msg
    # a player-visible name may not collide with a secret either
    no_trace(eng, lambda: eng.write_canon(rec("thread", "Varro skims the tithe")))
    out = eng.write_canon(rec("npc", "Varro the Tithekeepr", origin="improvised"))
    assert out["flags"] and out["flags"][0]["record"] == "npc_varro_tithekeeper"
    flagged = [e for e in eng.store.read(eng.campaign_id) if e["type"] == "canon_written"][-1]
    assert flagged["payload"]["flags"] == out["flags"]


def test_write_validation(lantern):
    eng = tithe_world(new_campaign(lantern))
    assert "origin 'audience' is not valid" in no_trace(eng, lambda: eng.write_canon(rec("npc", "Mira", origin="audience")))
    assert "type 'monster'" in no_trace(eng, lambda: eng.write_canon(rec("monster", "Mira")))
    assert "unknown canon field 'created_at'" in no_trace(eng, lambda: eng.write_canon(rec("npc", "Mira", created_at=1)))
    assert "Did you mean 'location_gull_quay'" in no_trace(
        eng, lambda: eng.write_canon(rec("npc", "Mira", depends_on=["location_gull_quy"])))
    assert "discovery path" in no_trace(eng, lambda: eng.write_canon(rec("fact", "Mira lies", "secret")))
    assert "only the GM" in no_trace(eng, lambda: eng.write_canon(rec("npc", "Mira"), by="ash"))
    assert "already exists" in no_trace(eng, lambda: eng.write_canon(rec("npc", "Mira", id="location_gull_quay")))
    out = eng.write_canon(rec("npc", "Mira", origin="improvised"), by="engine")
    assert out["id"] == "npc_mira"
    stored = eng.state["canon"]["npc_mira"]
    assert stored["origin"] == "improvised" and stored["established_session"] == 1
    assert stored["established_by"] == "engine" and stored["superseded_by"] is None


def test_no_retcons_mid_session(lantern):
    eng = tithe_world(new_campaign(lantern))  # session 1 is open
    msg = no_trace(eng, lambda: eng.supersede_canon("location_gull_quay", rec("location", "Gull Quay")))
    assert "no retcons mid-session" in msg
    eng.write_canon(rec("npc", "Dockhand Pell", origin="improvised"))  # creating is still fine
    eng.reveal("fact_varro_skims_tithe")  # so is revealing
    eng.end_session()
    eng.supersede_canon("location_gull_quay", rec("location", "Gull Quay"))  # post-session pass
    eng.start_session()
    no_trace(eng, lambda: eng.supersede_canon("npc_dockhand_pell", rec("npc", "Dockhand Pell")))


def test_supersede_before_first_session(lantern):
    eng = new_campaign(lantern)  # Session 0 prep: no session open yet
    eng.write_canon(rec("location", "Gull Quay"))
    assert eng.supersede_canon("location_gull_quay", rec("location", "Gull Quay"))["id"] == "location_gull_quay_2"


def test_supersede_is_append_only_with_history(lantern):
    eng = tithe_world(new_campaign(lantern))
    eng.end_session()
    before = dict(eng.state["canon"]["npc_varro_tithekeeper"])
    out = eng.supersede_canon("npc_varro_tithekeeper", rec(
        "npc", "Varro the Tithekeeper", aliases=["the Tithekeeper", "that tax man", "Old Varro"],
        depends_on=["location_tithe_house"]))
    new = out["id"]
    assert new == "npc_varro_tithekeeper_2"
    old = eng.state["canon"]["npc_varro_tithekeeper"]
    assert old["superseded_by"] == new and {k: v for k, v in old.items() if k != "superseded_by"} == {
        k: v for k, v in before.items() if k != "superseded_by"}
    # names resolve to the current version; the old one stays retrievable by id
    assert [r["id"] for r in eng.query_canon("ash", "Old Varro")["records"]] == [new]
    assert [r["id"] for r in eng.query_canon("ash", "Varro")["records"]] == [new]
    assert eng.query_canon("ash", "npc_varro_tithekeeper")["records"][0]["superseded_by"] == new
    assert [r["id"] for r in eng.canon_history("ash", new)] == ["npc_varro_tithekeeper", new]
    assert [r["id"] for r in eng.canon_history("gm", "npc_varro_tithekeeper")] == ["npc_varro_tithekeeper", new]
    # only the current version can be superseded or depended on
    assert "already superseded" in no_trace(eng, lambda: eng.supersede_canon("npc_varro_tithekeeper", rec("npc", "V")))
    assert f"depend on {new!r}" in no_trace(
        eng, lambda: eng.write_canon(rec("item", "Tithe ledger", depends_on=["npc_varro_tithekeeper"])))
    types = [e["type"] for e in eng.store.read(eng.campaign_id) if e["type"] != "judgement_input"][-2:]  # GM calls are logged (D-044)
    assert types == ["canon_written", "canon_superseded"]


def test_secret_successor_hides_correction_from_players(lantern):
    eng = tithe_world(new_campaign(lantern))
    eng.end_session()
    eng.supersede_canon("location_gull_quay", rec("location", "Gull Quay", "secret",
                                                   discovery_paths=["npc_varro_tithekeeper"]))
    found = eng.query_canon("ash", "Gull Quay")["records"]
    assert [r["id"] for r in found] == ["location_gull_quay"] and found[0]["superseded_by"] is None
    assert [r["id"] for r in eng.query_canon("gm", "Gull Quay")["records"]] == ["location_gull_quay_2"]


def test_reveal_promotes_to_players(lantern):
    eng = tithe_world(new_campaign(lantern))
    assert eng.query_canon("ash", "fact_varro_skims_tithe")["records"] == []
    eng.reveal("fact_varro_skims_tithe")
    found = eng.query_canon("ash", "fact_varro_skims_tithe")["records"]
    assert found[0]["knowledge"] == "revealed" and "discovery_paths" not in found[0]
    assert "already revealed" in no_trace(eng, lambda: eng.reveal("fact_varro_skims_tithe"))
    assert "Did you mean" in no_trace(eng, lambda: eng.reveal("fact_varro_skim_tithe"))
    assert "only the GM" in no_trace(eng, lambda: eng.reveal("location_gull_quay", by="bram"))


def test_scene_bundle_is_graph_walk_with_gm_secrets(lantern):
    eng = tithe_world(new_campaign(lantern))
    head = eng.store.head(eng.campaign_id)
    gm = eng.scene_bundle("location_tithe_house", ["npc_varro_tithekeeper"])
    assert gm["secrets"] == ["fact_varro_skims_tithe"]
    assert gm["by_type"] == {"npc": ["npc_varro_tithekeeper"], "location": ["location_gull_quay", "location_tithe_house"],
                             "faction": ["faction_counting_order"], "fact": ["fact_varro_skims_tithe"]}
    players = eng.scene_bundle("location_tithe_house", ["npc_varro_tithekeeper"], scope="players")
    assert "secrets" not in players and "fact_varro_skims_tithe" not in players["records"]
    assert eng.scene_bundle("location_tithe_house", ["npc_varro_tithekeeper"]) == gm  # pure and repeatable
    assert eng.store.head(eng.campaign_id) == head
    with pytest.raises(EngineError, match="not a location"):
        eng.scene_bundle("npc_varro_tithekeeper", [])
    with pytest.raises(EngineError, match="Did you mean"):
        eng.scene_bundle("location_tithe_hose", [])
    with pytest.raises(EngineError, match="unknown canon scope"):
        eng.query_canon("audience", "Varro")


def test_replay_is_byte_identical(lantern):
    eng = tithe_world(new_campaign(lantern))
    eng.end_session()
    eng.supersede_canon("location_gull_quay", rec("location", "Gull Quay", aliases=["the quay"]))
    eng.reveal("fact_varro_skims_tithe")
    events = list(eng.store.read(eng.campaign_id))
    assert hash_obj(fold(events)) == eng.state_hash()
    loaded = Engine.load(lantern, "test-seed", eng.store, eng.campaign_id, clock=lambda: None)
    assert loaded.state_hash() == eng.state_hash()
    assert loaded.query_canon("ash", "the quay") == eng.query_canon("ash", "the quay")


def test_logs_without_canon_fold_unchanged(lantern):
    eng = new_campaign(lantern)
    eng.start_session()
    assert "canon" not in eng.state  # existing logs keep their state hash; no kernel bump


def test_canon_tools_in_schema(lantern, tide):
    for pack in (lantern, tide):
        players = generate(pack, new_campaign(pack).state["determinism"]["effective"], "players")
        gm = generate(pack, new_campaign(pack).state["determinism"]["effective"], "gm")
        assert "query_canon" in players and "write_canon" not in players and "reveal" not in players
        assert {"query_canon", "write_canon", "reveal"} <= set(gm)
        assert not free_values(gm["write_canon"])


def test_digest_stub_is_scoped(lantern):
    eng = tithe_world(new_campaign(lantern))
    eng.write_canon(rec("thread", "Who sank the ledger barge", "secret", discovery_paths=["npc_varro_tithekeeper"]))
    players, gm = eng.canon_digest("ash"), eng.canon_digest("gm")
    assert players["npc"] == ["Varro the Tithekeeper: Varro the Tithekeeper: one fact."]
    assert players["thread"] == [] and len(gm["thread"]) == 1

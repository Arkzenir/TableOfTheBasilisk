"""The shipped sectioned fixture pack (T0.15; BUILD_PLAN P0.6, P0.13; ARCHITECTURE §2.8, §2.11)."""

import pytest

from basilisk.harness.scripted import run_script, smoke_script
from basilisk.kernel.engine import Engine
from basilisk.kernel.packlint import errors, lint, readiness
from basilisk.kernel.packs import resolve

PACK = "lanternlight_sectioned"


@pytest.fixture(scope="module")
def pair(packs_dir):
    return resolve("lanternlight", packs_dir), resolve(PACK, packs_dir)


def test_it_is_lanternlight_with_only_the_rules_text_changed(pair):
    parent, child = pair
    assert child.lineage[-2:] == ["lanternlight@0.1.0", f"{PACK}@0.1.0"]
    strip = lambda d: {k: v for k, v in d.items() if k not in ("meta", "rules_text")}  # noqa: E731
    assert strip(child.data) == strip(parent.data)
    assert child.get("rules_text.mode") == "sectioned" and parent.get("rules_text.mode") == "inline"


def test_conformance_with_no_kernel_change(pair):
    parent, child = pair
    assert errors(lint(child)) == []
    assert readiness(child) == readiness(parent)


def _stream(engine):
    """The event stream with pack identity and rules lookups set aside."""
    out = []
    for ev in engine.store.read(engine.campaign_id):
        payload = dict(ev["payload"])
        if ev["type"] == "campaign_started":
            for key in ("campaign_id", "pack_id", "pack_hash"):
                payload.pop(key)
        if ev["type"] == "rules_queried":
            payload = {k: payload[k] for k in ("seat", "query")}  # the answer differs; the lookup does not
        out.append((ev["seq"], ev["type"], ev["actor"], ev["caused_by"], ev["session_id"], ev["scene_id"], payload))
    return out


def test_its_campaign_matches_the_parent_event_for_event(pair, packs_dir):
    parent, child = pair
    a, _ = run_script(smoke_script(parent), packs_dir)
    b, report = run_script(smoke_script(child), packs_dir)
    assert not report.actions_never_taken
    assert _stream(a) == _stream(b)
    lookups = [e["payload"] for e in b.store.read(b.campaign_id) if e["type"] == "rules_queried"]
    inline = [e["payload"] for e in a.store.read(a.campaign_id) if e["type"] == "rules_queried"]
    assert lookups and all(p["via"] == "ref" and p["sections"] for p in lookups)  # sectioned: found by rule id
    assert all(p["via"] is None for p in inline)  # inline: already in context


def test_every_section_is_reachable_by_id_and_alias(pair):
    _, child = pair
    eng = Engine.start_campaign(child, "seed", {"seats": {"gm": "gm", "ash": "player"}}, clock=lambda: None)
    for s in child.get("rules_text.sections"):
        assert [x["id"] for x in eng.query_rules("ash", s["id"])["sections"]] == [s["id"]]
        for name in [s["title"], *s.get("aliases", [])]:
            assert s["id"] in [x["id"] for x in eng.query_rules("ash", name)["sections"]], name
    for action in child.catalogue("actions"):
        hit = eng.query_rules("ash", action["id"])
        assert hit["via"] == "ref" and hit["sections"][0]["parent"] == "actions"
    assert eng.rules_layer().startswith("LANTERNLIGHT (demo), digest")

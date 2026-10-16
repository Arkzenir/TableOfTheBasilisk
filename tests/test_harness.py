from pathlib import Path

from basilisk.broadcast.cards import CardRenderer
from basilisk.harness.scripted import determinism_check, run_script, smoke_script, verify
from basilisk.kernel.events import EventStore
from basilisk.kernel.packs import resolve
from basilisk.ops.nounlint import run as noun_lint

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_campaigns_all_packs(packs_dir):
    for pid in ("lanternlight", "tidewrack", "lanternlight_house"):
        pack = resolve(pid, packs_dir)
        script = smoke_script(pack, sessions=3)
        engine, report = run_script(script, packs_dir)
        assert report.actions_never_taken == [], pid
        assert report.settings_changes == 2
        assert verify(engine.store, report.campaign_id, pack, script["seed"], report.state_hash) == []
        assert determinism_check(script, packs_dir) == []


def test_different_seeds_diverge(packs_dir, lantern):
    _, a = run_script(smoke_script(lantern, seed="one"), packs_dir)
    _, b = run_script(smoke_script(lantern, seed="two"), packs_dir)
    assert a.head_hash != b.head_hash


def test_seed_verification_detects_wrong_seed(packs_dir, lantern):
    script = smoke_script(lantern)
    engine, report = run_script(script, packs_dir)
    assert verify(engine.store, report.campaign_id, lantern, "not-the-seed")


def test_scenario_file_runs(packs_dir):
    from basilisk.harness.scripted import load_script
    script = load_script(ROOT / "scenarios" / "lanternlight_demo.yaml")
    engine, report = run_script(script, packs_dir)
    assert verify(engine.store, report.campaign_id, engine.pack, script["seed"], report.state_hash) == []
    assert report.rejected  # the scenario includes deliberate refusals


def test_rule_cards_render(packs_dir, tide):
    script = smoke_script(tide, sessions=1)
    engine, report = run_script(script, packs_dir)
    cards = CardRenderer(list(engine.store.read(report.campaign_id)), tide).all_cards()
    assert cards and all(card.startswith("┌") for card in cards)
    assert any("ruling" in c for c in cards)
    widths = {len(line) for card in cards for line in card.splitlines()}
    assert widths == {46}


def test_kernel_noun_lint_clean():
    assert noun_lint(ROOT) == []


def test_kernel_noun_lint_detects_pollution(tmp_path):
    import shutil
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copytree(ROOT / "packs", tmp_path / "packs")
    shutil.copytree(ROOT / "tools", tmp_path / "tools")
    bad = tmp_path / "src" / "basilisk" / "kernel" / "bad.py"
    bad.write_text("max_hp = 10  # vigor\n")
    hits = noun_lint(tmp_path)
    assert any("'hp'" in h for h in hits) and any("'vigor'" in h for h in hits)

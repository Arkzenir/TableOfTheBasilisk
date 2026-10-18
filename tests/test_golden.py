"""Golden fixtures (T0.10; ARCHITECTURE §2.10; docs/dev/TESTING.md).

Every playable pack ships `packs/<id>/fixtures/golden.yaml`: scripted runs as
`(seed, script) -> expected log head hash`. A kernel change that alters any
pack's event log fails here. When the change is intended, regenerate them
deliberately and say why in the commit:

    TOB_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py
"""

import os
from pathlib import Path

import pytest
import yaml

from basilisk.harness.scripted import load_script, run_script, smoke_script
from basilisk.kernel.packs import discover, resolve
from conftest import PACKS, ROOT

UPDATE = os.environ.get("TOB_UPDATE_GOLDEN") == "1"
PLAYABLE = sorted(p for p in discover(PACKS) if not resolve(p, PACKS).data["meta"]["abstract"])
HEADER = ("# Golden fixtures (ARCHITECTURE §2.10): (seed, script) -> expected log head.\n"
          "# Regenerate only deliberately: TOB_UPDATE_GOLDEN=1 python -m pytest tests/test_golden.py\n")
SCENARIOS = {"lanternlight": ["scenarios/lanternlight_demo.yaml"]}  # hand-written scenarios that pin a pack


def _path(pack_id: str) -> Path:
    return PACKS / pack_id / "fixtures" / "golden.yaml"


def _default(pack_id: str) -> list[dict]:
    runs = [{"name": "smoke", "script": {"smoke": {"seed": "golden-seed", "sessions": 3, "scenes_per_session": 2}}}]
    runs += [{"name": Path(s).stem, "script": {"scenario": s}} for s in SCENARIOS.get(pack_id, [])]
    return runs


def _run(pack_id: str, script: dict) -> tuple[str, int]:
    pack = resolve(pack_id, PACKS)
    if "smoke" in script:
        spec = script["smoke"]
        full = smoke_script(pack, seed=spec["seed"], sessions=spec["sessions"],
                            scenes_per_session=spec["scenes_per_session"])
    else:
        full = load_script(ROOT / script["scenario"])
    _, report = run_script(full, PACKS)
    return report.head_hash, report.events


@pytest.mark.parametrize("pack_id", PLAYABLE)
def test_golden_fixtures(pack_id):
    path = _path(pack_id)
    if UPDATE:
        runs = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("fixtures") if path.exists() else None
        runs = runs or _default(pack_id)
        for run in runs:
            run["head"], run["events"] = _run(pack_id, run["script"])
        path.parent.mkdir(exist_ok=True)
        path.write_bytes((HEADER + yaml.safe_dump({"fixtures": runs}, sort_keys=False)).encode("utf-8"))
        return
    assert path.exists(), f"{pack_id} has no golden fixtures; create them with TOB_UPDATE_GOLDEN=1"
    runs = yaml.safe_load(path.read_text(encoding="utf-8"))["fixtures"]
    assert runs, f"{path} lists no fixtures"
    for run in runs:
        head, events = _run(pack_id, run["script"])
        assert (head, events) == (run["head"], run["events"]), (
            f"{pack_id}/{run['name']}: the event log changed. If that is intended, regenerate with "
            "TOB_UPDATE_GOLDEN=1 and explain the change in the commit (docs/dev/TESTING.md).")

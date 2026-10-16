"""Soak runner: back-to-back scripted campaigns for hardware and stability testing.

Run on the office PC (systemd unit basilisk-soak.service) during P0-P2: it
exercises the engine for hours, verifies every campaign (hash chain, replay,
seed re-derivation), and stops on the first problem so it is visible.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..harness.scripted import run_script, smoke_script, verify
from ..kernel.events import EventStore
from ..kernel.packs import discover, resolve


def playable_packs(packs_dir: Path) -> list[str]:
    out = []
    for pid in sorted(discover(packs_dir)):
        try:
            resolve(pid, packs_dir, allow_abstract=False)
            out.append(pid)
        except Exception:  # noqa: BLE001 - abstract or broken packs are skipped
            continue
    return out


def soak(packs_dir: Path, data_dir: Path, hours: float, sessions: int = 3) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    log = data_dir / "soak.log.jsonl"
    packs = playable_packs(packs_dir)
    if not packs:
        print("no playable packs")
        return 1
    deadline = time.time() + hours * 3600 if hours > 0 else float("inf")
    i = 0
    while time.time() < deadline:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        store = EventStore(data_dir / f"soak-{day}.db")
        pack_id = packs[i % len(packs)]
        pack = resolve(pack_id, packs_dir)
        seed = f"soak-{day}-{i}"
        t0 = time.time()
        script = smoke_script(pack, seed=seed, sessions=sessions, campaign_id=f"soak-{pack_id}-{int(t0)}-{i}")
        engine, report = run_script(script, packs_dir, store=store)
        problems = verify(store, report.campaign_id, pack, seed, report.state_hash)
        record = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run": i, "pack": pack_id,
            "campaign": report.campaign_id, "events": report.events, "seconds": round(time.time() - t0, 3),
            "state_hash": report.state_hash, "problems": problems,
        }
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        store.close()
        print(json.dumps(record), flush=True)
        if problems:
            return 2
        i += 1
    return 0

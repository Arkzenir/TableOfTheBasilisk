import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from basilisk.kernel.packs import resolve  # noqa: E402

PACKS = ROOT / "packs"


@pytest.fixture(scope="session")
def packs_dir():
    return PACKS


@pytest.fixture(scope="session")
def lantern():
    return resolve("lanternlight", PACKS)


@pytest.fixture(scope="session")
def tide():
    return resolve("tidewrack", PACKS)


def new_campaign(pack, determinism=None, seed="test-seed"):
    from basilisk.kernel.engine import Engine
    eng = Engine.start_campaign(pack, seed, {
        "seats": {"gm": "gm", "ash": "player", "bram": "player"},
        "determinism": determinism or {},
    }, clock=lambda: None)
    return eng


def pytest_collection_modifyitems(config, items):
    """Live provider tests cost money and need network: opt in with TOB_LIVE=1 (docs/dev/TESTING.md)."""
    if os.environ.get("TOB_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live provider test; set TOB_LIVE=1 (and ask the owner first)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """The default run makes zero network calls (AGENTS.md, §3.3): any attempt to
    open a connection fails the test, so the rule is enforced, not hoped for.
    Tests marked `live` (opt-in with TOB_LIVE=1) are exempt."""
    if "live" in request.keywords:
        return
    import socket

    def refuse(*args, **kwargs):
        raise RuntimeError("network access in an offline test; mark it @pytest.mark.live (docs/dev/TESTING.md)")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

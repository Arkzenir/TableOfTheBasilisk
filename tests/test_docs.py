"""Keep agent-facing docs and code in sync (docs/dev/TESTING.md, 'Docs consistency')."""

import re
from pathlib import Path

from basilisk.kernel.engine import EVENT_TYPES

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "basilisk"
STATUSES = {"ready", "in-progress", "done", "blocked", "human", "deferred"}


def documented_events() -> set[str]:
    text = (ROOT / "docs" / "dev" / "EVENTS.md").read_text(encoding="utf-8")
    return set(re.findall(r"^\| `([a-z_]+)` \|", text, re.M))


def emitted_events() -> set[str]:
    found = set()
    for path in SRC.rglob("*.py"):
        found |= set(re.findall(r"_emit\(\s*\"([a-z_]+)\"", path.read_text(encoding="utf-8")))
    # raw event dicts are built only in the event store (e.g. campaign_forked)
    events_py = (SRC / "kernel" / "events.py").read_text(encoding="utf-8")
    found |= set(re.findall(r"\"type\":\s*\"([a-z_]+)\"", events_py))
    return found


def test_event_registry_matches_docs():
    documented = documented_events()
    assert documented == set(EVENT_TYPES), (
        f"missing from EVENTS.md: {sorted(set(EVENT_TYPES) - documented)}; "
        f"documented but not in EVENT_TYPES: {sorted(documented - set(EVENT_TYPES))}"
    )


def test_every_emitted_event_is_registered():
    unregistered = emitted_events() - set(EVENT_TYPES)
    assert not unregistered, f"emitted but not in EVENT_TYPES: {sorted(unregistered)}"


def test_task_statuses_are_valid():
    text = (ROOT / "docs" / "dev" / "TASKS.md").read_text(encoding="utf-8")
    headings = re.findall(r"^### (T\d+\.\d+[a-z]?) .*$", text, re.M)
    assert headings, "no tasks found"
    for line in re.findall(r"^### T\d+\.\d+[a-z]? .*$", text, re.M):
        statuses = set(re.findall(r"`([a-z-]+)`", line))
        assert statuses & STATUSES, f"task heading without a valid status: {line}"
        assert statuses <= STATUSES, f"unknown status in: {line}"


def test_agent_instructions_present():
    assert (ROOT / "AGENTS.md").exists()
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").startswith("@AGENTS.md")

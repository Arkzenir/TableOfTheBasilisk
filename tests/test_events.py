import sqlite3

import pytest

from basilisk.kernel.events import EventStore, EventStoreError


def ev(t, **payload):
    return {"campaign_id": "c", "type": t, "actor": "engine", "payload": payload}


def test_append_chain_and_tamper_detection(tmp_path):
    store = EventStore(tmp_path / "e.db")
    for i in range(10):
        store.append(ev("x", i=i))
    assert store.verify_chain("c") == []
    with pytest.raises(sqlite3.DatabaseError):
        store.db.execute("UPDATE events SET body='{}' WHERE seq=3")
    with pytest.raises(sqlite3.DatabaseError):
        store.db.execute("DELETE FROM events WHERE seq=3")
    # tamper by bypassing the trigger: detection must still work
    store.db.execute("DROP TRIGGER events_no_update")
    store.db.execute("UPDATE events SET body=replace(body, '\"i\":3', '\"i\":4') WHERE seq=4")
    assert any("hash mismatch" in p for p in store.verify_chain("c"))


def test_transactions_roll_back():
    store = EventStore()
    store.append(ev("x"))
    store.begin()
    store.append(ev("y"))
    store.rollback()
    assert store.head("c")[0] == 1


def test_fork_and_snapshot():
    store = EventStore()
    for i in range(5):
        store.append(ev("x", i=i))
    assert store.fork("c", 3, "c2") == 3
    events = list(store.read("c2"))
    assert len(events) == 4 and events[-1]["type"] == "campaign_forked"
    assert store.verify_chain("c2") == []
    with pytest.raises(EventStoreError):
        store.fork("c", 3, "c2")
    store.write_snapshot("c", 5, {"k": 1}, "ph", "0.1.0")
    assert store.latest_snapshot("c")["state"] == {"k": 1}


def test_backup(tmp_path):
    store = EventStore(tmp_path / "a.db")
    store.append(ev("x"))
    store.backup_to(tmp_path / "b.db")
    assert EventStore(tmp_path / "b.db").verify_chain("c") == []

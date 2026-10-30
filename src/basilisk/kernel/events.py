"""Event store (§5.6, §5.7).

Append-only. Every event is hash-chained to the one before it in its campaign,
so tampering or truncation is detectable. Current state is always a fold over
the log; snapshots are caches, never the source of truth. There is no update
or delete path.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterator

from .canonical import canonical, sha256_hex

GENESIS = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    campaign_id TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    body        TEXT NOT NULL,
    prev_hash   TEXT NOT NULL,
    hash        TEXT NOT NULL,
    PRIMARY KEY (campaign_id, seq)
);
CREATE TABLE IF NOT EXISTS snapshots (
    campaign_id    TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    state          TEXT NOT NULL,
    state_hash     TEXT NOT NULL,
    pack_hash      TEXT NOT NULL,
    kernel_version TEXT NOT NULL,
    PRIMARY KEY (campaign_id, seq)
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
"""

EVENT_FIELDS = ("seq", "ts", "campaign_id", "session_id", "scene_id", "actor", "type", "payload", "caused_by")


class EventStoreError(RuntimeError):
    pass


def event_hash(prev_hash: str, body: dict) -> str:
    return sha256_hex(prev_hash + canonical(body))


class EventStore:
    def __init__(self, path: str | Path = ":memory:", create: bool = True):
        """Open an event store. With `create=False` a missing file is an error,
        so a mistyped path is never mistaken for an empty, healthy store."""
        self.path = str(path)
        if not create and self.path != ":memory:" and not Path(self.path).is_file():
            raise EventStoreError(f"no event store at {self.path}")
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL" if self.path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(_SCHEMA)
        self._txn_depth = 0

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------ transactions

    def begin(self) -> None:
        if self._txn_depth == 0:
            self.db.execute("BEGIN")
        self._txn_depth += 1

    def commit(self) -> None:
        self._txn_depth -= 1
        if self._txn_depth == 0:
            self.db.commit()

    def rollback(self) -> None:
        self._txn_depth = 0
        self.db.rollback()

    # ------------------------------------------------------------ writing

    def head(self, campaign_id: str) -> tuple[int, str]:
        row = self.db.execute(
            "SELECT seq, hash FROM events WHERE campaign_id=? ORDER BY seq DESC LIMIT 1", (campaign_id,)
        ).fetchone()
        return (row[0], row[1]) if row else (0, GENESIS)

    def append(self, event: dict) -> dict:
        """Append an event. `seq` is assigned here; the stored event is returned."""
        body = {k: event.get(k) for k in EVENT_FIELDS if k != "seq"}
        if not body["campaign_id"] or not body["type"]:
            raise EventStoreError("events need campaign_id and type")
        last_seq, prev = self.head(body["campaign_id"])
        body["seq"] = last_seq + 1
        h = event_hash(prev, body)
        self.db.execute(
            "INSERT INTO events (campaign_id, seq, body, prev_hash, hash) VALUES (?,?,?,?,?)",
            (body["campaign_id"], body["seq"], canonical(body), prev, h),
        )
        if self._txn_depth == 0:
            self.db.commit()
        return {**body, "prev_hash": prev, "hash": h}

    # ------------------------------------------------------------ reading

    def campaigns(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT campaign_id FROM events ORDER BY campaign_id")]

    def read(self, campaign_id: str, after: int = 0, upto: int | None = None) -> Iterator[dict]:
        q = "SELECT body, prev_hash, hash FROM events WHERE campaign_id=? AND seq>?"
        args: list = [campaign_id, after]
        if upto is not None:
            q += " AND seq<=?"
            args.append(upto)
        for body, prev, h in self.db.execute(q + " ORDER BY seq", args):
            yield {**json.loads(body), "prev_hash": prev, "hash": h}

    def verify_chain(self, campaign_id: str) -> list[str]:
        """Return a list of problems; empty means the chain is intact."""
        problems = []
        prev = GENESIS
        expected_seq = 1
        for ev in self.read(campaign_id):
            body = {k: ev[k] for k in EVENT_FIELDS}
            if ev["seq"] != expected_seq:
                problems.append(f"gap: expected seq {expected_seq}, found {ev['seq']}")
            if ev["prev_hash"] != prev:
                problems.append(f"seq {ev['seq']}: prev_hash does not match")
            if event_hash(prev, body) != ev["hash"]:
                problems.append(f"seq {ev['seq']}: hash mismatch (body altered)")
            prev = ev["hash"]
            expected_seq += 1
        return problems

    # ------------------------------------------------------------ snapshots

    def write_snapshot(self, campaign_id: str, seq: int, state: dict, pack_hash: str, kernel_version: str) -> str:
        text = canonical(state)
        h = sha256_hex(text)
        self.db.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?)",
            (campaign_id, seq, text, h, pack_hash, kernel_version),
        )
        if self._txn_depth == 0:
            self.db.commit()
        return h

    def latest_snapshot(self, campaign_id: str, at_or_before: int | None = None) -> dict | None:
        q = "SELECT seq, state, state_hash, pack_hash, kernel_version FROM snapshots WHERE campaign_id=?"
        args: list = [campaign_id]
        if at_or_before is not None:
            q += " AND seq<=?"
            args.append(at_or_before)
        row = self.db.execute(q + " ORDER BY seq DESC LIMIT 1", args).fetchone()
        if not row:
            return None
        seq, state, sh, ph, kv = row
        if sha256_hex(state) != sh:
            raise EventStoreError(f"snapshot at seq {seq} is corrupt")
        return {"seq": seq, "state": json.loads(state), "state_hash": sh, "pack_hash": ph, "kernel_version": kv}

    # ------------------------------------------------------------ fork / backup

    def fork(self, campaign_id: str, at_seq: int, new_campaign_id: str) -> int:
        """Copy events 1..at_seq into a new campaign (re-chained), then mark the fork.
        Fork is for debugging and recovery, never editorial use (§5.6, P6)."""
        if self.head(new_campaign_id)[0]:
            raise EventStoreError(f"campaign {new_campaign_id} already exists")
        head = self.head(campaign_id)[0]
        if isinstance(at_seq, bool) or not isinstance(at_seq, int) or not 1 <= at_seq <= head:
            raise EventStoreError(f"fork seq must be from 1 to {head} (campaign {campaign_id} has {head} events)")
        if any(ev["type"] == "campaign_concluded" for ev in self.read(campaign_id, upto=at_seq)):
            raise EventStoreError(f"campaign {campaign_id} has concluded by seq {at_seq}; fork at an earlier seq")
        self.begin()  # all or nothing: a half-copied fork would read as a real campaign
        try:
            for ev in self.read(campaign_id, upto=at_seq):
                copied = {k: ev[k] for k in EVENT_FIELDS}
                copied["campaign_id"] = new_campaign_id
                self.append(copied)
            self.append({
                "campaign_id": new_campaign_id, "type": "campaign_forked", "actor": "operator",
                "ts": None, "session_id": None, "scene_id": None, "caused_by": None,
                "payload": {"source_campaign": campaign_id, "source_seq": at_seq,
                            "source_hash": self._hash_at(campaign_id, at_seq)},
            })
            self.commit()
        except BaseException:
            self.rollback()
            raise
        return at_seq

    def _hash_at(self, campaign_id: str, seq: int) -> str:
        row = self.db.execute("SELECT hash FROM events WHERE campaign_id=? AND seq=?", (campaign_id, seq)).fetchone()
        return row[0] if row else GENESIS

    def backup_to(self, dest: str | Path) -> None:
        """Consistent online copy, safe while the store is being written."""
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(str(dest))) as target:
            self.db.backup(target)

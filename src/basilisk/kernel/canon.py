"""Canon store (§1.3, §6.2, §6.5 Layers 0–1).

Canon records live in folded state under `state["canon"]`, keyed by id. They are
append-only: a correction is a new record plus a `canon_superseded` event that
sets `superseded_by` on the old one, and `reveal` only promotes knowledge.

The alias table, token table, and relation graph are *derived* indexes, rebuilt
deterministically from state by `CanonIndex`. There is one index per scope:

- `gm` sees every record.
- `players` is built from a record set that never contains `secret` records.
  The filter runs at index construction, so no player-scoped query can reach a
  secret however it is phrased (§6.2: enforced by filtering, never instruction).

The `canon` key is created by the first canon event, so logs written before the
store existed fold to exactly the same state.
"""

from __future__ import annotations

import copy
import difflib
import re
from typing import Any, Iterable

from .command import EngineError, _suggest, atomic

RECORD_TYPES = ("npc", "location", "faction", "item", "fact", "thread", "event")
KNOWLEDGE = ("secret", "suspected", "revealed")
ORIGINS = ("prepped", "improvised")  # there is no audience origin (P9)
SCOPES = ("gm", "players")
INPUT_FIELDS = ("id", "type", "name", "aliases", "body", "knowledge", "depends_on", "discovery_paths", "origin")
REQUIRED_FIELDS = ("type", "name", "body", "knowledge", "origin")

EVENT_TYPES = frozenset({"canon_written", "canon_superseded", "fact_revealed"})

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
NEAR_CUTOFF = 85  # percent similarity at which two names are flagged as a near-collision
BUNDLE_RADIUS = 2  # hops from the scene's seeds in the relation graph
# Words that carry no identity: "the Tithekeeper", "that tax man", "a tax man" all
# reduce to the same key.
FILLER = frozenset({"a", "an", "the", "that", "this", "these", "those", "of", "some"})


# ====================================================================== names

def tokens(text: str) -> list[str]:
    """Lowercase word tokens with possessives and punctuation removed."""
    text = re.sub(r"['’]s\b", "", str(text).lower())
    return re.findall(r"[a-z0-9]+", text)


def name_keys(text: str) -> set[str]:
    """Alias-table keys for one name: the full normalised form and the form
    without filler words."""
    words = tokens(text)
    keys = {" ".join(words), " ".join(w for w in words if w not in FILLER)}
    keys.discard("")
    return keys


def _names(rec: dict) -> list[str]:
    return [rec["name"], *rec.get("aliases", [])]


def _slug(text: str) -> str:
    words = [w for w in tokens(text) if w not in FILLER] or tokens(text) or ["record"]
    return "_".join(words)[:48].strip("_")


# ====================================================================== reducer

def apply_event(state: dict, ev: dict) -> None:
    """Fold one canon event. Called from `engine.apply_event`."""
    t, p = ev["type"], ev.get("payload") or {}
    records = state.setdefault("canon", {})
    if t == "canon_written":
        rec = copy.deepcopy(p["record"])
        rec["created_at"] = ev["seq"]
        records[rec["id"]] = rec
    elif t == "canon_superseded":
        records[p["old"]]["superseded_by"] = p["new"]
    elif t == "fact_revealed":
        records[p["id"]]["knowledge"] = "revealed"
    else:
        raise EngineError(f"not a canon event: {t!r}")


# ====================================================================== index

def _fingerprint(records: dict) -> tuple:
    # Only these fields of a stored record change after it is written; atomic
    # rollback clears the cache, since a rolled-back id and seq can be reused.
    return tuple((rid, r["superseded_by"], r["knowledge"]) for rid, r in records.items())


class CanonIndex:
    """Derived lookup tables for one scope (§6.5 Layer 0). Pure function of the
    canon records it is built from."""

    def __init__(self, records: dict[str, dict], scope: str):
        self.scope = scope
        if scope == "players":
            visible = {rid: r for rid, r in records.items() if r["knowledge"] != "secret"}
        else:
            visible = dict(records)
        self.records: dict[str, dict] = {rid: self._present(r, records, visible, scope) for rid, r in visible.items()}
        self.predecessor: dict[str, str] = {}
        for rid, rec in self.records.items():
            if rec["superseded_by"]:
                self.predecessor[rec["superseded_by"]] = rid
        self.current = [rid for rid, rec in self.records.items() if not rec["superseded_by"]]

        self.aliases: dict[str, list[str]] = {}
        self.tokens: dict[str, set[str]] = {}
        for rid in self.current:
            for name in _names(self.records[rid]):
                for key in sorted(name_keys(name)):
                    if rid not in self.aliases.setdefault(key, []):
                        self.aliases[key].append(rid)
                for word in tokens(name):
                    if word not in FILLER:
                        self.tokens.setdefault(word, set()).add(rid)

        graph: dict[str, set[str]] = {rid: set() for rid in self.current}
        for rid in self.current:
            rec = self.records[rid]
            for other in [*rec["depends_on"], *rec.get("discovery_paths", [])]:
                other = self.successor(other)
                if other in graph and other != rid:
                    graph[rid].add(other)
                    graph[other].add(rid)
        self.graph = {rid: sorted(n) for rid, n in graph.items()}
        self._sorted_keys: tuple[list[str], list[str]] | None = None

    @staticmethod
    def _present(rec: dict, records: dict, visible: dict, scope: str) -> dict:
        """The record as this scope sees it. Players never see discovery paths,
        never see ids of records absent from their index, and see the first
        visible successor in a supersede chain (none if every successor is
        secret: the table still holds the old belief)."""
        out = copy.deepcopy(rec)
        if scope == "gm":
            return out
        out.pop("discovery_paths", None)
        out["depends_on"] = [d for d in out["depends_on"] if d in visible]
        nxt, seen = out["superseded_by"], set()
        while nxt is not None and nxt not in visible and nxt not in seen:
            seen.add(nxt)
            nxt = records[nxt]["superseded_by"] if nxt in records else None
        out["superseded_by"] = nxt
        return out

    def successor(self, rid: str) -> str:
        """Follow `superseded_by` to the current record in this scope."""
        seen = set()
        while rid in self.records and self.records[rid]["superseded_by"] and rid not in seen:
            seen.add(rid)
            rid = self.records[rid]["superseded_by"]
        return rid

    def resolve(self, text: str) -> tuple[str | None, list[str]]:
        """Resolve an id, a name, an alias, or a partial name to current ids.
        Returns `(via, ids)`; `via` is `id`, `alias`, `partial`, or None."""
        text = str(text).strip()
        if text in self.records:
            return "id", [text]
        hits: list[str] = []
        for key in sorted(name_keys(text)):
            for rid in self.aliases.get(key, []):
                if rid not in hits:
                    hits.append(rid)
        if hits:
            return "alias", sorted(hits)
        words = [w for w in tokens(text) if w not in FILLER]
        if words:
            sets = [self.tokens.get(w, set()) for w in words]
            found = set.intersection(*sets) if all(sets) else set()
            if found:
                return "partial", sorted(found)
        return None, []

    def suggestions(self, text: str, n: int = 3) -> list[str]:
        """Close names for a query that resolved to nothing: whole names first,
        then single words ("Varo" → Varro the Tithekeeper)."""
        if self._sorted_keys is None:
            self._sorted_keys = (sorted(self.aliases), sorted(self.tokens))
        alias_keys, word_keys = self._sorted_keys
        out: list[str] = []
        for key in sorted(name_keys(text)):
            for close in difflib.get_close_matches(key, alias_keys, n=n, cutoff=0.6):
                out += [rid for rid in self.aliases[close] if rid not in out]
        if not out:
            for word in tokens(text):
                for close in difflib.get_close_matches(word, word_keys, n=n, cutoff=0.75):
                    out += [rid for rid in sorted(self.tokens[close]) if rid not in out]
        return out[:n]

    def history(self, rid: str) -> list[dict]:
        """Every visible version of a record, oldest first."""
        first, seen = rid, {rid}
        while first in self.predecessor and self.predecessor[first] not in seen:
            first = self.predecessor[first]
            seen.add(first)
        chain, node = [], first
        while node in self.records and node not in {r["id"] for r in chain}:
            chain.append(copy.deepcopy(self.records[node]))
            node = self.records[node]["superseded_by"]
        return chain


def build_index(state: dict, scope: str) -> CanonIndex:
    return CanonIndex(state.get("canon") or {}, scope)


# ====================================================================== commands

class CanonCommands:
    """Engine commands and queries for canon. Mixed into `Engine`; uses its
    state, `_emit`, and seat roles."""

    # ------------------------------------------------------------ indexes

    def _canon_index(self, scope: str) -> CanonIndex:
        records = self.state.get("canon") or {}
        key = _fingerprint(records)
        cache = self.__dict__.setdefault("_derived_caches", {})
        hit = cache.get(("canon", scope))
        if hit is None or hit[0] != key:
            hit = (key, CanonIndex(records, scope))
            cache[("canon", scope)] = hit
        return hit[1]

    def _canon_scope(self, scope: str) -> str:
        if scope in SCOPES:
            return scope
        if scope in self.seats:
            return "gm" if self._role(scope) == "gm" else "players"
        raise EngineError(f"unknown canon scope {scope!r}; use one of {', '.join(SCOPES)} or a seat id "
                          f"({', '.join(sorted(self.seats)) or 'none'})")

    def _canon_author(self, by: str | None) -> str:
        by = by or self.gm_seat
        if by != "engine" and self._role(by) != "gm":
            raise EngineError(f"only the GM seat ({self.gm_seat}) or the engine may write canon, not {by!r}")
        return by

    def _session_open(self) -> bool:
        """True between `session_started` and `session_ended`. Read from the log
        rather than folded state, so existing logs keep their state hash (D-011)."""
        open_ = False
        for ev in self.store.read(self.campaign_id):
            if ev["type"] == "session_started":
                open_ = True
            elif ev["type"] == "session_ended":
                open_ = False
        return open_

    # ------------------------------------------------------------ validation

    def _canon_record(self, record: dict, by: str, replacing: str | None = None) -> tuple[dict, list[dict]]:
        """Validate a record for writing and return it with near-collision flags.
        Rejects unknown fields, bad enums, missing dependencies, and exact name
        collisions with any current record (secrets included)."""
        if not isinstance(record, dict):
            raise EngineError("a canon record must be a mapping of fields")
        unknown = sorted(set(record) - set(INPUT_FIELDS))
        if unknown:
            raise EngineError(f"unknown canon field {unknown[0]!r}; fields are {', '.join(INPUT_FIELDS)} "
                              "(the engine sets established_*, superseded_by, and created_at)")
        missing = [f for f in REQUIRED_FIELDS if f not in record]
        if missing:
            raise EngineError(f"canon record is missing {', '.join(missing)}")
        for field, options in (("type", RECORD_TYPES), ("knowledge", KNOWLEDGE), ("origin", ORIGINS)):
            if record[field] not in options:
                raise EngineError(f"canon {field} {record[field]!r} is not valid; use one of {', '.join(options)}")
        name = record["name"]
        if not isinstance(name, str) or not tokens(name):
            raise EngineError("canon name must be text containing at least one letter or digit")
        if not isinstance(record["body"], str):
            raise EngineError("canon body must be text: one fact, one record")
        aliases = record.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(a, str) and tokens(a) for a in aliases):
            raise EngineError("canon aliases must be a list of names")
        aliases = list(dict.fromkeys(a.strip() for a in aliases if a.strip() != name.strip()))
        self._refuse_excluded({"name": name, "aliases": aliases, "body": record["body"]})

        gm = self._canon_index("gm")
        stored = self.state.get("canon") or {}

        depends_on = list(dict.fromkeys(record.get("depends_on") or []))
        for dep in depends_on:
            if dep not in stored:
                raise EngineError(_suggest("canon record to depend on", dep, gm.current)
                                  + " Write dependencies first (§7.6.2 axiom 1).")
            if stored[dep]["superseded_by"] and dep != replacing:
                raise EngineError(f"canon record {dep!r} was superseded; depend on {gm.successor(dep)!r} instead")
        paths = list(dict.fromkeys(record.get("discovery_paths") or []))
        known = set(stored) | set(self.state["entities"])
        for path in paths:
            if path not in known:
                raise EngineError(_suggest("canon record or entity for a discovery path", path, known))
        if record["knowledge"] == "secret" and not paths:
            raise EngineError("a secret needs at least one discovery path: who knows it or what reveals it "
                              "(§7.6.2 axioms 3 and 10)")

        if "id" in record:
            rid = record["id"]
            if not isinstance(rid, str) or not ID_RE.match(rid):
                raise EngineError(f"canon id {rid!r} must be lowercase letters, digits, and underscores, "
                                  "starting with a letter")
            if rid in stored:
                raise EngineError(f"canon id {rid!r} already exists; ids are never reused")
        else:
            base = f"{record['type']}_{_slug(name)}"
            rid, n = base, 2
            while rid in stored:
                rid, n = f"{base}_{n}", n + 1

        # Collisions are checked against the GM index: a player-visible name must
        # not collide with a secret either.
        new_keys: dict[str, str] = {}
        for label in [name, *aliases]:
            for key in name_keys(label):
                new_keys.setdefault(key, label)
        flags: list[dict] = []
        for key in sorted(new_keys):
            owners = [o for o in gm.aliases.get(key, []) if o != replacing]
            if owners:
                raise EngineError(f"name {new_keys[key]!r} collides with canon record {owners[0]!r}; "
                                  "names are unique — reference that record by id, or choose a distinct name")
        others = sorted(k for k, owners in gm.aliases.items() if any(o != replacing for o in owners))
        for key in sorted(new_keys):
            for close in difflib.get_close_matches(key, others, n=3, cutoff=NEAR_CUTOFF / 100):
                for owner in gm.aliases[close]:
                    if owner != replacing:
                        flags.append({"name": new_keys[key], "near": close, "record": owner})

        out = {
            "id": rid,
            "type": record["type"],
            "name": name.strip(),
            "aliases": aliases,
            "body": record["body"],
            "knowledge": record["knowledge"],
            "depends_on": depends_on,
            "discovery_paths": paths,
            "origin": record["origin"],
            "established_session": int(self.state.get("session") or 0),
            "established_by": by,
            "superseded_by": None,
        }
        return out, flags

    # ------------------------------------------------------------ commands

    @atomic
    def write_canon(self, record: dict, by: str | None = None) -> dict:
        """GM tool `write_canon(record)` (§7.1): the engine assigns the id and
        validates. Returns `{"id", "flags"}`; flags list near-collisions."""
        by = self._canon_author(by)
        rec, flags = self._canon_record(record, by)
        self._emit("canon_written", {"record": rec, "flags": flags}, actor=by)
        return {"id": rec["id"], "flags": flags}

    @atomic
    def supersede_canon(self, old_id: str, record: dict, by: str | None = None) -> dict:
        """Append a correction (§1.3.2): write `record` as a new record and mark
        `old_id` superseded by it. The old record stays retrievable by id."""
        by = self._canon_author(by)
        if self._session_open():
            raise EngineError(f"no retcons mid-session: end session {self.state['session']} before superseding "
                              "canon; during play, write_canon a new record instead (§7.6.3)")
        stored = self.state.get("canon") or {}
        if old_id not in stored:
            raise EngineError(_suggest("canon record", old_id, stored))
        if stored[old_id]["superseded_by"]:
            raise EngineError(f"canon record {old_id!r} was already superseded by "
                              f"{stored[old_id]['superseded_by']!r}; supersede the current version")
        rec, flags = self._canon_record(record, by, replacing=old_id)
        cause = self._emit("canon_written", {"record": rec, "flags": flags, "supersedes": old_id}, actor=by)
        self._emit("canon_superseded", {"old": old_id, "new": rec["id"]}, actor=by, caused_by=cause)
        return {"id": rec["id"], "flags": flags}

    @atomic
    def reveal(self, fact_id: str, by: str | None = None) -> int:
        """GM tool `reveal(fact_id)` (§1.3.2): promote a record to `revealed`."""
        by = self._canon_author(by)
        stored = self.state.get("canon") or {}
        if fact_id not in stored:
            raise EngineError(_suggest("canon record", fact_id, stored))
        rec = stored[fact_id]
        if rec["superseded_by"]:
            raise EngineError(f"canon record {fact_id!r} was superseded by {rec['superseded_by']!r}; "
                              "reveal the current version")
        if rec["knowledge"] == "revealed":
            raise EngineError(f"canon record {fact_id!r} is already revealed")
        return self._emit("fact_revealed", {"id": fact_id, "from": rec["knowledge"]}, actor=by)

    # ------------------------------------------------------------ queries

    def query_canon(self, scope: str, id_or_text: str) -> dict:
        """`query_canon(entity_id | query)` (§7.1, §6.5 Layer 0): an exact id,
        then the alias table, then partial names. Knowledge-scoped."""
        index = self._canon_index(self._canon_scope(scope))
        via, ids = index.resolve(id_or_text)
        out: dict[str, Any] = {"query": id_or_text, "via": via,
                               "records": [copy.deepcopy(index.records[i]) for i in ids]}
        if not ids:
            out["suggestions"] = index.suggestions(id_or_text)
        return out

    def canon_history(self, scope: str, record_id: str) -> list[dict]:
        """Every version of a record in this scope, oldest first (§1.3.2)."""
        index = self._canon_index(self._canon_scope(scope))
        if record_id not in index.records:
            raise EngineError(_suggest("canon record", record_id, index.current))
        return index.history(record_id)

    def scene_bundle(self, location_id: str, present_ids: Iterable[str], scope: str = "gm") -> dict:
        """Scene context bundle (§6.5 Layer 1): a breadth-first walk of the
        relation graph from the location and the present records. Only the GM
        view carries `secrets`, the active secrets for the scene."""
        scope = self._canon_scope(scope)
        index = self._canon_index(scope)
        seeds = []
        for rid in [location_id, *present_ids]:
            if rid not in index.records:
                raise EngineError(_suggest("canon record", rid, index.current))
            seeds.append(index.successor(rid))
        if index.records[seeds[0]]["type"] != "location":
            raise EngineError(f"scene location {location_id!r} is a {index.records[seeds[0]]['type']}, not a location")
        seen = list(dict.fromkeys(seeds))
        frontier = list(seen)
        for _ in range(BUNDLE_RADIUS):
            nxt = []
            for rid in frontier:
                for other in index.graph.get(rid, []):
                    if other not in seen:
                        seen.append(other)
                        nxt.append(other)
            frontier = nxt
        ids = sorted(seen)
        by_type = {t: [i for i in ids if index.records[i]["type"] == t] for t in RECORD_TYPES}
        bundle: dict[str, Any] = {
            "scope": scope,
            "location": seeds[0],
            "present": seeds[1:],
            "by_type": {t: v for t, v in by_type.items() if v},
            "records": {i: copy.deepcopy(index.records[i]) for i in ids},
        }
        if scope == "gm":
            bundle["secrets"] = [i for i in ids if index.records[i]["knowledge"] == "secret"]
        return bundle

    def canon_digest(self, scope: str = "players") -> dict:
        """Canon digest stub (§6.5, BUILD_PLAN P0.9): one line per current thread,
        npc, and faction in the scope. The Utility Model replaces this with a
        written summary in P3; the shape stays the same."""
        index = self._canon_index(self._canon_scope(scope))
        out: dict[str, list[str]] = {}
        for kind in ("thread", "npc", "faction"):
            out[kind] = [f"{index.records[i]['name']}: {index.records[i]['body']}"
                         for i in sorted(index.current) if index.records[i]["type"] == kind]
        return out

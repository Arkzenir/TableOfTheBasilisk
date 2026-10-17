"""Spatial model (§1.4, §8.2): the backend interface, ZoneGraph, and RangeBands.

The backends own geometry; the pack owns what it means. A scene is spatial
when `set_scene` is given regions (ZoneGraph) or participants (RangeBands).
Its spatial part lives in folded state under `state["scene"]["spatial"]`, and
only then, so logs written before spatial scenes existed fold to exactly the
same state.

    zone:  {mode: zone, regions: [{id, label, adjacency, terrain, elevation, cover}], visibility}
    bands: {mode: bands, bands: [band ids, closest first], participants: [entity ids],
            ranges: {"a|b": band id}, visibility}

Every backend answers the same questions — is an entity in the scene, which
positions are one move away, how many steps separate two entities — so the
tool surface and the candidate generator (§1.4.2) are identical above all of
them. A *position* is an opaque id: a region id in a zone scene, `band:entity`
("this band from that entity") in a range-band scene.

`visible_to` is per observer, so a seat can be shown a partial view while the
GM and the broadcast see everything (§8.2). The model selects; the engine
computes (§1.4.1). Nothing here accepts or returns coordinates.
"""

from __future__ import annotations

import copy
from collections import deque
from typing import Any

from .canon import ID_RE
from .command import EngineError, _suggest, atomic

EVENT_TYPES = frozenset({"visibility_set"})

MAX_REGIONS = 64       # kernel settings; larger scenes belong to a different backend
MAX_PARTICIPANTS = 16
REGION_FIELDS = ("id", "label", "adjacency", "terrain", "elevation", "cover")


def values(pack, key: str) -> list[dict]:
    """A pack's spatial catalogue (`terrain`, `cover`, `bands`); empty under `spatial: none`."""
    spatial = pack.get("spatial")
    return list(spatial.get(key) or []) if isinstance(spatial, dict) else []


def declared_backends(pack) -> list[str]:
    """The backends a pack permits; `spatial: none` permits none (§1.4)."""
    spatial = pack.get("spatial")
    if spatial in (None, "none") or not isinstance(spatial, dict):
        return []
    return list(spatial.get("backends") or [])


# ====================================================================== backends

class SpatialBackend:
    """One spatial implementation (§1.4). `entities` is the folded entity map;
    `among` is the set of entities the moving seat can see."""

    name = ""        # pack-facing backend id, as listed in `spatial.backends`
    mode = ""        # §8.2 `spatial_mode`

    def build(self, args: dict, pack, entities: dict) -> dict:
        """The layout recorded in `scene_set` from `set_scene`'s arguments."""
        raise NotImplementedError

    def contains(self, spatial: dict, entities: dict, eid: str) -> bool:
        raise NotImplementedError

    def position_of(self, spatial: dict, entities: dict, eid: str) -> str | None:
        """The entity's own position id, if the backend has one (a region)."""
        return None

    def check_position(self, spatial: dict, entities: dict, position: str, among: set | None) -> None:
        raise NotImplementedError

    def moves(self, spatial: dict, entities: dict, eid: str, among: set, at: str | None = None) -> list[str]:
        """Positions one move away, from the current position or from `at`."""
        raise NotImplementedError

    def check_move(self, spatial: dict, entities: dict, eid: str, to: str, among: set) -> None:
        raise NotImplementedError

    def move_changes(self, spatial: dict, entities: dict, eid: str, to: str) -> list[dict]:
        raise NotImplementedError

    def place_changes(self, spatial: dict, entities: dict, eid: str, position: str) -> list[dict]:
        raise NotImplementedError

    def steps(self, spatial: dict, entities: dict, eid: str, at: str | None = None) -> dict[str, int]:
        """Steps from the entity (at `at`, or where it is) to every other entity in the scene it can reach."""
        raise NotImplementedError

    def region(self, spatial: dict, entities: dict, eid: str, at: str | None) -> dict | None:
        return None

    def label(self, spatial: dict, entities: dict, position: str) -> str:
        return position

    def view(self, spatial: dict, entities: dict, seen: list[str]) -> dict:
        """Extra `scene_view` fields and the tokens, restricted to `seen`."""
        raise NotImplementedError


class ZoneGraph(SpatialBackend):
    """Abstract regions with undirected adjacency. A move is one step to an
    adjacent region; steps are graph distance."""

    name = "zone_graph"
    mode = "zone"

    def build(self, args: dict, pack, entities: dict) -> dict:
        return {"mode": self.mode, "regions": self.normalise(args.get("regions"), pack)}

    def normalise(self, regions: Any, pack) -> list[dict]:
        if not isinstance(regions, list) or not regions:
            raise EngineError("regions must be a non-empty list of {id, label, adjacency}")
        if len(regions) > MAX_REGIONS:
            raise EngineError(f"a zone scene has at most {MAX_REGIONS} regions, got {len(regions)}")
        allowed = {key: {v["id"]: v for v in values(pack, key)} for key in ("terrain", "cover")}
        out: dict[str, dict] = {}
        for raw in regions:
            if not isinstance(raw, dict):
                raise EngineError("each region must be a mapping with id, label, and adjacency")
            extra = set(raw) - set(REGION_FIELDS)
            if extra:
                raise EngineError(f"unknown region field(s) {sorted(extra)}; allowed: {', '.join(REGION_FIELDS)}")
            rid = raw.get("id")
            if not isinstance(rid, str) or not ID_RE.match(rid):
                raise EngineError(f"region id {rid!r} must be lowercase letters, digits and underscores")
            if rid in out:
                raise EngineError(f"region {rid!r} is listed twice")
            region = {"id": rid, "label": str(raw.get("label") or rid), "adjacency": [],
                      "terrain": None, "elevation": 0, "cover": None}
            for key in ("terrain", "cover"):
                value = raw.get(key)
                if value is not None:
                    if value not in allowed[key]:
                        raise EngineError(_suggest(f"{key} for region {rid}", value, allowed[key]))
                    region[key] = value
            elevation = raw.get("elevation", 0)
            if isinstance(elevation, bool) or not isinstance(elevation, int):
                raise EngineError(f"region {rid}: elevation must be an integer")
            region["elevation"] = elevation
            adjacency = raw.get("adjacency") or []
            if not isinstance(adjacency, list):
                raise EngineError(f"region {rid}: adjacency must be a list of region ids")
            region["adjacency"] = list(adjacency)
            out[rid] = region
        # Adjacency is undirected: a link listed on either side counts for both.
        links: dict[str, set[str]] = {rid: set() for rid in out}
        for rid, region in out.items():
            for other in region["adjacency"]:
                if other == rid:
                    raise EngineError(f"region {rid} cannot be adjacent to itself")
                if other not in out:
                    raise EngineError(_suggest(f"region adjacent to {rid}", other, out))
                links[rid].add(other)
                links[other].add(rid)
        for rid in out:
            out[rid]["adjacency"] = sorted(links[rid])
        return [out[rid] for rid in sorted(out)]

    def _graph(self, spatial: dict) -> dict[str, list[str]]:
        return {r["id"]: r["adjacency"] for r in spatial["regions"]}

    def _hops(self, spatial: dict, start: str) -> dict[str, int]:
        graph = self._graph(spatial)
        if start not in graph:
            return {}
        seen, queue = {start: 0}, deque([start])
        while queue:
            here = queue.popleft()
            for nxt in graph[here]:
                if nxt not in seen:
                    seen[nxt] = seen[here] + 1
                    queue.append(nxt)
        return seen

    def contains(self, spatial, entities, eid):
        return entities[eid].get("zone") in self._graph(spatial)

    def position_of(self, spatial, entities, eid):
        zone = entities[eid].get("zone")
        return zone if zone in self._graph(spatial) else None

    def check_position(self, spatial, entities, position, among):
        graph = self._graph(spatial)
        if position not in graph:
            raise EngineError(_suggest("region", position, graph))

    def moves(self, spatial, entities, eid, among, at=None):
        start = at if at is not None else entities[eid].get("zone")
        return list(self._graph(spatial).get(start, []))

    def check_move(self, spatial, entities, eid, to, among):
        graph = self._graph(spatial)
        frm = entities[eid].get("zone")
        if to not in graph:
            raise EngineError(_suggest("region", to, graph))
        if frm not in graph:
            raise EngineError("the entity is not placed in this scene; the GM places it first")
        if to == frm:
            raise EngineError(f"already in {to}")
        if to not in graph[frm]:
            raise EngineError(f"{to} is not adjacent to {frm}. Reachable in one move: "
                              f"{', '.join(graph[frm]) or 'none'}.")

    def move_changes(self, spatial, entities, eid, to):
        return [{"path": ["entities", eid, "zone"], "value": to}]

    def place_changes(self, spatial, entities, eid, position):
        return [{"path": ["entities", eid, "zone"], "value": position}]

    def steps(self, spatial, entities, eid, at=None):
        hops = self._hops(spatial, at if at is not None else entities[eid].get("zone"))
        return {o: hops[e["zone"]] for o, e in sorted(entities.items())
                if o != eid and e.get("zone") in hops}

    def region(self, spatial, entities, eid, at):
        rid = at if at is not None else entities[eid].get("zone")
        return next((r for r in spatial["regions"] if r["id"] == rid), None)

    def label(self, spatial, entities, position):
        return next((r["label"] for r in spatial["regions"] if r["id"] == position), position)

    def view(self, spatial, entities, seen):
        return {"regions": copy.deepcopy(spatial["regions"]),
                "tokens": [{"entity_id": e, "region_id": entities[e]["zone"]} for e in seen]}


def _pair(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


class RangeBands(SpatialBackend):
    """Relative distance bands between entities, for systems that do not model
    maps (§1.4). The band set comes from the pack, closest first. Every pair of
    participants is in exactly one band; a move shifts the mover one band
    closer to or further from one other participant. A position id is
    `band:entity`."""

    name = "range_bands"
    mode = "bands"

    def _bands(self, pack) -> list[str]:
        return [b["id"] for b in values(pack, "bands")]

    def build(self, args: dict, pack, entities: dict) -> dict:
        bands = self._bands(pack)
        if len(bands) < 2:
            raise EngineError(f"pack {pack.id} declares fewer than two bands in spatial.bands")
        participants = args.get("participants")
        if not isinstance(participants, list) or not participants:
            raise EngineError("participants must be a non-empty list of entity ids")
        if len(participants) > MAX_PARTICIPANTS:
            raise EngineError(f"a band scene has at most {MAX_PARTICIPANTS} participants, got {len(participants)}")
        for eid in participants:
            if eid not in entities:
                raise EngineError(_suggest("entity", eid, entities))
        if len(set(participants)) != len(participants):
            raise EngineError("participants lists an entity twice")
        people = sorted(participants)
        ranges = {_pair(a, b): bands[-1] for i, a in enumerate(people) for b in people[i + 1:]}
        for item in args.get("ranges") or []:
            between, band = item.get("between") if isinstance(item, dict) else None, (item or {}).get("band")
            if not isinstance(between, list) or len(between) != 2 or between[0] == between[1]:
                raise EngineError("each range needs between: [entity, other entity] and a band")
            for eid in between:
                if eid not in people:
                    raise EngineError(_suggest("participant", eid, people))
            if band not in bands:
                raise EngineError(_suggest("band", band, bands))
            ranges[_pair(*between)] = band
        return {"mode": self.mode, "bands": bands, "participants": people, "ranges": ranges}

    def contains(self, spatial, entities, eid):
        return eid in spatial["participants"]

    def _parse(self, spatial, position, among):
        band, _, other = str(position).partition(":")
        targets = [o for o in spatial["participants"] if among is None or o in among]
        if band not in spatial["bands"] or other not in targets:
            options = [f"{b}:{o}" for o in targets for b in spatial["bands"]]
            raise EngineError(_suggest("position", position, options))
        return band, other

    def check_position(self, spatial, entities, position, among):
        self._parse(spatial, position, among)

    def _ranges(self, spatial, eid, at):
        ranges = dict(spatial["ranges"])
        if at is not None:
            band, _, other = at.partition(":")
            ranges[_pair(eid, other)] = band
        return ranges

    def moves(self, spatial, entities, eid, among, at=None):
        if eid not in spatial["participants"]:
            return []
        bands, ranges, out = spatial["bands"], self._ranges(spatial, eid, at), []
        for other in spatial["participants"]:
            if other == eid or other not in among:
                continue
            i = bands.index(ranges[_pair(eid, other)])
            out += [f"{bands[j]}:{other}" for j in (i - 1, i + 1) if 0 <= j < len(bands)]
        return out

    def check_move(self, spatial, entities, eid, to, among):
        if eid not in spatial["participants"]:
            raise EngineError("the entity is not placed in this scene; the GM places it first")
        band, other = self._parse(spatial, to, among)
        if other == eid:
            raise EngineError("a band is measured from another entity, not from yourself")
        bands = spatial["bands"]
        current = spatial["ranges"][_pair(eid, other)]
        if band == current:
            raise EngineError(f"already {band} from {other}")
        if abs(bands.index(band) - bands.index(current)) != 1:
            near = self.moves(spatial, entities, eid, {other})
            raise EngineError(f"{band} is more than one band from {current} ({other}). "
                              f"Reachable in one move: {', '.join(near) or 'none'}.")

    def move_changes(self, spatial, entities, eid, to):
        band, _, other = to.partition(":")
        return [{"path": ["scene", "spatial", "ranges", _pair(eid, other)], "value": band}]

    def place_changes(self, spatial, entities, eid, position):
        band, _, other = position.partition(":")
        if other == eid:
            raise EngineError("a band is measured from another entity, not from yourself")
        changes = []
        if eid not in spatial["participants"]:
            if len(spatial["participants"]) >= MAX_PARTICIPANTS:
                raise EngineError(f"a band scene has at most {MAX_PARTICIPANTS} participants")
            changes.append({"path": ["scene", "spatial", "participants"],
                            "value": sorted(spatial["participants"] + [eid])})
            for o in spatial["participants"]:
                if o != other:  # newcomers start at the furthest band from everyone else
                    changes.append({"path": ["scene", "spatial", "ranges", _pair(eid, o)],
                                    "value": spatial["bands"][-1]})
        changes.append({"path": ["scene", "spatial", "ranges", _pair(eid, other)], "value": band})
        return changes

    def steps(self, spatial, entities, eid, at=None):
        if eid not in spatial["participants"]:
            return {}
        bands, ranges = spatial["bands"], self._ranges(spatial, eid, at)
        return {o: bands.index(ranges[_pair(eid, o)]) for o in spatial["participants"] if o != eid}

    def label(self, spatial, entities, position):
        band, _, other = position.partition(":")
        name = entities.get(other, {}).get("name", other)
        return f"{band} {name}"

    def view(self, spatial, entities, seen):
        visible = set(seen)
        pairs = [{"between": key.split("|"), "band": band} for key, band in sorted(spatial["ranges"].items())
                 if set(key.split("|")) <= visible]
        return {"bands": list(spatial["bands"]), "ranges": pairs, "tokens": [{"entity_id": e} for e in seen]}


BACKENDS: dict[str, SpatialBackend] = {b.name: b for b in (ZoneGraph(), RangeBands())}
BY_MODE: dict[str, SpatialBackend] = {b.mode: b for b in BACKENDS.values()}


# ====================================================================== reducer

def apply_event(state: dict, ev: dict) -> None:
    """Fold one spatial event. Called from `engine.apply_event`."""
    p = ev.get("payload") or {}
    if ev["type"] == "visibility_set":
        vis = state["scene"]["spatial"]["visibility"]
        if p["visible_to"] is None:
            vis.pop(p["entity"], None)
        else:
            vis[p["entity"]] = list(p["visible_to"])


def scene_spatial(payload: dict) -> dict | None:
    """The spatial part of a `scene_set` payload, as folded into state."""
    spec = payload.get("spatial")
    if spec is None:
        return None
    return {**copy.deepcopy(spec), "visibility": {}}


# ====================================================================== commands

class SpatialCommands:
    """Engine commands and queries for the spatial model. Mixed into `Engine`."""

    def _spatial(self) -> dict | None:
        return self.state["scene"].get("spatial")

    def _backend(self, spatial: dict) -> SpatialBackend:
        return BY_MODE[spatial["mode"]]

    def _spatial_spec(self, regions: Any = None, participants: Any = None, ranges: Any = None) -> dict:
        """Validate a scene's layout against the pack's permitted backends."""
        if regions is not None and participants is not None:
            raise EngineError("a scene uses regions (zone_graph) or participants (range_bands), not both")
        backend = BACKENDS["zone_graph" if regions is not None else "range_bands"]
        permitted = declared_backends(self.pack)
        if backend.name not in permitted:
            raise EngineError(f"pack {self.pack.id} does not permit {backend.name} scenes; "
                              f"permitted backends: {', '.join(permitted) or 'none'}")
        if ranges is not None and backend.name != "range_bands":
            raise EngineError("ranges belong to range_bands scenes; a zone scene uses regions and placements")
        return backend.build({"regions": regions, "participants": participants, "ranges": ranges},
                             self.pack, self.state["entities"])

    def _seen_by(self, seat: str) -> set[str]:
        return {e for e in self.state["entities"] if self.visible(seat, e)}

    def _in_scene(self, entity_id: str) -> bool:
        spatial = self._spatial()
        return bool(spatial) and self._backend(spatial).contains(spatial, self.state["entities"], entity_id)

    def _check_position(self, position: str, observer: str | None = None) -> None:
        spatial = self._spatial()
        if spatial is not None:
            among = self._seen_by(observer) if observer else None
            self._backend(spatial).check_position(spatial, self.state["entities"], position, among)

    def _check_move(self, entity_id: str, to: str) -> None:
        spatial = self._spatial()
        if spatial is None:
            return  # outside a spatial scene a zone is a plain label (§1.4: theatre of the mind)
        seer = self.state["entities"][entity_id]["controller"]
        self._backend(spatial).check_move(spatial, self.state["entities"], entity_id, to, self._seen_by(seer))

    def _move_changes(self, entity_id: str, to: str) -> list[dict]:
        spatial = self._spatial()
        if spatial is None:
            return [{"path": ["entities", entity_id, "zone"], "value": to}]
        return self._backend(spatial).move_changes(spatial, self.state["entities"], entity_id, to)

    def visible(self, seat: str, entity_id: str) -> bool:
        """Whether `seat` can see `entity_id` in the current scene (§8.2 `visible_to`).
        The GM sees everything; a seat always sees the entities it controls."""
        spatial = self._spatial()
        if spatial is None or self._role(seat) == "gm":
            return True
        ent = self.state["entities"].get(entity_id)
        if ent is None:
            return False
        if ent["controller"] == seat:
            return True
        allowed = spatial["visibility"].get(entity_id)
        return allowed is None or seat in allowed

    def _placement_effects(self, placements: dict | None) -> list[tuple[str, str]]:
        if placements and self._spatial()["mode"] != "zone":
            raise EngineError("placements are for zone scenes; a band scene places by participants and ranges")
        out = []
        for eid in sorted(placements or {}):
            self._entity(eid)
            region = placements[eid]
            self._check_position(region)
            out.append((eid, region))
        return out

    def _place(self, entity_id: str, position: str, actor: str) -> None:
        spatial = self._spatial()
        changes = self._backend(spatial).place_changes(spatial, self.state["entities"], entity_id, position)
        self._emit("effect_applied", {
            "primitive": "move", "target": entity_id,
            "params": {"to": position, "reason": "placement", "target": entity_id},
            "changes": changes,
        }, actor=actor)

    @atomic
    def place_entity(self, entity_id: str, position: str, by: str | None = None) -> None:
        """GM placement: puts an entity at a position of the current scene without
        a move, for arrivals and scene setup. In a band scene this also adds a
        newcomer to the participants."""
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM places entities")
        self._entity(entity_id)
        if self._spatial() is None:
            raise EngineError("the current scene has no positions; set a scene with regions or participants first")
        self._check_position(position)
        self._place(entity_id, position, by)

    @atomic
    def set_visibility(self, entity_id: str, visible_to: list[str] | None, by: str | None = None) -> None:
        """Restrict which seats can see an entity in this scene; None makes it
        visible to every seat again. Resets at the next scene."""
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM sets visibility")
        self._entity(entity_id)
        if self._spatial() is None:
            raise EngineError("the current scene has no positions; visibility is per scene")
        if not self._in_scene(entity_id):
            raise EngineError(f"{entity_id} is not placed in this scene")
        seats = None
        if visible_to is not None:
            unknown = [s for s in visible_to if s not in self.seats]
            if unknown:
                raise EngineError(_suggest("seat", unknown[0], self.seats))
            seats = sorted(set(visible_to))
        self._emit("visibility_set", {"entity": entity_id, "visible_to": seats}, actor=by)

    def scene_view(self, seat: str) -> dict:
        """What `seat` can see of the current scene, by id. Never coordinates (§1.4.1)."""
        if seat not in self.seats and seat != "gm":
            raise EngineError(_suggest("seat", seat, self.seats))
        spatial = self._spatial()
        view = {"scene_id": self.state["scene"]["id"], "mode": None, "regions": [], "tokens": []}
        if spatial is None:
            return view
        seen = [e for e in sorted(self.state["entities"]) if self._in_scene(e) and self.visible(seat, e)]
        view["mode"] = spatial["mode"]
        if spatial["mode"] != "zone":
            del view["regions"]
        view.update(self._backend(spatial).view(spatial, self.state["entities"], seen))
        return view

    def reachable(self, entity_id: str, at: str | None = None) -> list[str]:
        """Positions one move away from the entity (from `at` if given), in a
        stable order. Only entities its seat can see are measured from."""
        spatial = self._spatial()
        if spatial is None or not self._in_scene(entity_id):
            return []
        seer = self.state["entities"][entity_id]["controller"]
        return self._backend(spatial).moves(spatial, self.state["entities"], entity_id, self._seen_by(seer), at)

    def position_of(self, entity_id: str) -> str | None:
        spatial = self._spatial()
        if spatial is None:
            return None
        return self._backend(spatial).position_of(spatial, self.state["entities"], entity_id)

    def steps_from(self, entity_id: str, at: str | None = None) -> dict[str, int]:
        """Steps from the entity to every other entity in the scene (regions
        crossed, or bands out). Callers filter by what a seat can see."""
        spatial = self._spatial()
        if spatial is None or not self._in_scene(entity_id):
            return {}
        return self._backend(spatial).steps(spatial, self.state["entities"], entity_id, at)

    def distance(self, a: str, b: str) -> int | None:
        """Steps between two regions (zone scene) or two entities (band scene)."""
        spatial = self._spatial()
        if spatial is None:
            return None
        backend = self._backend(spatial)
        if spatial["mode"] == "zone":
            return backend._hops(spatial, a).get(b) if b in backend._graph(spatial) else None
        return backend.steps(spatial, self.state["entities"], a).get(b) if a in spatial["participants"] else None

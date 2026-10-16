"""Spatial model (§1.4, §8.2): the backend interface and ZoneGraph.

The backends own geometry; the pack owns what it means. A scene is spatial
when `set_scene` is given regions. Its spatial part lives in folded state under
`state["scene"]["spatial"]`, and only then, so logs written before this module
existed fold to exactly the same state.

    spatial: {mode, regions: [{id, label, adjacency, terrain, elevation, cover}],
              visibility: {entity_id: [seat ids]}}

An entity is in the scene when its `zone` is one of the scene's regions.
Positions change only through `move` effects (adjacency checked here) and GM
placement; `visible_to` is per observer, so a seat can be shown a partial view
while the GM and the broadcast see everything (§8.2).

The model selects; the engine computes (§1.4.1). Nothing here accepts or
returns coordinates.
"""

from __future__ import annotations

import copy
from collections import deque
from typing import Any

from .canon import ID_RE
from .command import EngineError, _suggest, atomic

EVENT_TYPES = frozenset({"visibility_set"})

MAX_REGIONS = 64  # a kernel setting; scenes larger than this belong to a different backend
REGION_FIELDS = ("id", "label", "adjacency", "terrain", "elevation", "cover")


# ====================================================================== backends

class SpatialBackend:
    """One spatial implementation (§1.4). Identical surface above all of them:
    agents never learn which backend is running."""

    name = ""        # pack-facing backend id, as listed in `spatial.backends`
    mode = ""        # §8.2 `spatial_mode`

    def normalise(self, regions: Any, pack) -> list[dict]:
        raise NotImplementedError

    def neighbours(self, spatial: dict, region_id: str) -> list[str]:
        raise NotImplementedError

    def distance(self, spatial: dict, a: str, b: str) -> int | None:
        raise NotImplementedError

    def check_move(self, spatial: dict, frm: str | None, to: str) -> None:
        raise NotImplementedError


class ZoneGraph(SpatialBackend):
    """Abstract regions with undirected adjacency. A move is one step to an
    adjacent region; distance is the number of steps."""

    name = "zone_graph"
    mode = "zone"

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

    def neighbours(self, spatial: dict, region_id: str) -> list[str]:
        return list(self._graph(spatial).get(region_id, []))

    def distance(self, spatial: dict, a: str, b: str) -> int | None:
        graph = self._graph(spatial)
        if a not in graph or b not in graph:
            return None
        seen, queue = {a: 0}, deque([a])
        while queue:
            here = queue.popleft()
            if here == b:
                return seen[here]
            for nxt in graph[here]:
                if nxt not in seen:
                    seen[nxt] = seen[here] + 1
                    queue.append(nxt)
        return None  # disconnected

    def check_move(self, spatial: dict, frm: str | None, to: str) -> None:
        graph = self._graph(spatial)
        if to not in graph:
            raise EngineError(_suggest("region", to, graph))
        if frm not in graph:
            raise EngineError("the entity is not placed in this scene; the GM places it first")
        if to == frm:
            raise EngineError(f"already in {to}")
        if to not in graph[frm]:
            raise EngineError(f"{to} is not adjacent to {frm}. Reachable in one move: "
                              f"{', '.join(graph[frm]) or 'none'}.")


BACKENDS: dict[str, SpatialBackend] = {b.name: b for b in (ZoneGraph(),)}
BY_MODE: dict[str, SpatialBackend] = {b.mode: b for b in BACKENDS.values()}


def values(pack, key: str) -> list[dict]:
    """A pack's spatial value catalogue (`terrain`, `cover`); empty under `spatial: none`."""
    spatial = pack.get("spatial")
    return list(spatial.get(key) or []) if isinstance(spatial, dict) else []


def declared_backends(pack) -> list[str]:
    """The backends a pack permits; `spatial: none` permits none (§1.4)."""
    spatial = pack.get("spatial")
    if spatial in (None, "none") or not isinstance(spatial, dict):
        return []
    return list(spatial.get("backends") or [])


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
    return {"mode": spec["mode"], "regions": copy.deepcopy(spec["regions"]), "visibility": {}}


# ====================================================================== commands

class SpatialCommands:
    """Engine commands and queries for the spatial model. Mixed into `Engine`."""

    def _spatial(self) -> dict | None:
        return self.state["scene"].get("spatial")

    def _backend(self, spatial: dict) -> SpatialBackend:
        return BY_MODE[spatial["mode"]]

    def _spatial_spec(self, regions: Any) -> dict:
        """Validate a scene's regions against the pack's permitted backends."""
        permitted = declared_backends(self.pack)
        backend = BACKENDS["zone_graph"]
        if backend.name not in permitted:
            raise EngineError(f"pack {self.pack.id} does not permit {backend.name} scenes; "
                              f"permitted backends: {', '.join(permitted) or 'none'}")
        return {"mode": backend.mode, "regions": backend.normalise(regions, self.pack)}

    def _in_scene(self, entity_id: str) -> bool:
        spatial = self._spatial()
        if not spatial:
            return False
        zone = self.state["entities"][entity_id].get("zone")
        return any(r["id"] == zone for r in spatial["regions"])

    def _check_region(self, region_id: str) -> None:
        spatial = self._spatial()
        if spatial is not None:
            regions = [r["id"] for r in spatial["regions"]]
            if region_id not in regions:
                raise EngineError(_suggest("region", region_id, regions))

    def _check_move(self, entity_id: str, to: str) -> None:
        spatial = self._spatial()
        if spatial is None:
            return  # outside a spatial scene a zone is a plain label (§1.4: theatre of the mind)
        self._backend(spatial).check_move(spatial, self.state["entities"][entity_id].get("zone"), to)

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
        out = []
        for eid in sorted(placements or {}):
            self._entity(eid)
            region = placements[eid]
            self._check_region(region)
            out.append((eid, region))
        return out

    def _place(self, entity_id: str, region_id: str, actor: str) -> None:
        self._emit("effect_applied", {
            "primitive": "move", "target": entity_id,
            "params": {"to": region_id, "reason": "placement", "target": entity_id},
            "changes": [{"path": ["entities", entity_id, "zone"], "value": region_id}],
        }, actor=actor)

    @atomic
    def place_entity(self, entity_id: str, region_id: str, by: str | None = None) -> None:
        """GM placement: puts an entity in a region of the current scene without a
        move, for arrivals and scene setup."""
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM places entities")
        self._entity(entity_id)
        if self._spatial() is None:
            raise EngineError("the current scene has no regions; set a scene with regions first")
        self._check_region(region_id)
        self._place(entity_id, region_id, by)

    @atomic
    def set_visibility(self, entity_id: str, visible_to: list[str] | None, by: str | None = None) -> None:
        """Restrict which seats can see an entity in this scene; None makes it
        visible to every seat again. Resets at the next scene."""
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM sets visibility")
        self._entity(entity_id)
        if self._spatial() is None:
            raise EngineError("the current scene has no regions; visibility is per scene")
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
        """What `seat` can see of the current scene: regions, and the tokens
        visible to it, by id. Never coordinates (§1.4.1)."""
        if seat not in self.seats and seat != "gm":
            raise EngineError(_suggest("seat", seat, self.seats))
        spatial = self._spatial()
        view = {"scene_id": self.state["scene"]["id"], "mode": None, "regions": [], "tokens": []}
        if spatial is None:
            return view
        view["mode"] = spatial["mode"]
        view["regions"] = copy.deepcopy(spatial["regions"])
        for eid in sorted(self.state["entities"]):
            if self._in_scene(eid) and self.visible(seat, eid):
                view["tokens"].append({"entity_id": eid, "region_id": self.state["entities"][eid]["zone"]})
        return view

    def reachable(self, entity_id: str) -> list[str]:
        """Regions one move away from the entity's region, in id order."""
        spatial = self._spatial()
        if spatial is None or not self._in_scene(entity_id):
            return []
        return self._backend(spatial).neighbours(spatial, self.state["entities"][entity_id]["zone"])

    def distance(self, a: str, b: str) -> int | None:
        """Steps between two regions of the current scene, or None if unconnected."""
        spatial = self._spatial()
        if spatial is None:
            return None
        return self._backend(spatial).distance(spatial, a, b)

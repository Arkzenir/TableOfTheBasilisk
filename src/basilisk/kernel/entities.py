"""Entities: player characters from chargen (§1.5) and GM-spawned entities
(§5.2, §5.3). Mixed into `Engine`.
"""

from __future__ import annotations

from .command import EngineError, _suggest, atomic, check_id, check_name, gm_call


class EntityCommands:
    """Character creation and spawning."""

    def _new_entity(self, entity_id: str, name: str, kind: str, controller: str, stats: dict[str, int]) -> dict:
        ent = {
            "id": entity_id, "name": name, "kind": kind, "controller": controller,
            "stats": {}, "resources": {}, "tracks": {}, "conditions": {}, "tags": [],
            "inventory": [], "zone": None, "currencies": {}, "details": [],
        }
        for s in self.pack.catalogue("entity_model.stats"):
            value = int(stats.get(s["id"], s.get("default", 0)))
            lo, hi = s.get("range", [value, value])
            ent["stats"][s["id"]] = max(lo, min(hi, value))
        unknown = set(stats) - set(ent["stats"])
        if unknown:
            raise EngineError(_suggest("stat", sorted(unknown)[0], ent["stats"]))
        for r in self.pack.catalogue("entity_model.resources"):
            ent["resources"][r["id"]] = self._max(ent, r)
        for t in self.pack.catalogue("entity_model.tracks"):
            ent["tracks"][t["id"]] = 0
        for c in self.pack.catalogue("gm.meta_currencies"):
            if c.get("holder", "each_player") == "each_player" and kind == "pc":  # pools are shared (§2.3)
                ent["currencies"][c["id"]] = int(c.get("start", 0))
        return ent

    @atomic
    def create_character(self, agent_id: str, name: str, choices: dict[str, str] | None = None,
                         entity_id: str | None = None) -> str:
        if self.seats.get(agent_id) != "player":
            raise EngineError(f"{agent_id!r} is not a player seat")
        entity_id = check_id("entity", entity_id or agent_id)
        check_name("a character's name", name)
        if entity_id in self.state["entities"]:
            raise EngineError(f"entity {entity_id!r} already exists")
        choices = dict(choices or {})
        start = self._emit("chargen_started", {"agent": agent_id, "entity": entity_id}, actor=agent_id)
        stats: dict[str, int] = {}
        tags: list[str] = []
        details: list[str] = []
        unique: dict[str, str] = {}
        items: list[str] = []  # starting equipment and currencies from choices (§1.5)
        grants: dict[str, int] = {}
        tables = self.pack.by_id("randomizers.tables")
        for step in self.pack.get("chargen.steps") or []:
            kind = step["kind"]
            if kind == "roll":
                for target in step["targets"]:
                    result, _ = self._roll(step["roll"], {}, start, f"chargen:{step['id']}:{target}", actor="engine")
                    stats[target] = result.total
            elif kind == "choice":
                options = {o["id"]: o for o in step.get("options") or []}
                taken = set(self.state["chargen_taken"].get(step["id"], [])) if step.get("unique_per_table") else set()
                available = [o for o in options if o not in taken]
                pick = choices.get(step["id"])
                if pick not in options:
                    raise EngineError(_suggest(f"option for {step['id']}", pick, available))
                if pick in taken:
                    raise EngineError(f"{pick!r} is already taken at this table ({step['id']} is unique per table)")
                self._judge(agent_id, "chargen_choice", None, pick, available, start)
                stats.update(options[pick].get("stats") or {})
                tags += options[pick].get("tags") or []
                items += options[pick].get("items") or []
                for cid, amount in (options[pick].get("currencies") or {}).items():
                    grants[cid] = grants.get(cid, 0) + int(amount)
                if step.get("unique_per_table"):
                    unique[step["id"]] = pick
            elif kind == "assign":  # place a fixed array of values onto stats (§1.5)
                pick = choices.get(step["id"])
                values, targets = list(step["values"]), list(step["targets"])
                if not isinstance(pick, dict) or sorted(pick) != sorted(targets):
                    raise EngineError(f"{step['id']}: assign each of {', '.join(targets)} one of the values "
                                      f"{values}, as {{stat: value}}")
                if sorted(pick.values()) != sorted(values):
                    raise EngineError(f"{step['id']}: the values must be exactly {sorted(values)}, each used once; "
                                      f"got {sorted(pick.values())}")
                self._judge(agent_id, "chargen_assign", None, {t: pick[t] for t in targets}, values, start)
                stats.update({t: int(pick[t]) for t in targets})
            elif kind == "table":
                table = tables[step["table"]]
                result, roll_seq = self._roll(table["roll"], {}, start, f"chargen:{step['id']}", actor="engine")
                entry = next(e for e in table["entries"] if e["range"][0] <= result.total <= e["range"][1])
                self._emit("table_rolled", {"table": table["id"], "value": result.total, "text": entry.get("text", "")},
                           caused_by=roll_seq)
                details.append(entry.get("text", ""))
        ent = self._new_entity(entity_id, name, "pc", agent_id, stats)
        ent["tags"] = sorted(set(tags))
        ent["details"] = details
        ent["inventory"] = list(items)
        currencies = self.pack.by_id("gm.meta_currencies")
        for cid, amount in sorted(grants.items()):
            ent["currencies"][cid] = min(int(currencies[cid].get("max", 10**6)), ent["currencies"].get(cid, 0) + amount)
        limit = self.capacity(ent)
        if limit is not None and self.carried(ent) > limit:
            raise EngineError(f"{entity_id} would start carrying {self.carried(ent)} of {limit}: "
                              "these choices give more equipment than the character can carry")
        for hook in self._hooks_at("sheet.validate"):  # cross-field constraints (§2.7)
            problems = self._call_hook(hook["name"], "sheet.validate", self._sheet_view(ent), {}, start, rolls=False)
            if problems:
                raise EngineError(f"{entity_id}'s sheet breaks {hook['name']}: {'; '.join(map(str, problems))}")
        self._emit("character_created", {"entity": ent, "unique_choices": unique, "choices": choices},
                   actor=agent_id, caused_by=start)
        return entity_id

    @atomic
    @gm_call()
    def spawn_entity(self, entity_id: str, name: str, stats: dict[str, int] | None = None,
                     zone: str | None = None, by: str | None = None) -> str:
        by = by or self.gm_seat
        if self._role(by) != "gm":
            raise EngineError("only the GM can spawn entities")
        check_id("entity", entity_id)
        check_name("an entity's name", name)
        for sid, value in (stats or {}).items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise EngineError(f"stat {sid!r} must be an integer, not {value!r}")
        if entity_id in self.state["entities"]:
            raise EngineError(f"entity {entity_id!r} already exists")
        if zone is not None:
            self._check_position(zone)
        relative = zone is not None and (self._spatial() or {}).get("mode") == "bands"
        ent = self._new_entity(entity_id, name, "npc", "gm", stats or {})
        ent["zone"] = None if relative else zone
        self._emit("entity_spawned", {"entity": ent}, actor=by)
        if relative:  # a band position is relative to others: join the scene there
            self._place(entity_id, zone, by)
        return entity_id

"""Character sheet read views (§7.1, BUILD_PLAN P0.8).

`read_sheet` is a seat's own sheet in full; `read_party_sheets` shows the other
party members in summary. Both speak the pack's vocabulary (§2.3): every field
carries the label the game uses, never just a kernel id.

The full view marks each field `private` or not, and the summary is exactly
the full view with every private field removed (`summarise`), so a summary
can never carry a field the full view marks private.

What is public is the pack's choice, read from `presentation`:
- conditions are always public (the table can see what has befallen someone);
- `nameplate_resources` are public (the overlay already shows them, §8.4);
- `sheet.public` lists further stats, derived values, resources, tracks, or
  currencies to show;
- everything else (stats, inventory, chargen details, and so on) is private.
A catalogue entry with `private: true` can never be made public.

Pure reads: nothing here emits events or changes state.
"""

from __future__ import annotations

from . import hooks as hook_runtime
from .progression import spec as _progression
from .command import EngineError, _suggest

SECTIONS = (
    ("stat", "entity_model.stats"), ("derived", "entity_model.derived"), ("resource", "entity_model.resources"),
    ("track", "entity_model.tracks"), ("currency", "gm.meta_currencies"),
)


def public_ids(pack) -> set[str]:
    sheet = (pack.get("presentation.sheet") or {})
    return set(pack.get("presentation.nameplate_resources") or []) | set(sheet.get("public") or [])


def lint_sheet(pack) -> list[str]:
    """Problems in a pack's sheet presentation, for pack lint (§2.10)."""
    out = []
    known = {item["id"]: item for _, dotted in SECTIONS for item in pack.catalogue(dotted)}
    for fid in sorted(public_ids(pack)):
        if fid not in known:
            out.append("sheet.public / nameplate_resources: " + _suggest("sheet field", fid, known))
        elif known[fid].get("private"):
            out.append(f"{fid} is marked private: true and cannot be shown on summaries")
    return out


def progression_model(pack) -> str:
    return str(_progression(pack).get("model"))


def harm_targets(pack) -> list[str]:
    """The resources and tracks a pack declares as harm (§2.3 `entity_model.harm`)."""
    return list((pack.get("entity_model.harm") or {}).get("targets") or [])


def lint_harm(pack) -> list[str]:
    spec = pack.get("entity_model.harm")
    if spec is None:
        return []
    if not isinstance(spec, dict) or set(spec) - {"targets"}:
        return ["entity_model.harm declares targets only; on_zero and on_fill live on each resource or track"]
    known = {r["id"] for r in pack.catalogue("entity_model.resources")} | \
            {t["id"] for t in pack.catalogue("entity_model.tracks")}
    out = [f"harm target {t!r} is not a resource or track; known: {', '.join(sorted(known)) or 'none'}"
           for t in spec.get("targets") or [] if t not in known]
    if not spec.get("targets"):
        out.append("entity_model.harm needs at least one target")
    return out


def summarise(full: dict) -> dict:
    """The summary view: the full view minus every private field."""
    return {**{k: v for k, v in full.items() if k != "fields"},
            "fields": [dict(f) for f in full["fields"] if not f["private"]]}


class SheetCommands:
    """Sheet read views. Mixed into `Engine`."""

    def _sheet_label(self, fid: str) -> tuple[str, str]:
        vocab = (self.pack.get("vocabulary") or {}).get(fid) or {}
        card = (self.pack.get("presentation.rule_cards") or {}).get(fid) or {}
        label = vocab.get("label") or card.get("title") or fid.replace("_", " ").title()
        return str(label), str(vocab.get("short") or label)

    def _field(self, section: str, fid: str, value, private: bool, **extra) -> dict:
        label, short = self._sheet_label(fid)
        return {"section": section, "id": fid, "label": label, "short": short, "value": value,
                "private": private, **extra}

    def full_sheet(self, entity_id: str) -> dict:
        """Every field of an entity's sheet, each marked private or public."""
        ent = self._entity(entity_id)
        public = public_ids(self.pack)
        derived = self._derived(ent)
        fields = []
        for section, dotted in SECTIONS:
            for item in self.pack.catalogue(dotted):
                fid = item["id"]
                shown = fid in public and not item.get("private")
                if section == "stat":
                    fields.append(self._field(section, fid, ent["stats"][fid], not shown))
                elif section == "derived":
                    fields.append(self._field(section, fid, derived[fid], not shown))
                elif section == "resource":
                    fields.append(self._field(section, fid, ent["resources"][fid], not shown,
                                              max=self._max(ent, item)))
                elif section == "track":
                    fields.append(self._field(section, fid, ent["tracks"][fid], not shown, max=int(item["boxes"])))
                elif fid in self._currencies(ent):
                    fields.append(self._field(section, fid, self._currencies(ent)[fid], not shown,
                                              max=int(item["max"]) if "max" in item else None))
        for cid in sorted(ent["conditions"]):
            fields.append(self._field("condition", cid, int(ent["conditions"][cid].get("level", 1)), False))
        for tag in ent["tags"]:
            fields.append(self._field("tag", tag, 1, True))
        if self._inventory_model() == "weight":
            fields.append(self._field("inventory", "inventory", list(ent["inventory"]), True,
                                      carried=self.carried(ent), max=self.capacity(ent)))
        else:
            fields.append(self._field("inventory", "inventory", list(ent["inventory"]), True))
        fields.append(self._field("details", "details", list(ent.get("details") or []), True))
        if self.progression_active():  # what is earned and what can be chosen (P0.15)
            prog = self._progress(ent)
            fields.append(self._field("progress", "progress", prog["points"], True, model=progression_model(self.pack),
                                      pending=prog["pending"], advances=list(prog["advances"]),
                                      options=self.advance_options(entity_id)))
        return {"entity": entity_id, "name": ent["name"], "kind": ent["kind"], "controller": ent["controller"],
                "fields": fields}

    def sheet_problems(self, entity_id: str) -> list[str]:
        """Ways an entity's sheet breaks the pack's entity model (§2.10: "no effect
        sequence yields an invalid sheet"). Empty for a valid sheet."""
        ent = self._entity(entity_id)
        out = []
        for s in self.pack.catalogue("entity_model.stats"):
            lo, hi = s.get("range", [ent["stats"].get(s["id"], 0)] * 2)
            if not lo <= ent["stats"].get(s["id"], lo) <= hi:
                out.append(f"stat {s['id']} = {ent['stats'][s['id']]} outside {lo}..{hi}")
        if set(ent["stats"]) != {s["id"] for s in self.pack.catalogue("entity_model.stats")}:
            out.append("stats do not match the entity model")
        for r in self.pack.catalogue("entity_model.resources"):
            lo, hi, v = int(r.get("min", 0)), self._max(ent, r), ent["resources"].get(r["id"])
            if not isinstance(v, int) or not lo <= v <= hi:
                out.append(f"resource {r['id']} = {v} outside {lo}..{hi}")
        for t in self.pack.catalogue("entity_model.tracks"):
            v = ent["tracks"].get(t["id"])
            if not isinstance(v, int) or not 0 <= v <= int(t["boxes"]):
                out.append(f"track {t['id']} = {v} outside 0..{t['boxes']}")
        for c in self.pack.catalogue("gm.meta_currencies"):
            if c["id"] in self._currencies(ent):
                v = self._currencies(ent)[c["id"]]
                if not isinstance(v, int) or v < 0 or ("max" in c and v > int(c["max"])):
                    out.append(f"currency {c['id']} = {v} outside 0..{c.get('max', 'unbounded')}")
        known = self.pack.by_id("entity_model.conditions")
        for cid, held in ent["conditions"].items():
            if cid not in known:
                out.append(f"unknown condition {cid}")
            elif "level" in held:
                top = int(known[cid].get("max_level", 3)) if known[cid].get("stacking") == "intensity" else 1
                if isinstance(held["level"], bool) or not isinstance(held["level"], int) or not 1 <= held["level"] <= top:
                    out.append(f"condition {cid} at level {held['level']}, outside 1..{top}")
        if "progress" in ent:
            prog = self._progress(ent)
            offered = {a["id"]: a for a in _progression(self.pack).get("advances") or []}
            if not isinstance(prog["pending"], int) or prog["pending"] < 0:
                out.append(f"progress pending = {prog['pending']}, below 0")
            for aid in prog["advances"]:
                if aid not in offered and not str(aid).startswith("use:"):
                    out.append(f"unknown advance taken: {aid}")
            once = [a for a in prog["advances"] if offered.get(a, {}).get("once")]
            if len(once) != len(set(once)):
                out.append(f"a once-only advance was taken twice: {sorted(once)}")
        if ent["tags"] != sorted(set(ent["tags"])):
            out.append("tags are not a sorted set")
        if not isinstance(ent["inventory"], list) or not all(isinstance(i, str) for i in ent["inventory"]):
            out.append("inventory is not a list of item ids")
        elif self._inventory_model() == "weight":
            unknown = [i for i in ent["inventory"] if i not in self.pack.by_id("entity_model.items")]
            if unknown:
                out.append(f"unknown items carried: {unknown}")
            limit = self.capacity(ent)
            if limit is not None and self.carried(ent) > limit:
                out.append(f"carries {self.carried(ent)} of {limit}")
        try:
            self._derived(ent)
        except Exception as e:  # noqa: BLE001 - any failure is a problem to report
            out.append(f"derived values do not evaluate: {e}")
        for hook in self._hooks_at("sheet.validate"):  # pack constraints, checked without logging (a read)
            try:
                result, _ = hook_runtime.run(hook, self._sheet_view(ent), {}, None)
            except hook_runtime.HookError as e:
                out.append(str(e))
                continue
            out += [f"{hook['name']}: {p}" for p in result or []]
        return out

    def _sheet_view(self, ent: dict) -> dict:
        """The sheet a `sheet.validate` hook sees: plain values only."""
        return {"stats": dict(ent["stats"]), "derived": dict(self._derived(ent)), "resources": dict(ent["resources"]),
                "tracks": dict(ent["tracks"]), "currencies": self._currencies(ent),
                "conditions": sorted(ent["conditions"]), "tags": list(ent["tags"]),
                "inventory": list(ent["inventory"]), "kind": ent["kind"]}

    def harm_state(self, entity_id: str) -> list[dict]:
        """Where an entity stands on each declared harm target (§2.3): value,
        bounds, and which way is worse. Resources run out towards their minimum;
        tracks fill towards their boxes. For later readers: lethality, metrics,
        the overlay. A pure read."""
        ent = self._entity(entity_id)
        resources = self.pack.by_id("entity_model.resources")
        tracks = self.pack.by_id("entity_model.tracks")
        out = []
        for tid in harm_targets(self.pack):
            label = self._sheet_label(tid)[0]
            if tid in resources:
                r = resources[tid]
                out.append({"id": tid, "label": label, "kind": "resource", "value": ent["resources"][tid],
                            "min": int(r.get("min", 0)), "max": self._max(ent, r), "worse": "lower"})
            else:
                out.append({"id": tid, "label": label, "kind": "track", "value": ent["tracks"][tid],
                            "min": 0, "max": int(tracks[tid]["boxes"]), "worse": "higher"})
        return out

    def read_sheet(self, seat: str, entity_id: str | None = None) -> dict:
        """A seat's own sheet in full (§7.1). The GM may read any sheet."""
        if seat not in self.seats and seat != "gm":
            raise EngineError(_suggest("seat", seat, self.seats))
        own = sorted(e for e, ent in self.state["entities"].items() if ent["controller"] == seat)
        if self._role(seat) == "gm":
            if entity_id is None:
                raise EngineError("name the entity whose sheet to read")
            return self.full_sheet(entity_id)
        if entity_id is None:
            if len(own) != 1:
                raise EngineError(f"{seat} controls {len(own)} entities; name one of: {', '.join(own) or 'none'}")
            entity_id = own[0]
        if entity_id not in own:
            # someone else's sheet is not readable in full; it does not exist for this tool (P3)
            raise EngineError(_suggest("sheet", entity_id, own) + " Other characters: read_party_sheets.")
        return self.full_sheet(entity_id)

    def read_party_sheets(self, seat: str) -> list[dict]:
        """The other party members (§7.1): summaries for a player, in full for the GM."""
        if seat not in self.seats and seat != "gm":
            raise EngineError(_suggest("seat", seat, self.seats))
        gm = self._role(seat) == "gm"
        party = sorted(e for e, ent in self.state["entities"].items()
                       if ent["kind"] == "pc" and (gm or ent["controller"] != seat))
        return [self.full_sheet(e) if gm else summarise(self.full_sheet(e)) for e in party]

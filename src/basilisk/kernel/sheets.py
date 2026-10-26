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
                elif fid in ent.get("currencies", {}):
                    fields.append(self._field(section, fid, ent["currencies"][fid], not shown,
                                              max=int(item["max"]) if "max" in item else None))
        for cid in sorted(ent["conditions"]):
            fields.append(self._field("condition", cid, 1, False))
        for tag in ent["tags"]:
            fields.append(self._field("tag", tag, 1, True))
        fields.append(self._field("inventory", "inventory", list(ent["inventory"]), True))
        fields.append(self._field("details", "details", list(ent.get("details") or []), True))
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
            if c["id"] in ent.get("currencies", {}):
                v = ent["currencies"][c["id"]]
                if not isinstance(v, int) or v < 0 or ("max" in c and v > int(c["max"])):
                    out.append(f"currency {c['id']} = {v} outside 0..{c.get('max', 'unbounded')}")
        known = set(self.pack.by_id("entity_model.conditions"))
        for cid in ent["conditions"]:
            if cid not in known:
                out.append(f"unknown condition {cid}")
        if ent["tags"] != sorted(set(ent["tags"])):
            out.append("tags are not a sorted set")
        if not isinstance(ent["inventory"], list) or not all(isinstance(i, str) for i in ent["inventory"]):
            out.append("inventory is not a list of item ids")
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
                "tracks": dict(ent["tracks"]), "currencies": dict(ent.get("currencies", {})),
                "conditions": sorted(ent["conditions"]), "tags": list(ent["tags"]),
                "inventory": list(ent["inventory"]), "kind": ent["kind"]}

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

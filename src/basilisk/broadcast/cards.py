"""Rule cards (ARCHITECTURE §8.6), rendered as text.

A pure function of events and the resolved pack: no model writes card text.
The broadcast renderer (P4.4) will draw the same data graphically; this text
form is the reference implementation and a debugging view (`tob sim --cards`).
"""

from __future__ import annotations

import textwrap
from collections import defaultdict

from ..kernel.packs import ResolvedPack

WIDTH = 46
ORIGIN = {"state": "", "auto": " (auto)", "gm": " (tag · GM)", "free": " (free · GM)"}


def _box(rows: list[tuple[str, str]]) -> str:
    inner = WIDTH - 4
    out = ["┌" + "─" * (WIDTH - 2) + "┐"]
    for left, right in rows:
        if right:
            gap = max(1, inner - len(left) - len(right))
            line = (left + " " * gap + right)[:inner]
        else:
            line = left[:inner]
        out.append("│ " + line.ljust(inner) + " │")
    out.append("└" + "─" * (WIDTH - 2) + "┘")
    return "\n".join(out)


def _wrap(text: str, indent: str = "") -> list[tuple[str, str]]:
    lines = textwrap.wrap(text, WIDTH - 4 - len(indent)) or [""]
    return [(indent + ln if i else ln, "") for i, ln in enumerate(lines)]


class CardRenderer:
    def __init__(self, events: list[dict], pack: ResolvedPack, names: dict[str, str] | None = None):
        self.events = events
        self.by_seq = {e["seq"]: e for e in events}
        self.children: dict[int, list[dict]] = defaultdict(list)
        for e in events:
            if e.get("caused_by"):
                self.children[e["caused_by"]].append(e)
        self.pack = pack
        self.cards = pack.get("presentation.rule_cards") or {}
        self.names = dict(names or {})
        for e in events:
            if e["type"] in ("character_created", "entity_spawned"):
                ent = e["payload"]["entity"]
                self.names.setdefault(ent["id"], ent["name"])
        self.fills = {e["payload"]["slot"]: e for e in events if e["type"] == "gm_ruling_filled"}

    def name(self, entity_id: str | None) -> str:
        return self.names.get(entity_id or "", entity_id or "?")

    def title(self, card_id: str) -> str:
        if card_id in self.cards:
            return str(self.cards[card_id].get("title", card_id))
        vocab = (self.pack.get("vocabulary") or {}).get(card_id) or {}
        return str(vocab.get("label", card_id.replace("_", " ")))

    def _descendants(self, seq: int) -> list[dict]:
        out, stack = [], list(self.children.get(seq, []))
        while stack:
            ev = stack.pop(0)
            out.append(ev)
            stack = self.children.get(ev["seq"], []) + stack
        return out

    def _effect_line(self, ev: dict, depth: int) -> list[tuple[str, str]]:
        p = ev["payload"]
        prim, params = p["primitive"], p["params"]
        who = self.name(p.get("target"))
        label = {
            "modify_resource": lambda: f"{who}: {self.title(params['resource'])} {params['old']} → {params['new']}",
            "set_resource": lambda: f"{who}: {self.title(params['resource'])} set to {params['new']}",
            "mark_track": lambda: f"{who}: {self.title(params['track'])} {params['old']} → {params['new']}",
            "clear_track": lambda: f"{who}: {self.title(params['track'])} cleared",
            "add_condition": lambda: f"{who} is {self.title(params['condition'])}",
            "remove_condition": lambda: f"{who} is no longer {self.title(params['condition'])}",
            "move": lambda: f"{who} moves to {params['to']}",
            "earn_currency": lambda: f"{who} gains {params['amount']} {self.title(params['currency'])}",
            "spend_currency": lambda: f"{who} spends {params['amount']} {self.title(params['currency'])}",
            "advance_clock": lambda: f"clock {params.get('clock')} {params['old']} → {params['new']}",
        }.get(prim, lambda: f"{who}: {prim}")()
        arrow = "↳" * depth + " "
        return _wrap(arrow + label, " " * (depth + 1))

    def action_card(self, root: dict) -> str:
        p = root["payload"]
        actor = self.name(p["entity"])
        rows: list[tuple[str, str]] = [(f"● {actor.upper()}", self.title(p["action"]).upper())]
        summary = self.cards.get(p["action"], {}).get("summary")
        if summary:
            rows += _wrap(summary)
        if p.get("target"):
            rows.append((f"→ {self.name(p['target'])}", ""))
        desc = self._descendants(root["seq"])
        proc = next((e for e in desc if e["type"] == "procedure_resolved"), None)
        roll = self.by_seq.get(proc["payload"]["roll_seq"]) if proc and proc["payload"]["roll_seq"] else None
        if roll:
            dice_txt = " ".join(f"{g['dice']} ({', '.join(map(str, g['rolls']))})" for g in roll["payload"]["groups"])
            parts = [dice_txt]
            for m in proc["payload"]["modifiers"]:
                sign = "+" if m["value"] >= 0 else "−"
                if m["kind"] == "free":
                    parts.append(f"{sign} {abs(m['value'])} (free · GM)")
                else:
                    parts.append(f"{sign} {self.title(m['source'])} {abs(m['value'])}{ORIGIN.get(m['origin'], '')}")
            rows += _wrap(" ".join(parts) + f" = {roll['payload']['total']}")
        if proc and proc["payload"].get("difficulty"):
            d = proc["payload"]["difficulty"]
            if d["origin"] == "gm-rung":
                rows.append((f"vs {d['rung'].title()} ({d['value']}) (rung · GM)", ""))
            elif d["origin"] == "gm-value":
                rows.append((f"vs {d['value']} (set by GM)", ""))
            else:
                rows.append((f"vs {d['value']} (derived)", ""))
        if proc:
            pp = proc["payload"]
            rows.append((f"▌{pp['outcome'].upper().replace('_', ' ')}", f"rank {pp['rank'] + 1}/{pp['ranks']}"))
        for ev in desc:
            depth = 1
            cause = self.by_seq.get(ev.get("caused_by"))
            while cause and cause["type"] == "effect_applied":
                depth += 1
                cause = self.by_seq.get(cause.get("caused_by"))
            if ev["type"] == "effect_applied":
                if ev["payload"]["changes"]:  # skip no-ops (e.g. removing a condition not held)
                    rows += self._effect_line(ev, depth)
            elif ev["type"] == "gm_ruling_requested":
                rp = ev["payload"]
                fill = self.fills.get(rp["slot"])
                who = "engine draw" if rp["mode"] == "engine_draw" else "GM choice"
                if fill:
                    rows += _wrap(f"{'↳' * depth} ruling ({who}): {fill['payload']['entry'].replace('_', ' ')}", " ")
                    if rp["mode"] == "gm_select":
                        for sub in self._descendants(fill["seq"]):
                            if sub["type"] == "effect_applied" and sub["payload"]["changes"]:
                                rows += self._effect_line(sub, depth + 1)
                else:
                    rows.append((f"{'↳' * depth} ruling pending (GM)", ""))
        if roll:
            rows.append((f"roll #{roll['payload']['counter']} · seed published at end", ""))
        return _box(rows)

    def settings_card(self, ev: dict) -> str:
        frm, to = ev["payload"]["from"], ev["payload"]["to"]
        rows: list[tuple[str, str]] = [("● TABLE SETTINGS", "FROM THIS SCENE")]
        for role in ("players", "gm"):
            for control, value in sorted(to[role].items()):
                if frm[role].get(control) != value:
                    rows += _wrap(f"{role}: {control.replace('_', ' ')} → {value}")
        return _box(rows)

    def all_cards(self) -> list[str]:
        out = []
        for ev in self.events:
            if ev["type"] == "action_committed":
                out.append(self.action_card(ev))
            elif ev["type"] == "determinism_changed":
                out.append(self.settings_card(ev))
        return out

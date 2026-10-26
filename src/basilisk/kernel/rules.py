"""Rules text: inline or sectioned, and key-first `query_rules` (§2.11, §6.5 Layer 0).

    rules_text:
      mode: inline | sectioned
      full_text               # inline: layer 2 of every context
      digest                  # sectioned: the always-loaded summary, layer 2
      sections: [{id, title, aliases, body, refs, parent}]
      max_section_tokens      # cap on any one section's body

Sections are opaque text keyed by id. The kernel recognises no section names,
no chapters, and no depth; `parent` nesting and `refs` (the catalogue ids a
section governs) are pack data. Inline packs may declare sections too, and
`query_rules` searches them the same way.

`query_rules` resolves in a fixed order: exact section id, catalogue id
through `refs`, alias key, then partial match (every query word appears in a
section's title or aliases). Name keys are canon's (`canon.name_keys`), so the
two indexes normalise identically. A miss returns the closest titles. Every
lookup is logged as `rules_queried`, a passive event: misses show where the
pack's aliases are weak (§2.11), and the rules-check card shows the section
title consulted, never its text (§8.6). Vector search is v2.
"""

from __future__ import annotations

import difflib

from .canon import FILLER, ID_RE, name_keys, tokens
from .command import EngineError, _suggest, atomic

EVENT_TYPES = frozenset({"rules_queried"})
MODES = ("inline", "sectioned")
DEFAULT_MAX_SECTION_TOKENS = 2_000
DIGEST_TOKEN_BUDGET = 6_000
SECTION_FIELDS = ("id", "title", "aliases", "body", "refs", "parent")
COVERED = ("actions", "resolution.procedures", "entity_model.conditions")


def approx_tokens(text: str) -> int:
    return len(text or "") // 4  # rough, matching the inline budget


def sections(pack) -> list[dict]:
    return list(pack.get("rules_text.sections") or [])


def catalogue_ids(pack) -> set[str]:
    """Every catalogue id a section may govern."""
    out: set[str] = set()
    for dotted in ("actions", "resolution.procedures", "resolution.outcome_scales", "resolution.situational_tags",
                   "resolution.difficulty_ladders", "entity_model.stats", "entity_model.derived",
                   "entity_model.resources", "entity_model.tracks", "entity_model.conditions",
                   "gm.meta_currencies", "gm.consequence_tables", "randomizers.tables", "randomizers.decks"):
        out |= {item["id"] for item in pack.catalogue(dotted)}
    return out


class SectionIndex:
    """Deterministic lookup tables built once from the pinned, resolved pack."""

    def __init__(self, pack):
        self.order = [s["id"] for s in sections(pack)]
        self.sections = {s["id"]: s for s in sections(pack)}
        self.refs: dict[str, list[str]] = {}
        self.keys: dict[str, list[str]] = {}
        self.words: dict[str, set[str]] = {}
        for s in sections(pack):
            for ref in s.get("refs") or []:
                self.refs.setdefault(ref, []).append(s["id"])
            for name in [s.get("title") or s["id"], *(s.get("aliases") or [])]:
                for key in name_keys(name):
                    self.keys.setdefault(key, [])
                    if s["id"] not in self.keys[key]:
                        self.keys[key].append(s["id"])
                for word in tokens(name):
                    self.words.setdefault(word, set()).add(s["id"])

    def resolve(self, text: str) -> tuple[str | None, list[str]]:
        text = str(text).strip()
        if text in self.sections:
            return "id", [text]
        if text in self.refs:
            return "ref", list(self.refs[text])
        hits: list[str] = []
        for key in sorted(name_keys(text)):
            hits += [sid for sid in self.keys.get(key, []) if sid not in hits]
        if hits:
            return "alias", self._ordered(hits)
        words = [w for w in tokens(text) if w not in FILLER]
        if words and all(w in self.words for w in words):
            found = set.intersection(*(self.words[w] for w in words))
            if found:
                return "partial", self._ordered(found)
        return None, []

    def _ordered(self, ids) -> list[str]:
        return [sid for sid in self.order if sid in set(ids)]

    def suggestions(self, text: str, n: int = 3) -> list[str]:
        titles = {str(s.get("title") or sid): sid for sid, s in self.sections.items()}
        close = difflib.get_close_matches(str(text), sorted(titles), n=n, cutoff=0.4)
        if not close:
            words = sorted(self.words)
            for word in tokens(text):
                for hit in difflib.get_close_matches(word, words, n=n, cutoff=0.7):
                    close += [str(self.sections[sid].get("title") or sid) for sid in self._ordered(self.words[hit])]
        return list(dict.fromkeys(close))[:n]


def layer_size(pack, inline_budget: int) -> dict:
    """Context layer 2's rough size against its budget (BUILD_PLAN P0.6): the
    inline text, or a sectioned pack's digest."""
    rt = pack.get("rules_text") or {}
    if rt.get("mode") == "sectioned":
        return {"mode": "sectioned", "tokens": approx_tokens(rt.get("digest")), "budget": DIGEST_TOKEN_BUDGET,
                "sections": len(rt.get("sections") or [])}
    return {"mode": "inline", "tokens": approx_tokens(rt.get("full_text")), "budget": inline_budget}


def lint_rules(pack, abstract: bool, inline_budget: int) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a pack's rules text (§2.10, §2.11)."""
    errs, warns = [], []
    rt = pack.get("rules_text") or {}
    mode = rt.get("mode", "inline")
    if mode not in MODES:
        errs.append(_suggest("rules_text mode", mode, MODES))
        return errs, warns
    full, digest = rt.get("full_text") or "", rt.get("digest") or ""
    if approx_tokens(full) > inline_budget:
        errs.append(f"inline rules text is ~{approx_tokens(full)} tokens; budget {inline_budget}")
    if mode == "inline" and not abstract and not full.strip():
        warns.append("no inline rules text")
    secs = sections(pack)
    if mode == "sectioned":
        if not digest.strip():
            errs.append("a sectioned pack needs a digest: the summary every context carries (§2.11)")
        if approx_tokens(digest) > DIGEST_TOKEN_BUDGET:
            errs.append(f"the digest is ~{approx_tokens(digest)} tokens; budget {DIGEST_TOKEN_BUDGET}")
        if not secs and not abstract:
            errs.append("a sectioned pack needs sections")
    cap = rt.get("max_section_tokens", DEFAULT_MAX_SECTION_TOKENS)
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        errs.append("max_section_tokens must be a positive integer")
        cap = DEFAULT_MAX_SECTION_TOKENS
    ids = [s.get("id") for s in secs]
    known = catalogue_ids(pack)
    owner: dict[str, str] = {}
    for s in secs:
        sid = s.get("id")
        where = f"section {sid}"
        extra = set(s) - set(SECTION_FIELDS)
        if extra:
            errs.append(f"{where}: unknown field(s) {sorted(extra)}; allowed: {', '.join(SECTION_FIELDS)}")
        if not isinstance(sid, str) or not ID_RE.match(sid):
            errs.append(f"{where}: id must be lowercase letters, digits and underscores")
        if ids.count(sid) > 1:
            errs.append(f"{where}: id is used twice")
        if not str(s.get("title") or "").strip() or not str(s.get("body") or "").strip():
            errs.append(f"{where}: needs a title and a body")
        if approx_tokens(str(s.get("body") or "")) > cap:
            errs.append(f"{where}: body is ~{approx_tokens(str(s['body']))} tokens; max_section_tokens is {cap}. "
                        "Split it into smaller sections.")
        for ref in s.get("refs") or []:
            if ref not in known:
                errs.append(f"{where}: " + _suggest("catalogue id for refs", ref, known))
        parent = s.get("parent")
        if parent is not None and parent not in ids:
            errs.append(f"{where}: " + _suggest("parent section", parent, [i for i in ids if i != sid]))
        for name in [s.get("title") or sid or "", *(s.get("aliases") or [])]:
            for key in name_keys(name):
                if owner.get(key, sid) != sid:
                    errs.append(f"{where}: name {name!r} collides with section {owner[key]}; "
                                "titles and aliases must be unique across sections")
                owner.setdefault(key, sid)
    parents = {s.get("id"): s.get("parent") for s in secs}
    for sid in parents:
        seen, cur = set(), sid
        while cur is not None and cur in parents:
            if cur in seen:
                errs.append(f"section {sid}: parent chain loops back on itself")
                break
            seen.add(cur)
            cur = parents[cur]
    if mode == "sectioned" and not abstract:
        covered = {ref for s in secs for ref in s.get("refs") or []}
        for dotted in COVERED:
            for item in pack.catalogue(dotted):
                if item["id"] not in covered:
                    errs.append(f"{dotted} {item['id']}: no section lists it in refs; "
                                "query_rules must reach every rule (§2.11)")
    return errs, warns


class RulesCommands:
    """`query_rules` and the rules layer of context. Mixed into `Engine`."""

    def _rules_index(self) -> SectionIndex:
        index = self.__dict__.get("_section_index")
        if index is None:  # the pack is pinned, so one index serves the whole campaign
            index = self.__dict__["_section_index"] = SectionIndex(self.pack)
        return index

    def rules_layer(self) -> str:
        """Context layer 2 (§6.1): the inline text, or a sectioned pack's digest."""
        rt = self.pack.get("rules_text") or {}
        return str(rt.get("digest") if rt.get("mode") == "sectioned" else rt.get("full_text") or "")

    @atomic
    def query_rules(self, seat: str, query: str) -> dict:
        """`query_rules(section_id | query)` (§7.1, §2.11): key-first lookup.
        Returns the matching sections' text, or suggestions on a miss."""
        if seat not in self.seats and seat not in ("gm", "engine"):
            raise EngineError(_suggest("seat", seat, self.seats))
        if not isinstance(query, str) or not query.strip():
            raise EngineError("query_rules needs a section id, a rule id, or some words to look up")
        index = self._rules_index()
        via, ids = index.resolve(query)
        out = {"query": query, "via": via,
               "sections": [{"id": sid, "title": index.sections[sid].get("title") or sid,
                             "parent": index.sections[sid].get("parent"), "body": index.sections[sid]["body"]}
                            for sid in ids]}
        if not ids:
            out["suggestions"] = index.suggestions(query)
            if not index.sections:
                out["note"] = "this pack's rules are inline: they are already in your context"
        self._emit("rules_queried", {"seat": seat, "query": query, "via": via, "sections": ids,
                                     "suggestions": out.get("suggestions", [])}, actor=seat)
        return out

"""Excluded terms (§1.2, §1.3.3, §2.10, BUILD_PLAN P0.14).

A pack lists the names its licence does not cover:

    meta:
      excluded_terms: [{term, aliases}]

The list is pack data, inherited along the extends chain and merged by term
(a child entry with the same term replaces its aliases). The kernel knows no
particular names.

One matcher serves every check: canon writes are refused here, the validation
pass and the TTS gate call it later (P3.3). Matching uses canon's own
normalisation (`canon.tokens`), so it is case-insensitive, ignores
punctuation and possessives, and matches whole words only: a term matches a
text when its words appear in the text consecutively. Deterministic and
model-free, so it costs nothing and replays exactly.
"""

from __future__ import annotations

from .canon import tokens
from .command import EngineError


def entries(pack) -> list[dict]:
    return list(pack.get("meta.excluded_terms") or [])


def _patterns(pack) -> list[tuple[str, tuple[str, ...]]]:
    out = []
    for entry in entries(pack):
        for name in [entry.get("term", ""), *(entry.get("aliases") or [])]:
            words = tuple(tokens(name))
            if words:
                out.append((str(entry["term"]), words))
    return out


def find(pack, text: str) -> list[str]:
    """Excluded terms appearing in `text`, as their declared terms, in pack order."""
    words = tokens(text or "")
    found: list[str] = []
    for term, pattern in _patterns(pack):
        n = len(pattern)
        if term not in found and any(tuple(words[i:i + n]) == pattern for i in range(len(words) - n + 1)):
            found.append(term)
    return found


def merge(chain_terms: list[list[dict]]) -> list[dict]:
    """Merge excluded-term lists from root to leaf, keyed by term."""
    out: dict[str, dict] = {}
    for terms in chain_terms:
        for entry in terms or []:
            out[str(entry.get("term"))] = {"term": entry.get("term"), "aliases": list(entry.get("aliases") or [])}
    return list(out.values())


def lint_terms(pack) -> list[str]:
    """Problems with excluded terms, for pack lint (§2.10). A term may not
    collide with the pack's own names: catalogue ids, vocabulary labels,
    rule-card titles, or rules-text section titles."""
    out = []
    for entry in entries(pack):
        if not isinstance(entry, dict) or not tokens(str(entry.get("term", ""))):
            out.append(f"excluded term {entry!r}: needs a term with at least one word")
            continue
        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(a, str) and tokens(a) for a in aliases):
            out.append(f"excluded term {entry['term']!r}: aliases must be a list of names")
    names: list[tuple[str, str]] = []
    for key, value in pack.data.items():
        if key == "meta":
            continue
        _ids_in(value, f"{key}", names)
    for vid, vocab in (pack.get("vocabulary") or {}).items():
        for field in ("label", "short", "plural"):
            if vocab.get(field):
                names.append((f"vocabulary {vid}.{field}", str(vocab[field])))
    for cid, card in (pack.get("presentation.rule_cards") or {}).items():
        names.append((f"rule card {cid}", str(card.get("title", ""))))
    for section in pack.get("rules_text.sections") or []:
        names.append((f"section {section.get('id')}", str(section.get("title", ""))))
    for where, name in names:
        for term in find(pack, name):
            out.append(f"excluded term {term!r} collides with the pack's own {where} ({name!r}); "
                       "rename one of them")
    return out


def _ids_in(node, where: str, names: list) -> None:
    """Every catalogue id anywhere in the pack, as words (`some_id` reads `some id`)."""
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and "id" in item:
                names.append((f"{where} id", str(item["id"]).replace("_", " ")))
            _ids_in(item, where, names)
    elif isinstance(node, dict):
        for key, value in node.items():
            _ids_in(value, f"{where}.{key}", names)


class TermCommands:
    """The excluded-term check, for canon and (later) the validation pass."""

    def excluded_in(self, text: str) -> list[str]:
        """Excluded terms in a line of text (§1.3.3 item 5)."""
        return find(self.pack, text)

    def _refuse_excluded(self, record: dict) -> None:
        for name in [record.get("name", ""), *(record.get("aliases") or []), record.get("body", "")]:
            hits = find(self.pack, str(name))
            if hits:
                raise EngineError(f"canon cannot contain {hits[0]!r}: this pack's licence does not cover it "
                                  "(meta.excluded_terms, §1.2). Rename or rewrite the record.")

"""Kernel noun lint (ARCHITECTURE §2.2, BUILD_PLAN P0.3).

Fails if a game noun appears anywhere in kernel source: the static list in
tools/kernel_nouns.txt plus every catalogue id defined by any pack on disk.
A kernel tested against one system quietly takes that system's shape; this is
how you notice.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CATALOGUES = (
    ("entity_model", "stats"), ("entity_model", "derived"), ("entity_model", "resources"),
    ("entity_model", "tracks"), ("entity_model", "conditions"), ("resolution", "situational_tags"),
    ("gm", "meta_currencies"), (None, "actions"),
)


def pack_nouns(packs_dir: Path) -> set[str]:
    nouns: set[str] = set()
    for path in Path(packs_dir).glob("*/pack.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for section, key in CATALOGUES:
            node = data.get(section, {}) if section else data
            for item in (node or {}).get(key, []) if isinstance(node, dict) else []:
                if isinstance(item, dict) and "id" in item:
                    nouns.add(str(item["id"]).lower())
    return nouns


def static_nouns(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {ln.strip().lower() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")}


def scan(kernel_dir: Path, nouns: set[str]) -> list[str]:
    hits = []
    for src in sorted(Path(kernel_dir).rglob("*.py")):
        for lineno, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
            for match in WORD.finditer(line):
                word = match.group(0).lower()
                candidates = {word} | set(word.split("_"))
                bad = candidates & nouns
                if bad:
                    hits.append(f"{src.name}:{lineno}: game noun {sorted(bad)[0]!r} in kernel source")
    return hits


def run(root: Path) -> list[str]:
    nouns = static_nouns(root / "tools" / "kernel_nouns.txt") | pack_nouns(root / "packs")
    return scan(root / "src" / "basilisk" / "kernel", nouns)

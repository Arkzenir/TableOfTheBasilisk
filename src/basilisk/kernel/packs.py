"""System pack loading and resolution (§2.3, §2.8, §2.9).

A pack is a directory containing `pack.yaml`. Packs extend other packs; the
loader resolves the inheritance chain into a single flattened document (the
resolved pack), which is what the kernel loads, what is hashed, and what a
campaign pins.

Merge rules:
  * maps deep-merge; the child wins on conflict
  * catalogues (lists whose items are all maps with an `id`) merge by id:
    same id deep-merges into the parent's entry, new ids append, and nothing
    is removed unless the child lists it under `remove:`
  * any other list, and every scalar, is replaced by the child's value
  * `remove: {"dotted.path": [ids]}` deletes catalogue entries explicitly
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import KERNEL_VERSION
from .canonical import hash_obj

PACK_FILE = "pack.yaml"

# Hooks (§2.7) register by shipping their source beside the declaring pack
# (`hooks/<name>.py`); `kernel/hooks.py` checks and runs them. A hook declared
# without its source is unregistered and the pack is refused.


class PackError(ValueError):
    pass


@dataclass
class ResolvedPack:
    data: dict
    hash: str
    lineage: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.data["meta"]["id"]

    @property
    def version(self) -> str:
        return self.data["meta"]["version"]

    # convenience lookups -------------------------------------------------
    def catalogue(self, dotted: str) -> list[dict]:
        node: Any = self.data
        for part in dotted.split("."):
            node = (node or {}).get(part)
        return node or []

    def by_id(self, dotted: str) -> dict[str, dict]:
        return {item["id"]: item for item in self.catalogue(dotted)}

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def parse_ref(ref: str) -> tuple[str, str | None]:
    if "@" in ref:
        pid, ver = ref.split("@", 1)
        return pid.strip(), ver.strip()
    return ref.strip(), None


def discover(packs_dir: str | Path) -> dict[str, dict[str, Path]]:
    """{pack_id: {version: path_to_pack_yaml}}"""
    found: dict[str, dict[str, Path]] = {}
    for path in sorted(Path(packs_dir).glob(f"*/{PACK_FILE}")):
        raw = load_raw(path)
        meta = raw.get("meta") or {}
        pid, ver = meta.get("id"), str(meta.get("version", ""))
        if not pid or not ver:
            raise PackError(f"{path}: meta.id and meta.version are required")
        if path.parent.name != pid:
            raise PackError(f"{path}: directory name must equal meta.id ({pid})")
        found.setdefault(pid, {})[ver] = path
    return found


_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # libyaml when installed; same results, faster
_PARSED: dict[bytes, object] = {}  # parsed documents by content hash: discovery reads every pack per resolve


def load_raw(path: str | Path) -> dict:
    raw = Path(path).read_bytes()
    key = hashlib.sha256(raw).digest()
    if key not in _PARSED:
        _PARSED[key] = yaml.load(raw.decode("utf-8"), Loader=_LOADER) or {}
    data = copy.deepcopy(_PARSED[key])
    if not isinstance(data, dict):
        raise PackError(f"{path}: top level must be a mapping")
    return data


def _is_catalogue(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(i, dict) and "id" in i for i in value)


def _merge(base: Any, child: Any) -> Any:
    if isinstance(base, dict) and isinstance(child, dict):
        out = copy.deepcopy(base)
        for key, value in child.items():
            out[key] = _merge(base[key], value) if key in base else copy.deepcopy(value)
        return out
    if isinstance(base, list) and isinstance(child, list) and _is_catalogue(base) and _is_catalogue(child):
        out = [copy.deepcopy(item) for item in base]
        index = {item["id"]: i for i, item in enumerate(out)}
        for item in child:
            if item["id"] in index:
                out[index[item["id"]]] = _merge(out[index[item["id"]]], item)
            else:
                index[item["id"]] = len(out)
                out.append(copy.deepcopy(item))
        return out
    if isinstance(base, list) and _is_catalogue(base) and child == []:
        return copy.deepcopy(base)  # an empty child catalogue removes nothing
    return copy.deepcopy(child)


def _duplicate_ids(node: Any, path: str = ""):
    """Yield (path, ids) for each catalogue in one pack file that declares an id
    twice. The merge would fold the second entry into the first unseen."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _duplicate_ids(value, f"{path}.{key}" if path else str(key))
    elif _is_catalogue(node) and node:
        ids = [str(item["id"]) for item in node]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            yield path, dupes
        for item in node:
            yield from _duplicate_ids(item, f"{path}[{item['id']}]")


def _apply_removals(data: dict, removals: dict[str, list[str]], pack_id: str) -> None:
    for dotted, ids in (removals or {}).items():
        node: Any = data
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, dict) or not _is_catalogue(node.get(parts[-1], [])):
            raise PackError(f"{pack_id}: remove target {dotted!r} is not a catalogue")
        existing = {i["id"] for i in node[parts[-1]]}
        missing = set(ids) - existing
        if missing:
            raise PackError(f"{pack_id}: cannot remove unknown ids {sorted(missing)} from {dotted}")
        node[parts[-1]] = [i for i in node[parts[-1]] if i["id"] not in set(ids)]


def _version_ok(kernel_compat: str | None) -> bool:
    """Accepts specs like '>=0.1,<0.2'. Absent spec means compatible."""
    if not kernel_compat:
        return True

    def tup(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.strip().split("."))

    kv = tup(KERNEL_VERSION)
    for clause in str(kernel_compat).split(","):
        clause = clause.strip()
        for op in (">=", "<=", "==", ">", "<"):
            if clause.startswith(op):
                target = tup(clause[len(op):])
                width = max(len(kv), len(target))
                a = kv + (0,) * (width - len(kv))
                b = target + (0,) * (width - len(target))
                ok = {">=": a >= b, "<=": a <= b, "==": a == b, ">": a > b, "<": a < b}[op]
                if not ok:
                    return False
                break
        else:
            raise PackError(f"bad kernel_compat clause {clause!r}")
    return True


def resolve(pack_ref: str, packs_dir: str | Path, *, allow_abstract: bool = True) -> ResolvedPack:
    index = discover(packs_dir)
    chain: list[tuple[str, dict]] = []
    seen: set[str] = set()
    ref: str | None = pack_ref
    while ref:
        pid, ver = parse_ref(ref)
        if pid not in index:
            raise PackError(f"unknown pack {pid!r}")
        versions = index[pid]
        if ver is None:
            if len(versions) > 1:
                raise PackError(f"pack {pid!r} has several versions; pin one with {pid}@<version>")
            ver = next(iter(versions))
        if ver not in versions:
            raise PackError(f"pack {pid}@{ver} not found (have {sorted(versions)})")
        key = f"{pid}@{ver}"
        if key in seen:
            raise PackError(f"inheritance cycle at {key}")
        seen.add(key)
        raw = load_raw(versions[ver])
        raw["__dir__"] = Path(versions[ver]).parent
        chain.append((key, raw))
        ref = (raw.get("meta") or {}).get("extends")

    chain.reverse()  # root first
    merged: dict = {}
    attributions: list[str] = []
    excluded: list[list[dict]] = []
    hook_decls: dict[str, dict] = {}
    hook_dirs: dict[str, Path] = {}
    for key, raw in chain:
        pack_dir = raw.pop("__dir__")
        for hook in raw.get("hooks") or []:  # hooks accumulate along the chain, by name
            name = hook.get("name") if isinstance(hook, dict) else hook
            hook_decls[name] = hook if isinstance(hook, dict) else {"name": name}
            hook_dirs[name] = pack_dir
        raw = copy.deepcopy(raw)
        removals = raw.pop("remove", None)
        meta = raw.pop("meta", {}) or {}
        dupes = list(_duplicate_ids(raw))
        if dupes:
            raise PackError(f"{key} declares an id twice in one catalogue: "
                            + "; ".join(f"{where}: {', '.join(ids)}" for where, ids in dupes)
                            + ". Ids are unique per catalogue; to change an inherited entry, declare it once")
        if not _version_ok(meta.get("kernel_compat")):
            raise PackError(f"{key} is not compatible with kernel {KERNEL_VERSION}")
        merged = _merge(merged, raw)
        _apply_removals(merged, removals, key)
        text = meta.get("attribution_text")
        if text and text not in attributions:
            attributions.append(text)
        if meta.get("excluded_terms"):
            excluded.append(meta["excluded_terms"])

    leaf_key, leaf_raw = chain[-1]
    leaf_meta = dict(leaf_raw.get("meta") or {})
    if leaf_meta.get("abstract") and not allow_abstract:
        raise PackError(f"{leaf_key} is abstract and cannot be played")
    merged["meta"] = {
        "id": leaf_meta["id"],
        "version": str(leaf_meta["version"]),
        "name": leaf_meta.get("name", leaf_meta["id"]),
        "license": leaf_meta.get("license"),
        "abstract": bool(leaf_meta.get("abstract", False)),
        "lineage": [k for k, _ in chain],
        "attributions": attributions,
        "kernel_version": KERNEL_VERSION,
    }
    if excluded:  # names the licence does not cover, inherited and merged by term (§1.2)
        from .terms import merge
        merged["meta"]["excluded_terms"] = merge(excluded)

    if hook_decls:  # checked against the determinism contract now; the source is hashed with the pack
        from .hooks import load as load_hooks
        try:
            merged["hooks"] = load_hooks([hook_decls[n] for n in sorted(hook_decls)], hook_dirs)
        except PackError as e:
            raise PackError(f"{leaf_key} {e}") from None

    return ResolvedPack(data=merged, hash=hash_obj(merged), lineage=[k for k, _ in chain])


def scaffold(pack_id: str, extends: str, packs_dir: str | Path, name: str | None = None) -> Path:
    """`tob pack new`: a pack containing only meta, which already resolves as its baseline."""
    target = Path(packs_dir) / pack_id
    if target.exists():
        raise PackError(f"{target} already exists")
    base = resolve(extends, packs_dir)
    target.mkdir(parents=True)
    doc = {
        "meta": {
            "id": pack_id,
            "version": "0.1.0",
            "extends": f"{base.id}@{base.version}",
            "name": name or pack_id,
            "license": "UNSET - choose an open license before broadcast (ARCHITECTURE §1.2)",
            "attribution_text": None,
            "kernel_compat": ">=0.1,<0.2",
        }
    }
    header = (
        f"# System pack '{pack_id}', extending {base.id}@{base.version}.\n"
        "# Add only what differs from the baseline. Catalogue entries merge by id;\n"
        "# use `remove: {\"entity_model.conditions\": [id, ...]}` to delete inherited entries.\n"
        "# Run `tob pack lint " + pack_id + "` after every change.\n"
    )
    (target / PACK_FILE).write_text(header + yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return target / PACK_FILE

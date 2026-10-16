"""Locate the project root (where packs/, scenarios/, deploy/ live)."""

from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    env = os.environ.get("BASILISK_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve().parents[2]  # src/basilisk/paths.py -> project root
    if (here / "packs").is_dir():
        return here
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "packs").is_dir() and (candidate / "pyproject.toml").exists():
            return candidate
    raise SystemExit("cannot find the project root; set BASILISK_ROOT")


def packs_dir() -> Path:
    return root() / "packs"


def data_dir() -> Path:
    return Path(os.environ.get("BASILISK_DATA", root() / "data")).resolve()

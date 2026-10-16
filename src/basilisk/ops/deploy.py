"""Release packaging, deploy, rollback, and backups for the office PC.

Releases are immutable directories with their own virtualenv:
    {app_dir}/releases/<stamp>-<git sha>/   code + .venv
    {app_dir}/current -> releases/<...>     atomic symlink switch
Every deploy runs `tob check --quick` on the target before switching, so a
release that fails the kernel gate on the real hardware never goes live.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

from ..paths import root
from .remote import host_env, run_script, ssh

INCLUDE = ["pyproject.toml", "README.md", "ROADMAP.md", "src", "packs", "scenarios", "deploy", "tools",
           "docs", "config/hosts.example.yaml", "config/campaign.example.yaml"]
EXCLUDE_PARTS = {"__pycache__", ".venv", ".pytest_cache", "data", "backups", ".git"}


def release_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root(), capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root(), capture_output=True,
                               text=True).stdout.strip()
        return f"{stamp}-{sha}{'-dirty' if dirty else ''}"
    except (OSError, subprocess.CalledProcessError):
        return f"{stamp}-nogit"


def build_tarball() -> tuple[bytes, list[str]]:
    base = root()
    buf = io.BytesIO()
    names: list[str] = []
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in INCLUDE:
            path = base / item
            if not path.exists():
                continue
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
            for f in files:
                rel = f.relative_to(base)
                if EXCLUDE_PARTS & set(rel.parts) or f.suffix in (".pyc", ".db"):
                    continue
                info = tar.gettarinfo(str(f), arcname=str(rel).replace("\\", "/"))
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with open(f, "rb") as fh:
                    tar.addfile(info, fh)
                names.append(str(rel))
    return buf.getvalue(), names


def deploy(host: dict, dry_run: bool = False) -> str:
    release = release_name()
    blob, names = build_tarball()
    print(f"release {release}: {len(names)} files, {len(blob) // 1024} KiB -> {host['ssh']}:{host['app_dir']}")
    if dry_run:
        for n in names[:40]:
            print("  ", n)
        if len(names) > 40:
            print(f"   ... {len(names) - 40} more")
        return release
    rel_dir = f"{host['app_dir']}/releases/{release}"
    t0 = time.time()
    ssh(host, f"mkdir -p '{rel_dir}' && tar -xzf - -C '{rel_dir}'", stdin=blob)
    print(f"uploaded in {time.time() - t0:.1f}s; installing and running the gate on the target...")
    run_script(host, root() / "deploy" / "remote" / "install_release.sh", {**host_env(host), "RELEASE": release})
    print(f"release {release} is live")
    return release


def rollback(host: dict) -> None:
    run_script(host, root() / "deploy" / "remote" / "rollback.sh", host_env(host))


def pull_backup(host: dict, db_name: str = "events.db") -> Path:
    remote_tmp = f"/tmp/tob-backup-{int(time.time())}.db"
    cmd = (f"'{host['app_dir']}/current/.venv/bin/tob' db backup '{host['data_dir']}/{db_name}' '{remote_tmp}' "
           f">/dev/null && cat '{remote_tmp}'; rc=$?; rm -f '{remote_tmp}'; exit $rc")
    data = ssh(host, cmd).stdout
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = root() / "backups" / host["name"] / f"{Path(db_name).stem}-{stamp}.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest

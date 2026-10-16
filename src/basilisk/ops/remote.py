"""SSH helpers and host configuration for the deploy target.

Uses the system OpenSSH client (available on Linux, macOS, and Windows 10+),
key-based authentication only (BatchMode), and never opens inbound ports.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import yaml

from ..paths import root

DEFAULTS = {
    "app_dir": "/opt/basilisk",
    "data_dir": "/srv/basilisk/data",
    "media_dir": "/srv/basilisk/media",
    "keep_releases": 5,
}


class RemoteError(RuntimeError):
    pass


def load_host(name: str) -> dict:
    path = root() / "config" / "hosts.yaml"
    if not path.exists():
        raise RemoteError("config/hosts.yaml not found - copy config/hosts.example.yaml and edit it")
    hosts = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("hosts") or {}
    if name not in hosts:
        raise RemoteError(f"no host {name!r} in config/hosts.yaml (have: {', '.join(hosts) or 'none'})")
    host = {**DEFAULTS, **hosts[name], "name": name}
    if "ssh" not in host:
        raise RemoteError(f"host {name!r} needs an ssh: user@address entry")
    return host


def require_ssh() -> str:
    exe = shutil.which("ssh")
    if not exe:
        raise RemoteError("OpenSSH client not found on PATH")
    return exe


def ssh(host: dict, command: str, *, stdin: bytes | None = None, tty: bool = False,
        capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    args = [require_ssh()]
    if tty:
        args.append("-t")
    else:
        args += ["-o", "BatchMode=yes"]
    args += ["-o", "ConnectTimeout=10", host["ssh"], command]
    proc = subprocess.run(args, input=stdin, capture_output=capture and not tty)
    if check and proc.returncode != 0:
        err = (proc.stderr or b"").decode(errors="replace").strip() if capture and not tty else ""
        raise RemoteError(f"remote command failed ({proc.returncode}): {command[:80]}\n{err}")
    return proc


def run_script(host: dict, script: Path, env: dict[str, str] | None = None, check: bool = True,
               capture: bool = False) -> subprocess.CompletedProcess:
    """Send a local bash script over stdin and run it remotely with environment variables."""
    exports = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in (env or {}).items())
    return ssh(host, f"{exports} bash -s", stdin=script.read_bytes(), capture=capture, check=check)


def host_env(host: dict) -> dict[str, str]:
    return {
        "APP_DIR": host["app_dir"], "DATA_DIR": host["data_dir"], "MEDIA_DIR": host["media_dir"],
        "KEEP_RELEASES": str(host["keep_releases"]),
    }

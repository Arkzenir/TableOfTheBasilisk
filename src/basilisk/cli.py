"""`tob` - the Table of The Basilisk development and deployment harness.

Run `tob --help` or `tob <command> --help`.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .kernel import KERNEL_VERSION
from .paths import data_dir, packs_dir, root

OK, WARN, FAIL = "ok  ", "warn", "FAIL"


def _print_check(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status}] {label}" + (f" - {detail}" if detail else ""))


# ====================================================================== local commands

def cmd_doctor(args) -> int:
    print(f"Table of The Basilisk {__version__} (kernel {KERNEL_VERSION})")
    print(f"  root: {root()}")
    failures = 0
    py = sys.version_info
    ok = py >= (3, 11)
    _print_check(OK if ok else FAIL, "python >= 3.11", platform.python_version())
    failures += not ok
    for mod in ("yaml", "sqlite3"):
        try:
            __import__(mod)
            _print_check(OK, f"module {mod}")
        except ImportError:
            _print_check(FAIL, f"module {mod}", "pip install -e .")
            failures += 1
    try:
        import pytest  # noqa: F401
        _print_check(OK, "pytest", "dev extras installed")
    except ImportError:
        _print_check(WARN, "pytest", 'not installed; run pip install -e ".[dev]" for the full gate')
    for exe, why in (("ssh", "deploy and remote commands"), ("git", "release names")):
        _print_check(OK if shutil.which(exe) else WARN, exe, why)
    hosts = root() / "config" / "hosts.yaml"
    _print_check(OK if hosts.exists() else WARN, "config/hosts.yaml",
                 "present" if hosts.exists() else "copy config/hosts.example.yaml before deploying")
    from .kernel.packlint import errors, lint
    from .kernel.packs import discover, resolve
    for pid in sorted(discover(packs_dir())):
        try:
            pack = resolve(pid, packs_dir())
            errs = errors(lint(pack))
            _print_check(FAIL if errs else OK, f"pack {pid}", f"{len(errs)} lint error(s)" if errs else pack.hash[:12])
            failures += bool(errs)
        except Exception as e:  # noqa: BLE001
            _print_check(FAIL, f"pack {pid}", str(e))
            failures += 1
    return 1 if failures else 0


def cmd_check(args) -> int:
    """The local gate. --quick skips pytest (used on the deploy target)."""
    from .harness.scripted import determinism_check, run_script, smoke_script, verify
    from .kernel.packlint import errors, lint
    from .kernel.packs import discover, resolve
    from .ops.nounlint import run as noun_lint

    failed = []
    print("== kernel noun lint")
    hits = noun_lint(root())
    for h in hits:
        print("  ", h)
    print("   clean" if not hits else f"   {len(hits)} hit(s)")
    if hits:
        failed.append("noun lint")

    print("== pack lint")
    playable = []
    for pid in sorted(discover(packs_dir())):
        pack = resolve(pid, packs_dir())
        errs = errors(lint(pack))
        print(f"   {pid:<22} {'OK' if not errs else f'{len(errs)} error(s)'}")
        for e in errs:
            print("     ", e)
        if errs:
            failed.append(f"lint {pid}")
        elif not pack.data["meta"]["abstract"]:
            playable.append(pack)

    print("== scripted campaigns (replay, seed re-derivation, double-run determinism)")
    sessions = 1 if args.quick else 3
    for pack in playable:
        t0 = time.time()
        script = smoke_script(pack, sessions=sessions)
        engine, report = run_script(script, packs_dir())
        problems = verify(engine.store, report.campaign_id, pack, script["seed"], report.state_hash)
        problems += determinism_check(script, packs_dir())
        if report.actions_never_taken:
            problems.append(f"actions never taken: {report.actions_never_taken}")
        status = "OK" if not problems else "FAIL"
        print(f"   {pack.id:<22} {status}  {report.events} events, {time.time() - t0:.2f}s")
        for p in problems:
            print("     ", p)
        if problems:
            failed.append(f"campaign {pack.id}")

    if not args.quick:
        print("== pytest")
        try:
            import pytest
        except ImportError:
            print('   pytest not installed: pip install -e ".[dev]"')
            failed.append("pytest missing")
        else:
            code = pytest.main(["-q", str(root() / "tests")])
            if code != 0:
                failed.append("pytest")

    print("\nGATE:", "PASS" if not failed else "FAIL (" + ", ".join(failed) + ")")
    return 1 if failed else 0


def cmd_lint_nouns(args) -> int:
    from .ops.nounlint import run
    hits = run(root())
    for h in hits:
        print(h)
    print("kernel noun lint: clean" if not hits else f"{len(hits)} hit(s)")
    return 1 if hits else 0


def cmd_pack(args) -> int:
    from .kernel.packlint import RULES_TEXT_TOKEN_BUDGET, errors, lint, readiness
    from .kernel.rules import layer_size
    from .kernel.packs import discover, resolve, scaffold

    if args.pack_cmd == "list":
        for pid, versions in sorted(discover(packs_dir()).items()):
            for ver in sorted(versions):
                pack = resolve(f"{pid}@{ver}", packs_dir())
                kind = "abstract" if pack.data["meta"]["abstract"] else "playable"
                print(f"{pid:<22} {ver:<8} {kind:<9} {pack.hash[:12]}  {' > '.join(pack.lineage)}")
        return 0
    if args.pack_cmd == "resolve":
        pack = resolve(args.pack, packs_dir())
        if args.json:
            print(json.dumps(pack.data, indent=2, sort_keys=True))
        else:
            print(f"{pack.id}@{pack.version}  hash {pack.hash}")
            print("lineage:", " > ".join(pack.lineage))
            print("attributions:", *pack.data["meta"]["attributions"], sep="\n  ")
        return 0
    if args.pack_cmd == "lint":
        ids = args.packs or sorted(discover(packs_dir()))
        code = 0
        for pid in ids:
            pack = resolve(pid, packs_dir())
            findings = lint(pack)
            print(f"{pid}: {len(errors(findings))} error(s), {len(findings) - len(errors(findings))} warning(s)")
            for f in findings:
                print("  ", f)
            ready = readiness(pack)
            print("   strict-ready:", ", ".join(f"{c}={'yes' if v else 'NO'}" for c, v in ready.items()))
            print(f"   hooks: {len(pack.get('hooks') or [])}")  # a health metric for the pack language (§2.4)
            size = layer_size(pack, RULES_TEXT_TOKEN_BUDGET)  # layer 2 against its budget (P0.6)
            print(f"   rules text: {size['mode']}, ~{size['tokens']} of {size['budget']} tokens"
                  + (f", {size['sections']} sections" if "sections" in size else ""))
            code |= bool(errors(findings))
        return code
    if args.pack_cmd == "new":
        path = scaffold(args.pack, args.extends, packs_dir(), args.name)
        print(f"created {path}\nnext: edit it, then `tob pack lint {args.pack}`")
        return 0
    return 2


def cmd_schemas(args) -> int:
    from .kernel.determinism import expand
    from .kernel.packs import resolve
    from .kernel.tools import free_values, generate

    pack = resolve(args.pack, packs_dir())
    eff = expand({"players": {"preset": args.preset}, "gm": {"preset": args.preset}})
    tools = generate(pack, eff, args.role)
    print(json.dumps(tools, indent=2))
    free = free_values(tools)
    print(f"\nfree values ({args.role}, {args.preset}):", ", ".join(free) if free else "none")
    return 0


def cmd_sim(args) -> int:
    from .broadcast.cards import CardRenderer
    from .harness.scripted import load_script, run_script, smoke_script, verify
    from .kernel.events import EventStore
    from .kernel.packs import resolve

    if args.script:
        script = load_script(args.script)
    elif args.smoke:
        script = smoke_script(resolve(args.smoke, packs_dir()), seed=args.seed or "smoke-seed",
                              sessions=args.sessions)
    else:
        print("give a script path or --smoke PACK")
        return 2
    if args.seed:
        script["seed"] = args.seed
    store = EventStore(args.db) if args.db else EventStore(":memory:")
    engine, report = run_script(script, packs_dir(), store=store)
    print(report.summary())
    problems = verify(store, report.campaign_id, engine.pack, script["seed"], report.state_hash)
    print("verify       ", "OK" if not problems else "; ".join(problems))
    if args.cards:
        events = list(store.read(report.campaign_id))
        print()
        for card in CardRenderer(events, engine.pack).all_cards()[: args.cards]:
            print(card)
    if args.db:
        print(f"log written to {args.db} (campaign {report.campaign_id})")
    return 1 if problems else 0


def cmd_verify(args) -> int:
    from .harness.scripted import verify
    from .kernel.events import EventStore
    from .kernel.packs import resolve

    store = EventStore(args.db, create=False)
    campaigns = [args.campaign] if args.campaign else store.campaigns()
    if not campaigns:
        print(f"{args.db}: no campaigns to verify")
        return 1
    code = 0
    for cid in campaigns:
        first = next(store.read(cid), None)
        pack = None
        if first and first["type"] == "campaign_started":
            try:
                pack = resolve(first["payload"]["pack_id"], packs_dir())
            except Exception:  # noqa: BLE001
                pack = None
        problems = verify(store, cid, pack, args.seed)
        print(f"{cid}: {'OK' if not problems else 'FAIL'}")
        if pack is None and first:
            print(f"   note: pack {first['payload'].get('pack_id')!r} is not in this checkout; "
                  "its pinned hash was not compared")
        for p in problems:
            print("  ", p)
        code |= bool(problems)
    return code


def cmd_fork(args) -> int:
    from .kernel.events import EventStore
    n = EventStore(args.db, create=False).fork(args.campaign, args.seq, args.new_campaign)
    print(f"forked {n} events of {args.campaign} into {args.new_campaign} (debugging only - never editorial, P6)")
    return 0


def cmd_db(args) -> int:
    from .kernel.events import EventStore
    if args.db_cmd == "backup":
        EventStore(args.src, create=False).backup_to(args.dst)
        print(f"backed up {args.src} -> {args.dst}")
        return 0
    return 2


def cmd_soak(args) -> int:
    from .ops.soak import soak
    target = Path(args.data_dir) if args.data_dir else data_dir()
    return soak(packs_dir(), target, args.hours, args.sessions)


# ====================================================================== remote commands

def cmd_deploy(args) -> int:
    from .ops.deploy import deploy
    from .ops.remote import load_host
    deploy(load_host(args.host), dry_run=args.dry_run, allow_dirty=args.allow_dirty)
    return 0


def cmd_rollback(args) -> int:
    from .ops.deploy import rollback
    from .ops.remote import load_host
    rollback(load_host(args.host))
    return 0


def cmd_host(args) -> int:
    from .ops.remote import load_host, ssh
    host = load_host(args.host)
    script = root() / "deploy" / "bootstrap_host.sh"
    ssh(host, "cat > /tmp/tob-bootstrap.sh", stdin=script.read_bytes())
    deploy_user = host["ssh"].split("@")[0] if "@" in host["ssh"] else "$USER"
    flags = (f"--deploy-user {deploy_user} --app '{host['app_dir']}' --data '{host['data_dir']}' "
             f"--media '{host['media_dir']}' --lan '{host.get('lan', '')}'")
    print("Running bootstrap with sudo on the host (you may be asked for your password)...")
    proc = ssh(host, f"sudo bash /tmp/tob-bootstrap.sh {flags}; rc=$?; rm -f /tmp/tob-bootstrap.sh; exit $rc",
               tty=True, check=False, capture=False)
    return proc.returncode


def cmd_remote(args) -> int:
    from .ops.remote import host_env, load_host, run_script, ssh
    host = load_host(args.host)
    scripts = root() / "deploy" / "remote"
    action = args.action
    if action == "status":
        return run_script(host, scripts / "status.sh", host_env(host), check=False).returncode
    if action == "doctor":
        return run_script(host, scripts / "doctor.sh", host_env(host), check=False).returncode
    if action == "encode-test":
        return run_script(host, scripts / "encode_test.sh", host_env(host), check=False).returncode
    if action == "logs":
        return ssh(host, "journalctl -u 'basilisk-*' -n 200 --no-pager", capture=False, check=False).returncode
    if action in ("soak-start", "soak-stop"):
        verb = "start" if action == "soak-start" else "stop"
        return ssh(host, f"sudo -n systemctl {verb} basilisk-soak.service", capture=False, check=False).returncode
    return 2


def cmd_backup(args) -> int:
    from .harness.scripted import verify
    from .kernel.events import EventStore
    from .ops.deploy import pull_backup
    from .ops.remote import load_host
    dest = pull_backup(load_host(args.host), args.db)
    store = EventStore(dest)
    bad = {cid: verify(store, cid) for cid in store.campaigns()}
    bad = {k: v for k, v in bad.items() if v}
    print(f"saved {dest} ({dest.stat().st_size // 1024} KiB, {len(store.campaigns())} campaign(s))")
    if not store.campaigns():  # an empty copy is not a backup
        print("integrity: PROBLEM - the backup holds no campaigns")
        return 1
    print("integrity:", "OK" if not bad else f"PROBLEMS in {sorted(bad)}")
    return 1 if bad else 0


# ====================================================================== parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tob", description="Table of The Basilisk development harness")
    p.add_argument("--version", action="version", version=f"tob {__version__} (kernel {KERNEL_VERSION})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check the local environment").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("check", help="run the full local gate (lint, campaigns, determinism, tests)")
    s.add_argument("--quick", action="store_true", help="skip pytest and use one-session campaigns")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("lint", help="lint helpers")
    s.add_argument("what", choices=["nouns"])
    s.set_defaults(fn=cmd_lint_nouns)

    s = sub.add_parser("pack", help="system pack tools")
    ps = s.add_subparsers(dest="pack_cmd", required=True)
    ps.add_parser("list")
    r = ps.add_parser("resolve")
    r.add_argument("pack")
    r.add_argument("--json", action="store_true")
    r = ps.add_parser("lint")
    r.add_argument("packs", nargs="*")
    r = ps.add_parser("new")
    r.add_argument("pack")
    r.add_argument("--extends", required=True, help="baseline, e.g. core.roll_over or lanternlight")
    r.add_argument("--name")
    s.set_defaults(fn=cmd_pack)

    s = sub.add_parser("schemas", help="print generated tool schemas for a pack, role and preset")
    s.add_argument("pack")
    s.add_argument("--role", choices=["players", "gm"], default="gm")
    s.add_argument("--preset", choices=["strict", "standard"], default="strict")
    s.set_defaults(fn=cmd_schemas)

    s = sub.add_parser("sim", help="run a scripted campaign")
    s.add_argument("script", nargs="?", help="scenario YAML")
    s.add_argument("--smoke", metavar="PACK", help="generate a pack-agnostic smoke campaign")
    s.add_argument("--sessions", type=int, default=3)
    s.add_argument("--seed")
    s.add_argument("--db", help="write the event log to this SQLite file")
    s.add_argument("--cards", type=int, nargs="?", const=8, default=0, metavar="N",
                   help="print the first N rule cards (default 8)")
    s.set_defaults(fn=cmd_sim)

    s = sub.add_parser("verify", help="verify hash chains and replay for an event store")
    s.add_argument("db")
    s.add_argument("--campaign")
    s.add_argument("--seed", help="also re-derive every roll from the published seed")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("fork", help="fork a campaign at a seq (debugging only)")
    s.add_argument("db")
    s.add_argument("campaign")
    s.add_argument("seq", type=int)
    s.add_argument("new_campaign")
    s.set_defaults(fn=cmd_fork)

    s = sub.add_parser("db", help="database utilities")
    ds = s.add_subparsers(dest="db_cmd", required=True)
    b = ds.add_parser("backup")
    b.add_argument("src")
    b.add_argument("dst")
    s.set_defaults(fn=cmd_db)

    s = sub.add_parser("soak", help="run scripted campaigns back to back (stability testing)")
    s.add_argument("--hours", type=float, default=1.0, help="0 = run until stopped")
    s.add_argument("--sessions", type=int, default=3)
    s.add_argument("--data-dir")
    s.set_defaults(fn=cmd_soak)

    s = sub.add_parser("deploy", help="package, upload, gate and switch a release on a host")
    s.add_argument("host")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--allow-dirty", action="store_true", help="deploy uncommitted changes (not recommended)")
    s.set_defaults(fn=cmd_deploy)

    s = sub.add_parser("rollback", help="switch a host back to its previous release")
    s.add_argument("host")
    s.set_defaults(fn=cmd_rollback)

    s = sub.add_parser("host", help="one-time host setup")
    hs = s.add_subparsers(dest="host_cmd", required=True)
    b = hs.add_parser("bootstrap")
    b.add_argument("host")
    s.set_defaults(fn=cmd_host)

    s = sub.add_parser("remote", help="operate a deployed host")
    s.add_argument("host")
    s.add_argument("action", choices=["status", "doctor", "encode-test", "logs", "soak-start", "soak-stop"])
    s.set_defaults(fn=cmd_remote)

    s = sub.add_parser("backup", help="pull an event-store backup from a host and verify it")
    bs = s.add_subparsers(dest="backup_cmd", required=True)
    b = bs.add_parser("pull")
    b.add_argument("host")
    b.add_argument("--db", default="events.db")
    s.set_defaults(fn=cmd_backup)
    return p


def _utf8_streams() -> None:
    """Cards and sheets print box-drawing and accented text; a Windows console
    defaults to a legacy code page that cannot encode it. Replace, never crash."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001 - CLI boundary: print, don't traceback, unless asked
        if "--debug" in sys.argv or __import__("os").environ.get("TOB_DEBUG"):
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

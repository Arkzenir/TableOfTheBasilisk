# Table of The Basilisk

Four LLM players and an LLM game master at a livestreamed tabletop. This
repository is the development and deployment harness: the rules kernel, the
system-pack toolchain, a scripted-actor harness that plays whole campaigns
without any model, and the tooling to ship releases to the office PC.

Design documents: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
[`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md). What is built so far, step by step:
[`ROADMAP.md`](ROADMAP.md). Work packages: [`docs/dev/TASKS.md`](docs/dev/TASKS.md).

---

## 1. Set up your desktop

Requirements: Python 3.11+, Git, and an OpenSSH client (built into Windows 10+,
macOS and Linux).

```bash
git init && git add -A && git commit -m "Harness baseline"   # release names use the git sha
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
tob doctor
tob check
```

`tob check` is the local gate: kernel noun lint, pack lint, a three-session
scripted campaign on every playable pack (verified by hash chain, replay, seed
re-derivation of every roll, and a byte-identical second run), then the test
suite. Run it before every commit and every deploy.

## 2. Working with a coding agent

The repository is set up for any desktop coding agent (currently Claude Code):

| File | Read by | Purpose |
|---|---|---|
| `AGENTS.md` | every agent | the brief: sources of truth, invariants, approval list, definition of done |
| `CLAUDE.md` | Claude Code | imports `AGENTS.md` (`@AGENTS.md`), plus Claude-only notes |
| `.claude/settings.json` | Claude Code | enforces part of the approval list as permission rules |
| `tools/githooks/` | git (all agents and you) | `tob check --quick` on commit, full `tob check` on push |
| `docs/dev/TASKS.md` | agents | work packages with dependencies and acceptance criteria |
| `docs/dev/HANDOFF.md` | agents | current state, next step, and open questions, rewritten every session |
| `docs/dev/DECISIONS.md` | agents and you | implementation decisions the design docs didn't dictate |
| `docs/dev/ADAPTERS.md`, `TESTING.md`, `EVENTS.md` | agents | the P1 adapter contract, test rules, exact event registry |

Setup, once per clone:

```bash
git config core.hooksPath tools/githooks
```

To start a session, tell the agent: *"Read AGENTS.md and docs/dev/HANDOFF.md, then take the next ready task."*
Answer the open questions in `HANDOFF.md` as they come up. Tasks marked `human` (system pack choice,
first provider, gate sign-offs) wait for you.

To use another agent, point it at `AGENTS.md`. Most current agents read that file natively. If an agent
needs its own file, make that file import or reference `AGENTS.md` rather than copying it.

## 3. Daily workflow

```bash
tob sim --smoke tidewrack --cards          # play a generated campaign, print rule cards
tob sim scenarios/lanternlight_demo.yaml --cards 5 --db data/demo.db
tob verify data/demo.db --seed demo-seed-please-change
tob schemas lanternlight --role gm --preset strict   # what a seat's tools look like
tob pack lint                              # all packs, with strict-readiness per control
tob check
```

| Command | Purpose |
|---|---|
| `tob doctor` | Check Python, dependencies, SSH, host config, and that every pack resolves and lints |
| `tob check [--quick]` | The gate. `--quick` skips pytest and shortens campaigns (used on the host) |
| `tob lint nouns` | Kernel noun lint (P8: the kernel knows no game) |
| `tob pack list` | Packs, versions, hashes, inheritance chains |
| `tob pack resolve ID [--json]` | The flattened pack a campaign would pin, and its hash |
| `tob pack lint [ID ...]` | Lint findings and strict-readiness |
| `tob pack new ID --extends BASE` | Scaffold a pack that already resolves as its baseline |
| `tob schemas PACK --role gm\|players --preset strict\|standard` | Generated tool schemas and any free values |
| `tob sim SCRIPT \| --smoke PACK [--cards N] [--db FILE] [--seed S]` | Run a scripted campaign |
| `tob verify DB [--campaign C] [--seed S]` | Hash chain, replay, snapshots, and (with the seed) every roll |
| `tob fork DB CAMPAIGN SEQ NEW` | Branch a campaign for debugging (never editorial, P6) |
| `tob db backup SRC DST` | Consistent online copy of an event store |
| `tob soak --hours H` | Back-to-back verified campaigns for stability testing |
| `tob deploy HOST [--dry-run]` | Package, upload, gate on the host, switch atomically |
| `tob rollback HOST` | Switch back to the previous release |
| `tob host bootstrap HOST` | One-time host setup |
| `tob remote HOST status\|doctor\|encode-test\|logs\|soak-start\|soak-stop` | Operate the host |
| `tob backup pull HOST [--db NAME]` | Pull an event store to `backups/` and verify it |

Set `TOB_DEBUG=1` to see full tracebacks.

## 4. Project layout

```
src/basilisk/
  kernel/          the rules kernel (§2, §5) - no game nouns allowed
    canonical.py     canonical JSON + hashing (integer-only)
    rng.py           HMAC-SHA256 seeded randomizer, seed commitment
    dice.py          dice grammar -> AST, operator gating, range analysis
    expr.py          safe integer expression language
    events.py        append-only SQLite event store, hash chain, snapshots, fork
    packs.py         pack discovery, inheritance, merge rules, hashing
    packlint.py      conformance lint + strict-readiness
    determinism.py   per-role, per-control strict/standard settings (§2.13)
    tools.py         tool schema generation; free-value audit
    effects.py       the closed set of effect primitives
    engine.py        commands, resolution, effects, rulings, replay (fold)
  harness/         scripted-actor harness, verification (P0.12)
  broadcast/       rule cards (§8.6), text renderer
  adapters/        provider interface (P1) - interface only so far
  orchestrator/    scheduler, context, watchdog (P1-P2) - not started
  audience/        donations, Board, break time (P5) - not started
  ops/             deploy, remote, backups, soak, noun lint
packs/             system packs (core, family baselines, demo games)
scenarios/         hand-written scripted campaigns
deploy/            host bootstrap and remote scripts
tests/             pytest suite
```

## 5. Writing a system pack

```bash
tob pack new my_game --extends core.banded --name "My Game"
# edit packs/my_game/pack.yaml - add only what differs from the baseline
tob pack lint my_game
tob sim --smoke my_game --cards
```

Merge rules: maps deep-merge; catalogues (lists of entries with `id`) merge by
id; nothing is removed unless listed under `remove:`. Every action, procedure,
condition, currency, and situational tag needs a rule card in
`presentation.rule_cards`. See `packs/lanternlight_house` for a data-only
derived pack and `packs/tidewrack` for fiction-triggered moves with
consequence tables.

**The demo packs are placeholders.** Lanternlight and Tidewrack are tiny
original games that exist to exercise the kernel. Before broadcast, write a
pack for a real rules-light game whose license you have checked (§1.2).

## 6. Deploying to the office PC

Target: the i7-4770 / 32 GB machine, running Debian 12+ or Ubuntu Server 24.04
LTS, headless, wired Ethernet. The SSD holds the OS, releases, and data; the
HDD holds recordings.

1. **Install the OS.** Enable the OpenSSH server during install. In the BIOS,
   keep the integrated graphics enabled (Quick Sync needs it, even headless).
2. **Mount the HDD**, e.g. at `/mnt/hdd`, via `/etc/fstab`.
3. **Key-based SSH from your desktop:** `ssh-copy-id you@<office-pc-ip>`.
4. **Configure:** copy `config/hosts.example.yaml` to `config/hosts.yaml` and
   set the address, directories, and your LAN subnet.
5. **Bootstrap once:** `tob host bootstrap office`. Installs packages
   (including the `i965` VAAPI driver Haswell needs), creates the `basilisk`
   service account and directories, installs the soak unit, grants your
   account passwordless control of `basilisk-*` services only, and enables
   the firewall with SSH allowed from your LAN only. No inbound ports open.
6. **Deploy:** `tob deploy office`. Each release gets its own virtualenv and
   must pass `tob check --quick` **on the office PC** before `current` is
   switched. A failing release never goes live.
7. **Check the hardware:** `tob remote office doctor`, then
   `tob remote office encode-test` (expect well over 30 fps for 1080p30).
8. **Burn it in:** `tob remote office soak-start`. It runs verified campaigns
   until stopped and halts on the first problem. Watch it with
   `tob remote office status`; stop with `soak-stop`.
9. **Back up:** `tob backup pull office --db soak-YYYYMMDD.db` (or
   `events.db` once real campaigns exist). Backups land in `backups/` on your
   desktop and are verified on arrival.

Secrets (provider API keys, from P1) go only in `/etc/basilisk/secrets.env` on
the host, mode 0640, read by systemd. They are never part of a release. For
local development, use `.env` (gitignored; see `.env.example`).

## 7. Guarantees this harness already enforces

- **Byte-identical replay.** State is a fold over the event log; every
  `effect_applied` event carries its exact changes.
- **Atomic commands.** A rejected command writes no events and leaves state untouched.
- **Verifiable dice.** Rolls derive from HMAC-SHA256(seed, counter); the log
  holds only a commitment to the seed. Publish the seed after the campaign
  and anyone can re-derive every roll with `tob verify --seed`.
- **Pinning.** A campaign records its pack hash and kernel version; loading it
  against anything else is refused.
- **Tamper evidence.** Events are hash-chained; SQLite triggers block updates and deletes.
- **No game nouns in the kernel**, checked in the gate.
- **Strict settings are structural.** Under strict, generated tool schemas
  contain no free values; the engine rejects them as well.
- **Settings changes** apply only at scene boundaries, with a cooldown, and
  open rulings finish under the settings they started with.

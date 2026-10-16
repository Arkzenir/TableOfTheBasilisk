@AGENTS.md

## Claude Code

The shared instructions above apply in full; this section only adds Claude-specific notes.

- `.claude/settings.json` enforces part of the "Stop and ask" list as permission rules:
  - deploy, remote, ssh, push, and live-test commands require approval
  - `.env` and host secrets are unreadable
  - edits to the design docs and gate files require approval
- Personal or machine-specific permissions go in `.claude/settings.local.json` (gitignored), not in the shared file.
- To confirm this file and `AGENTS.md` loaded, run `/context` and check the memory files listed.

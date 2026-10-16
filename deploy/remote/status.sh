#!/usr/bin/env bash
set -uo pipefail
: "${APP_DIR:?}" "${DATA_DIR:?}" "${MEDIA_DIR:?}"
echo "host:      $(hostname)   up $(uptime -p 2>/dev/null || true)"
echo "release:   $(basename "$(readlink -f "$APP_DIR/current" 2>/dev/null)" 2>/dev/null || echo none)"
echo "releases:  $(ls -1 "$APP_DIR/releases" 2>/dev/null | wc -l)"
echo
systemctl --no-pager --plain list-units 'basilisk-*' 2>/dev/null || true
echo
df -h "$DATA_DIR" "$MEDIA_DIR" 2>/dev/null
echo
command -v sensors >/dev/null && sensors 2>/dev/null | grep -E 'Package id|Core [0-9]' || echo "(lm-sensors not available)"
if [ -f "$DATA_DIR/soak.log.jsonl" ]; then
  echo; echo "last soak runs:"; tail -n 3 "$DATA_DIR/soak.log.jsonl"
fi

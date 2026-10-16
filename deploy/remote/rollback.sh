#!/usr/bin/env bash
# Switch `current` to the release before it and restart services.
set -euo pipefail
: "${APP_DIR:?}"
CUR="$(readlink -f "$APP_DIR/current")"
PREV="$(ls -1dt "$APP_DIR"/releases/*/ | sed 's:/*$::' | grep -vx "$CUR" | head -n 1 || true)"
if [ -z "$PREV" ]; then echo "no earlier release to roll back to" >&2; exit 1; fi
ln -sfn "$PREV" "$APP_DIR/current.new"
mv -Tf "$APP_DIR/current.new" "$APP_DIR/current"
sudo -n systemctl try-restart 'basilisk-*.service' 2>/dev/null || true
echo "rolled back: $(basename "$CUR") -> $(basename "$PREV")"

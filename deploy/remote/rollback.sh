#!/usr/bin/env bash
# Switch `current` to the release that was live before it and restart services.
# Walks $APP_DIR/history (written by install_release.sh), so only releases
# that passed the gate are candidates; a second rollback goes back further.
set -euo pipefail
: "${APP_DIR:?}"
HISTORY="$APP_DIR/history"
if [ ! -f "$HISTORY" ]; then
    echo "no release history at $HISTORY: deploy once with this version of tob first" >&2
    exit 1
fi
CUR="$(basename "$(readlink -f "$APP_DIR/current")")"
if [ "$(tail -n 1 "$HISTORY")" != "$CUR" ]; then
    echo "current ($CUR) is not the last release in $HISTORY; fix current or the history by hand" >&2
    exit 1
fi
PREV="$(sed '$d' "$HISTORY" | tail -n 1)"
if [ -z "$PREV" ] || [ ! -d "$APP_DIR/releases/$PREV" ]; then
    echo "no earlier release to roll back to" >&2
    exit 1
fi
ln -sfn "$APP_DIR/releases/$PREV" "$APP_DIR/current.new"
mv -Tf "$APP_DIR/current.new" "$APP_DIR/current"
sed -i '$d' "$HISTORY"
sudo -n systemctl try-restart 'basilisk-*.service' 2>/dev/null || true
echo "rolled back: $CUR -> $PREV"

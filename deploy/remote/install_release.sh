#!/usr/bin/env bash
# Runs on the host via `tob deploy`. Builds the release venv, runs the kernel
# gate ON THE TARGET, switches `current` atomically, prunes old releases,
# and restarts any running basilisk services.
#
# $APP_DIR/history lists every release that went live, oldest first. Only a
# release that passed the gate is ever written there, so rollback (which walks
# this file) can never activate a release that failed it, and pruning keeps
# whatever is listed last, whatever the directories' timestamps say.
set -euo pipefail
: "${APP_DIR:?}" "${RELEASE:?}" "${KEEP_RELEASES:=5}"
REL="$APP_DIR/releases/$RELEASE"
HISTORY="$APP_DIR/history"

echo "[install] creating venv in $REL/.venv"
python3 -m venv "$REL/.venv"
"$REL/.venv/bin/pip" install --quiet --upgrade pip
"$REL/.venv/bin/pip" install --quiet -e "$REL"

echo "[install] running the kernel gate on the target"
if ! BASILISK_ROOT="$REL" "$REL/.venv/bin/tob" check --quick; then
    echo "[install] GATE FAILED - release left in place but NOT activated: $REL" >&2
    exit 1
fi

# A host deployed before the history file existed: seed it with the live release.
if [ ! -f "$HISTORY" ] && [ -L "$APP_DIR/current" ]; then
    basename "$(readlink -f "$APP_DIR/current")" > "$HISTORY"
fi

ln -sfn "$REL" "$APP_DIR/current.new"
mv -Tf "$APP_DIR/current.new" "$APP_DIR/current"
echo "$RELEASE" >> "$HISTORY"
echo "[install] current -> $RELEASE"

# Keep the last KEEP_RELEASES releases that went live; remove every other
# release directory, including any that failed the gate.
KEEP="$(tail -n "$KEEP_RELEASES" "$HISTORY")"
for dir in "$APP_DIR"/releases/*/; do
    name="$(basename "$dir")"
    if ! printf '%s\n' "$KEEP" | grep -qxF "$name"; then
        rm -rf "$dir"
    fi
done
sudo -n systemctl try-restart 'basilisk-*.service' 2>/dev/null || true

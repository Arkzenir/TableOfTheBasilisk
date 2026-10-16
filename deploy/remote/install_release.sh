#!/usr/bin/env bash
# Runs on the host via `tob deploy`. Builds the release venv, runs the kernel
# gate ON THE TARGET, switches `current` atomically, prunes old releases,
# and restarts any running basilisk services.
set -euo pipefail
: "${APP_DIR:?}" "${RELEASE:?}" "${KEEP_RELEASES:=5}"
REL="$APP_DIR/releases/$RELEASE"

echo "[install] creating venv in $REL/.venv"
python3 -m venv "$REL/.venv"
"$REL/.venv/bin/pip" install --quiet --upgrade pip
"$REL/.venv/bin/pip" install --quiet -e "$REL"

echo "[install] running the kernel gate on the target"
if ! BASILISK_ROOT="$REL" "$REL/.venv/bin/tob" check --quick; then
    echo "[install] GATE FAILED - release left in place but NOT activated: $REL" >&2
    exit 1
fi

ln -sfn "$REL" "$APP_DIR/current.new"
mv -Tf "$APP_DIR/current.new" "$APP_DIR/current"
echo "[install] current -> $RELEASE"

ls -1dt "$APP_DIR"/releases/*/ 2>/dev/null | tail -n +"$((KEEP_RELEASES + 1))" | xargs -r rm -rf
sudo -n systemctl try-restart 'basilisk-*.service' 2>/dev/null || true

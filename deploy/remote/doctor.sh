#!/usr/bin/env bash
# Hardware and OS checks for the office PC (i7-4770 / HD 4600 expectations).
set -uo pipefail
: "${APP_DIR:?}" "${DATA_DIR:?}" "${MEDIA_DIR:?}"
pass() { echo "  [ok  ] $*"; }
warn() { echo "  [warn] $*"; }
fail() { echo "  [FAIL] $*"; FAILED=1; }
FAILED=0

echo "== system"
. /etc/os-release 2>/dev/null && pass "OS: ${PRETTY_NAME:-unknown}"
CPU="$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | xargs)"; pass "CPU: $CPU ($(nproc) threads)"
MEM_GB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
[ "$MEM_GB" -ge 8 ] && pass "RAM: ${MEM_GB} GiB" || warn "RAM: ${MEM_GB} GiB (8+ recommended)"

echo "== python"
if command -v python3 >/dev/null; then
  V=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)' && pass "python3 $V" || fail "python3 $V (need 3.11+)"
else fail "python3 missing"; fi

echo "== storage"
for d in "$DATA_DIR" "$MEDIA_DIR"; do
  if [ -d "$d" ]; then
    AVAIL=$(df -h --output=avail "$d" | tail -1 | xargs); DEV=$(df --output=source "$d" | tail -1)
    ROT=$(lsblk -no ROTA "$DEV" 2>/dev/null | head -1 | xargs)
    KIND=$([ "$ROT" = "0" ] && echo SSD || ([ "$ROT" = "1" ] && echo HDD || echo "?"))
    pass "$d on $DEV ($KIND), $AVAIL free"
  else fail "$d does not exist (run tob host bootstrap)"; fi
done
if command -v smartctl >/dev/null; then
  for disk in $(lsblk -dno NAME,TYPE | awk '$2=="disk"{print $1}'); do
    H=$(sudo -n smartctl -H "/dev/$disk" 2>/dev/null | grep -iE 'overall-health|SMART Health Status' | cut -d: -f2- | xargs)
    [ -z "$H" ] && warn "/dev/$disk SMART: needs sudo or unsupported (run: sudo smartctl -a /dev/$disk)" \
      || { [[ "$H" =~ PASSED|OK ]] && pass "/dev/$disk SMART: $H" || fail "/dev/$disk SMART: $H"; }
  done
else warn "smartmontools not installed"; fi

echo "== video encode (Quick Sync via VAAPI; Haswell needs the i965 driver)"
[ -e /dev/dri/renderD128 ] && pass "/dev/dri/renderD128 present" || fail "no render node - is the iGPU enabled in BIOS?"
id -nG basilisk 2>/dev/null | grep -qw render && pass "basilisk user in render group" || warn "basilisk user not in render group"
if command -v vainfo >/dev/null; then
  OUT=$(LIBVA_DRIVER_NAME=i965 vainfo 2>&1)
  echo "$OUT" | grep -q 'VAProfileH264.*VAEntrypointEncSlice' && pass "H.264 hardware encode available (i965)" \
    || fail "no H.264 encode entrypoint - install i965-va-driver"
else fail "vainfo missing (apt install vainfo)"; fi
command -v ffmpeg >/dev/null && { ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_vaapi && pass "ffmpeg has h264_vaapi" || fail "ffmpeg lacks h264_vaapi"; } || fail "ffmpeg missing"

echo "== thermals"
if command -v sensors >/dev/null; then
  T=$(sensors 2>/dev/null | grep -m1 'Package id 0' | grep -oE '\+[0-9]+' | head -1 | tr -d +)
  [ -n "$T" ] && { [ "$T" -lt 70 ] && pass "CPU package ${T}°C at idle" || warn "CPU package ${T}°C at idle - clean and repaste"; } || warn "no package temperature reported"
else warn "lm-sensors not installed"; fi

echo "== network"
ip route | grep -q '^default' && pass "default route present" || fail "no default route"
IFACE=$(ip route | awk '/^default/{print $5; exit}')
[[ "$IFACE" == e* ]] && pass "default route via wired interface $IFACE" || warn "default route via $IFACE - use wired Ethernet for streaming"
command -v ufw >/dev/null && sudo -n ufw status 2>/dev/null | head -1 | grep -q active && pass "ufw active" || warn "ufw status unknown (needs sudo) or inactive"

echo "== application"
[ -L "$APP_DIR/current" ] && pass "current release: $(basename "$(readlink -f "$APP_DIR/current")")" || warn "no release deployed yet (tob deploy)"
[ -f /etc/basilisk/secrets.env ] && pass "/etc/basilisk/secrets.env present" || warn "/etc/basilisk/secrets.env missing"

exit $FAILED

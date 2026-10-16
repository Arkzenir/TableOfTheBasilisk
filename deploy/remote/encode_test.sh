#!/usr/bin/env bash
# 20-second synthetic 1080p30 encodes (600 frames): Quick Sync via VAAPI and
# software x264. Anything comfortably above 30 fps means 1080p30 is viable
# with headroom for the renderer.
set -uo pipefail
FRAMES=600
SRC="testsrc2=size=1920x1080:rate=30"

report() {  # $1 label, rest: ffmpeg args
  local label="$1"; shift
  local out rtime
  out=$(ffmpeg -hide_banner -nostats -benchmark "$@" -f null - 2>&1)
  rtime=$(echo "$out" | grep -oE 'rtime=[0-9.]+' | tail -1 | cut -d= -f2)
  if [ -z "$rtime" ]; then
    echo "  $label: FAILED"; echo "$out" | tail -5 | sed 's/^/    /'; return 1
  fi
  awk -v f="$FRAMES" -v t="$rtime" -v l="$label" 'BEGIN { printf "  %-34s %6.1f fps (%.1fs for %d frames)\n", l, f/t, t, f }'
}

echo "== 1080p30 encode benchmark"
LIBVA_DRIVER_NAME=i965 report "h264_vaapi (Quick Sync, 6 Mbps)" \
  -vaapi_device /dev/dri/renderD128 -f lavfi -i "$SRC" -frames:v $FRAMES \
  -vf 'format=nv12,hwupload' -c:v h264_vaapi -b:v 6M
report "libx264 veryfast (CPU, 6 Mbps)" \
  -f lavfi -i "$SRC" -frames:v $FRAMES -c:v libx264 -preset veryfast -b:v 6M

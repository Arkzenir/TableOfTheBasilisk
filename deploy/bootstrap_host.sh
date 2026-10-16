#!/usr/bin/env bash
# One-time setup for the office PC (Debian 12+ / Ubuntu 22.04+, headless).
# Run via `tob host bootstrap <host>`, or directly:
#   sudo bash bootstrap_host.sh --deploy-user you --data /srv/basilisk/data \
#        --media /mnt/hdd/basilisk --lan 192.168.1.0/24
# Idempotent: safe to re-run.
set -euo pipefail

DEPLOY_USER="" APP=/opt/basilisk DATA=/srv/basilisk/data MEDIA=/srv/basilisk/media LAN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --deploy-user) DEPLOY_USER="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --data) DATA="$2"; shift 2 ;;
    --media) MEDIA="$2"; shift 2 ;;
    --lan) LAN="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
[ -n "$DEPLOY_USER" ] && id "$DEPLOY_USER" >/dev/null 2>&1 || { echo "--deploy-user must be an existing account" >&2; exit 1; }
command -v apt-get >/dev/null || { echo "this script supports Debian/Ubuntu only" >&2; exit 1; }
say() { echo -e "\n==> $*"; }

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip sqlite3 ffmpeg vainfo smartmontools \
  lm-sensors ufw unattended-upgrades ca-certificates curl rsync >/dev/null
# Haswell (i7-4770 / HD 4600) needs the legacy i965 VAAPI driver; iHD supports Broadwell+.
for pkg in i965-va-driver i965-va-driver-shaders intel-gpu-tools; do
  apt-get install -y -qq "$pkg" >/dev/null 2>&1 && echo "  installed $pkg" || echo "  (optional $pkg not available)"
done

say "service account and groups"
id basilisk >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin basilisk
for g in render video; do getent group "$g" >/dev/null && usermod -aG "$g" basilisk; done
usermod -aG basilisk "$DEPLOY_USER"

say "directories"
install -d -o "$DEPLOY_USER" -g basilisk -m 2775 "$APP" "$APP/releases"
install -d -o basilisk -g basilisk -m 2770 "$DATA" "$MEDIA"
install -d -o root -g basilisk -m 0750 /etc/basilisk
[ -f /etc/basilisk/secrets.env ] || {
  cat > /etc/basilisk/secrets.env << 'SECRETS'
# Provider API keys and other secrets. Never commit these; never put them in a release.
# Read by systemd units via EnvironmentFile. Owner root:basilisk, mode 0640.
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# GOOGLE_API_KEY=
# XAI_API_KEY=
# MISTRAL_API_KEY=
SECRETS
  chown root:basilisk /etc/basilisk/secrets.env; chmod 0640 /etc/basilisk/secrets.env; }
cat > /etc/basilisk/basilisk.env << ENVFILE
BASILISK_DATA=$DATA
BASILISK_MEDIA=$MEDIA
LIBVA_DRIVER_NAME=i965
ENVFILE
chmod 0644 /etc/basilisk/basilisk.env

say "systemd units"
write_unit() {
  cat > /etc/systemd/system/basilisk-soak.service << UNIT
[Unit]
Description=Table of The Basilisk - soak runner (scripted campaigns, stability testing)
After=network-online.target

[Service]
Type=simple
User=basilisk
Group=basilisk
WorkingDirectory=$APP/current
EnvironmentFile=/etc/basilisk/basilisk.env
EnvironmentFile=-/etc/basilisk/secrets.env
Environment=BASILISK_ROOT=$APP/current
ExecStart=$APP/current/.venv/bin/tob soak --hours 0 --data-dir $DATA
Nice=10
UMask=0007
Restart=no
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=$DATA
PrivateTmp=yes
ProtectHome=yes

[Install]
WantedBy=multi-user.target
UNIT
}
write_unit
systemctl daemon-reload
echo "  installed basilisk-soak.service (not enabled; start with: tob remote <host> soak-start)"

say "sudo rule for $DEPLOY_USER (service control only)"
SYSTEMCTL="$(command -v systemctl)"
SUDOERS=/etc/sudoers.d/basilisk-deploy
cat > "$SUDOERS.tmp" << RULE
$DEPLOY_USER ALL=(root) NOPASSWD: $SYSTEMCTL start basilisk-*, $SYSTEMCTL stop basilisk-*, \\
  $SYSTEMCTL restart basilisk-*, $SYSTEMCTL try-restart basilisk-*, $SYSTEMCTL status basilisk-*, \\
  /usr/sbin/smartctl -H *, /usr/sbin/ufw status
RULE
visudo -cf "$SUDOERS.tmp" >/dev/null && mv "$SUDOERS.tmp" "$SUDOERS" && chmod 0440 "$SUDOERS"

say "firewall (no inbound ports except SSH${LAN:+ from $LAN})"
ufw --force default deny incoming >/dev/null
ufw --force default allow outgoing >/dev/null
if [ -n "$LAN" ]; then ufw allow from "$LAN" to any port 22 proto tcp >/dev/null
else ufw allow 22/tcp >/dev/null; echo "  WARNING: no --lan given; SSH allowed from anywhere"; fi
ufw --force enable >/dev/null
ufw status | head -5

say "automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

say "done"
cat << NEXT
Next, from your desktop:
  tob deploy <host>              # first release
  tob remote <host> doctor       # hardware and driver checks
  tob remote <host> encode-test  # confirm 1080p30 encode headroom
  tob remote <host> soak-start   # long-run stability test
Log out and back in once so '$DEPLOY_USER' picks up the basilisk group.
NEXT

#!/usr/bin/env bash
# bootstrap.sh — Ubuntu 24.04 provisioning for the Windrose dedicated server host.
# Idempotent: safe to re-run.  Run as the target user with sudo privileges.
# ADR-001 (host platform), ADR-002 (Wine), ADR-003 (systemd), ADR-004 (networking)
set -euo pipefail

LOGFILE="/var/log/windrose-bootstrap.log"
exec > >(tee -a "$LOGFILE") 2>&1

echo "=== Windrose bootstrap $(date -Iseconds) ==="

# ---------------------------------------------------------------------------
# 1. Pre-flight checks (ADR-001)
# ---------------------------------------------------------------------------
echo "--- Pre-flight checks ---"

ARCH=$(uname -m)
if [[ "$ARCH" != "x86_64" ]]; then
  echo "FATAL: architecture is '$ARCH'; x86_64 required (ADR-001)." >&2
  exit 1
fi
echo "arch: $ARCH OK"

if ! grep -q avx2 /proc/cpuinfo; then
  echo "FATAL: CPU does not support AVX2 (required by Windrose — ADR-001)." >&2
  exit 1
fi
echo "AVX2: present OK"

RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ "$RAM_MB" -lt 7800 ]]; then
  echo "WARNING: RAM is ${RAM_MB} MB — Windrose needs >=8 GB for 2 players." >&2
else
  echo "RAM: ${RAM_MB} MB OK"
fi

IPV6_DISABLED=$(cat /sys/module/ipv6/parameters/disable 2>/dev/null || echo "0")
if [[ "$IPV6_DISABLED" == "1" ]]; then
  echo "FATAL: IPv6 is disabled. Windrose P2P proxy requires dual-stack (ADR-001)." >&2
  echo "Fix: remove 'ipv6.disable=1' from /etc/default/grub, run update-grub, reboot." >&2
  exit 1
fi
echo "IPv6: enabled OK"

UBUNTU_VER=$(lsb_release -rs 2>/dev/null || echo "0")
if [[ "$UBUNTU_VER" != "24.04" ]]; then
  echo "WARNING: Ubuntu ${UBUNTU_VER} detected; scripts are tested against 24.04." >&2
fi

# ---------------------------------------------------------------------------
# 2. APT setup (multiverse for steamcmd, i386 for Wine32)
# ---------------------------------------------------------------------------
echo "--- Configuring APT ---"

sudo dpkg --add-architecture i386
sudo add-apt-repository -y multiverse
sudo apt-get update -q

# ---------------------------------------------------------------------------
# 3. Package installation (ADR-002: Ubuntu 24.04 Wine package set)
# ---------------------------------------------------------------------------
echo "--- Installing packages ---"

# Confirm steamcmd EULA non-interactively
echo steamcmd steam/question select "I AGREE" | sudo debconf-set-selections
echo steamcmd steam/license note '' | sudo debconf-set-selections

PACKAGES=(
  # Wine — Ubuntu 24.04 package set; wine-installer is broken on 24.04 (ADR-002)
  wine wine32 wine64 libwine "libwine:i386" fonts-wine winbind
  # Headless X display (Wine needs a display even for a headless server binary)
  xvfb
  # SteamCMD
  steamcmd lib32gcc-s1
  # Python 3.12 (Ubuntu 24.04 default; required by the Telegram bot — ADR-006)
  python3 python3-pip python3-venv
  # Firewall and intrusion prevention
  ufw fail2ban
  # Automatic security patches (ADR-005)
  unattended-upgrades
  # UPnP probing (ADR-004)
  miniupnpc
  # Utilities
  curl wget jq zstd logrotate lm-sensors
)

sudo apt-get install -y --no-install-recommends "${PACKAGES[@]}"

echo "--- Packages installed ---"

# ---------------------------------------------------------------------------
# 4. Laptop power management — 24/7 unattended operation (ADR-001)
# ---------------------------------------------------------------------------
echo "--- Configuring power management ---"

sudo systemctl mask --now \
  sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || true

LOGIND="/etc/systemd/logind.conf"
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/'                        "$LOGIND"
sudo sed -i 's/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' "$LOGIND"
sudo sed -i 's/^#\?HandleLidSwitchDocked=.*/HandleLidSwitchDocked=ignore/'            "$LOGIND"
sudo systemctl restart systemd-logind

echo "Power management: lid-close ignored, sleep targets masked OK"

# ---------------------------------------------------------------------------
# 5. UFW firewall — SSH-only inbound (ADR-004: P2P mode by default)
# ---------------------------------------------------------------------------
echo "--- Configuring UFW ---"

sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh comment 'SSH admin access'
sudo ufw --force enable

echo "UFW: SSH-only inbound OK"

# ---------------------------------------------------------------------------
# 6. fail2ban
# ---------------------------------------------------------------------------
echo "--- Configuring fail2ban ---"
sudo systemctl enable --now fail2ban
echo "fail2ban: enabled OK"

# ---------------------------------------------------------------------------
# 7. unattended-upgrades — security patches; auto-reboot Sunday 04:00 (ADR-005)
# ---------------------------------------------------------------------------
echo "--- Configuring unattended-upgrades ---"

sudo tee /etc/apt/apt.conf.d/51windrose-reboot >/dev/null <<'APT_CONF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
Unattended-Upgrade::Automatic-Reboot-WithUsers "false";
APT_CONF

sudo systemctl enable --now unattended-upgrades
echo "unattended-upgrades: security-only, auto-reboot Sunday 04:00 OK"

# ---------------------------------------------------------------------------
# 8. logrotate for windrose logs (ADR-005)
# ---------------------------------------------------------------------------
echo "--- Configuring logrotate ---"

sudo tee /etc/logrotate.d/windrose >/dev/null <<'LOGROTATE_CONF'
/var/log/windrose-health.log
/var/log/windrose-backup.log
/var/log/windrose-cron.log
/var/log/windrose-bootstrap.log
{
    weekly
    rotate 8
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
}
LOGROTATE_CONF

echo "logrotate: windrose log rotation configured OK"

# ---------------------------------------------------------------------------
# 9. Directory scaffolding (ADR-003 filesystem layout)
# ---------------------------------------------------------------------------
echo "--- Creating directory scaffolding ---"

mkdir -p \
  "$HOME/windrose" \
  "$HOME/windrose/pfx" \
  "$HOME/log" \
  "$HOME/windrose-backups" \
  "$HOME/scripts" \
  "$HOME/windrose-telegram-bot"

touch "$HOME/log/windrose.log"
sudo touch \
  /var/log/windrose-health.log \
  /var/log/windrose-backup.log \
  /var/log/windrose-cron.log
sudo chmod 664 \
  /var/log/windrose-health.log \
  /var/log/windrose-backup.log \
  /var/log/windrose-cron.log

echo "Directories: created OK"

# ---------------------------------------------------------------------------
# 10. UPnP verification — informational, non-fatal (ADR-004)
# ---------------------------------------------------------------------------
echo "--- UPnP probe (informational) ---"
if upnpc -s 2>/dev/null | grep -q 'Found valid IGD'; then
  echo "UPnP: router IGD found OK"
else
  echo "INFO: No UPnP IGD found. Verify router UPnP settings per ADR-004."
fi

echo ""
echo "=== bootstrap.sh complete $(date -Iseconds) ==="
echo "Next step: run scripts/install_windrose.sh"

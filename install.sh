#!/usr/bin/env bash
# install.sh — One-command Windrose dedicated server installer for Ubuntu 24.04.
#
# Usage:
#   bash install.sh
#
# What it does:
#   1. Installs prerequisites (Wine, SteamCMD, Python, xvfb, UFW, etc.)
#   2. Downloads the Windrose server binary via SteamCMD (Wine/Windows binary on Linux)
#   3. Prompts for Telegram bot credentials and writes .env
#   4. Installs the Python bot dependencies
#   5. Registers Windrose and windrose-bot as systemd services
#   6. Sets up cron jobs for health checks, backups, and updates
#   7. Starts everything and reports status
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$REPO_DIR/scripts"
LOG_DIR="/var/log"
LOG_FILE="$LOG_DIR/windrose-bootstrap.log"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'

log()  { echo "$(date -Iseconds) $*" | tee -a "$LOG_FILE"; }
step() { echo -e "\n${CYAN}==> $*${NC}"; log "==> $*"; }
ok()   { echo -e "${GREEN}    $*${NC}"; }
warn() { echo -e "${YELLOW}    $*${NC}"; log "WARN: $*"; }
die()  { echo -e "${RED}FATAL: $*${NC}"; log "FATAL: $*"; exit 1; }

run_step() {
  local script="$1"
  log "    Running: $SCRIPTS_DIR/$script"
  bash "$SCRIPTS_DIR/$script" || die "$script failed (exit $?)"
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
clear
echo ""
echo -e "${CYAN}  ╔════════════════════════════════════════════╗"
echo    "  ║   Windrose Dedicated Server — Ubuntu       ║"
echo    "  ║   Self-host installer                      ║"
echo -e "  ╚════════════════════════════════════════════╝${NC}"
echo ""
echo "  This will install and start the Windrose dedicated server."
echo "  Estimated time: 10–20 minutes (SteamCMD download speed varies)."
echo ""
echo "  Log file: $LOG_FILE"
echo ""
read -r -p "  Press ENTER to begin, or Ctrl+C to cancel: "

# ---------------------------------------------------------------------------
# Step 1 — Prerequisites
# ---------------------------------------------------------------------------
step "Step 1/6 — Installing prerequisites (Wine, SteamCMD, Python, xvfb, UFW...)"
run_step bootstrap.sh

# ---------------------------------------------------------------------------
# Step 2 — Download Windrose
# ---------------------------------------------------------------------------
step "Step 2/6 — Downloading Windrose server binary via SteamCMD"
echo "  (This downloads several GB — grab a coffee)"
run_step install_windrose.sh

# ---------------------------------------------------------------------------
# Step 3 — Telegram bot credentials
# ---------------------------------------------------------------------------
step "Step 3/6 — Telegram bot configuration"

BOT_DIR="$HOME/windrose-telegram-bot"
BOT_ENV_DST="$BOT_DIR/.env"
BOT_ENV_EX="$REPO_DIR/bot/.env.example"

mkdir -p "$BOT_DIR"

if [[ ! -f "$BOT_ENV_DST" ]]; then
  cp "$BOT_ENV_EX" "$BOT_ENV_DST"
  log "Created $BOT_ENV_DST from template"
fi

echo ""
echo -e "${YELLOW}  To enable the Telegram bot, enter your credentials below."
echo "  Leave blank to skip (edit $BOT_ENV_DST later)."
echo -e "${NC}"

read -r -p "  BOT_TOKEN (from @BotFather): " BOT_TOKEN
read -r -p "  ADMIN_CHAT_ID (your Telegram user ID): " ADMIN_ID
read -r -p "  ALLOWED_CHAT_IDS (comma-separated, or same as above): " ALLOW_IDS

if [[ -n "$BOT_TOKEN" ]]; then
  ALLOW_IDS="${ALLOW_IDS:-$ADMIN_ID}"
  sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$BOT_TOKEN|"             "$BOT_ENV_DST"
  sed -i "s|^ADMIN_CHAT_ID=.*|ADMIN_CHAT_ID=$ADMIN_ID|"     "$BOT_ENV_DST"
  sed -i "s|^ALLOWED_CHAT_IDS=.*|ALLOWED_CHAT_IDS=$ALLOW_IDS|" "$BOT_ENV_DST"
  log "Telegram credentials written to .env"
else
  warn "Skipping Telegram credentials — edit $BOT_ENV_DST manually later"
fi

# ---------------------------------------------------------------------------
# Step 4 — Bot dependencies
# ---------------------------------------------------------------------------
step "Step 4/6 — Installing Telegram bot"
run_step install_bot.sh

# ---------------------------------------------------------------------------
# Step 5 — systemd services
# ---------------------------------------------------------------------------
step "Step 5/6 — Registering systemd services"
run_step install_service.sh

# ---------------------------------------------------------------------------
# Step 6 — Cron jobs
# ---------------------------------------------------------------------------
step "Step 6/6 — Setting up cron jobs (health check, backup, update)"

# Copy scripts to ~/scripts so cron paths stay stable
mkdir -p "$HOME/scripts"
for f in healthcheck.sh backup_world.sh update_windrose.sh; do
  cp "$SCRIPTS_DIR/$f" "$HOME/scripts/$f"
  chmod +x "$HOME/scripts/$f"
done

run_step install_cron.sh

# ---------------------------------------------------------------------------
# Start services
# ---------------------------------------------------------------------------
log "Starting services..."
sudo systemctl start windrose.service || warn "windrose.service failed to start — check logs"

if systemctl list-unit-files windrose-bot.service &>/dev/null; then
  sudo systemctl start windrose-bot.service || warn "windrose-bot.service failed to start — check logs"
fi

# ---------------------------------------------------------------------------
# Done — status report
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}  ╔════════════════════════════════════════════╗"
echo    "  ║          Installation complete!            ║"
echo -e "  ╚════════════════════════════════════════════╝${NC}"
echo ""

SVC_STATE=$(systemctl is-active windrose.service 2>/dev/null || echo 'unknown')
BOT_STATE=$(systemctl is-active windrose-bot.service 2>/dev/null || echo 'not installed')

echo "  windrose.service     : $SVC_STATE"
echo "  windrose-bot.service : $BOT_STATE"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status windrose"
echo "    journalctl -fu windrose"
echo "    journalctl -fu windrose-bot"
echo ""
log "=== install.sh complete ==="

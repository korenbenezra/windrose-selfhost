#!/usr/bin/env bash
# install_service.sh — Stamp and install systemd units and the sudoers drop-in.
# Run as the target user (with sudo) after install_windrose.sh.
# ADR-003 (systemd), ADR-007 (sudoers scoping)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

WINDROSE_USER="${WINDROSE_USER:-$USER}"
BOT_USER="${BOT_USER:-$USER}"

SYSTEMD_DIR="$REPO_DIR/systemd"
SYSTEM_UNIT_DIR="/etc/systemd/system"
SUDOERS_DIR="/etc/sudoers.d"

echo "=== install_service.sh $(date -Iseconds) ==="
echo "    WINDROSE_USER : $WINDROSE_USER"
echo "    BOT_USER      : $BOT_USER"

# ---------------------------------------------------------------------------
# Helper: stamp placeholders in a unit file and write to dest
# ---------------------------------------------------------------------------
stamp_unit() {
  local src="$1"
  local dst="$2"

  if [[ ! -f "$src" ]]; then
    echo "FATAL: source unit not found: $src" >&2
    exit 1
  fi

  sed \
    -e "s/WINDROSE_USER_PLACEHOLDER/$WINDROSE_USER/g" \
    -e "s/BOT_USER_PLACEHOLDER/$BOT_USER/g" \
    "$src"
}

# ---------------------------------------------------------------------------
# 1. Install windrose.service
# ---------------------------------------------------------------------------
echo "--- Installing windrose.service ---"
stamp_unit "$SYSTEMD_DIR/windrose.service" \
  | sudo tee "$SYSTEM_UNIT_DIR/windrose.service" >/dev/null
sudo chmod 644 "$SYSTEM_UNIT_DIR/windrose.service"
echo "Installed: $SYSTEM_UNIT_DIR/windrose.service OK"

# ---------------------------------------------------------------------------
# 2. Install windrose-bot.service (if present)
# ---------------------------------------------------------------------------
if [[ -f "$SYSTEMD_DIR/windrose-bot.service" ]]; then
  echo "--- Installing windrose-bot.service ---"
  stamp_unit "$SYSTEMD_DIR/windrose-bot.service" \
    | sudo tee "$SYSTEM_UNIT_DIR/windrose-bot.service" >/dev/null
  sudo chmod 644 "$SYSTEM_UNIT_DIR/windrose-bot.service"
  echo "Installed: $SYSTEM_UNIT_DIR/windrose-bot.service OK"
fi

# ---------------------------------------------------------------------------
# 3. Install and validate the sudoers drop-in (ADR-003, ADR-007)
#    visudo -c validates syntax before the file is activated.
# ---------------------------------------------------------------------------
echo "--- Installing sudoers drop-in ---"

SUDOERS_TMPFILE=$(mktemp /tmp/windrose-sudoers.XXXXXX)
trap 'rm -f "$SUDOERS_TMPFILE"' EXIT

stamp_unit "$SYSTEMD_DIR/sudoers-windrose-bot" > "$SUDOERS_TMPFILE"

# Validate before installing
if ! sudo visudo -c -f "$SUDOERS_TMPFILE"; then
  echo "FATAL: sudoers drop-in failed visudo -c syntax check." >&2
  echo "       Inspect $SUDOERS_TMPFILE before proceeding." >&2
  exit 1
fi

sudo cp "$SUDOERS_TMPFILE" "$SUDOERS_DIR/windrose-bot"
sudo chmod 0440 "$SUDOERS_DIR/windrose-bot"
sudo chown root:root "$SUDOERS_DIR/windrose-bot"
echo "Installed: $SUDOERS_DIR/windrose-bot (mode 0440) OK"

# ---------------------------------------------------------------------------
# 4. Reload systemd and enable units
# ---------------------------------------------------------------------------
echo "--- Reloading systemd ---"
sudo systemctl daemon-reload

sudo systemctl enable windrose.service
echo "windrose.service: enabled OK"

if [[ -f "$SYSTEM_UNIT_DIR/windrose-bot.service" ]]; then
  sudo systemctl enable windrose-bot.service
  echo "windrose-bot.service: enabled OK"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=== install_service.sh complete $(date -Iseconds) ==="
echo "Start the server:  sudo systemctl start windrose.service"
echo "Check status:      sudo systemctl status windrose.service"
echo "Live logs:         journalctl -fu windrose"

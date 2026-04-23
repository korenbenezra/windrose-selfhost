#!/usr/bin/env bash
# install_cron.sh — Install the Windrose cron schedule for the current user.
# Idempotent: safe to re-run; existing Windrose cron entries are replaced.
# ADR-005 (update strategy / cron schedule)
set -euo pipefail

echo "=== install_cron.sh $(date -Iseconds) ==="
echo "    User: $USER"

SCRIPTS_DIR="$HOME/scripts"

# ---------------------------------------------------------------------------
# Build the cron block
# Cron schedule per ADR-005:
#   02:30  nightly world backup (before the update run)
#   03:00  SteamCMD update pull
#   03:15  service restart (15 min after SteamCMD starts; binary is settled)
#   */10   healthcheck (detects crashes within 10 min)
# ---------------------------------------------------------------------------
CRON_BLOCK="$(cat << CRON
# --- Windrose automation (managed by install_cron.sh) ---
# Nightly world backup at 02:30 -- runs BEFORE the update (ADR-005)
30 2 * * * $SCRIPTS_DIR/backup_world.sh >> /var/log/windrose-backup.log 2>&1
# Nightly SteamCMD update pull at 03:00
00 3 * * * $SCRIPTS_DIR/update_windrose.sh >> /var/log/windrose-cron.log 2>&1
# Service restart at 03:15 -- 15 min after SteamCMD to avoid mid-download restart
15 3 * * * /usr/bin/sudo /bin/systemctl restart windrose.service >> /var/log/windrose-cron.log 2>&1
# Healthcheck every 10 minutes
*/10 * * * * $SCRIPTS_DIR/healthcheck.sh >> /var/log/windrose-health.log 2>&1
# --- End Windrose automation ---
CRON
)"

# ---------------------------------------------------------------------------
# Merge: strip any existing Windrose block, append the new one
# ---------------------------------------------------------------------------
EXISTING=$(crontab -l 2>/dev/null || true)

# Remove old Windrose block (between the sentinel comments) if present
STRIPPED=$(echo "$EXISTING" \
  | awk '/^# --- Windrose automation/{skip=1} !skip{print} /^# --- End Windrose automation/{skip=0}')

NEW_CRONTAB="${STRIPPED}
${CRON_BLOCK}
"

echo "$NEW_CRONTAB" | crontab -

echo "Crontab installed. Current crontab:"
echo "---"
crontab -l
echo "---"

# ---------------------------------------------------------------------------
# Verify the three log files are writable
# ---------------------------------------------------------------------------
for LOG in /var/log/windrose-backup.log /var/log/windrose-cron.log /var/log/windrose-health.log; do
  if [[ ! -w "$LOG" ]]; then
    echo "WARNING: $LOG is not writable by $USER — cron output will fail."
    echo "         Fix: sudo chmod 664 $LOG"
  fi
done

echo ""
echo "=== install_cron.sh complete $(date -Iseconds) ==="

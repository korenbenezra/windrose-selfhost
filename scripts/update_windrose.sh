#!/usr/bin/env bash
# update_windrose.sh — Backup-first SteamCMD update for Windrose.
# Cron schedule: 00 3 * * * (03:00 nightly) per ADR-005.
# ADR-002 (SteamCMD flags), ADR-005 (update strategy)
set -uo pipefail

APP_ID=4129620
INSTALL_DIR="$HOME/windrose"
BACKUP_DIR="$HOME/windrose-backups"
STEAMCMD_BIN=/usr/games/steamcmd
CRON_LOG="/var/log/windrose-cron.log"
ENV_FILE="$HOME/windrose-telegram-bot/.env"

ts() { date '+%Y-%m-%dT%H:%M:%S'; }
log() { echo "$(ts) [update] $*" | tee -a "$CRON_LOG"; }

# ---------------------------------------------------------------------------
# Telegram notification helper (reads BOT_TOKEN + ADMIN_CHAT_ID from .env)
# Non-fatal: if the .env is missing or the API call fails, we just log it.
# ---------------------------------------------------------------------------
tg_notify() {
  local msg="$1"
  if [[ ! -f "$ENV_FILE" ]]; then
    log "INFO: $ENV_FILE not found; skipping Telegram notification"
    return 0
  fi
  local token chat_id
  token=$(grep -E '^BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
  chat_id=$(grep -E '^ADMIN_CHAT_ID=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
  if [[ -z "$token" || -z "$chat_id" ]]; then
    log "INFO: BOT_TOKEN or ADMIN_CHAT_ID missing from .env; skipping notification"
    return 0
  fi
  curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    -d chat_id="$chat_id" \
    -d text="$msg" \
    -d parse_mode="HTML" >/dev/null 2>&1 || log "WARN: Telegram notification failed"
}

log "=== Windrose update started ==="

# ---------------------------------------------------------------------------
# 1. Pre-update backup (ADR-005: backup-first before every update)
# ---------------------------------------------------------------------------
mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%dT%H%M%S)
BACKUP_FILE="$BACKUP_DIR/saves-${TS}-pre-update.tar.zst"

log "Taking pre-update backup: $BACKUP_FILE"
if tar --zstd -cf "$BACKUP_FILE" -C "$INSTALL_DIR" R5/Saved 2>&1 | tee -a "$CRON_LOG"; then
  log "Pre-update backup OK: $BACKUP_FILE"
else
  log "ERROR: Pre-update backup failed — aborting update"
  tg_notify "&#x26A0; Windrose update ABORTED: backup failed at $(ts)"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Stop the service
# ---------------------------------------------------------------------------
log "Stopping windrose.service"
if ! sudo -n systemctl stop windrose.service 2>&1 | tee -a "$CRON_LOG"; then
  log "ERROR: Could not stop windrose.service"
  tg_notify "&#x26A0; Windrose update ABORTED: could not stop service at $(ts)"
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. Run SteamCMD — +@sSteamCmdForcePlatformType windows is REQUIRED (ADR-002)
# ---------------------------------------------------------------------------
log "Running SteamCMD app_update $APP_ID validate"
if "$STEAMCMD_BIN" \
     +@sSteamCmdForcePlatformType windows \
     +force_install_dir "$INSTALL_DIR" \
     +login anonymous \
     +app_update "$APP_ID" validate \
     +quit 2>&1 | tee -a "$CRON_LOG"; then
  log "SteamCMD completed OK"
else
  log "ERROR: SteamCMD failed; attempting to restart service anyway"
  tg_notify "&#x26A0; Windrose SteamCMD update FAILED at $(ts) — attempting recovery restart"
  sudo -n systemctl start windrose.service 2>&1 | tee -a "$CRON_LOG" || true
  exit 1
fi

# ---------------------------------------------------------------------------
# 4. Start the service
# ---------------------------------------------------------------------------
log "Starting windrose.service"
if ! sudo -n systemctl start windrose.service 2>&1 | tee -a "$CRON_LOG"; then
  log "ERROR: Could not start windrose.service after update"
  tg_notify "&#x274C; Windrose update: service failed to start after update at $(ts)"
  exit 1
fi

# ---------------------------------------------------------------------------
# 5. Wait up to 120s for active state (ADR-005)
# ---------------------------------------------------------------------------
log "Waiting up to 120s for windrose.service to become active"
for i in $(seq 1 60); do
  sleep 2
  if systemctl is-active --quiet windrose.service; then
    log "windrose.service active after $((i*2))s"
    tg_notify "&#x2705; Windrose updated and running (took $((i*2))s to start)"
    exit 0
  fi
done

log "ERROR: windrose.service did not reach active state within 120s"
tg_notify "&#x274C; Windrose update: service did not become active within 120s at $(ts)"
exit 1

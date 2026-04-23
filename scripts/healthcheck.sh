#!/usr/bin/env bash
# healthcheck.sh — Cron-driven health check for windrose.service.
# Cron schedule: */10 * * * * (every 10 minutes) per ADR-005.
# ADR-003 (systemd), ADR-005 (update strategy / healthcheck loop)
#
# Exit codes:
#   0 — service is healthy (active)
#   1 — service was dead; successfully restarted
#   2 — service was dead; restart attempt failed
#   3 — windrose.service unit not found
set -uo pipefail

HEALTH_LOG="/var/log/windrose-health.log"
STATE_FILE="/tmp/windrose-health-last-state"

ts() { date '+%Y-%m-%dT%H:%M:%S'; }
log() { echo "$(ts) [healthcheck] $*" | tee -a "$HEALTH_LOG"; }

# ---------------------------------------------------------------------------
# 1. Check whether the unit exists at all
# ---------------------------------------------------------------------------
if ! systemctl list-unit-files windrose.service &>/dev/null \
   || ! systemctl list-unit-files windrose.service | grep -q windrose.service; then
  log "ERROR: windrose.service unit not found — is install_service.sh complete?"
  echo "unit-missing" > "$STATE_FILE"
  exit 3
fi

# ---------------------------------------------------------------------------
# 2. Check active state
# ---------------------------------------------------------------------------
if systemctl is-active --quiet windrose.service; then
  log "OK: windrose.service is active"
  echo "healthy" > "$STATE_FILE"
  exit 0
fi

FAILED_STATE=$(systemctl is-active windrose.service 2>/dev/null || true)
log "WARN: windrose.service state=$FAILED_STATE — attempting restart"
echo "restarting" > "$STATE_FILE"

# ---------------------------------------------------------------------------
# 3. Attempt restart
# ---------------------------------------------------------------------------
if ! sudo -n systemctl restart windrose.service 2>&1 | tee -a "$HEALTH_LOG"; then
  log "ERROR: systemctl restart failed (sudo/sudoers issue?)"
  echo "restart-failed" > "$STATE_FILE"
  exit 2
fi

# ---------------------------------------------------------------------------
# 4. Wait up to 30 seconds for the service to reach active state
# ---------------------------------------------------------------------------
for i in $(seq 1 15); do
  sleep 2
  if systemctl is-active --quiet windrose.service; then
    log "RECOVERED: windrose.service is active after ${i}x2s wait"
    echo "recovered" > "$STATE_FILE"
    exit 1
  fi
done

log "ERROR: windrose.service did not become active within 30s after restart"
echo "restart-failed" > "$STATE_FILE"
exit 2

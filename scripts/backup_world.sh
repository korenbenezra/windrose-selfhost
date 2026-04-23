#!/usr/bin/env bash
# backup_world.sh — Nightly world-save snapshot with 7-day rolling retention.
# Cron schedule: 30 2 * * * (02:30 nightly) per ADR-005.
# ADR-005 (update strategy / backup safety)
set -uo pipefail

INSTALL_DIR="$HOME/windrose"
BACKUP_DIR="$HOME/windrose-backups"
BACKUP_LOG="/var/log/windrose-backup.log"
RETAIN_DAYS=7

ts() { date '+%Y-%m-%dT%H:%M:%S'; }
log() { echo "$(ts) [backup] $*" | tee -a "$BACKUP_LOG"; }

log "=== Windrose backup started ==="

mkdir -p "$BACKUP_DIR"

# ---------------------------------------------------------------------------
# 1. Create snapshot
# ---------------------------------------------------------------------------
TS=$(date +%Y%m%dT%H%M%S)
BACKUP_FILE="$BACKUP_DIR/saves-${TS}.tar.zst"

log "Snapshotting $INSTALL_DIR/R5/Saved -> $BACKUP_FILE"

if tar --zstd -cf "$BACKUP_FILE" -C "$INSTALL_DIR" R5/Saved 2>&1 | tee -a "$BACKUP_LOG"; then
  SIZE=$(du -sh "$BACKUP_FILE" 2>/dev/null | cut -f1 || echo "?")
  log "Backup OK: $BACKUP_FILE ($SIZE)"
else
  log "ERROR: tar failed; backup may be incomplete"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. 7-day rolling retention — delete backups older than RETAIN_DAYS
#    Only touches files matching the saves-*.tar.zst pattern (not pre-update backups).
# ---------------------------------------------------------------------------
log "Pruning backups older than $RETAIN_DAYS days"

find "$BACKUP_DIR" \
  -maxdepth 1 \
  -name 'saves-[0-9]*T[0-9]*.tar.zst' \
  -not -name '*-pre-update*' \
  -mtime "+${RETAIN_DAYS}" \
  -print \
  -delete 2>&1 | tee -a "$BACKUP_LOG"

REMAINING=$(find "$BACKUP_DIR" -maxdepth 1 -name 'saves-*.tar.zst' | wc -l)
log "Retention complete. Backup files on disk: $REMAINING"

log "=== Windrose backup finished ==="

#!/usr/bin/env bash
# start_windrose.sh — Launch script invoked by the windrose.service systemd unit.
# ADR-002 (Wine + xvfb-run), ADR-003 (systemd)
set -euo pipefail

INSTALL_DIR="$HOME/windrose"
SERVER_EXE="$INSTALL_DIR/R5/Binaries/Win64/WindroseServer-Win64-Shipping.exe"
LOG_FILE="$HOME/log/windrose.log"
LOG_MAX_BYTES=$((100 * 1024 * 1024))   # 100 MB

# ---------------------------------------------------------------------------
# Log rotation — if windrose.log exceeds 100 MB, rotate to .old (ADR-003)
# ---------------------------------------------------------------------------
if [[ -f "$LOG_FILE" ]]; then
  LOG_SIZE=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
  if [[ "$LOG_SIZE" -gt "$LOG_MAX_BYTES" ]]; then
    mv "$LOG_FILE" "${LOG_FILE}.old"
    touch "$LOG_FILE"
    echo "$(date -Iseconds) [start_windrose] Rotated windrose.log (was ${LOG_SIZE} bytes)" \
      >> "$LOG_FILE"
  fi
fi

# ---------------------------------------------------------------------------
# Environment (ADR-002)
# ---------------------------------------------------------------------------
export WINEPREFIX="$INSTALL_DIR/pfx"
export WINEDEBUG=-all
export DISPLAY=:99

# ---------------------------------------------------------------------------
# Launch via xvfb-run (ADR-002: Wine requires a display even headless)
# exec replaces this shell process so systemd tracks the correct PID
# ---------------------------------------------------------------------------
exec xvfb-run \
  --auto-servernum \
  --server-args="-screen 0 1024x768x24" \
  wine "$SERVER_EXE" -log

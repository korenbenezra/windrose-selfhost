#!/usr/bin/env bash
# install_windrose.sh — Download Windrose via SteamCMD and initialise the Wine prefix.
# Run once as the windrose server user after bootstrap.sh completes.
# ADR-002 (Wine), ADR-003 (systemd)
set -euo pipefail

APP_ID=4129620
INSTALL_DIR="$HOME/windrose"
WINEPREFIX="$HOME/windrose/pfx"
STEAMCMD_BIN=/usr/games/steamcmd
SERVER_EXE="$INSTALL_DIR/R5/Binaries/Win64/WindroseServer-Win64-Shipping.exe"

echo "=== install_windrose.sh $(date -Iseconds) ==="

# ---------------------------------------------------------------------------
# 1. Verify SteamCMD is installed
# ---------------------------------------------------------------------------
if [[ ! -x "$STEAMCMD_BIN" ]]; then
  echo "FATAL: SteamCMD not found at $STEAMCMD_BIN. Run bootstrap.sh first." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Download the Windows server binary (ADR-002)
#    +@sSteamCmdForcePlatformType windows is REQUIRED on Linux; without it
#    SteamCMD sees a Linux host and fails to find the app (no Linux binary exists).
# ---------------------------------------------------------------------------
echo "--- Running SteamCMD to download Windrose (App ID $APP_ID) ---"
echo "    Install directory: $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"

"$STEAMCMD_BIN" \
  +@sSteamCmdForcePlatformType windows \
  +force_install_dir "$INSTALL_DIR" \
  +login anonymous \
  +app_update "$APP_ID" validate \
  +quit

echo "--- SteamCMD completed ---"

# ---------------------------------------------------------------------------
# 3. Verify the server binary was downloaded
# ---------------------------------------------------------------------------
if [[ ! -f "$SERVER_EXE" ]]; then
  echo "FATAL: Expected binary not found: $SERVER_EXE" >&2
  echo "       Check SteamCMD output above for errors." >&2
  exit 1
fi
echo "Binary verified: $SERVER_EXE OK"

# ---------------------------------------------------------------------------
# 4. Initialise the WINEPREFIX (ADR-002)
#    First Wine run always takes ~30s to set up the prefix; subsequent runs are fast.
# ---------------------------------------------------------------------------
echo "--- Initialising WINEPREFIX at $WINEPREFIX ---"

export WINEPREFIX="$WINEPREFIX"
export WINEDEBUG=-all
export DISPLAY=:99

# Start a throwaway Xvfb to provide the X display Wine needs during init
Xvfb :99 -screen 0 1024x768x24 &
XVFB_PID=$!
sleep 2

wine wineboot --init 2>/dev/null || true

kill "$XVFB_PID" 2>/dev/null || true
wait "$XVFB_PID" 2>/dev/null || true

echo "WINEPREFIX initialised OK"

# ---------------------------------------------------------------------------
# 5. Copy the start script into place (if present in project scripts/)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/start_windrose.sh" ]]; then
  cp "$SCRIPT_DIR/start_windrose.sh" "$INSTALL_DIR/start_windrose.sh"
  chmod +x "$INSTALL_DIR/start_windrose.sh"
  echo "start_windrose.sh copied to $INSTALL_DIR/ OK"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=== install_windrose.sh complete $(date -Iseconds) ==="
echo "Next steps:"
echo "  1. Run scripts/install_service.sh to install the systemd unit."
echo "  2. Edit ~/windrose/R5/ServerDescription.json once the server first starts"
echo "     (see ADR-004 for P2P config fields)."

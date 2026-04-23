# install_windrose.ps1 — Download Windrose via SteamCMD (native Windows).
# Run once as Administrator after bootstrap.ps1 completes.
#
# Mirrors: install_windrose.sh (Linux/Wine path)
# Key difference: no +@sSteamCmdForcePlatformType flag needed — SteamCMD on
# Windows already targets the Windows binary natively.
#Requires -RunAsAdministrator
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$APP_ID       = 4129620
$INSTALL_DIR  = "$env:USERPROFILE\windrose"
$STEAMCMD_EXE = "$env:USERPROFILE\steamcmd\steamcmd.exe"
$SERVER_EXE   = "$INSTALL_DIR\R5\Binaries\Win64\WindroseServer-Win64-Shipping.exe"
$LOG_DIR      = "$env:USERPROFILE\log"
$LOG_FILE     = "$LOG_DIR\windrose-install.log"

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [install_windrose] $Msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

Write-Log "=== install_windrose.ps1 started ==="

# ---------------------------------------------------------------------------
# 1. Verify SteamCMD is present
# ---------------------------------------------------------------------------
if (-not (Test-Path $STEAMCMD_EXE)) {
    Write-Log "FATAL: SteamCMD not found at $STEAMCMD_EXE. Run bootstrap.ps1 first."
    exit 1
}
Write-Log "SteamCMD: $STEAMCMD_EXE OK"

# ---------------------------------------------------------------------------
# 2. Download Windrose server binary via SteamCMD
#    On Windows, no platform override flag is needed — SteamCMD targets Windows natively.
# ---------------------------------------------------------------------------
Write-Log "--- Running SteamCMD to download Windrose (App ID $APP_ID) ---"
Write-Log "    Install directory: $INSTALL_DIR"

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null

& $STEAMCMD_EXE `
    +force_install_dir $INSTALL_DIR `
    +login anonymous `
    +app_update $APP_ID validate `
    +quit

if ($LASTEXITCODE -ne 0) {
    Write-Log "FATAL: SteamCMD exited with code $LASTEXITCODE."
    exit 1
}

Write-Log "--- SteamCMD completed ---"

# ---------------------------------------------------------------------------
# 3. Verify the server binary was downloaded
# ---------------------------------------------------------------------------
if (-not (Test-Path $SERVER_EXE)) {
    Write-Log "FATAL: Expected binary not found: $SERVER_EXE"
    Write-Log "       Check SteamCMD output above for errors."
    exit 1
}
Write-Log "Binary verified: $SERVER_EXE OK"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Log ""
Write-Log "=== install_windrose.ps1 complete ==="
Write-Log "Next step: run scripts\install_service.ps1"

# start_windrose.ps1  -  Launch script invoked by the windrose Windows Service (via NSSM).
# On Windows the .exe runs directly  -  no Wine, no Xvfb needed.
#
# Mirrors: start_windrose.sh (Linux/Wine path)
param(
    [string]$HomeDir = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# -HomeDir is passed by NSSM via install_service.ps1 and holds the installer's actual
# home directory (e.g. C:\Users\koren). Fallback to USERPROFILE for manual runs.
$OWNER_HOME  = if ($HomeDir) { $HomeDir } elseif ($env:WINDROSE_HOME) { $env:WINDROSE_HOME } else { $env:USERPROFILE }

$INSTALL_DIR = "$OWNER_HOME\windrose"
$SERVER_EXE  = "$INSTALL_DIR\R5\Binaries\Win64\WindroseServer-Win64-Shipping.exe"
$LOG_DIR     = "$OWNER_HOME\log"
$LOG_FILE    = "$LOG_DIR\windrose.log"
$LOG_MAX_MB  = 100

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

# ---------------------------------------------------------------------------
# Log rotation  -  if windrose.log exceeds 100 MB, rotate to .old
# ---------------------------------------------------------------------------
if (Test-Path $LOG_FILE) {
    $size = (Get-Item $LOG_FILE).Length / 1MB
    if ($size -gt $LOG_MAX_MB) {
        $old = "$LOG_FILE.old"
        Move-Item $LOG_FILE $old -Force
        New-Item -ItemType File -Path $LOG_FILE | Out-Null
        Add-Content -Path $LOG_FILE -Encoding UTF8 `
            -Value "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [start_windrose] Rotated windrose.log (was $([Math]::Round($size)) MB)"
    }
}

# ---------------------------------------------------------------------------
# Verify binary exists before launching
# ---------------------------------------------------------------------------
if (-not (Test-Path $SERVER_EXE)) {
    $msg = "FATAL: Server binary not found: $SERVER_EXE. Run install_windrose.ps1 first."
    Add-Content -Path $LOG_FILE -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [start_windrose] $msg"
    Write-Error $msg
    exit 1
}

# ---------------------------------------------------------------------------
# Launch  -  stdout/stderr are captured by NSSM's own log rotation.
# The process runs in the foreground so NSSM tracks the correct PID.
# ---------------------------------------------------------------------------
$LASTEXITCODE = 0
& $SERVER_EXE -log
exit $LASTEXITCODE

# install_service.ps1 — Register Windrose as a Windows Service via NSSM.
# Run as Administrator after install_windrose.ps1 completes.
# NSSM provides: auto-restart on crash, stdout/stderr log capture, startup type.
#
# Mirrors: install_service.sh + systemd units (Linux/Wine path)
#Requires -RunAsAdministrator
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$NSSM_EXE    = "$env:ProgramFiles\nssm\nssm.exe"
$SCRIPTS_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$REPO_DIR    = Split-Path -Parent $SCRIPTS_DIR
$LOG_DIR     = "$env:USERPROFILE\log"
$LOG_FILE    = "$LOG_DIR\windrose-install.log"

$SVC_NAME      = 'Windrose'
$SVC_EXE       = 'powershell.exe'
$SVC_ARGS      = "-NonInteractive -ExecutionPolicy Bypass -File `"$SCRIPTS_DIR\start_windrose.ps1`""
$SVC_STDOUT    = "$LOG_DIR\windrose.log"
$SVC_STDERR    = "$LOG_DIR\windrose-error.log"

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [install_service] $Msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

Write-Log "=== install_service.ps1 started ==="

# ---------------------------------------------------------------------------
# 1. Verify NSSM is present
# ---------------------------------------------------------------------------
if (-not (Test-Path $NSSM_EXE)) {
    Write-Log "FATAL: NSSM not found at $NSSM_EXE. Run bootstrap.ps1 first."
    exit 1
}
Write-Log "NSSM: $NSSM_EXE OK"

# ---------------------------------------------------------------------------
# 2. Remove existing service if present (idempotent re-run)
# ---------------------------------------------------------------------------
$existing = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
if ($existing) {
    Write-Log "Removing existing '$SVC_NAME' service..."
    if ($existing.Status -eq 'Running') {
        & $NSSM_EXE stop $SVC_NAME
        Start-Sleep -Seconds 3
    }
    & $NSSM_EXE remove $SVC_NAME confirm
    Write-Log "Existing service removed"
}

# ---------------------------------------------------------------------------
# 3. Install the Windrose service
# ---------------------------------------------------------------------------
Write-Log "--- Installing Windows Service: $SVC_NAME ---"

& $NSSM_EXE install $SVC_NAME $SVC_EXE $SVC_ARGS
& $NSSM_EXE set $SVC_NAME DisplayName  'Windrose Dedicated Server'
& $NSSM_EXE set $SVC_NAME Description  'Windrose game server managed by windrose-selfhost'
& $NSSM_EXE set $SVC_NAME Start        SERVICE_AUTO_START
& $NSSM_EXE set $SVC_NAME AppStdout    $SVC_STDOUT
& $NSSM_EXE set $SVC_NAME AppStderr    $SVC_STDERR
& $NSSM_EXE set $SVC_NAME AppRotateFiles        1
& $NSSM_EXE set $SVC_NAME AppRotateBytes        104857600  # 100 MB
& $NSSM_EXE set $SVC_NAME AppRestartDelay       5000       # 5s before restart on crash
& $NSSM_EXE set $SVC_NAME AppThrottle           30000      # 30s throttle to prevent restart storms

Write-Log "Service '$SVC_NAME' registered OK"

# ---------------------------------------------------------------------------
# 4. Install the Telegram bot service (if install_bot.ps1 has already been run)
# ---------------------------------------------------------------------------
$BOT_SCRIPT = "$env:USERPROFILE\windrose-telegram-bot\bot.py"
$BOT_VENV   = "$env:USERPROFILE\windrose-telegram-bot\venv\Scripts\python.exe"
$BOT_SVC    = 'WindroseBot'
$BOT_LOG    = "$LOG_DIR\windrose-bot.log"

if (Test-Path $BOT_VENV) {
    Write-Log "--- Installing Windows Service: $BOT_SVC ---"

    $existingBot = Get-Service -Name $BOT_SVC -ErrorAction SilentlyContinue
    if ($existingBot) {
        if ($existingBot.Status -eq 'Running') { & $NSSM_EXE stop $BOT_SVC }
        & $NSSM_EXE remove $BOT_SVC confirm
    }

    & $NSSM_EXE install $BOT_SVC $BOT_VENV $BOT_SCRIPT
    & $NSSM_EXE set $BOT_SVC DisplayName  'Windrose Telegram Bot'
    & $NSSM_EXE set $BOT_SVC Description  'Windrose Telegram bot managed by windrose-selfhost'
    & $NSSM_EXE set $BOT_SVC Start        SERVICE_AUTO_START
    & $NSSM_EXE set $BOT_SVC AppDirectory "$env:USERPROFILE\windrose-telegram-bot"
    & $NSSM_EXE set $BOT_SVC AppStdout    $BOT_LOG
    & $NSSM_EXE set $BOT_SVC AppStderr    $BOT_LOG
    & $NSSM_EXE set $BOT_SVC AppRotateFiles  1
    & $NSSM_EXE set $BOT_SVC AppRotateBytes  10485760  # 10 MB
    & $NSSM_EXE set $BOT_SVC AppRestartDelay 10000

    Write-Log "Service '$BOT_SVC' registered OK"
} else {
    Write-Log "INFO: Bot venv not found — skipping WindroseBot service (run install_bot.ps1 later)"
}

# ---------------------------------------------------------------------------
# 5. Start the Windrose service
# ---------------------------------------------------------------------------
Write-Log "--- Starting $SVC_NAME service ---"
Start-Service -Name $SVC_NAME
Start-Sleep -Seconds 5

$status = (Get-Service -Name $SVC_NAME).Status
Write-Log "Service status: $status"

if ($status -ne 'Running') {
    Write-Log "WARNING: Service did not reach Running state — check $SVC_STDOUT"
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Log ""
Write-Log "=== install_service.ps1 complete ==="
Write-Log "Check status:  Get-Service Windrose"
Write-Log "Live logs:     Get-Content $SVC_STDOUT -Wait"

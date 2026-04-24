# start_bot.ps1 - Start the Windrose Telegram bot (Windows Service or direct).
# Mirrors: start_bot.sh (Linux path)
param(
    # Optional owner home override when running as Administrator.
    [string]$HomeDir = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$OWNER_HOME   = if ($HomeDir) { $HomeDir } elseif ($env:WINDROSE_HOME) { $env:WINDROSE_HOME } else { $env:USERPROFILE }
$BOT_DIR      = "$OWNER_HOME\windrose-telegram-bot"
$BOT_ENV      = "$BOT_DIR\.env"
$BOT_SCRIPT   = "$BOT_DIR\bot.py"
$PYTHON_EXE   = "$BOT_DIR\venv\Scripts\python.exe"
$PID_FILE     = "$BOT_DIR\bot.pid"
$LOG_DIR      = "$OWNER_HOME\log"
$LOG_FILE     = "$LOG_DIR\windrose-bot.log"
$ERR_FILE     = "$LOG_DIR\windrose-bot-error.log"
$BOT_SERVICE  = 'WindroseBot'

Write-Host "=== start_bot.ps1 $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') ==="

# ---------------------------------------------------------------------------
# 1. Pre-flight checks
# ---------------------------------------------------------------------------
if (-not (Test-Path $BOT_DIR)) {
    Write-Error "ERROR: $BOT_DIR does not exist - run install_bot.ps1 first"
    exit 1
}

if (-not (Test-Path $BOT_ENV)) {
    Write-Error "ERROR: $BOT_ENV not found - run install_bot.ps1 and set credentials"
    exit 1
}

if (-not (Test-Path $PYTHON_EXE)) {
    Write-Error "ERROR: virtualenv missing at $PYTHON_EXE - run install_bot.ps1 first"
    exit 1
}

if (-not (Test-Path $BOT_SCRIPT)) {
    Write-Error "ERROR: bot script not found at $BOT_SCRIPT - run install_bot.ps1 first"
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Prefer Windows Service if available
# ---------------------------------------------------------------------------
$svc = Get-Service -Name $BOT_SERVICE -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -eq 'Running') {
        Write-Host "Bot is already running via service '$BOT_SERVICE'."
        Write-Host "Logs: $LOG_FILE"
        exit 0
    }

    try {
        Write-Host "--- Using Windows Service ---"
        Start-Service -Name $BOT_SERVICE -ErrorAction Stop
        Start-Sleep -Seconds 2
        $status = (Get-Service -Name $BOT_SERVICE).Status
        Write-Host "Service status: $status"
        if ($status -eq 'Running') {
            Write-Host ""
            Write-Host "Bot started via service. Follow logs with:"
            Write-Host "  Get-Content $LOG_FILE -Wait"
            exit 0
        }
    } catch {
        Write-Warning "Could not start service '$BOT_SERVICE': $_"
        Write-Host "Falling back to direct process start..."
    }
}

# ---------------------------------------------------------------------------
# 3. Fall back: direct background process
# ---------------------------------------------------------------------------
if (Test-Path $PID_FILE) {
    $pidText = (Get-Content $PID_FILE -Raw).Trim()
    if ($pidText -match '^\d+$') {
        $existingPid = [int]$pidText
        $existingProc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProc) {
            Write-Host "Bot is already running (PID $existingPid)"
            exit 0
        }
    }
    Write-Host "Stale PID file found - removing"
    Remove-Item -Path $PID_FILE -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

Write-Host "--- Starting bot directly ---"
$proc = Start-Process `
    -FilePath $PYTHON_EXE `
    -ArgumentList @($BOT_SCRIPT) `
    -WorkingDirectory $BOT_DIR `
    -RedirectStandardOutput $LOG_FILE `
    -RedirectStandardError $ERR_FILE `
    -PassThru

Set-Content -Path $PID_FILE -Value $proc.Id -Encoding ascii
Write-Host "Bot started (PID $($proc.Id))"
Write-Host "Logs: $LOG_FILE"
Write-Host "Errors: $ERR_FILE"
Write-Host "Stop with: $PSScriptRoot\stop_bot.ps1"

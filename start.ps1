# start.ps1 - Start the Windrose game server service and the Telegram bot.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$REPO_DIR    = Split-Path -Parent $MyInvocation.MyCommand.Path
$BOT_MAIN    = "$REPO_DIR\windrose_bot\main.py"
$ENV_FILE    = "$REPO_DIR\.env"
$ENV_EXAMPLE = "$REPO_DIR\.env.example"
$PID_FILE    = "$REPO_DIR\windrose_bot.pid"
$LOG_DIR     = "$REPO_DIR\logs"
$LOG_FILE    = "$LOG_DIR\windrose-bot.log"
$ERR_FILE    = "$LOG_DIR\windrose-bot-error.log"
$VENV_PYTHON = "$REPO_DIR\.venv\Scripts\python.exe"
$SVC_NAME    = "Windrose"

function Get-WindroseBotProcesses {
    try {
        return @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            ($_.Name -match '^python(\.exe|w\.exe)?$') -and
            $_.CommandLine -and (
                $_.CommandLine -match 'windrose_bot\.main' -or
                $_.CommandLine -match 'windrose_bot[\\/]+main\.py'
            )
        })
    } catch {
        return @()
    }
}

Write-Host "=== start.ps1 $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') ==="

$legacySvc = Get-Service -Name WindroseBot -ErrorAction SilentlyContinue
if ($legacySvc -and $legacySvc.Status -eq 'Running') {
    Write-Host "ERROR: Legacy Windows service 'WindroseBot' is running and conflicts with start.ps1." -ForegroundColor Red
    Write-Host "Run as Administrator:" -ForegroundColor Yellow
    Write-Host "  Stop-Service WindroseBot -Force"
    Write-Host "  Set-Service WindroseBot -StartupType Disabled"
    exit 1
}

# --- 1. Start the Windrose game server service ---
$svc = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "WARNING: Windows service '$SVC_NAME' not found — skipping game server start." -ForegroundColor Yellow
} elseif ($svc.Status -eq 'Running') {
    Write-Host "Game server is already running."
} else {
    Write-Host "Starting Windrose game server service..."
    Start-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        $svc.Refresh()
        if ($svc.Status -eq 'Running') { break }
        Start-Sleep -Milliseconds 500
    }
    $svc.Refresh()
    if ($svc.Status -eq 'Running') {
        Write-Host "Game server started."
    } else {
        Write-Host "WARNING: Game server did not reach Running state (status: $($svc.Status))." -ForegroundColor Yellow
    }
}

# --- 2. Start the Telegram bot ---
if (-not (Test-Path $BOT_MAIN)) {
    Write-Error "ERROR: Missing $BOT_MAIN"
    exit 1
}

if (-not (Test-Path $ENV_FILE)) {
    if (Test-Path $ENV_EXAMPLE) {
        Copy-Item -Path $ENV_EXAMPLE -Destination $ENV_FILE -Force
        Write-Host "Created $ENV_FILE from $ENV_EXAMPLE"
        Write-Host "Edit BOT_TOKEN (and IDs if needed), then run .\start.ps1 again."
        exit 1
    }
    Write-Error "ERROR: Missing $ENV_FILE and $ENV_EXAMPLE"
    exit 1
}

$pythonExe = if (Test-Path $VENV_PYTHON) {
    $VENV_PYTHON
} else {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Error "ERROR: Python not found. Install Python or create .venv."
        exit 1
    }
    $py.Source
}

if (Test-Path $PID_FILE) {
    $pidText = (Get-Content $PID_FILE -Raw).Trim()
    if ($pidText -match '^\d+$') {
        $existingPid = [int]$pidText
        if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
            Write-Host "Bot is already running (PID $existingPid)"
            exit 0
        }
    }
    Write-Host "Stale PID file found - removing"
    Remove-Item -Path $PID_FILE -Force -ErrorAction SilentlyContinue
}

$existingBotProcs = Get-WindroseBotProcesses
if (@($existingBotProcs).Count -gt 0) {
    $existingPid = [int](@($existingBotProcs)[0].ProcessId)
    Set-Content -Path $PID_FILE -Value $existingPid -Encoding ascii
    Write-Host "Bot is already running (PID $existingPid)"
    exit 0
}

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

Write-Host "--- Starting windrose_bot.main ---"
$proc = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList @('-m', 'windrose_bot.main') `
    -WorkingDirectory $REPO_DIR `
    -RedirectStandardOutput $LOG_FILE `
    -RedirectStandardError $ERR_FILE `
    -PassThru

Set-Content -Path $PID_FILE -Value $proc.Id -Encoding ascii
Start-Sleep -Seconds 2
$alive = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
if (-not $alive) {
    Remove-Item -Path $PID_FILE -Force -ErrorAction SilentlyContinue
    Write-Host "ERROR: Bot process exited immediately. Check logs:" -ForegroundColor Red
    Write-Host "  $LOG_FILE"
    Write-Host "  $ERR_FILE"
    if (Test-Path $ERR_FILE) {
        Write-Host ""
        Write-Host "Last error log lines:" -ForegroundColor Yellow
        Get-Content -Path $ERR_FILE -Tail 30 | ForEach-Object { Write-Host "  $_" }
    }
    exit 1
}

Write-Host "Bot started (PID $($proc.Id))"
Write-Host "Logs: $LOG_FILE"
Write-Host "Errors: $ERR_FILE"

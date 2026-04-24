# stop_bot.ps1 - Stop the Windrose Telegram bot (Windows Service or direct).
# Mirrors: stop_bot.sh (Linux path)
param(
    # Optional owner home override when running as Administrator.
    [string]$HomeDir = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$OWNER_HOME   = if ($HomeDir) { $HomeDir } elseif ($env:WINDROSE_HOME) { $env:WINDROSE_HOME } else { $env:USERPROFILE }
$BOT_DIR      = "$OWNER_HOME\windrose-telegram-bot"
$PID_FILE     = "$BOT_DIR\bot.pid"
$BOT_SERVICE  = 'WindroseBot'

Write-Host "=== stop_bot.ps1 $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') ==="

# ---------------------------------------------------------------------------
# 1. Prefer Windows Service if available
# ---------------------------------------------------------------------------
$svc = Get-Service -Name $BOT_SERVICE -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -eq 'Running') {
        try {
            Write-Host "--- Stopping Windows Service ---"
            Stop-Service -Name $BOT_SERVICE -ErrorAction Stop
            Start-Sleep -Seconds 2
            $status = (Get-Service -Name $BOT_SERVICE).Status
            Write-Host "Service status: $status"
        } catch {
            Write-Warning "Could not stop service '$BOT_SERVICE': $_"
            Write-Host "Attempting direct process stop fallback..."
        }
    } else {
        Write-Host "Service '$BOT_SERVICE' is already stopped."
    }

    if (Test-Path $PID_FILE) {
        Remove-Item -Path $PID_FILE -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# 2. Fall back: direct background process
# ---------------------------------------------------------------------------
if (Test-Path $PID_FILE) {
    $pidText = (Get-Content $PID_FILE -Raw).Trim()
    if ($pidText -match '^\d+$') {
        $pidValue = [int]$pidText
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping bot process (PID $pidValue)..."
            Stop-Process -Id $pidValue -Force -ErrorAction Stop
            Remove-Item -Path $PID_FILE -Force -ErrorAction SilentlyContinue
            Write-Host "Bot stopped."
            exit 0
        }
    }
    Write-Host "Stale PID file found - removing"
    Remove-Item -Path $PID_FILE -Force -ErrorAction SilentlyContinue
}

$directBot = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Name -match '^python(\.exe|w\.exe)?$') -and
        $_.CommandLine -and
        $_.CommandLine -like "*windrose-telegram-bot*bot.py*"
    }

if ($directBot) {
    foreach ($p in $directBot) {
        Write-Host "Stopping bot process (PID $($p.ProcessId))..."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Bot stopped."
    exit 0
}

Write-Host "Bot is not running."

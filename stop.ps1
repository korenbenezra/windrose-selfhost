# stop.ps1 - Stop the Windrose game server service and the Telegram bot.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$REPO_DIR   = Split-Path -Parent $MyInvocation.MyCommand.Path
$PID_FILE   = "$REPO_DIR\windrose_bot.pid"
$SVC_NAME   = "Windrose"

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

Write-Host "=== stop.ps1 $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') ==="

# --- 1. Stop the Windrose game server service ---
$svc = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq 'Running') {
    Write-Host "Stopping Windrose game server service..."
    Stop-Service -Name $SVC_NAME -Force -ErrorAction SilentlyContinue
    # Wait up to 15 s for the service to reach Stopped
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        $svc.Refresh()
        if ($svc.Status -eq 'Stopped') { break }
        Start-Sleep -Milliseconds 500
    }
    $svc.Refresh()
    if ($svc.Status -eq 'Stopped') {
        Write-Host "Game server stopped."
    } else {
        Write-Host "WARNING: Game server did not stop cleanly (status: $($svc.Status))." -ForegroundColor Yellow
    }
} else {
    Write-Host "Game server is not running."
}

# --- 2. Stop the Telegram bot process ---
if (Test-Path $PID_FILE) {
    $pidText = (Get-Content $PID_FILE -Raw).Trim()
    if ($pidText -match '^\d+$') {
        $pidValue = [int]$pidText
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping bot process (PID $pidValue)..."
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $PID_FILE -Force -ErrorAction SilentlyContinue
            Write-Host "Bot stopped."
            exit 0
        }
    }
    Write-Host "Stale PID file found - removing"
    Remove-Item -Path $PID_FILE -Force -ErrorAction SilentlyContinue
}

$directBot = Get-WindroseBotProcesses
if ($directBot) {
    foreach ($p in $directBot) {
        Write-Host "Stopping bot process (PID $($p.ProcessId))..."
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Bot stopped."
    exit 0
}

Write-Host "Bot is not running."

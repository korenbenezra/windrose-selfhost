# stop.ps1 - Stop the refactored Windrose Telegram bot from repo root.
# Targets windrose_bot.main (bot/ is deprecated).
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$REPO_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PID_FILE = "$REPO_DIR\windrose_bot.pid"

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

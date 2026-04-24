# install.ps1  -  One-command Windrose dedicated server installer for Windows.
#
# Usage (run as Administrator in PowerShell):
#   .\install.ps1
#
# What it does:
#   1. Installs prerequisites (SteamCMD, Python, NSSM, zstd)
#   2. Downloads the Windrose server binary via SteamCMD
#   3. Prompts for Telegram bot credentials and writes .env
#   4. Installs the Python bot dependencies
#   5. Registers Windrose and WindroseBot as auto-start Windows Services
#   6. Sets up Task Scheduler tasks for health checks, backups, and updates
#   7. Starts everything and reports status
#
#Requires -RunAsAdministrator
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$REPO_DIR    = Split-Path -Parent $MyInvocation.MyCommand.Path
$SCRIPTS_DIR = "$REPO_DIR\scripts"
$LOG_DIR     = "$env:USERPROFILE\log"
$LOG_FILE    = "$LOG_DIR\windrose-install.log"

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

function Write-Log {
    param([string]$Msg, [string]$Color = 'White')
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') $Msg"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

function Write-Step {
    param([string]$Msg)
    Write-Host ""
    Write-Host "==> $Msg" -ForegroundColor Cyan
    Write-Log "==> $Msg"
}

function Invoke-Step {
    param([string]$Script)
    $path = "$SCRIPTS_DIR\$Script"
    Write-Log "    Running: $path"
    & powershell.exe -NonInteractive -ExecutionPolicy Bypass -File $path
    if ($LASTEXITCODE -ne 0) {
        Write-Log "FATAL: $Script failed with exit code $LASTEXITCODE" 'Red'
        exit $LASTEXITCODE
    }
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
Clear-Host
Write-Host ""
Write-Host "  +============================================+" -ForegroundColor Magenta
Write-Host "  |   Windrose Dedicated Server  -  Windows      |" -ForegroundColor Magenta
Write-Host "  |   Self-host installer                      |" -ForegroundColor Magenta
Write-Host "  +============================================+" -ForegroundColor Magenta
Write-Host ""
Write-Host "  This will install and start the Windrose dedicated server."
Write-Host "  Estimated time: 5-15 minutes (SteamCMD download speed varies)."
Write-Host ""
Write-Host "  Log file: $LOG_FILE"
Write-Host ""

$confirm = Read-Host "  Press ENTER to begin, or Ctrl+C to cancel"

# ---------------------------------------------------------------------------
# Step 1  -  Prerequisites
# ---------------------------------------------------------------------------
Write-Step "Step 1/6  -  Installing prerequisites (SteamCMD, Python, NSSM, zstd)"
Invoke-Step 'bootstrap.ps1'

# ---------------------------------------------------------------------------
# Step 2  -  Download Windrose
# ---------------------------------------------------------------------------
Write-Step "Step 2/6  -  Downloading Windrose server binary via SteamCMD"
Write-Host "  (This downloads several GB  -  grab a coffee)" -ForegroundColor DarkGray
Invoke-Step 'install_windrose.ps1'

# ---------------------------------------------------------------------------
# Step 3  -  Telegram bot credentials
# ---------------------------------------------------------------------------
Write-Step "Step 3/6  -  Telegram bot configuration"

$BOT_DIR     = "$env:USERPROFILE\windrose-telegram-bot"
$BOT_ENV_DST = "$BOT_DIR\.env"
$BOT_ENV_EX  = "$REPO_DIR\bot\.env.example"

New-Item -ItemType Directory -Force -Path $BOT_DIR | Out-Null

if (-not (Test-Path $BOT_ENV_DST)) {
    Copy-Item $BOT_ENV_EX $BOT_ENV_DST
    Write-Log "Created $BOT_ENV_DST from template"
}

Write-Host ""
Write-Host "  To enable the Telegram bot, enter your credentials below." -ForegroundColor Yellow
Write-Host "  Leave blank to skip (you can edit $BOT_ENV_DST later)." -ForegroundColor DarkGray
Write-Host ""

$botToken = Read-Host "  BOT_TOKEN (from @BotFather)"
$adminId  = Read-Host "  ADMIN_CHAT_ID (your Telegram user ID)"
$allowIds = Read-Host "  ALLOWED_CHAT_IDS (comma-separated, or same as ADMIN_CHAT_ID)"

if ($botToken) {
    $env_content = Get-Content $BOT_ENV_DST -Raw
    $notifyIds = if ($allowIds) { $allowIds } else { $adminId }
    $env_content = $env_content -replace 'BOT_TOKEN=.*',         "BOT_TOKEN=$botToken"
    $env_content = $env_content -replace 'ADMIN_IDS=.*',         "ADMIN_IDS=$adminId"
    $env_content = $env_content -replace 'NOTIFY_CHAT_IDS=.*',   "NOTIFY_CHAT_IDS=$notifyIds"
    $env_content = $env_content -replace 'SERVER_FILES_DIR=.*',  "SERVER_FILES_DIR=$env:USERPROFILE\windrose\R5\Saved"
    $env_content = $env_content -replace 'LOG_PATH=.*',          "LOG_PATH=$env:USERPROFILE\windrose\R5\Saved\Logs\R5.log"
    Set-Content $BOT_ENV_DST $env_content -Encoding UTF8
    Write-Log "Telegram credentials written to .env"
} else {
    Write-Log "Skipping Telegram bot credentials  -  edit $BOT_ENV_DST manually later"
}

# ---------------------------------------------------------------------------
# Step 4  -  Bot dependencies
# ---------------------------------------------------------------------------
Write-Step "Step 4/6  -  Installing Telegram bot"
Invoke-Step 'install_bot.ps1'

# ---------------------------------------------------------------------------
# Step 5  -  Windows Services
# ---------------------------------------------------------------------------
Write-Step "Step 5/6  -  Registering Windows Services"
Invoke-Step 'install_service.ps1'

# ---------------------------------------------------------------------------
# Step 6  -  Task Scheduler (health check, backup, update)
# ---------------------------------------------------------------------------
Write-Step "Step 6/6  -  Setting up scheduled tasks"

$PS = 'powershell.exe'
$flags = '-NonInteractive -ExecutionPolicy Bypass -File'

$tasks = @(
    @{
        Name    = 'WindroseHealthcheck'
        Script  = "$SCRIPTS_DIR\healthcheck.ps1"
        Trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 10) `
                      -Once -At (Get-Date)
        Desc    = 'Windrose health check every 10 minutes'
    },
    @{
        Name    = 'WindroseBackup'
        Script  = "$SCRIPTS_DIR\backup_world.ps1"
        Trigger = New-ScheduledTaskTrigger -Daily -At '02:30'
        Desc    = 'Windrose nightly world backup at 02:30'
    },
    @{
        Name    = 'WindroseUpdate'
        Script  = "$SCRIPTS_DIR\update_windrose.ps1"
        Trigger = New-ScheduledTaskTrigger -Daily -At '03:00'
        Desc    = 'Windrose nightly SteamCMD update at 03:00'
    }
)

foreach ($t in $tasks) {
    $action  = New-ScheduledTaskAction -Execute $PS -Argument "$flags `"$($t.Script)`""
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

    if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
    }

    Register-ScheduledTask `
        -TaskName    $t.Name `
        -Action      $action `
        -Trigger     $t.Trigger `
        -Settings    $settings `
        -Principal   $principal `
        -Description $t.Desc | Out-Null

    Write-Log "Scheduled task registered: $($t.Name)"
}

# ---------------------------------------------------------------------------
# Done  -  status report
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  +============================================+" -ForegroundColor Green
Write-Host "  |          Installation complete!            |" -ForegroundColor Green
Write-Host "  +============================================+" -ForegroundColor Green
Write-Host ""

$svc = Get-Service -Name 'Windrose' -ErrorAction SilentlyContinue
$bot = Get-Service -Name 'WindroseBot' -ErrorAction SilentlyContinue
Write-Host "  Windrose service   : $($svc.Status)" -ForegroundColor $(if ($svc.Status -eq 'Running') { 'Green' } else { 'Yellow' })
Write-Host "  WindroseBot service: $($bot.Status)" -ForegroundColor $(if ($bot.Status -eq 'Running') { 'Green' } else { 'Yellow' })
Write-Host ""
Write-Host "  Useful commands:"
Write-Host "    Get-Service Windrose, WindroseBot"
Write-Host "    Get-Content $env:USERPROFILE\log\windrose.log -Wait"
Write-Host "    Get-Content $env:USERPROFILE\log\windrose-bot.log -Wait"
Write-Host ""
Write-Log "=== install.ps1 complete ==="

# update_windrose.ps1  -  Backup-first SteamCMD update for Windrose on Windows.
# Scheduled daily at 03:00 by install.ps1 (Task Scheduler task "Windrose-Update").
Set-StrictMode -Version Latest
$ErrorActionPreference = 'SilentlyContinue'

$APP_ID       = 4129620
$INSTALL_DIR  = "$env:USERPROFILE\windrose"
$BACKUP_DIR   = "$env:USERPROFILE\windrose-backups"
$STEAMCMD_EXE = "$env:USERPROFILE\steamcmd\steamcmd.exe"
$LOG_FILE     = "$env:USERPROFILE\log\windrose-update.log"
$REPO_DIR     = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ENV_FILE     = "$REPO_DIR\.env"
$SVC_NAME     = 'Windrose'

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [update] $Msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

function Send-TelegramNotify {
    param([string]$Msg)
    if (-not (Test-Path $ENV_FILE)) {
        Write-Log "INFO: .env not found; skipping Telegram notification"
        return
    }
    $token   = (Select-String -Path $ENV_FILE -Pattern '^BOT_TOKEN=(.+)').Matches.Groups[1].Value.Trim('"')
    $adminIds = (Select-String -Path $ENV_FILE -Pattern '^ADMIN_IDS=(.+)').Matches.Groups[1].Value.Trim('"')
    $chatId   = ($adminIds -split '[,\s]+' | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1)
    if (-not $token -or -not $chatId) {
        Write-Log "INFO: BOT_TOKEN or ADMIN_IDS missing; skipping notification"
        return
    }
    try {
        $body = @{ chat_id = $chatId; text = $Msg; parse_mode = 'HTML' }
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
                          -Method Post -Body $body -ErrorAction Stop | Out-Null
    } catch {
        Write-Log "WARN: Telegram notification failed: $_"
    }
}

New-Item -ItemType Directory -Force -Path $BACKUP_DIR | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $LOG_FILE) | Out-Null

Write-Log "=== Windrose update started ==="

# ---------------------------------------------------------------------------
# 1. Pre-update backup (backup-first before every update)
# ---------------------------------------------------------------------------
$TS          = Get-Date -Format 'yyyyMMddTHHmmss'
$SAVES_DIR   = "$INSTALL_DIR\R5\Saved"
$BACKUP_FILE = "$BACKUP_DIR\saves-${TS}-pre-update.zip"

Write-Log "Taking pre-update backup: $BACKUP_FILE"
try {
    Compress-Archive -Path $SAVES_DIR -DestinationPath $BACKUP_FILE -Force -ErrorAction Stop
    Write-Log "Pre-update backup OK: $BACKUP_FILE"
} catch {
    Write-Log "ERROR: Pre-update backup failed: $_  -  aborting update"
    Send-TelegramNotify "&#x26A0; Windrose update ABORTED: backup failed at $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')"
    exit 1
}

# ---------------------------------------------------------------------------
# 2. Stop the service
# ---------------------------------------------------------------------------
Write-Log "Stopping $SVC_NAME service"
try {
    Stop-Service -Name $SVC_NAME -Force -ErrorAction Stop
    Write-Log "$SVC_NAME stopped"
} catch {
    Write-Log "ERROR: Could not stop $SVC_NAME service: $_"
    Send-TelegramNotify "&#x26A0; Windrose update ABORTED: could not stop service at $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')"
    exit 1
}

# ---------------------------------------------------------------------------
# 3. Run SteamCMD  -  platform flag required even on Windows (no Linux depot)
# ---------------------------------------------------------------------------
Write-Log "Running SteamCMD app_update $APP_ID validate"

& $STEAMCMD_EXE `
    +@sSteamCmdForcePlatformType windows `
    +force_install_dir $INSTALL_DIR `
    +login anonymous `
    +app_update $APP_ID validate `
    +quit

if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: SteamCMD failed (exit $LASTEXITCODE); attempting recovery restart"
    Send-TelegramNotify "&#x26A0; Windrose SteamCMD update FAILED  -  attempting recovery restart at $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')"
    Start-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
    exit 1
}

Write-Log "SteamCMD completed OK"

# ---------------------------------------------------------------------------
# 4. Start the service
# ---------------------------------------------------------------------------
Write-Log "Starting $SVC_NAME service"
try {
    Start-Service -Name $SVC_NAME -ErrorAction Stop
} catch {
    Write-Log "ERROR: Could not start $SVC_NAME after update: $_"
    Send-TelegramNotify "&#x274C; Windrose update: service failed to start after update at $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')"
    exit 1
}

# ---------------------------------------------------------------------------
# 5. Wait up to 120s for Running state
# ---------------------------------------------------------------------------
Write-Log "Waiting up to 120s for $SVC_NAME to reach Running state"
for ($i = 1; $i -le 60; $i++) {
    Start-Sleep -Seconds 2
    $svc = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Log "$SVC_NAME Running after $($i * 2)s"
        Send-TelegramNotify "&#x2705; Windrose updated and running (took $($i * 2)s to start)"
        exit 0
    }
}

Write-Log "ERROR: $SVC_NAME did not reach Running state within 120s"
Send-TelegramNotify "&#x274C; Windrose update: service did not become active within 120s at $(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')"
exit 1

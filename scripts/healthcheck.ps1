# healthcheck.ps1  -  Scheduled health check for the Windrose Windows Service.
# Schedule: every 10 minutes via Task Scheduler (set up by install.ps1).
#
# Exit codes (mirrors healthcheck.sh):
#   0  -  service is healthy (running)
#   1  -  service was stopped; successfully restarted
#   2  -  service was stopped; restart attempt failed
#   3  -  Windrose service not found
Set-StrictMode -Version Latest
$ErrorActionPreference = 'SilentlyContinue'

$SVC_NAME   = 'Windrose'
$LOG_FILE   = "$env:USERPROFILE\log\windrose-health.log"
$STATE_FILE = "$env:TEMP\windrose-health-last-state"

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [healthcheck] $Msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path (Split-Path $LOG_FILE) | Out-Null

# ---------------------------------------------------------------------------
# 1. Check whether the service unit exists at all
# ---------------------------------------------------------------------------
$svc = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Log "ERROR: '$SVC_NAME' service not found  -  is install_service.ps1 complete?"
    Set-Content $STATE_FILE 'unit-missing' -Encoding UTF8
    exit 3
}

# ---------------------------------------------------------------------------
# 2. Check running state
# ---------------------------------------------------------------------------
if ($svc.Status -eq 'Running') {
    Write-Log "OK: $SVC_NAME service is Running"
    Set-Content $STATE_FILE 'healthy' -Encoding UTF8
    exit 0
}

Write-Log "WARN: $SVC_NAME service state=$($svc.Status)  -  attempting restart"
Set-Content $STATE_FILE 'restarting' -Encoding UTF8

# ---------------------------------------------------------------------------
# 3. Attempt restart
# ---------------------------------------------------------------------------
try {
    Restart-Service -Name $SVC_NAME -Force -ErrorAction Stop
} catch {
    Write-Log "ERROR: Restart-Service failed: $_"
    Set-Content $STATE_FILE 'restart-failed' -Encoding UTF8
    exit 2
}

# ---------------------------------------------------------------------------
# 4. Wait up to 30 seconds for the service to reach Running state
# ---------------------------------------------------------------------------
for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 2
    $svc = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Log "RECOVERED: $SVC_NAME is Running after $($i * 2)s"
        Set-Content $STATE_FILE 'recovered' -Encoding UTF8
        exit 1
    }
}

Write-Log "ERROR: $SVC_NAME did not reach Running state within 30s after restart"
Set-Content $STATE_FILE 'restart-failed' -Encoding UTF8
exit 2

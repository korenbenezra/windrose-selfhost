# backup_world.ps1  -  Nightly world-save snapshot with 7-day rolling retention.
# Scheduled daily at 02:30 by install.ps1 (Task Scheduler task "Windrose-Backup").
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$INSTALL_DIR  = "$env:USERPROFILE\windrose"
$BACKUP_DIR   = "$env:USERPROFILE\windrose-backups"
$LOG_FILE     = "$env:USERPROFILE\log\windrose-backup.log"
$RETAIN_DAYS  = 7

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [backup] $Msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $BACKUP_DIR | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $LOG_FILE) | Out-Null

Write-Log "=== Windrose backup started ==="

# ---------------------------------------------------------------------------
# 1. Create snapshot using zstd (if available) or Compress-Archive fallback
# ---------------------------------------------------------------------------
$TS          = Get-Date -Format 'yyyyMMddTHHmmss'
$SAVES_DIR   = "$INSTALL_DIR\R5\Saved"

if (-not (Test-Path $SAVES_DIR)) {
    Write-Log "ERROR: Saves directory not found: $SAVES_DIR"
    exit 1
}

$zstd = Get-Command zstd -ErrorAction SilentlyContinue
if ($zstd) {
    $BACKUP_FILE = "$BACKUP_DIR\saves-${TS}.tar.zst"
    Write-Log "Snapshotting $SAVES_DIR -> $BACKUP_FILE (tar+zstd)"
    # Single-process: avoids PS 5.1 binary-stream corruption across the pipe boundary.
    & tar -c --use-compress-program=zstd -f $BACKUP_FILE -C $INSTALL_DIR R5/Saved
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: tar+zstd failed (exit $LASTEXITCODE)"
        exit 1
    }
} else {
    $BACKUP_FILE = "$BACKUP_DIR\saves-${TS}.zip"
    Write-Log "Snapshotting $SAVES_DIR -> $BACKUP_FILE (zip fallback  -  install zstd for better compression)"
    Compress-Archive -Path $SAVES_DIR -DestinationPath $BACKUP_FILE -Force
}

$size = [Math]::Round((Get-Item $BACKUP_FILE).Length / 1MB, 1)
Write-Log "Backup OK: $BACKUP_FILE ($size MB)"

# ---------------------------------------------------------------------------
# 2. 7-day rolling retention
# ---------------------------------------------------------------------------
Write-Log "Pruning backups older than $RETAIN_DAYS days"

$cutoff = (Get-Date).AddDays(-$RETAIN_DAYS)
Get-ChildItem $BACKUP_DIR -File |
    Where-Object { $_.Name -match '^saves-\d{8}T\d{6}\.(tar\.zst|zip)$' -and $_.LastWriteTime -lt $cutoff } |
    ForEach-Object {
        Write-Log "  Deleting old backup: $($_.Name)"
        Remove-Item $_.FullName -Force
    }

$remaining = @(Get-ChildItem $BACKUP_DIR -File | Where-Object { $_.Name -match '^saves-' }).Count
Write-Log "Retention complete. Backup files on disk: $remaining"

Write-Log "=== Windrose backup finished ==="

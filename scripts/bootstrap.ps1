# bootstrap.ps1 — Windows provisioning for the Windrose dedicated server host.
# Idempotent: safe to re-run. Run as Administrator in PowerShell.
# Installs: SteamCMD, Python 3, NSSM (service manager), zstd.
#
# Mirrors: bootstrap.sh (Linux/Wine path)
#
# Requirements: Windows 10/11 x64, AVX2 CPU, >=8 GB RAM, winget available.
#Requires -RunAsAdministrator
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$INSTALL_DIR  = "$env:USERPROFILE\windrose"
$STEAMCMD_DIR = "$env:USERPROFILE\steamcmd"
$LOG_DIR      = "$env:USERPROFILE\log"
$BACKUP_DIR   = "$env:USERPROFILE\windrose-backups"
$SCRIPTS_DIR  = "$env:USERPROFILE\scripts"
$BOT_DIR      = "$env:USERPROFILE\windrose-telegram-bot"
$LOG_FILE     = "$LOG_DIR\windrose-bootstrap.log"

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [bootstrap] $Msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

# ---------------------------------------------------------------------------
# Setup log directory early so Write-Log works
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

Write-Log "=== bootstrap.ps1 started ==="

# ---------------------------------------------------------------------------
# 1. Pre-flight checks
# ---------------------------------------------------------------------------
Write-Log "--- Pre-flight checks ---"

$arch = $env:PROCESSOR_ARCHITECTURE
if ($arch -ne 'AMD64') {
    Write-Log "FATAL: architecture is '$arch'; x86_64 (AMD64) required."
    exit 1
}
Write-Log "arch: $arch OK"

# AVX2 check via CPUID (WMI)
$cpu = Get-WmiObject Win32_Processor | Select-Object -First 1
# Windows doesn't expose AVX2 directly in WMI; check via PowerShell/.NET
Add-Type -TypeDefinition @'
using System;
using System.Runtime.Intrinsics.X86;
public class CpuCheck {
    public static bool HasAvx2() {
        try { return Avx2.IsSupported; }
        catch { return false; }
    }
}
'@ -ErrorAction SilentlyContinue
try {
    if (-not [CpuCheck]::HasAvx2()) {
        Write-Log "FATAL: CPU does not support AVX2 (required by Windrose)."
        exit 1
    }
    Write-Log "AVX2: present OK"
} catch {
    Write-Log "WARNING: Could not verify AVX2 support — proceeding anyway."
}

$ram = (Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory / 1MB
if ($ram -lt 7800) {
    Write-Log "WARNING: RAM is $([Math]::Round($ram)) MB — Windrose needs >=8 GB for 2 players."
} else {
    Write-Log "RAM: $([Math]::Round($ram)) MB OK"
}

# ---------------------------------------------------------------------------
# 2. Directory scaffolding
# ---------------------------------------------------------------------------
Write-Log "--- Creating directory scaffolding ---"

foreach ($dir in @($INSTALL_DIR, "$INSTALL_DIR\pfx", $LOG_DIR, $BACKUP_DIR, $SCRIPTS_DIR, $BOT_DIR)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

Write-Log "Directories created OK"

# ---------------------------------------------------------------------------
# 3. winget presence check
# ---------------------------------------------------------------------------
Write-Log "--- Checking winget ---"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Log "FATAL: winget not found. Install the App Installer from the Microsoft Store first."
    Write-Log "       https://aka.ms/getwinget"
    exit 1
}
Write-Log "winget: present OK"

# ---------------------------------------------------------------------------
# 4. Install Python 3 (if not already present)
# ---------------------------------------------------------------------------
Write-Log "--- Checking Python 3 ---"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Log "Installing Python 3 via winget..."
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('PATH', 'User')
} else {
    $pyver = python --version 2>&1
    Write-Log "Python already installed: $pyver"
}

# ---------------------------------------------------------------------------
# 5. Download SteamCMD (if not already present)
# ---------------------------------------------------------------------------
Write-Log "--- Checking SteamCMD ---"
$steamcmdExe = "$STEAMCMD_DIR\steamcmd.exe"

if (-not (Test-Path $steamcmdExe)) {
    Write-Log "Downloading SteamCMD..."
    New-Item -ItemType Directory -Force -Path $STEAMCMD_DIR | Out-Null
    $zip = "$env:TEMP\steamcmd.zip"
    Invoke-WebRequest -Uri 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip' `
                      -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $STEAMCMD_DIR -Force
    Remove-Item $zip
    Write-Log "SteamCMD installed at $STEAMCMD_DIR OK"
} else {
    Write-Log "SteamCMD already present: $steamcmdExe"
}

# ---------------------------------------------------------------------------
# 6. Download NSSM (Non-Sucking Service Manager) for Windows Service support
# ---------------------------------------------------------------------------
Write-Log "--- Checking NSSM ---"
$nssmExe = "$env:ProgramFiles\nssm\nssm.exe"

if (-not (Test-Path $nssmExe)) {
    Write-Log "Downloading NSSM..."
    $nssmZip = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' `
                      -OutFile $nssmZip -UseBasicParsing
    $nssmExtract = "$env:TEMP\nssm-extract"
    Expand-Archive -Path $nssmZip -DestinationPath $nssmExtract -Force
    $nssmBin = Get-ChildItem "$nssmExtract" -Recurse -Filter 'nssm.exe' |
               Where-Object { $_.FullName -like '*win64*' } |
               Select-Object -First 1
    New-Item -ItemType Directory -Force -Path "$env:ProgramFiles\nssm" | Out-Null
    Copy-Item $nssmBin.FullName "$env:ProgramFiles\nssm\nssm.exe"
    Remove-Item $nssmZip, $nssmExtract -Recurse -Force
    Write-Log "NSSM installed at $nssmExe OK"
} else {
    Write-Log "NSSM already present: $nssmExe"
}

# Add NSSM to PATH for this session and permanently
$nssmDir = "$env:ProgramFiles\nssm"
if ($env:PATH -notlike "*$nssmDir*") {
    [System.Environment]::SetEnvironmentVariable(
        'PATH',
        [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ";$nssmDir",
        'Machine'
    )
    $env:PATH += ";$nssmDir"
}

# ---------------------------------------------------------------------------
# 7. Install zstd for backup compression (via winget)
# ---------------------------------------------------------------------------
Write-Log "--- Checking zstd ---"
if (-not (Get-Command zstd -ErrorAction SilentlyContinue)) {
    Write-Log "Installing zstd via winget..."
    winget install --id Facebook.Zstandard --silent --accept-package-agreements --accept-source-agreements
    $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('PATH', 'User')
} else {
    Write-Log "zstd already present"
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Log ""
Write-Log "=== bootstrap.ps1 complete ==="
Write-Log "Next step: run scripts\install_windrose.ps1"

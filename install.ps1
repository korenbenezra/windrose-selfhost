# install.ps1 - Windows-only installer for the refactored Windrose Telegram bot.
#
# Usage:
#   .\install.ps1
#
# What it does:
#   1. Creates/updates .env in repo root (no manual file creation needed)
#   2. Creates .venv in repo root (if missing)
#   3. Installs bot dependencies from windrose_bot\requirements.txt
#   4. Verifies runtime imports for windrose_bot
param(
    # Use values from existing .env / environment variables; do not prompt.
    [switch]$NonInteractive
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$REPO_DIR        = Split-Path -Parent $MyInvocation.MyCommand.Path
$BOT_MAIN        = "$REPO_DIR\windrose_bot\main.py"
$REQ_FILE        = "$REPO_DIR\windrose_bot\requirements.txt"
$ENV_FILE        = "$REPO_DIR\.env"
$ENV_EXAMPLE     = "$REPO_DIR\.env.example"
$VENV_DIR        = "$REPO_DIR\.venv"
$VENV_PYTHON     = "$VENV_DIR\Scripts\python.exe"
$VENV_PIP        = "$VENV_DIR\Scripts\pip.exe"
$INSTALL_LOG_DIR = "$REPO_DIR\logs"
$INSTALL_LOG     = "$INSTALL_LOG_DIR\install.log"

function Write-Log {
    param([string]$Msg, [string]$Color = 'White')
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [install] $Msg"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $INSTALL_LOG -Value $line -Encoding UTF8
}

function Set-EnvIfMissing {
    param([string]$Path, [string]$Key, [string]$Value)
    if (-not (Get-EnvValue -Path $Path -Key $Key)) {
        Set-Or-AddEnv -Path $Path -Key $Key -Value $Value
    }
}

function Set-Or-AddEnv {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )
    $content = Get-Content -Path $Path -Raw
    if ($content.Length -gt 0 -and $content[0] -eq [char]0xFEFF) {
        $content = $content.Substring(1)
    }
    if ($content -match "(?m)^$([regex]::Escape($Key))=") {
        $content = [regex]::Replace(
            $content,
            "(?m)^$([regex]::Escape($Key))=.*$",
            "$Key=$Value"
        )
    } else {
        if (-not $content.EndsWith("`n")) { $content += "`n" }
        $content += "$Key=$Value`n"
    }
    [System.IO.File]::WriteAllText(
        $Path,
        $content,
        (New-Object System.Text.UTF8Encoding($false))
    )
}

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Key
    )
    if (-not (Test-Path $Path)) { return '' }
    $line = Get-Content -Path $Path | Where-Object { $_ -match "^\uFEFF?$([regex]::Escape($Key))=" } | Select-Object -First 1
    if (-not $line) { return '' }
    return ($line -replace "^\uFEFF?$([regex]::Escape($Key))=", '').Trim()
}

New-Item -ItemType Directory -Force -Path $INSTALL_LOG_DIR | Out-Null

Write-Host ""
Write-Host "  +============================================+" -ForegroundColor Cyan
Write-Host "  |      Windrose Bot Installer (Windows)      |" -ForegroundColor Cyan
Write-Host "  +============================================+" -ForegroundColor Cyan
Write-Host ""

Write-Log "Starting installer in $REPO_DIR"

if (-not (Test-Path $BOT_MAIN)) {
    Write-Log "FATAL: windrose_bot main not found at $BOT_MAIN" 'Red'
    exit 1
}
if (-not (Test-Path $REQ_FILE)) {
    Write-Log "FATAL: requirements not found at $REQ_FILE" 'Red'
    exit 1
}

# ---------------------------------------------------------------------------
# 1) Find Python
# ---------------------------------------------------------------------------
$pythonCmd = $null
foreach ($candidate in @('py', 'python')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*WindowsApps*' -and (Test-Path $cmd.Source)) {
        $pythonCmd = $candidate
        break
    }
}
if (-not $pythonCmd) {
    Write-Log "FATAL: Python not found. Install Python 3.11+ and re-run." 'Red'
    exit 1
}
Write-Log "Python launcher: $pythonCmd"

# ---------------------------------------------------------------------------
# 2) Create .venv (if needed)
# ---------------------------------------------------------------------------
if (-not (Test-Path $VENV_PYTHON)) {
    Write-Log "Creating virtualenv at $VENV_DIR"
    & $pythonCmd -m venv $VENV_DIR
}
if (-not (Test-Path $VENV_PYTHON)) {
    Write-Log "FATAL: Virtualenv creation failed ($VENV_PYTHON missing)" 'Red'
    exit 1
}
Write-Log "Virtualenv ready: $VENV_DIR"

# ---------------------------------------------------------------------------
# 3) Install dependencies
# ---------------------------------------------------------------------------
Write-Log "Installing dependencies from $REQ_FILE"
& $VENV_PIP install --disable-pip-version-check -r $REQ_FILE
Write-Log "Dependencies installed"

# ---------------------------------------------------------------------------
# 4) Create/update .env in repo root
# ---------------------------------------------------------------------------
if (-not (Test-Path $ENV_FILE)) {
    if (-not (Test-Path $ENV_EXAMPLE)) {
        Write-Log "FATAL: Missing $ENV_FILE and $ENV_EXAMPLE" 'Red'
        exit 1
    }
    Copy-Item -Path $ENV_EXAMPLE -Destination $ENV_FILE -Force
    Write-Log "Created $ENV_FILE from $ENV_EXAMPLE"
}

$existingToken = Get-EnvValue -Path $ENV_FILE -Key 'BOT_TOKEN'
$existingAdmins = Get-EnvValue -Path $ENV_FILE -Key 'ADMIN_IDS'
$existingNotify = Get-EnvValue -Path $ENV_FILE -Key 'NOTIFY_CHAT_IDS'

$canPrompt = (-not $NonInteractive) -and [Environment]::UserInteractive

Write-Host ""
Write-Host "Telegram configuration" -ForegroundColor Yellow

$newToken = $existingToken
$adminIds = if ($existingAdmins) { $existingAdmins } else { '123456789' }
$notifyIds = if ($existingNotify) { $existingNotify } else { $adminIds }

if ($canPrompt) {
    $tokenPrompt = if ($existingToken -and $existingToken -notmatch '^(your-bot-token-here|your_telegram_bot_token)?$') {
        "BOT_TOKEN [press ENTER to keep current]"
    } else {
        "BOT_TOKEN (from @BotFather)"
    }
    $inputToken = Read-Host $tokenPrompt
    if ($inputToken) { $newToken = $inputToken }

    $inputAdmins = Read-Host "ADMIN_IDS (comma separated Telegram IDs, e.g. 123456789,987654321)"
    if ($inputAdmins) { $adminIds = $inputAdmins }

    $inputNotify = Read-Host "NOTIFY_CHAT_IDS (comma separated, ENTER = same as ADMIN_IDS)"
    if ($inputNotify) { $notifyIds = $inputNotify } else { $notifyIds = $adminIds }
} else {
    if (-not $newToken) {
        $newToken = $env:BOT_TOKEN
    }
    if (-not $existingAdmins -and $env:ADMIN_IDS) {
        $adminIds = $env:ADMIN_IDS
    }
    if (-not $existingNotify -and $env:NOTIFY_CHAT_IDS) {
        $notifyIds = $env:NOTIFY_CHAT_IDS
    }
}

if (-not $newToken -or $newToken -match '^(your-bot-token-here|your_telegram_bot_token)$') {
    Write-Log "FATAL: BOT_TOKEN is required. Run .\\install.ps1 interactively, or pass -NonInteractive with BOT_TOKEN env var set." 'Red'
    exit 1
}

$serverFilesDefault = "$env:USERPROFILE\windrose\R5\Saved"

Set-Or-AddEnv -Path $ENV_FILE -Key 'BOT_TOKEN'       -Value $newToken
Set-Or-AddEnv -Path $ENV_FILE -Key 'ADMIN_IDS'       -Value $adminIds
Set-Or-AddEnv -Path $ENV_FILE -Key 'NOTIFY_CHAT_IDS' -Value $notifyIds

# Path-style keys: only write when absent so re-runs do not clobber user edits.
Set-EnvIfMissing -Path $ENV_FILE -Key 'SERVER_FILES_DIR'    -Value $serverFilesDefault
Set-EnvIfMissing -Path $ENV_FILE -Key 'WINDROSE_SCRIPTS_DIR' -Value "$REPO_DIR\scripts"

$existingLogPath = Get-EnvValue -Path $ENV_FILE -Key 'LOG_PATH'
if (-not $existingLogPath) {
    $logPathPrompt = ''
    if ($canPrompt) {
        Write-Host ""
        Write-Host "LOG_PATH: full path to the Windrose server log file." -ForegroundColor Yellow
        Write-Host "  Example: $env:USERPROFILE\windrose\R5\Saved\Logs\WindroseServer.log" -ForegroundColor DarkGray
        $logPathPrompt = Read-Host "LOG_PATH (ENTER to skip and configure later)"
    }
    if ($logPathPrompt) {
        Set-Or-AddEnv -Path $ENV_FILE -Key 'LOG_PATH' -Value $logPathPrompt
    } else {
        Write-Log "WARNING: LOG_PATH not set  -  player monitor will be inactive until configured in .env" 'Yellow'
    }
}

Write-Log "Updated .env configuration"

# ---------------------------------------------------------------------------
# 5) Smoke test imports
# ---------------------------------------------------------------------------
$smokeOutFile = [System.IO.Path]::GetTempFileName()
$smokeErrFile = [System.IO.Path]::GetTempFileName()
$smokePyFile  = "$REPO_DIR\.install-smoke.py"
try {
    [System.IO.File]::WriteAllText(
        $smokePyFile,
        "import telegram, dotenv, watchdog, psutil`nimport windrose_bot.main`nprint('imports OK')`n",
        (New-Object System.Text.UTF8Encoding($false))
    )

    $smokeProc = Start-Process `
        -FilePath $VENV_PYTHON `
        -ArgumentList @($smokePyFile) `
        -WorkingDirectory $REPO_DIR `
        -Wait `
        -PassThru `
        -NoNewWindow `
        -RedirectStandardOutput $smokeOutFile `
        -RedirectStandardError $smokeErrFile

    $smokeOut = [string](Get-Content -Path $smokeOutFile -Raw -ErrorAction SilentlyContinue)
    if ($null -eq $smokeOut) { $smokeOut = '' }
    $smokeOut = $smokeOut.Trim()

    $smokeErr = [string](Get-Content -Path $smokeErrFile -Raw -ErrorAction SilentlyContinue)
    if ($null -eq $smokeErr) { $smokeErr = '' }
    $smokeErr = $smokeErr.Trim()

    if ($smokeProc.ExitCode -ne 0) {
        Write-Log "FATAL: Import check failed (exit $($smokeProc.ExitCode))." 'Red'
        if ($smokeOut) { Write-Host $smokeOut -ForegroundColor Yellow }
        if ($smokeErr) { Write-Host $smokeErr -ForegroundColor Yellow }
        exit $smokeProc.ExitCode
    }

    if ($smokeErr) {
        Write-Log "Import check stderr: $smokeErr" 'Yellow'
    }
    Write-Log "Import check: $(if ($smokeOut) { $smokeOut } else { 'OK' })"
}
finally {
    Remove-Item -Path $smokeOutFile, $smokeErrFile, $smokePyFile -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# 6. Register scheduled maintenance tasks (requires Administrator)
# ---------------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if ($isAdmin) {
    Write-Log "Registering scheduled maintenance tasks..."

    $psExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $psFlags = "-NonInteractive -ExecutionPolicy Bypass -File"

    $tasks = @(
        @{ Name = "Windrose-Backup";      Schedule = "DAILY";  Time = "02:30"; Script = "$REPO_DIR\scripts\backup_world.ps1" },
        @{ Name = "Windrose-Update";      Schedule = "DAILY";  Time = "03:00"; Script = "$REPO_DIR\scripts\update_windrose.ps1" },
        @{ Name = "Windrose-Healthcheck"; Schedule = "MINUTE"; Time = $null;   Interval = 10; Script = "$REPO_DIR\scripts\healthcheck.ps1" }
    )

    foreach ($t in $tasks) {
        $tr = "`"$psExe`" $psFlags `"$($t.Script)`""
        if ($t.Schedule -eq 'MINUTE') {
            schtasks /Create /F /TN $t.Name /SC MINUTE /MO $t.Interval /RU SYSTEM /TR $tr | Out-Null
        } else {
            schtasks /Create /F /TN $t.Name /SC $t.Schedule /ST $t.Time /RU SYSTEM /TR $tr | Out-Null
        }
        if ($LASTEXITCODE -eq 0) {
            Write-Log "  Scheduled task registered: $($t.Name)"
        } else {
            Write-Log "  WARNING: Failed to register task $($t.Name) (exit $LASTEXITCODE)" 'Yellow'
        }
    }
} else {
    Write-Log "Skipping scheduled task registration (not Administrator)  -  re-run as Administrator to register tasks" 'Yellow'
}

Write-Host ""
Write-Host "Install complete." -ForegroundColor Green
Write-Host "Use:"
Write-Host "  .\start.ps1"
Write-Host "  .\stop.ps1"
Write-Host ""
Write-Log "Install complete"

# install_bot.ps1 — Set up the Windrose Telegram bot virtualenv and config on Windows.
# Run as Administrator after install_service.ps1 completes.
#
# Mirrors: install_bot.sh (Linux path)
#Requires -RunAsAdministrator
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SCRIPTS_DIR  = Split-Path -Parent $MyInvocation.MyCommand.Path
$REPO_DIR     = Split-Path -Parent $SCRIPTS_DIR

$BOT_SRC      = "$REPO_DIR\bot"
$BOT_DIR      = "$env:USERPROFILE\windrose-telegram-bot"
$VENV         = "$BOT_DIR\venv"
$PYTHON_EXE   = "$VENV\Scripts\python.exe"
$PIP_EXE      = "$VENV\Scripts\pip.exe"
$BOT_ENV_SRC  = "$BOT_SRC\.env"
$BOT_ENV_EX   = "$BOT_SRC\.env.example"
$BOT_ENV_DST  = "$BOT_DIR\.env"
$LOG_DIR      = "$env:USERPROFILE\log"
$LOG_FILE     = "$LOG_DIR\windrose-install.log"

function Write-Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') [install_bot] $Msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

Write-Log "=== install_bot.ps1 started ==="
Write-Log "    Bot source : $BOT_SRC"
Write-Log "    Install dir: $BOT_DIR"

# ---------------------------------------------------------------------------
# 1. Create the install directory and copy bot files
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $BOT_DIR | Out-Null

Copy-Item "$BOT_SRC\bot.py"           "$BOT_DIR\bot.py" -Force
Copy-Item "$BOT_SRC\requirements.txt" "$BOT_DIR\requirements.txt" -Force

Write-Log "Bot files copied OK"

# ---------------------------------------------------------------------------
# 2. Create .env on first install
# ---------------------------------------------------------------------------
if (-not (Test-Path $BOT_ENV_DST)) {
    if (Test-Path $BOT_ENV_SRC) {
        Copy-Item $BOT_ENV_SRC $BOT_ENV_DST
        Write-Log "Created $BOT_ENV_DST from $BOT_ENV_SRC"
    } else {
        Copy-Item $BOT_ENV_EX $BOT_ENV_DST
        Write-Log "Created $BOT_ENV_DST from $BOT_ENV_EX"
    }
    Write-Host ""
    Write-Host "  *** IMPORTANT: edit $BOT_ENV_DST now ***" -ForegroundColor Yellow
    Write-Host "  Set BOT_TOKEN, ADMIN_CHAT_ID, ALLOWED_CHAT_IDS, and LOG_PATH" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Log ".env already exists — not overwriting"
}

# ---------------------------------------------------------------------------
# 3. Verify Python is available
# ---------------------------------------------------------------------------
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Log "FATAL: python not found on PATH. Run bootstrap.ps1 first."
    exit 1
}

# ---------------------------------------------------------------------------
# 4. Create Python virtualenv
# ---------------------------------------------------------------------------
if (-not (Test-Path $PYTHON_EXE)) {
    Write-Log "--- Creating virtualenv at $VENV ---"
    python -m venv $VENV
    Write-Log "Virtualenv created OK"
} else {
    Write-Log "Virtualenv already exists — upgrading packages"
}

# ---------------------------------------------------------------------------
# 5. Install / upgrade dependencies
# ---------------------------------------------------------------------------
Write-Log "--- Installing Python dependencies ---"
& $PIP_EXE install --quiet --upgrade pip
& $PIP_EXE install --quiet -r "$BOT_DIR\requirements.txt"
Write-Log "Dependencies installed OK"

# ---------------------------------------------------------------------------
# 6. Verify the bot module imports cleanly
# ---------------------------------------------------------------------------
Write-Log "--- Verifying bot module ---"
$check = & $PYTHON_EXE -c "import telegram, dotenv, watchdog; print('imports OK')" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: import check failed: $check"
    exit 1
}
Write-Log "Module check: $check"

# ---------------------------------------------------------------------------
# 7. Register/refresh the WindroseBot Windows Service (if NSSM is present)
# ---------------------------------------------------------------------------
$NSSM_EXE = "$env:ProgramFiles\nssm\nssm.exe"
$BOT_SVC  = 'WindroseBot'
$BOT_LOG  = "$LOG_DIR\windrose-bot.log"

if (Test-Path $NSSM_EXE) {
    Write-Log "--- Registering WindroseBot Windows Service ---"

    $existingBot = Get-Service -Name $BOT_SVC -ErrorAction SilentlyContinue
    if ($existingBot) {
        if ($existingBot.Status -eq 'Running') { & $NSSM_EXE stop $BOT_SVC }
        & $NSSM_EXE remove $BOT_SVC confirm
    }

    & $NSSM_EXE install $BOT_SVC $PYTHON_EXE "$BOT_DIR\bot.py"
    & $NSSM_EXE set $BOT_SVC DisplayName  'Windrose Telegram Bot'
    & $NSSM_EXE set $BOT_SVC Description  'Windrose Telegram bot managed by windrose-selfhost'
    & $NSSM_EXE set $BOT_SVC Start        SERVICE_AUTO_START
    & $NSSM_EXE set $BOT_SVC AppDirectory $BOT_DIR
    & $NSSM_EXE set $BOT_SVC AppStdout    $BOT_LOG
    & $NSSM_EXE set $BOT_SVC AppStderr    $BOT_LOG
    & $NSSM_EXE set $BOT_SVC AppRotateFiles  1
    & $NSSM_EXE set $BOT_SVC AppRotateBytes  10485760  # 10 MB
    & $NSSM_EXE set $BOT_SVC AppRestartDelay 10000

    Write-Log "WindroseBot service registered OK"
} else {
    Write-Log "INFO: NSSM not found — run install_service.ps1 to register the bot as a service"
}

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Log ""
Write-Log "=== install_bot.ps1 complete ==="
Write-Log "Next steps:"
Write-Log "  1. Edit $BOT_ENV_DST (BOT_TOKEN, ADMIN_CHAT_ID, ALLOWED_CHAT_IDS)"
Write-Log "  2. Start-Service WindroseBot"
Write-Log "  3. Get-Service WindroseBot"
Write-Log "  4. Get-Content $BOT_LOG -Wait"

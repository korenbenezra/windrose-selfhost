# Windrose Server (Windows)

Setup for running a Windrose dedicated server on Windows Server / Windows 10/11 x64.

## Requirements

- Windows 10/11 or Windows Server 2019+ (`x86_64`)
- AVX2 CPU
- 8 GB+ RAM
- PowerShell 5.1+ (run as Administrator)
- [winget](https://aka.ms/getwinget) available

## Quick Start

Open PowerShell **as Administrator**:

```powershell
git clone <your-repo-url> windrose-selfhost
cd windrose-selfhost

# Install dependencies (SteamCMD, Python 3, NSSM, zstd)
.\scripts\bootstrap.ps1

# Download and install Windrose server files
.\scripts\install_windrose.ps1 -HomeDir $env:USERPROFILE

# Register Windrose as a Windows Service (auto-start, crash restart via NSSM)
.\scripts\install_service.ps1 -HomeDir $env:USERPROFILE

# Start the server
Start-Service Windrose
```

## Check Server

```powershell
Get-Service Windrose
Get-Content "$env:USERPROFILE\log\windrose.log" -Wait
```

## Daily Commands

```powershell
Start-Service Windrose
Stop-Service Windrose
Restart-Service Windrose
```

Or via NSSM directly:

```powershell
nssm start Windrose
nssm stop Windrose
nssm restart Windrose
```

## Optional: Telegram Bot

```powershell
# Install bot dependencies and create the .env file
.\scripts\install_bot.ps1 -HomeDir $env:USERPROFILE

# Edit the .env file
notepad "$env:USERPROFILE\windrose-telegram-bot\.env"

# Register and start the bot service
.\scripts\install_service.ps1 -HomeDir $env:USERPROFILE

Start-Service WindroseBot
Get-Service WindroseBot
```

Set these in `.env`:
- `BOT_TOKEN`
- `ADMIN_IDS`
- `NOTIFY_CHAT_IDS`
- `LOG_PATH`

## Optional: Automation (backup/update/healthcheck)

The PowerShell scripts in `scripts/` can be scheduled via Windows Task Scheduler:

```powershell
# Run backup manually
.\scripts\backup_world.ps1

# Run update manually
.\scripts\update_windrose.ps1

# Run healthcheck manually
.\scripts\healthcheck.ps1
```

To schedule them, open **Task Scheduler** and create tasks pointing to the `.ps1` files,
or use the `schtasks` command:

```powershell
schtasks /create /tn "WindroseBackup" /tr "powershell -File C:\path\to\scripts\backup_world.ps1" /sc daily /st 03:00
```

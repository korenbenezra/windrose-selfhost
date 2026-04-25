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
git clone https://github.com/korenbenezra/windrose-selfhost.git windrose-selfhost
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
# Install bot dependencies and configure .env interactively
.\install.ps1

# Start the game server + bot
.\start.ps1

# Stop both
.\stop.ps1
```

Set these in `.env` (the installer will prompt for them):
- `BOT_TOKEN` — token from [@BotFather](https://t.me/BotFather)
- `ADMIN_IDS` — your Telegram user ID (message [@userinfobot](https://t.me/userinfobot) to find it)
- `NOTIFY_CHAT_IDS` — same as `ADMIN_IDS` if you want alerts sent to yourself
- `LOG_PATH` — path to the Windrose server log file

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

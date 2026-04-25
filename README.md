# Windrose Self-Host (Windows)

Run your own Windrose dedicated server on Windows, with an optional Telegram bot to manage it remotely.

---

## Requirements

- Windows 10/11 or Windows Server 2019+ (64-bit)
- A CPU with AVX2 support
- 8 GB+ RAM
- PowerShell 5.1+ (run as Administrator)
- [winget](https://aka.ms/getwinget) installed

---

## Quick Setup

Open PowerShell **as Administrator** and run these commands one by one:

```powershell
# 1. Clone the repo
git clone https://github.com/korenbenezra/windrose-selfhost.git windrose-selfhost
cd windrose-selfhost

# 2. Install required tools (SteamCMD, Python 3, NSSM, zstd)
.\scripts\bootstrap.ps1

# 3. Download the Windrose server files
.\scripts\install_windrose.ps1 -HomeDir $env:USERPROFILE

# 4. Register as a Windows Service (auto-starts on boot, restarts on crash)
.\scripts\install_service.ps1 -HomeDir $env:USERPROFILE

# 5. Start the server
Start-Service Windrose
```

**Check it's running:**

```powershell
Get-Service Windrose
Get-Content "$env:USERPROFILE\log\windrose.log" -Wait
```

---

## Managing the Server

```powershell
Start-Service Windrose
Stop-Service Windrose
Restart-Service Windrose
```

---

## Optional: Telegram Bot

Manage your server remotely from Telegram.

**Setup:**

```powershell
.\install.ps1   # installs bot and prompts for your config
.\start.ps1     # starts both the game server and bot
.\stop.ps1      # stops both
```

You'll need to set these during install (or edit `.env` manually):

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Get from [@BotFather](https://t.me/BotFather) on Telegram |
| `ADMIN_IDS` | Your Telegram user ID — get it from [@userinfobot](https://t.me/userinfobot) |
| `NOTIFY_CHAT_IDS` | Where to send alerts (usually same as `ADMIN_IDS`) |
| `LOG_PATH` | Path to the Windrose log file |

**Bot commands:**

| Command | What it does |
|---|---|
| `/status` | Show if the server is online |
| `/players` | List connected players |
| `/uptime` | Show how long the server has been running |
| `/logs` | Show recent server logs |
| `/backup` | Trigger a world backup *(admin only)* |
| `/restart` | Restart the server *(admin only)* |
| `/update` | Update the server to the latest version *(admin only)* |

---

## Optional: Scheduled Automation

Run these manually or schedule them in Windows Task Scheduler:

```powershell
.\scripts\backup_world.ps1    # backup your world
.\scripts\update_windrose.ps1 # update the server
.\scripts\healthcheck.ps1     # check server health
```

**Example: schedule a daily backup at 3 AM**

```powershell
schtasks /create /tn "WindroseBackup" /tr "powershell -File C:\path\to\scripts\backup_world.ps1" /sc daily /st 03:00
```

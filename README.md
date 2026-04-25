# Windrose Server Manager

A simple way to host a Windrose dedicated server on Windows and manage it straight from your phone using Telegram. Start, stop, back up, and check on your server from anywhere - no remote desktop needed.

---

## Requirements

- Windows 10/11 or Windows Server 2019+ (64-bit)
- 8 GB+ RAM
- PowerShell 5.1+ (run as Administrator)
- [winget](https://aka.ms/getwinget) installed

---

## Setup

Open PowerShell **as Administrator**:

```powershell
git clone https://github.com/korenbenezra/windrose-selfhost.git windrose-selfhost
cd windrose-selfhost
.\install.ps1
```

The installer will guide you through the setup and ask for your Telegram bot credentials:

| What it asks | Where to get it |
|---|---|
| **Bot token** | Message [@BotFather](https://t.me/BotFather) on Telegram |
| **Your Telegram ID** | Message [@userinfobot](https://t.me/userinfobot) |

---

## Start & Stop

```powershell
.\start.ps1   # starts the server and bot
.\stop.ps1    # stops everything
```

---

## Telegram Bot Commands

Once running, control your server from Telegram:

| Command | What it does |
|---|---|
| `/status` | Is the server online? |
| `/players` | Who's connected |
| `/uptime` | How long it's been running |
| `/logs` | Recent server logs |
| `/backup` | Back up your world *(admin)* |
| `/restart` | Restart the server *(admin)* |
| `/update` | Update to the latest version *(admin)* |

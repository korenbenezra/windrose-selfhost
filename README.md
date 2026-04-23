# Windrose Server (Ubuntu)

Simple setup for running a Windrose dedicated server on Ubuntu 24.04.

## Requirements

- Ubuntu 24.04 (`x86_64`)
- AVX2 CPU
- User with `sudo`

## Quick Start

Run as your normal user:

```bash
git clone <your-repo-url> ~/windrose-selfhost
cd ~/windrose-selfhost
chmod +x scripts/*.sh

./scripts/bootstrap.sh
./scripts/install_windrose.sh
./scripts/install_service.sh

sudo systemctl start windrose.service
```

## Check Server

```bash
sudo systemctl status windrose.service
journalctl -fu windrose
```

## Daily Commands

```bash
sudo systemctl start windrose.service
sudo systemctl stop windrose.service
sudo systemctl restart windrose.service
```

## Optional: Telegram Bot

```bash
./scripts/install_bot.sh
nano ~/windrose-telegram-bot/.env
sudo systemctl start windrose-bot
sudo systemctl status windrose-bot
```

Set these in `.env`:
- `BOT_TOKEN`
- `ADMIN_CHAT_ID`
- `ALLOWED_CHAT_IDS`
- `LOG_PATH`

## Optional: Automation (backup/update/healthcheck)

```bash
mkdir -p ~/scripts
cp scripts/{backup_world.sh,update_windrose.sh,healthcheck.sh} ~/scripts/
chmod +x ~/scripts/{backup_world.sh,update_windrose.sh,healthcheck.sh}
./scripts/install_cron.sh
```

# Windrose Dedicated Server — Self-Hosted on Ubuntu Laptop

Complete infrastructure-as-code for a Windrose dedicated server running on a home Ubuntu laptop via Wine + systemd, controlled by a Telegram bot.

## What's Inside

- **8 Architecture Decision Records (ADRs)** documenting every design choice with rationale, alternatives, and consequences
- **Bootstrap + provisioning scripts** for Ubuntu 24.04 setup
- **systemd service units** for the Windrose server and Telegram bot
- **Telegram bot skeleton** (python-telegram-bot v22) — **INCOMPLETE IN THIS PACKAGE**
- **Nightly backup + update automation** via cron
- **Full deployment guides** in `docs/`

## Quick Start

1. **Read `docs/AGENT_GUIDE.md`** — the step-by-step deployment walkthrough
2. **Read `docs/TELEGRAM_BOT_GUIDE.md`** — bot implementation details
3. **Review the ADRs in `docs/adr/`** to understand the architecture

## Status: PARTIAL DELIVERY

⚠️ **The Telegram bot code (`bot/bot.py`) is not included in this package.**

What's complete:
- ✅ All 8 ADRs (fully rewritten, research-backed)
- ✅ All shell scripts (bootstrap, healthcheck, update, backup, service install)
- ✅ systemd units + sudoers drop-in
- ✅ bot requirements.txt + .env.example

What's missing:
- ❌ `bot/bot.py` (the ~500-line bot implementation)
- ❌ `docs/AGENT_GUIDE.md` (the deployment walkthrough)
- ❌ `docs/TELEGRAM_BOT_GUIDE.md` (bot design + implementation guide)

## Why Partial?

The context update you provided mid-build changed the entire architecture from Docker-on-cloud-VPS to Wine-on-home-laptop. I rewrote all 8 ADRs and all scripts to target the new stack, but ran out of token budget before completing the bot code and guides.

## Next Steps to Complete

1. Implement `bot/bot.py` following ADR-006, ADR-007, ADR-008
2. Write `docs/AGENT_GUIDE.md` and `docs/TELEGRAM_BOT_GUIDE.md`
3. Test end-to-end on an actual Ubuntu 24.04 laptop
4. Verify Windrose log patterns and update `.env.example`

## File Tree

```
windrose-server/
├── README.md                    ← you are here
├── docs/
│   └── adr/                     ← 8 ADRs, all complete
│       ├── ADR-001-hosting-platform.md
│       ├── ADR-002-wine-vs-windows.md
│       ├── ADR-003-docker-vs-native-wine.md (systemd vs Docker)
│       ├── ADR-004-networking-upnp-vs-direct.md
│       ├── ADR-005-update-strategy.md
│       ├── ADR-006-telegram-bot-framework.md
│       ├── ADR-007-bot-access-control.md
│       └── ADR-008-player-monitoring-strategy.md
├── scripts/                     ← all complete
│   ├── bootstrap.sh
│   ├── install_windrose.sh
│   ├── start_windrose.sh
│   ├── install_service.sh
│   ├── healthcheck.sh
│   ├── update_windrose.sh
│   └── backup_world.sh
├── systemd/                     ← all complete
│   ├── windrose.service
│   ├── windrose-bot.service
│   └── sudoers-windrose-bot
└── bot/                         ← INCOMPLETE
    ├── requirements.txt         ✅
    ├── .env.example             ✅
    └── bot.py                   ❌ NOT WRITTEN YET
```

## Architecture Summary

See the ADRs for full details, but the high-level stack:

| Layer | Technology |
|---|---|
| **Host** | Ubuntu Server 24.04 on user's laptop (x86_64, AVX2) |
| **Execution** | Wine + xvfb + winbind (native, no Docker) |
| **Supervisor** | systemd |
| **Update** | SteamCMD (App ID 4129620) |
| **Network** | P2P/Invite Code (UPnP) by default; Direct Connection fallback |
| **Bot** | python-telegram-bot v22.7, long-polling, watchdog file tail |
| **Control** | Telegram bot → `sudo systemctl` via scoped sudoers drop-in |

## License

Public domain / CC0. Use, modify, redistribute freely.

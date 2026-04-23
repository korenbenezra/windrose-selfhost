# ADR-006 — Telegram Bot Framework Selection

## Status
**Accepted**

## Date
2026-04-23

## Context

We need a Python library to build a Telegram bot that:

- Handles slash commands (`/start`, `/status`, `/players`, `/logs`, `/stop`, `/restart`, `/update`, `/uptime`, `/backup`)
- Handles inline-keyboard callback queries (button-driven control panel)
- Runs a background "player monitor" loop — tailing the Windrose log file (primary) with a polling fallback
- Sends push notifications to one admin chat and optionally to a set of friend chats (`NOTIFY_CHAT_IDS`)
- Runs as a long-lived systemd service alongside the Windrose systemd service on the same laptop
- Uses long polling (no webhook / no public HTTPS required)

`python-telegram-bot` is at **v22.7** as of March 2026. v22 is the current stable line; v21 is EOL for new feature work. v22 requires Python ≥ 3.10 (Ubuntu 24.04 ships 3.12 by default — no issue).

## Decision

**`python-telegram-bot v22.7+`** installed with the `[job-queue]` extra:

```
pip install "python-telegram-bot[job-queue]>=22.7,<23" python-dotenv watchdog
```

## Rationale

- **Built-in `JobQueue` (APScheduler-backed)** runs repeating tasks in the same event loop as the bot. We use it for the polling-mode player monitor fallback and for periodic health-state syncs.
- **`ApplicationBuilder` + `run_polling()`** is a clean single-entry-point pattern that drops straight into a `Type=simple` systemd unit.
- **`CallbackQueryHandler`** with string-matched `callback_data` cleanly expresses the control-panel tree (root → confirm → action → back).
- **`set_my_commands()`** registers slash commands in Telegram's `/` autocomplete menu — the polish of a "real" bot with one function call.
- **Active maintenance, deep examples repo** — the `echobot.py`, `inlinekeyboard.py`, and `timerbot.py` examples in the official repo map cleanly onto our command/callback/job structure.

## Alternatives Considered

| Library | Async | Job scheduler | Inline keyboards | Why Rejected / Chosen |
|---|---|---|---|---|
| **python-telegram-bot v22 (chosen)** | native asyncio | `JobQueue` built-in | Full | **Chosen** — most complete feature set |
| aiogram v3 | native asyncio | Manual (bring your own APScheduler) | Full | **Rejected** — job-queue wiring is DIY, we'd reinvent the player monitor glue |
| pyTelegramBotAPI | partial asyncio | None | Basic | **Rejected** — less complete |
| Raw `httpx` against Bot API | any | DIY | DIY | **Rejected** — reinventing a library |
| Telethon / Pyrogram (MTProto user libs) | native asyncio | DIY | yes but not primary | **Rejected** — aimed at user accounts, not Bot API; overpowered |

## Consequences

### Positive
- Single `pip install` + one systemd unit deploys the bot.
- `async def` handlers throughout; no callback hell.
- Handlers receive typed `Update` and `ContextTypes.DEFAULT_TYPE` — IDE autocomplete works.
- Stable API — patch releases (22.7 → 22.8 → …) are safe.

### Negative
- `run_polling()` blocks the main thread. Fine — the process is supervised by systemd. Adding a second async entry point (e.g., a Flask health endpoint) would require restructuring.
- Python 3.10+ requirement. Ubuntu 24.04 ships 3.12 → satisfied.
- One more dependency tree to maintenance — `pip install --upgrade` as part of the monthly ops checklist.

### Version-choice note
v21 → v22 is mostly non-breaking for public API users. The migration notes relevant to us:
- `Application.post_init` unchanged.
- `Update.effective_user` / `Update.effective_chat` unchanged.
- `CallbackQuery.edit_message_text()` unchanged.
- `telegram.constants.ParseMode` unchanged.
- Python minimum raised from 3.9 (v21) to 3.10 (v22).

## Implementation Guide

### Dependencies (`bot/requirements.txt`)
```
python-telegram-bot[job-queue]>=22.7,<23
python-dotenv>=1.0,<2
watchdog>=4.0,<5
```

### Bot entry skeleton
```python
import logging, os, asyncio
from telegram import BotCommand, Update
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.environ["BOT_TOKEN"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("windrose-bot")

async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start",   "🏴‍☠️ Open the control panel"),
        BotCommand("status",  "📊 Server status"),
        BotCommand("players", "👥 Players online"),
        BotCommand("logs",    "📋 Last 30 log lines"),
        BotCommand("uptime",  "⏱ Server uptime"),
        BotCommand("backup",  "💾 Take a world backup"),
        BotCommand("restart", "🔄 Restart the server"),
        BotCommand("stop",    "⏹ Stop the server"),
        BotCommand("update",  "⬆️ Update via SteamCMD"),
    ])

def build_app() -> Application:
    return (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

# Full handlers and JobQueue wiring live in bot.py.
```

## Code Examples

### JobQueue registration
```python
from datetime import timedelta

# Register a repeating background task:
app.job_queue.run_repeating(
    player_monitor_poll_job,            # async def (context) -> None
    interval=timedelta(seconds=30),
    first=timedelta(seconds=10),        # delay initial run to avoid false joins
    name="player_monitor_poll",
)
```

### Inline keyboard with confirmation flow
```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, proceed", callback_data=f"cb_confirmed_{action}"),
        InlineKeyboardButton("❌ Cancel",        callback_data="cb_panel"),
    ]])
```

## References

- python-telegram-bot docs: https://docs.python-telegram-bot.org/
- PyPI: https://pypi.org/project/python-telegram-bot/
- v22 release notes: https://github.com/python-telegram-bot/python-telegram-bot/releases
- Telegram Bot API: https://core.telegram.org/bots/api
- APScheduler (powers JobQueue): https://apscheduler.readthedocs.io/
- watchdog: https://pypi.org/project/watchdog/

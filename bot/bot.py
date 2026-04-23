"""
bot.py -- Windrose Telegram bot.

Commands: /start /status /players /logs /uptime /backup /restart /stop /update
Access control: @restricted decorator (ADR-007 -- numeric user-ID whitelist)
Player monitor: watchdog file-tail with journalctl-polling fallback (ADR-008)
Framework: python-telegram-bot v22.7 with JobQueue (ADR-006)
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import subprocess
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Config / environment
# ---------------------------------------------------------------------------
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID: int = int(os.environ["ADMIN_CHAT_ID"])

_extra = os.environ.get("ALLOWED_CHAT_IDS", "")
ALLOWED_IDS: set[int] = {ADMIN_CHAT_ID} | {
    int(x.strip()) for x in _extra.split(",") if x.strip()
}

NOTIFY_IDS: list[int] = [
    int(x.strip()) for x in os.environ.get("NOTIFY_CHAT_IDS", "").split(",")
    if x.strip()
] or [ADMIN_CHAT_ID]

LOG_PATH: str = os.environ.get(
    "LOG_PATH",
    str(Path.home() / "log" / "windrose.log"),
)
POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
PLAYER_MONITOR_MODE: str = os.environ.get("PLAYER_MONITOR_MODE", "auto")

LOG_PATTERN_CONNECT: str = os.environ.get(
    "LOG_PATTERN_CONNECT",
    r"Client connected.*?([A-Za-z0-9_\- ]{3,32})$",
)
LOG_PATTERN_DISCONNECT: str = os.environ.get(
    "LOG_PATTERN_DISCONNECT",
    r"Client disconnected.*?([A-Za-z0-9_\- ]{3,32})$",
)

STATE_PATH = Path(__file__).parent / "state.json"
BACKUP_SCRIPT = str(Path.home() / "scripts" / "backup_world.sh")
UPDATE_SCRIPT = str(Path.home() / "scripts" / "update_windrose.sh")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s -- %(message)s",
)
log = logging.getLogger("windrose-bot")

# ---------------------------------------------------------------------------
# Access control (ADR-007)
# ---------------------------------------------------------------------------
def restricted(func):
    """Silently drop updates from users not in ALLOWED_IDS (ADR-007).

    Silence (not an error reply) so probers cannot confirm the bot exists.
    Logs at WARNING for admin audit via journalctl -u windrose-bot.
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      *args, **kwargs):
        user = update.effective_user
        if user is None or user.id not in ALLOWED_IDS:
            log.warning(
                "Blocked access: user_id=%s username=%s kind=%s data=%s",
                getattr(user, "id", None),
                getattr(user, "username", None),
                "command" if update.message else
                "callback" if update.callback_query else "?",
                (update.message.text if update.message else
                 update.callback_query.data if update.callback_query else None),
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# ---------------------------------------------------------------------------
# Player state persistence (ADR-008)
# ---------------------------------------------------------------------------
_known_players: set[str] = set()


def _load_state() -> None:
    global _known_players
    if not STATE_PATH.exists():
        return
    try:
        data = json.loads(STATE_PATH.read_text())
        _known_players = set(data.get("known_players", []))
    except (json.JSONDecodeError, OSError):
        log.warning("state.json unreadable; starting with empty player list")


def _save_state() -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"known_players": list(_known_players)}))
    tmp.replace(STATE_PATH)  # atomic on POSIX (ADR-008)

# ---------------------------------------------------------------------------
# Notification broadcast (ADR-007)
# ---------------------------------------------------------------------------
async def broadcast(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    for chat_id in NOTIFY_IDS:
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=text, parse_mode=ParseMode.HTML
            )
        except Exception as exc:
            log.warning("broadcast failed for %s: %s", chat_id, exc)

# ---------------------------------------------------------------------------
# Log line parser -- shared by both monitor modes (ADR-008)
# ---------------------------------------------------------------------------
_pat_connect: re.Pattern | None = None
_pat_disconnect: re.Pattern | None = None


def _compile_patterns() -> None:
    global _pat_connect, _pat_disconnect
    _pat_connect = re.compile(LOG_PATTERN_CONNECT)
    _pat_disconnect = re.compile(LOG_PATTERN_DISCONNECT)


async def _handle_line(line: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _known_players
    assert _pat_connect and _pat_disconnect

    m = _pat_connect.search(line)
    if m:
        name = m.group(1).strip()
        if name and name not in _known_players:
            _known_players.add(name)
            _save_state()
            await broadcast(context, f"\U0001f7e2 <b>{html.escape(name)}</b> joined the server!")
        return

    m = _pat_disconnect.search(line)
    if m:
        name = m.group(1).strip()
        if name and name in _known_players:
            _known_players.discard(name)
            _save_state()
            await broadcast(context, f"\U0001f534 <b>{html.escape(name)}</b> left the server.")

# ---------------------------------------------------------------------------
# Player monitor -- watchdog tailer (ADR-008 Option A)
# ---------------------------------------------------------------------------
_watchdog_observer = None


def _start_watchdog(context: ContextTypes.DEFAULT_TYPE, loop: asyncio.AbstractEventLoop) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class _Tailer(FileSystemEventHandler):
        def __init__(self) -> None:
            p = Path(LOG_PATH)
            self._pos: int = p.stat().st_size if p.exists() else 0

        def on_modified(self, event) -> None:
            if event.src_path != LOG_PATH:
                return
            try:
                with open(LOG_PATH, errors="replace") as f:
                    f.seek(self._pos)
                    chunk = f.read()
                    self._pos = f.tell()
            except FileNotFoundError:
                self._pos = 0
                return
            for line in chunk.splitlines():
                asyncio.run_coroutine_threadsafe(_handle_line(line, context), loop)

    global _watchdog_observer
    handler = _Tailer()
    observer = Observer()
    observer.schedule(handler, path=str(Path(LOG_PATH).parent), recursive=False)
    observer.start()
    _watchdog_observer = observer
    log.info("Player monitor: watchdog active on %s", LOG_PATH)

# ---------------------------------------------------------------------------
# Player monitor -- journalctl polling fallback (ADR-008 Option B)
# ---------------------------------------------------------------------------
async def _poll_journal_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    window = POLL_INTERVAL + 10  # slight overlap to avoid gaps
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["journalctl", "-u", "windrose.service",
             "--since", f"{window} seconds ago",
             "--no-pager", "-q"],
            capture_output=True, text=True, timeout=10,
        )
        for line in (result.stdout + result.stderr).splitlines():
            await _handle_line(line, context)
    except Exception as exc:
        log.warning("journalctl poll error: %s", exc)

# ---------------------------------------------------------------------------
# systemd helpers
# ---------------------------------------------------------------------------
def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo", "-n", "systemctl", *args, "windrose.service"],
        capture_output=True, text=True,
    )


def _service_active() -> bool:
    return _systemctl("is-active").returncode == 0


def _service_uptime() -> str:
    r = subprocess.run(
        ["systemctl", "show", "windrose.service", "-p", "ActiveEnterTimestamp"],
        capture_output=True, text=True,
    )
    line = r.stdout.strip()
    return line.split("=", 1)[1].strip() if "=" in line else "unknown"


def _last_log_lines(n: int = 30) -> str:
    r = subprocess.run(
        ["journalctl", "-u", "windrose.service", "-n", str(n), "--no-pager", "-q"],
        capture_output=True, text=True,
    )
    return (r.stdout + r.stderr).strip() or "(no log output)"

# ---------------------------------------------------------------------------
# Keyboard builders (ADR-007 confirmation flow for destructive actions)
# ---------------------------------------------------------------------------
def _main_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001f4ca Status",  callback_data="cb_status"),
            InlineKeyboardButton("\U0001f465 Players", callback_data="cb_players"),
        ],
        [
            InlineKeyboardButton("\U0001f4cb Logs",    callback_data="cb_logs"),
            InlineKeyboardButton("⏱ Uptime",      callback_data="cb_uptime"),
        ],
        [
            InlineKeyboardButton("\U0001f4be Backup",  callback_data="cb_backup_ask"),
            InlineKeyboardButton("\U0001f504 Restart", callback_data="cb_restart_ask"),
        ],
        [
            InlineKeyboardButton("⏹ Stop",        callback_data="cb_stop_ask"),
            InlineKeyboardButton("⬆ Update",      callback_data="cb_update_ask"),
        ],
    ])


def _confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, proceed", callback_data=f"cb_confirmed_{action}"),
        InlineKeyboardButton("❌ Cancel",       callback_data="cb_panel"),
    ]])

# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Windrose Server Control</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=_main_panel(),
    )


@restricted
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = "active" if _service_active() else "inactive/failed"
    await update.message.reply_text(
        f"<b>Server status:</b> {state}", parse_mode=ParseMode.HTML
    )


@restricted
async def cmd_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _known_players:
        names = "\n".join(f"  • {html.escape(p)}" for p in sorted(_known_players))
        text = f"<b>Players online ({len(_known_players)}):</b>\n{names}"
    else:
        text = "<b>No players currently online.</b>"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


@restricted
async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = _last_log_lines(30)
    await update.message.reply_text(
        f"<pre>{html.escape(lines[-3500:])}</pre>",
        parse_mode=ParseMode.HTML,
    )


@restricted
async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    since = _service_uptime()
    await update.message.reply_text(
        f"<b>Server running since:</b> {html.escape(since)}", parse_mode=ParseMode.HTML
    )


@restricted
async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Start a world backup now?",
        reply_markup=_confirm_keyboard("backup"),
    )


@restricted
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Restart the server? Players will be briefly disconnected.",
        reply_markup=_confirm_keyboard("restart"),
    )


@restricted
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Stop</b> the server? All players will be disconnected.",
        parse_mode=ParseMode.HTML,
        reply_markup=_confirm_keyboard("stop"),
    )


@restricted
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Run a SteamCMD update? Server will stop, update, then restart.",
        reply_markup=_confirm_keyboard("update"),
    )

# ---------------------------------------------------------------------------
# Inline-keyboard callback handler (entire handler guarded by @restricted)
# ---------------------------------------------------------------------------
@restricted
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data: str = query.data

    async def edit(text: str, markup=None) -> None:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    if data == "cb_panel":
        await edit("<b>Windrose Server Control</b>", _main_panel())

    elif data == "cb_status":
        state = "active" if _service_active() else "inactive/failed"
        await edit(f"<b>Server status:</b> {state}", _main_panel())

    elif data == "cb_players":
        if _known_players:
            names = "\n".join(f"  • {html.escape(p)}" for p in sorted(_known_players))
            text = f"<b>Players online ({len(_known_players)}):</b>\n{names}"
        else:
            text = "<b>No players currently online.</b>"
        await edit(text, _main_panel())

    elif data == "cb_logs":
        lines = _last_log_lines(20)
        await edit(f"<pre>{html.escape(lines[-3000:])}</pre>", _main_panel())

    elif data == "cb_uptime":
        since = _service_uptime()
        await edit(f"<b>Running since:</b> {html.escape(since)}", _main_panel())

    elif data == "cb_backup_ask":
        await edit("Start a world backup now?", _confirm_keyboard("backup"))

    elif data == "cb_restart_ask":
        await edit(
            "Restart the server? Players will be briefly disconnected.",
            _confirm_keyboard("restart"),
        )

    elif data == "cb_stop_ask":
        await edit(
            "<b>Stop</b> the server? All players will be disconnected.",
            _confirm_keyboard("stop"),
        )

    elif data == "cb_update_ask":
        await edit(
            "Run SteamCMD update? Server will stop, update, then restart.",
            _confirm_keyboard("update"),
        )

    elif data == "cb_confirmed_backup":
        await edit("Backup started...")
        proc = await asyncio.to_thread(
            subprocess.run, ["bash", BACKUP_SCRIPT],
            capture_output=True, text=True, timeout=300,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        await edit(f"<b>Backup:</b> {result}", _main_panel())

    elif data == "cb_confirmed_restart":
        await edit("Restarting...")
        _systemctl("restart")
        await edit("<b>Restart issued.</b> Server active in ~30s.", _main_panel())

    elif data == "cb_confirmed_stop":
        await edit("Stopping...")
        _systemctl("stop")
        await edit("<b>Server stopped.</b>", _main_panel())

    elif data == "cb_confirmed_update":
        await edit("Update started (takes a few minutes)...")
        proc = await asyncio.to_thread(
            subprocess.run, ["bash", UPDATE_SCRIPT],
            capture_output=True, text=True, timeout=600,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        await edit(f"<b>Update:</b> {result}", _main_panel())

# ---------------------------------------------------------------------------
# Startup: register commands, load state, wire player monitor (ADR-006, ADR-008)
# ---------------------------------------------------------------------------
async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start",   "Open the control panel"),
        BotCommand("status",  "Server status"),
        BotCommand("players", "Players online"),
        BotCommand("logs",    "Last 30 log lines"),
        BotCommand("uptime",  "Server uptime"),
        BotCommand("backup",  "Take a world backup"),
        BotCommand("restart", "Restart the server"),
        BotCommand("stop",    "Stop the server"),
        BotCommand("update",  "Update via SteamCMD"),
    ])

    _load_state()
    _compile_patterns()

    loop = asyncio.get_event_loop()
    mode = PLAYER_MONITOR_MODE
    log_path = Path(LOG_PATH)
    log_exists = log_path.exists()
    log_fresh = log_exists and (time.time() - log_path.stat().st_mtime) < 600

    if mode == "watchdog" or (mode == "auto" and log_fresh):
        _start_watchdog(application, loop)
    elif mode == "off":
        log.info("Player monitor: disabled (PLAYER_MONITOR_MODE=off)")
    else:
        # polling fallback: log missing/stale, or forced polling mode
        log.info(
            "Player monitor: journalctl polling (mode=%s, log_exists=%s, log_fresh=%s)",
            mode, log_exists, log_fresh,
        )
        application.job_queue.run_repeating(
            lambda ctx: _poll_journal_job(ctx),
            interval=timedelta(seconds=POLL_INTERVAL),
            first=timedelta(seconds=10),
            name="player_monitor_poll",
        )


def build_app() -> Application:
    return ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()


def main() -> None:
    app = build_app()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("players", cmd_players))
    app.add_handler(CommandHandler("logs",    cmd_logs))
    app.add_handler(CommandHandler("uptime",  cmd_uptime))
    app.add_handler(CommandHandler("backup",  cmd_backup))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("stop",    cmd_stop))
    app.add_handler(CommandHandler("update",  cmd_update))
    app.add_handler(CallbackQueryHandler(button_handler))
    log.info("Windrose bot starting (long polling)")
    app.run_polling()


if __name__ == "__main__":
    main()

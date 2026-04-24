"""
bot.py -- Windrose Telegram bot (Phase 2).

Commands: /start /status /players /logs /uptime /backup /restart /stop /update
          /history /playtime /notify
Access control: @restricted decorator — two-tier (admin / notify_only)
Player monitor: watchdog file-tail with journalctl-polling fallback (ADR-008)
Framework: python-telegram-bot v22.7 with JobQueue (ADR-006)
"""
from __future__ import annotations

import asyncio
import datetime
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
from typing import Any

import psutil
from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import InvalidToken
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Config / environment
# ---------------------------------------------------------------------------
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

BOT_TOKEN: str = os.environ["BOT_TOKEN"]

# Support both legacy ADMIN_CHAT_ID and new ADMIN_IDS
_admin_ids_raw = os.environ.get("ADMIN_IDS", os.environ.get("ADMIN_CHAT_ID", ""))
ADMIN_IDS: set[int] = {int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip()}

NOTIFY_IDS: list[int] = [
    int(x.strip()) for x in os.environ.get("NOTIFY_CHAT_IDS", "").split(",")
    if x.strip()
] or list(ADMIN_IDS)

CONTAINER_NAME: str = os.environ.get("CONTAINER_NAME", "windrose-server")
SERVER_FILES_DIR: str = os.environ.get(
    "SERVER_FILES_DIR", str(Path.home() / "windrose" / "server-files")
)
SERVER_DESC_PATH = Path(SERVER_FILES_DIR) / "ServerDescription.json"

LOG_PATH: str = os.environ.get(
    "LOG_PATH", str(Path.home() / "log" / "windrose.log"),
)
POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
PLAYER_MONITOR_MODE: str = os.environ.get("PLAYER_MONITOR_MODE", "auto")

LOG_PATTERN_CONNECT: str = os.environ.get(
    "LOG_PATTERN_CONNECT", r"Client connected.*?([A-Za-z0-9_\- ]{3,32})$",
)
LOG_PATTERN_DISCONNECT: str = os.environ.get(
    "LOG_PATTERN_DISCONNECT", r"Client disconnected.*?([A-Za-z0-9_\- ]{3,32})$",
)

CPU_ALERT_THRESHOLD: float = float(os.environ.get("CPU_ALERT_THRESHOLD", "85"))
RAM_ALERT_THRESHOLD: float = float(os.environ.get("RAM_ALERT_THRESHOLD", "90"))
IDLE_TIMEOUT_MINUTES: int = int(os.environ.get("IDLE_TIMEOUT_MINUTES", "60"))

STATE_PATH = Path(__file__).parent / "state.json"
_SCRIPTS_DIR = Path(os.environ.get("WINDROSE_SCRIPTS_DIR", r"D:\repositories\windrose-selfhost\scripts"))
BACKUP_SCRIPT = str(_SCRIPTS_DIR / "backup_world.ps1")
UPDATE_SCRIPT = str(_SCRIPTS_DIR / "update_windrose.ps1")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s -- %(message)s",
)
log = logging.getLogger("windrose-bot")

# ---------------------------------------------------------------------------
# Runtime config validation
# ---------------------------------------------------------------------------
def _validate_runtime_config() -> None:
    token = BOT_TOKEN.strip()
    if not token or token == "your-telegram-bot-token-here":
        raise SystemExit(
            "Invalid BOT_TOKEN in .env (placeholder value detected). "
            "Set BOT_TOKEN to the real token from BotFather."
        )
    if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{20,}", token):
        raise SystemExit(
            "Invalid BOT_TOKEN format in .env. Expected '<bot_id>:<secret>'."
        )

# ---------------------------------------------------------------------------
# State persistence — full Phase 2 schema (ADR-008, ADR-009)
# ---------------------------------------------------------------------------
_STATE: dict[str, Any] = {
    "known_players": [],
    "users": {"admins": [], "notify_only": []},
    "notify_waitlist": [],
    "sessions_active": {},
    "sessions_history": [],
    "playtime_totals": {},
    "schedule_enabled": False,
    "schedule_time": "03:00",
    "idle_warning_sent": False,
    "idle_empty_since": None,
}


def _load_state() -> None:
    if not STATE_PATH.exists():
        return
    try:
        saved = json.loads(STATE_PATH.read_text())
        for key in _STATE:
            if key in saved:
                _STATE[key] = saved[key]
    except (json.JSONDecodeError, OSError):
        log.warning("state.json unreadable; starting with defaults")


def _save_state() -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_STATE, indent=2, default=str))
    tmp.replace(STATE_PATH)


def _known_players() -> set[str]:
    return set(_STATE["known_players"])


def _set_known_players(players: set[str]) -> None:
    _STATE["known_players"] = list(players)
    _save_state()

# ---------------------------------------------------------------------------
# Access control — two-tier (ADR-007, ADR-009)
# ---------------------------------------------------------------------------
def _all_admins() -> set[int]:
    return ADMIN_IDS | {int(x) for x in _STATE["users"]["admins"]}


def _all_notify_only() -> set[int]:
    return {int(x) for x in _STATE["users"]["notify_only"]}


def _is_admin(user_id: int) -> bool:
    return user_id in _all_admins()


def _is_allowed(user_id: int) -> bool:
    return _is_admin(user_id) or user_id in _all_notify_only()


def restricted(func=None, *, admin_only: bool = False):
    """Decorator: drop updates from unknown users; optionally require admin tier."""
    def decorator(f):
        @wraps(f)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = update.effective_user
            uid = getattr(user, "id", None)
            if uid is None or not _is_allowed(uid):
                log.warning(
                    "Blocked access: user_id=%s username=%s",
                    uid, getattr(user, "username", None),
                )
                return
            if admin_only and not _is_admin(uid):
                if update.callback_query:
                    await update.callback_query.answer("Admin access required.", show_alert=True)
                elif update.message:
                    await update.message.reply_text("Admin access required.")
                return
            return await f(update, context, *args, **kwargs)
        return wrapped
    if func is not None:
        return decorator(func)
    return decorator

# ---------------------------------------------------------------------------
# Notification broadcast
# ---------------------------------------------------------------------------
async def broadcast(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    targets = set(NOTIFY_IDS) | _all_admins()
    for chat_id in targets:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        except Exception as exc:
            log.warning("broadcast failed for %s: %s", chat_id, exc)


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    for chat_id in _all_admins():
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        except Exception as exc:
            log.warning("admin notify failed for %s: %s", chat_id, exc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + "] " + str(round(pct)) + "%"


def fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

# ---------------------------------------------------------------------------
# Windows service helpers (replaces Docker/container helpers)
# ---------------------------------------------------------------------------
_SVC_NAME = "Windrose"


def _sc(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sc.exe", *args], capture_output=True, text=True)


def _container_running() -> bool:
    r = _sc("query", _SVC_NAME)
    return "RUNNING" in r.stdout


def _container_status() -> str:
    r = _sc("query", _SVC_NAME)
    for line in r.stdout.splitlines():
        if "STATE" in line:
            parts = line.split()
            if len(parts) >= 4:
                return parts[3].lower()
    return "unknown"


def _container_uptime() -> str:
    for proc in psutil.process_iter(["name", "create_time"]):
        try:
            if "WindroseServer" in (proc.info["name"] or ""):
                started = datetime.datetime.fromtimestamp(
                    proc.info["create_time"], tz=datetime.timezone.utc
                )
                delta = datetime.datetime.now(datetime.timezone.utc) - started
                total = int(delta.total_seconds())
                h, rem = divmod(total, 3600)
                m, s = divmod(rem, 60)
                return f"{h}h {m:02d}m {s:02d}s"
        except Exception:
            pass
    return "unknown"


def _docker_stop() -> None:
    _sc("stop", _SVC_NAME)


def _docker_start() -> None:
    _sc("start", _SVC_NAME)


def _docker_restart() -> None:
    _sc("stop", _SVC_NAME)
    time.sleep(8)
    _sc("start", _SVC_NAME)


def _last_log_lines(n: int = 30) -> str:
    try:
        with open(LOG_PATH, errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).strip() or "(no log output)"
    except Exception as exc:
        return f"(error reading log: {exc})"

# ---------------------------------------------------------------------------
# Log line parser
# ---------------------------------------------------------------------------
_pat_connect: re.Pattern | None = None
_pat_disconnect: re.Pattern | None = None


def _compile_patterns() -> None:
    global _pat_connect, _pat_disconnect
    _pat_connect = re.compile(LOG_PATTERN_CONNECT)
    _pat_disconnect = re.compile(LOG_PATTERN_DISCONNECT)


async def _handle_line(line: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert _pat_connect and _pat_disconnect
    players = _known_players()

    m = _pat_connect.search(line)
    if m:
        name = m.group(1).strip()
        if name and name not in players:
            players.add(name)
            _set_known_players(players)
            _record_join(name)
            await broadcast(context, f"\U0001f7e2 <b>{html.escape(name)}</b> joined the server!")
            # reset idle tracking
            _STATE["idle_empty_since"] = None
            _STATE["idle_warning_sent"] = False
            _save_state()
            # notify waitlist
            await _flush_waitlist(context)
        return

    m = _pat_disconnect.search(line)
    if m:
        name = m.group(1).strip()
        if name and name in players:
            players.discard(name)
            _set_known_players(players)
            _record_leave(name)
            await broadcast(context, f"\U0001f534 <b>{html.escape(name)}</b> left the server.")

# ---------------------------------------------------------------------------
# Session history tracking (Feature 5)
# ---------------------------------------------------------------------------
def _record_join(name: str) -> None:
    _STATE["sessions_active"][name] = _now_iso()
    _save_state()


def _record_leave(name: str) -> None:
    joined_str = _STATE["sessions_active"].pop(name, None)
    if joined_str:
        try:
            joined_dt = datetime.datetime.fromisoformat(joined_str.replace("Z", "+00:00"))
            left_dt = datetime.datetime.now(datetime.timezone.utc)
            duration_s = int((left_dt - joined_dt).total_seconds())
        except Exception:
            duration_s = 0
        _STATE["sessions_history"].append({
            "name": name,
            "joined": joined_str,
            "left": _now_iso(),
            "duration_s": duration_s,
        })
        # cap history at 500 entries
        _STATE["sessions_history"] = _STATE["sessions_history"][-500:]
        _STATE["playtime_totals"][name] = (
            _STATE["playtime_totals"].get(name, 0) + duration_s
        )
    _save_state()

# ---------------------------------------------------------------------------
# Notify waitlist (Feature 7)
# ---------------------------------------------------------------------------
async def _flush_waitlist(context: ContextTypes.DEFAULT_TYPE) -> None:
    waitlist: list[int] = _STATE.get("notify_waitlist", [])
    if not waitlist:
        return
    _STATE["notify_waitlist"] = []
    _save_state()
    for chat_id in waitlist:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="The Windrose server is now online! Use your invite code to join.",
            )
        except Exception as exc:
            log.warning("waitlist notify failed for %s: %s", chat_id, exc)

# ---------------------------------------------------------------------------
# Player monitor — watchdog tailer (ADR-008 Option A)
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


async def _poll_journal_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    # On Windows: tail LOG_PATH for lines written in the last POLL_INTERVAL seconds
    try:
        if not Path(LOG_PATH).exists():
            return
        with open(LOG_PATH, errors="replace") as f:
            lines = f.readlines()
        for line in lines[-200:]:
            await _handle_line(line, context)
    except Exception as exc:
        log.warning("log poll error: %s", exc)

# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------

# CPU alert state
_cpu_high_count = 0

async def _resource_alert_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    global _cpu_high_count
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory().percent

    if cpu > CPU_ALERT_THRESHOLD:
        _cpu_high_count += 1
        if _cpu_high_count >= 3:
            _cpu_high_count = 0
            await notify_admins(
                context,
                f"⚠️ Warning: CPU has been above {CPU_ALERT_THRESHOLD:.0f}% for 3 minutes. "
                f"Current: {cpu:.0f}%",
            )
    else:
        _cpu_high_count = 0

    if ram > RAM_ALERT_THRESHOLD:
        await notify_admins(
            context,
            f"⚠️ Warning: RAM usage at {ram:.0f}%. Consider restarting the server.",
        )


_IDLE_CHECK_INTERVAL = 300  # 5 minutes


async def _idle_autostop_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _container_running():
        _STATE["idle_empty_since"] = None
        _STATE["idle_warning_sent"] = False
        _save_state()
        return

    active = _STATE.get("sessions_active", {})
    now = datetime.datetime.now(datetime.timezone.utc)

    if active:
        _STATE["idle_empty_since"] = None
        _STATE["idle_warning_sent"] = False
        _save_state()
        return

    idle_since_str = _STATE.get("idle_empty_since")
    if idle_since_str is None:
        _STATE["idle_empty_since"] = _now_iso()
        _save_state()
        return

    try:
        idle_since = datetime.datetime.fromisoformat(idle_since_str.replace("Z", "+00:00"))
    except Exception:
        _STATE["idle_empty_since"] = _now_iso()
        _save_state()
        return

    idle_minutes = (now - idle_since).total_seconds() / 60
    timeout = IDLE_TIMEOUT_MINUTES

    if idle_minutes >= timeout:
        _docker_stop()
        _STATE["idle_empty_since"] = None
        _STATE["idle_warning_sent"] = False
        _save_state()
        await notify_admins(
            context,
            f"🛑 Server auto-stopped after {timeout} minutes of inactivity. "
            "Use /start to bring it back.",
        )
    elif idle_minutes >= timeout - 5 and not _STATE.get("idle_warning_sent"):
        _STATE["idle_warning_sent"] = True
        _save_state()
        await notify_admins(
            context,
            f"⏳ Server has been idle for {int(idle_minutes)} minutes. "
            "Auto-stopping in 5 minutes unless someone joins.",
        )


# Scheduled restart job handle
_scheduled_restart_job = None


async def _scheduled_restart_job_fn(context: ContextTypes.DEFAULT_TYPE) -> None:
    await notify_admins(context, "🔄 Scheduled restart starting...")
    _docker_stop()
    await asyncio.sleep(5)
    proc = await asyncio.to_thread(
        subprocess.run, ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", UPDATE_SCRIPT],
        capture_output=True, text=True, timeout=600,
    )
    _docker_start()
    result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    await notify_admins(context, f"✅ Scheduled restart complete. Update: {result}")
    await _flush_waitlist(context)


def _register_scheduled_restart(app: Application) -> None:
    global _scheduled_restart_job
    if not _STATE.get("schedule_enabled"):
        return
    schedule_time_str = _STATE.get("schedule_time", "03:00")
    try:
        h, m = map(int, schedule_time_str.split(":"))
        t = datetime.time(h, m, tzinfo=datetime.timezone.utc)
    except Exception:
        log.warning("Invalid schedule_time in state: %s", schedule_time_str)
        return
    _scheduled_restart_job = app.job_queue.run_daily(
        _scheduled_restart_job_fn,
        time=t,
        name="scheduled_restart",
    )
    log.info("Scheduled restart registered at %s UTC", schedule_time_str)


def _cancel_scheduled_restart() -> None:
    global _scheduled_restart_job
    if _scheduled_restart_job:
        _scheduled_restart_job.schedule_removal()
        _scheduled_restart_job = None

# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------
def _main_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Status",      callback_data="cb_status"),
            InlineKeyboardButton("👥 Players",     callback_data="cb_players"),
        ],
        [
            InlineKeyboardButton("📋 Logs",        callback_data="cb_logs"),
            InlineKeyboardButton("⏱ Uptime",       callback_data="cb_uptime"),
        ],
        [
            InlineKeyboardButton("💾 Backup",      callback_data="cb_backup_ask"),
            InlineKeyboardButton("🔄 Restart",     callback_data="cb_restart_ask"),
        ],
        [
            InlineKeyboardButton("⏹ Stop",         callback_data="cb_stop_ask"),
            InlineKeyboardButton("⬆ Update",       callback_data="cb_update_ask"),
        ],
        [
            InlineKeyboardButton("🖥 Sys Info",    callback_data="v2_sysinfo"),
            InlineKeyboardButton("👤 Users",        callback_data="v2_users_menu"),
        ],
        [
            InlineKeyboardButton("⚙️ Server Settings", callback_data="v2_settings_menu"),
            InlineKeyboardButton("📅 Schedule",    callback_data="v2_schedule_menu"),
        ],
        [
            InlineKeyboardButton("🔔 Notify Me",   callback_data="v2_notify_sub"),
        ],
    ])


def _confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, proceed", callback_data=f"cb_confirmed_{action}"),
        InlineKeyboardButton("❌ Cancel",       callback_data="cb_panel"),
    ]])


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("« Back", callback_data="cb_panel"),
    ]])

# ---------------------------------------------------------------------------
# Sys info builder (Feature 3)
# ---------------------------------------------------------------------------
def _build_sysinfo_text() -> str:
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    temp_str = "N/A"
    temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if temp_path.exists():
        try:
            temp_str = f"{int(temp_path.read_text().strip()) / 1000:.1f}°C"
        except Exception:
            pass

    status = _container_status().capitalize()
    uptime = _container_uptime()

    return (
        "<b>System Info</b>\n\n"
        f"CPU:    {make_bar(cpu)}\n"
        f"RAM:    {make_bar(ram.percent)}\n"
        f"Disk:   {make_bar(disk.percent)}\n"
        f"Temp:   {temp_str}\n"
        f"Container: {status}\n"
        f"Uptime: {uptime}"
    )


def _sysinfo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="v2_sysinfo")],
        [InlineKeyboardButton("« Back",    callback_data="cb_panel")],
    ])

# ---------------------------------------------------------------------------
# Server settings sub-menu keyboards/helpers (Feature 1)
# ---------------------------------------------------------------------------
def _settings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 View Invite Code",  callback_data="v2_settings_invite")],
        [InlineKeyboardButton("🔒 Change Password",   callback_data="v2_settings_changepw")],
        [InlineKeyboardButton("🔓 Remove Password",   callback_data="v2_settings_removepw_ask")],
        [InlineKeyboardButton("« Back",               callback_data="cb_panel")],
    ])


def _read_server_desc() -> dict:
    try:
        return json.loads(SERVER_DESC_PATH.read_text())
    except Exception:
        return {}


def _write_server_desc(data: dict) -> None:
    tmp = SERVER_DESC_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(SERVER_DESC_PATH)

# ---------------------------------------------------------------------------
# Users sub-menu keyboards (Feature 2)
# ---------------------------------------------------------------------------
def _users_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Users",       callback_data="v2_users_list")],
        [InlineKeyboardButton("➕ Add Admin",         callback_data="v2_users_add_admin")],
        [InlineKeyboardButton("➕ Add Notify User",  callback_data="v2_users_add_notify")],
        [InlineKeyboardButton("➖ Remove User",       callback_data="v2_users_remove")],
        [InlineKeyboardButton("« Back",              callback_data="cb_panel")],
    ])

# ---------------------------------------------------------------------------
# Schedule sub-menu keyboards (Feature 8)
# ---------------------------------------------------------------------------
def _schedule_menu_keyboard() -> InlineKeyboardMarkup:
    enabled = _STATE.get("schedule_enabled", False)
    toggle_label = "✅ Enabled — Disable" if enabled else "❌ Disabled — Enable"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 View Schedule",    callback_data="v2_schedule_view")],
        [InlineKeyboardButton("⏰ Set Time",          callback_data="v2_schedule_set")],
        [InlineKeyboardButton(toggle_label,           callback_data="v2_schedule_toggle")],
        [InlineKeyboardButton("« Back",              callback_data="cb_panel")],
    ])

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
    state = "running" if _container_running() else _container_status()
    await update.message.reply_text(f"<b>Server status:</b> {state}", parse_mode=ParseMode.HTML)


@restricted
async def cmd_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    players = _known_players()
    if players:
        names = "\n".join(f"  • {html.escape(p)}" for p in sorted(players))
        text = f"<b>Players online ({len(players)}):</b>\n{names}"
    else:
        text = "<b>No players currently online.</b>"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


@restricted
async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = _last_log_lines(30)
    await update.message.reply_text(
        f"<pre>{html.escape(lines[-3500:])}</pre>", parse_mode=ParseMode.HTML,
    )


@restricted
async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uptime = _container_uptime()
    await update.message.reply_text(f"<b>Container uptime:</b> {uptime}", parse_mode=ParseMode.HTML)


@restricted(admin_only=True)
async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Start a world backup now?", reply_markup=_confirm_keyboard("backup"))


@restricted(admin_only=True)
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Restart the server? Players will be briefly disconnected.",
        reply_markup=_confirm_keyboard("restart"),
    )


@restricted(admin_only=True)
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Stop</b> the server? All players will be disconnected.",
        parse_mode=ParseMode.HTML,
        reply_markup=_confirm_keyboard("stop"),
    )


@restricted(admin_only=True)
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Run a SteamCMD update? Server will stop, update, then restart.",
        reply_markup=_confirm_keyboard("update"),
    )


@restricted
async def cmd_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if _container_running():
        await update.message.reply_text("Server is already online!")
        return
    waitlist: list = _STATE["notify_waitlist"]
    if uid not in waitlist:
        waitlist.append(uid)
        _save_state()
    await update.message.reply_text(
        "Got it! You'll be notified when the server comes online."
    )


@restricted
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history = _STATE.get("sessions_history", [])[-20:]
    if not history:
        await update.message.reply_text("No session history yet.")
        return
    rows = ["<b>Session History</b>", "<pre>"]
    rows.append(f"{'Player':<20} {'Joined (UTC)':<20} {'Duration'}")
    rows.append("-" * 52)
    for entry in reversed(history):
        name = entry.get("name", "?")[:18]
        joined = entry.get("joined", "")[:16].replace("T", " ")
        dur = fmt_duration(entry.get("duration_s", 0))
        rows.append(f"{name:<20} {joined:<20} {dur}")
    rows.append("</pre>")
    await update.message.reply_text("\n".join(rows), parse_mode=ParseMode.HTML)


@restricted
async def cmd_playtime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    totals: dict = _STATE.get("playtime_totals", {})
    if not totals:
        await update.message.reply_text("No playtime data yet.")
        return
    sorted_players = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    lines = ["<b>Playtime Leaderboard</b>"]
    for i, (name, secs) in enumerate(sorted_players, 1):
        lines.append(f"{i}. {html.escape(name)} — {fmt_duration(secs)}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

# ---------------------------------------------------------------------------
# Message handler for multi-step flows (password, user ID, schedule time)
# ---------------------------------------------------------------------------
@restricted
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    waiting = context.user_data.get("waiting_for")
    if not waiting:
        return

    text = (update.message.text or "").strip()
    context.user_data.pop("waiting_for", None)

    if waiting == "new_password":
        if not _is_admin(update.effective_user.id):
            return
        if _container_running():
            await update.message.reply_text(
                "⚠️ Server must be stopped before changing config. Stop it first.",
                reply_markup=_back_keyboard(),
            )
            return
        desc = _read_server_desc()
        desc["ServerPassword"] = text
        _write_server_desc(desc)
        await update.message.reply_text("✅ Password updated.", reply_markup=_back_keyboard())

    elif waiting == "add_admin_id":
        if not _is_admin(update.effective_user.id):
            return
        try:
            new_id = int(text)
        except ValueError:
            await update.message.reply_text("Invalid ID. Must be a numeric Telegram user ID.")
            return
        admins: list = _STATE["users"]["admins"]
        if new_id not in admins:
            admins.append(new_id)
            _save_state()
        await update.message.reply_text(f"✅ Added {new_id} as admin.", reply_markup=_back_keyboard())

    elif waiting == "add_notify_id":
        if not _is_admin(update.effective_user.id):
            return
        try:
            new_id = int(text)
        except ValueError:
            await update.message.reply_text("Invalid ID. Must be a numeric Telegram user ID.")
            return
        notify_only: list = _STATE["users"]["notify_only"]
        if new_id not in notify_only:
            notify_only.append(new_id)
            _save_state()
        await update.message.reply_text(f"✅ Added {new_id} as notify-only user.", reply_markup=_back_keyboard())

    elif waiting == "remove_user_id":
        if not _is_admin(update.effective_user.id):
            return
        try:
            rm_id = int(text)
        except ValueError:
            await update.message.reply_text("Invalid ID. Must be a numeric Telegram user ID.")
            return
        removed = False
        for tier in ("admins", "notify_only"):
            lst: list = _STATE["users"][tier]
            if rm_id in lst:
                lst.remove(rm_id)
                removed = True
        if removed:
            _save_state()
            await update.message.reply_text(f"✅ Removed user {rm_id}.", reply_markup=_back_keyboard())
        else:
            await update.message.reply_text(f"User {rm_id} not found in any tier.", reply_markup=_back_keyboard())

    elif waiting == "schedule_time":
        if not _is_admin(update.effective_user.id):
            return
        if not re.fullmatch(r"\d{1,2}:\d{2}", text):
            await update.message.reply_text("Invalid format. Use HH:MM (e.g. 03:00).")
            return
        try:
            h, m = map(int, text.split(":"))
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except ValueError:
            await update.message.reply_text("Invalid time. Use HH:MM between 00:00 and 23:59.")
            return
        _STATE["schedule_time"] = f"{h:02d}:{m:02d}"
        _save_state()
        app = context.application
        _cancel_scheduled_restart()
        if _STATE.get("schedule_enabled"):
            _register_scheduled_restart(app)
        await update.message.reply_text(
            f"✅ Schedule time set to {_STATE['schedule_time']} UTC.",
            reply_markup=_back_keyboard(),
        )

# ---------------------------------------------------------------------------
# Inline-keyboard callback handler
# ---------------------------------------------------------------------------
@restricted
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data: str = query.data
    uid = update.effective_user.id

    def is_admin() -> bool:
        return _is_admin(uid)

    async def edit(text: str, markup=None) -> None:
        await query.answer()
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    async def admin_required() -> bool:
        if not is_admin():
            await query.answer("Admin access required.", show_alert=True)
            return True
        return False

    # ---- main panel ----
    if data == "cb_panel":
        await edit("<b>Windrose Server Control</b>", _main_panel())

    elif data == "cb_status":
        state = "running" if _container_running() else _container_status()
        await edit(f"<b>Server status:</b> {state}", _main_panel())

    elif data == "cb_players":
        players = _known_players()
        if players:
            names = "\n".join(f"  • {html.escape(p)}" for p in sorted(players))
            text = f"<b>Players online ({len(players)}):</b>\n{names}"
        else:
            text = "<b>No players currently online.</b>"
        await edit(text, _main_panel())

    elif data == "cb_logs":
        lines = _last_log_lines(20)
        await edit(f"<pre>{html.escape(lines[-3000:])}</pre>", _main_panel())

    elif data == "cb_uptime":
        uptime = _container_uptime()
        await edit(f"<b>Container uptime:</b> {uptime}", _main_panel())

    # ---- confirm dialogs ----
    elif data == "cb_backup_ask":
        if await admin_required(): return
        await edit("Start a world backup now?", _confirm_keyboard("backup"))

    elif data == "cb_restart_ask":
        if await admin_required(): return
        await edit("Restart the server? Players will be briefly disconnected.", _confirm_keyboard("restart"))

    elif data == "cb_stop_ask":
        if await admin_required(): return
        await edit("<b>Stop</b> the server? All players will be disconnected.", _confirm_keyboard("stop"))

    elif data == "cb_update_ask":
        if await admin_required(): return
        await edit("Run SteamCMD update? Server will stop, update, then restart.", _confirm_keyboard("update"))

    # ---- confirmed actions ----
    elif data == "cb_confirmed_backup":
        if await admin_required(): return
        await edit("Backup started...")
        proc = await asyncio.to_thread(
            subprocess.run, ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", BACKUP_SCRIPT],
            capture_output=True, text=True, timeout=300,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        await edit(f"<b>Backup:</b> {result}", _main_panel())

    elif data == "cb_confirmed_restart":
        if await admin_required(): return
        await edit("Restarting...")
        _docker_restart()
        await edit("<b>Restart issued.</b> Server active in ~30s.", _main_panel())
        await _flush_waitlist(context)

    elif data == "cb_confirmed_stop":
        if await admin_required(): return
        await edit("Stopping...")
        _docker_stop()
        await edit("<b>Server stopped.</b>", _main_panel())

    elif data == "cb_confirmed_update":
        if await admin_required(): return
        await edit("Update started (takes a few minutes)...")
        proc = await asyncio.to_thread(
            subprocess.run, ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", UPDATE_SCRIPT],
            capture_output=True, text=True, timeout=600,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        await edit(f"<b>Update:</b> {result}", _main_panel())

    # ---- Sys Info (Feature 3) ----
    elif data == "v2_sysinfo":
        await edit(_build_sysinfo_text(), _sysinfo_keyboard())

    # ---- Notify Me (Feature 7) ----
    elif data == "v2_notify_sub":
        if _container_running():
            await edit("Server is already online!", _main_panel())
            return
        waitlist: list = _STATE["notify_waitlist"]
        if uid not in waitlist:
            waitlist.append(uid)
            _save_state()
        await edit("🔔 You'll be notified when the server comes online.", _main_panel())

    # ---- Server Settings (Feature 1) ----
    elif data == "v2_settings_menu":
        if await admin_required(): return
        await edit("<b>Server Settings</b>", _settings_menu_keyboard())

    elif data == "v2_settings_invite":
        if await admin_required(): return
        desc = _read_server_desc()
        code = html.escape(str(desc.get("InviteCode", "Not found")))
        await edit(f"<b>Invite Code:</b> <code>{code}</code>", _settings_menu_keyboard())

    elif data == "v2_settings_changepw":
        if await admin_required(): return
        if _container_running():
            await edit(
                "⚠️ Server must be stopped before changing config. Stop it first.",
                _settings_menu_keyboard(),
            )
            return
        context.user_data["waiting_for"] = "new_password"
        await edit("Send the new password as your next message.", _back_keyboard())

    elif data == "v2_settings_removepw_ask":
        if await admin_required(): return
        await edit(
            "Remove the server password? This will allow anyone with the invite code to join.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Yes, remove", callback_data="v2_settings_removepw_confirmed"),
                InlineKeyboardButton("❌ Cancel",      callback_data="v2_settings_menu"),
            ]]),
        )

    elif data == "v2_settings_removepw_confirmed":
        if await admin_required(): return
        if _container_running():
            await edit(
                "⚠️ Server must be stopped before changing config. Stop it first.",
                _settings_menu_keyboard(),
            )
            return
        desc = _read_server_desc()
        desc["ServerPassword"] = ""
        _write_server_desc(desc)
        await edit("✅ Password removed.", _settings_menu_keyboard())

    # ---- Users (Feature 2) ----
    elif data == "v2_users_menu":
        if await admin_required(): return
        await edit("<b>User Management</b>", _users_menu_keyboard())

    elif data == "v2_users_list":
        if await admin_required(): return
        admins = list(_all_admins())
        notify = list(_all_notify_only())
        lines = ["<b>Users</b>\n", "<b>Admins:</b>"]
        for a in admins:
            lines.append(f"  • {a}")
        lines.append("\n<b>Notify-only:</b>")
        for n in notify:
            lines.append(f"  • {n}")
        if not notify:
            lines.append("  (none)")
        await edit("\n".join(lines), _users_menu_keyboard())

    elif data == "v2_users_add_admin":
        if await admin_required(): return
        context.user_data["waiting_for"] = "add_admin_id"
        await edit("Send the Telegram user ID to add as admin.", _back_keyboard())

    elif data == "v2_users_add_notify":
        if await admin_required(): return
        context.user_data["waiting_for"] = "add_notify_id"
        await edit("Send the Telegram user ID to add as notify-only user.", _back_keyboard())

    elif data == "v2_users_remove":
        if await admin_required(): return
        context.user_data["waiting_for"] = "remove_user_id"
        await edit("Send the Telegram user ID to remove.", _back_keyboard())

    # ---- Schedule (Feature 8) ----
    elif data == "v2_schedule_menu":
        if await admin_required(): return
        await edit("<b>Scheduled Restart</b>", _schedule_menu_keyboard())

    elif data == "v2_schedule_view":
        if await admin_required(): return
        enabled = _STATE.get("schedule_enabled", False)
        t = _STATE.get("schedule_time", "03:00")
        status = f"{t} UTC" if enabled else "Disabled"
        await edit(f"<b>Schedule:</b> {status}", _schedule_menu_keyboard())

    elif data == "v2_schedule_set":
        if await admin_required(): return
        context.user_data["waiting_for"] = "schedule_time"
        await edit("Send the restart time in HH:MM UTC format (e.g. 03:00).", _back_keyboard())

    elif data == "v2_schedule_toggle":
        if await admin_required(): return
        _STATE["schedule_enabled"] = not _STATE.get("schedule_enabled", False)
        _save_state()
        _cancel_scheduled_restart()
        if _STATE["schedule_enabled"]:
            _register_scheduled_restart(context.application)
        status = "enabled" if _STATE["schedule_enabled"] else "disabled"
        await edit(f"✅ Scheduled restart {status}.", _schedule_menu_keyboard())

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start",    "Open the control panel"),
        BotCommand("status",   "Server status"),
        BotCommand("players",  "Players online"),
        BotCommand("logs",     "Last 30 log lines"),
        BotCommand("uptime",   "Server uptime"),
        BotCommand("backup",   "Take a world backup"),
        BotCommand("restart",  "Restart the server"),
        BotCommand("stop",     "Stop the server"),
        BotCommand("update",   "Update via SteamCMD"),
        BotCommand("notify",   "Notify me when server starts"),
        BotCommand("history",  "Session history"),
        BotCommand("playtime", "Playtime leaderboard"),
    ])

    _load_state()
    _compile_patterns()

    jq = application.job_queue
    jq.run_repeating(_resource_alert_job,  interval=60,                  first=60,  name="resource_alerts")
    jq.run_repeating(_idle_autostop_job,   interval=_IDLE_CHECK_INTERVAL, first=120, name="idle_autostop")

    _register_scheduled_restart(application)

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
        log.info(
            "Player monitor: journalctl polling (mode=%s, log_exists=%s, log_fresh=%s)",
            mode, log_exists, log_fresh,
        )
        jq.run_repeating(
            _poll_journal_job,
            interval=timedelta(seconds=POLL_INTERVAL),
            first=timedelta(seconds=10),
            name="player_monitor_poll",
        )


def build_app() -> Application:
    return ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()


def main() -> None:
    _validate_runtime_config()
    app = build_app()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("players",  cmd_players))
    app.add_handler(CommandHandler("logs",     cmd_logs))
    app.add_handler(CommandHandler("uptime",   cmd_uptime))
    app.add_handler(CommandHandler("backup",   cmd_backup))
    app.add_handler(CommandHandler("restart",  cmd_restart))
    app.add_handler(CommandHandler("stop",     cmd_stop))
    app.add_handler(CommandHandler("update",   cmd_update))
    app.add_handler(CommandHandler("notify",   cmd_notify))
    app.add_handler(CommandHandler("history",  cmd_history))
    app.add_handler(CommandHandler("playtime", cmd_playtime))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    log.info("Windrose bot starting (long polling)")
    try:
        app.run_polling()
    except InvalidToken:
        raise SystemExit(
            "Telegram rejected BOT_TOKEN from .env. "
            "Check token value and restart windrose-bot."
        )


if __name__ == "__main__":
    main()

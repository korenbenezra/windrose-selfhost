"""main.py — composition root: ApplicationBuilder, handler registration, job setup."""
from __future__ import annotations

import asyncio
import datetime
import logging
import subprocess
import sys
import time as _time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.error import InvalidToken
from telegram.ext import Application, ApplicationBuilder, ApplicationHandlerStop, TypeHandler

from windrose_bot import config, state
from windrose_bot.core.errors import error_handler
from windrose_bot.handlers.callbacks import build_callback_handlers
from windrose_bot.handlers.commands import build_command_handlers
from windrose_bot.handlers.flows import build_conversation_handlers
from windrose_bot.services import container, monitor
from windrose_bot.services.resources import make_bar

log = logging.getLogger(__name__)


class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def _configure_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s -- %(message)s")

    out_handler = logging.StreamHandler(sys.stdout)
    out_handler.setLevel(logging.INFO)
    out_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    out_handler.setFormatter(fmt)

    err_handler = logging.StreamHandler(sys.stderr)
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(out_handler)
    root.addHandler(err_handler)

    logging.captureWarnings(True)


# ---------------------------------------------------------------------------
# Rate limiting (ADR-0007) — TypeHandler in group -1, runs before all handlers
# ---------------------------------------------------------------------------
_rate_counts: dict[int, list[float]] = defaultdict(list)


async def _rate_limit_handler(update: Update, context) -> None:
    user = update.effective_user
    if user is None:
        return
    now = _time.monotonic()
    timestamps = [t for t in _rate_counts[user.id] if now - t < 60.0]
    if len(timestamps) >= config.RATE_LIMIT_MESSAGES_PER_MINUTE:
        if update.effective_message:
            await update.effective_message.reply_text(
                "⏳ Too many messages. Please slow down."
            )
        raise ApplicationHandlerStop
    timestamps.append(now)
    _rate_counts[user.id] = timestamps


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------
_cpu_high_count = 0
_server_was_running: bool | None = None


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


async def _notify_admins(context, text: str) -> None:
    from windrose_bot.core.security import all_admins
    for chat_id in all_admins():
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        except Exception as exc:
            log.warning("admin notify failed for %s: %s", chat_id, exc)


async def _flush_waitlist(context) -> None:
    """Send 'server is online' to everyone in the notify waitlist and clear it."""
    waitlist = list(state._STATE.get("notify_waitlist", []))
    if not waitlist:
        return
    state._STATE["notify_waitlist"] = []
    state.save()
    for chat_id in waitlist:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ The Windrose server is now online!",
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            log.warning("waitlist flush failed for %s: %s", chat_id, exc)


async def _server_state_poll_job(context) -> None:
    """Detect server online/offline transitions; flush notify waitlist on startup."""
    global _server_was_running
    running = await container.running()
    if _server_was_running is False and running:
        await _flush_waitlist(context)
        await _notify_admins(context, "✅ Windrose server is online.")
    elif _server_was_running is True and not running:
        await _notify_admins(context, "⏹ Windrose server went offline.")
    _server_was_running = running


async def _resource_alert_job(context) -> None:
    global _cpu_high_count
    import psutil
    cpu = psutil.cpu_percent(interval=0.0)
    ram = psutil.virtual_memory().percent
    if cpu > config.CPU_ALERT_THRESHOLD:
        _cpu_high_count += 1
        if _cpu_high_count >= 3:
            _cpu_high_count = 0
            await _notify_admins(context, f"⚠️ CPU above {config.CPU_ALERT_THRESHOLD:.0f}% for 3 minutes. Current: {cpu:.0f}%")
    else:
        _cpu_high_count = 0
    if ram > config.RAM_ALERT_THRESHOLD:
        await _notify_admins(context, f"⚠️ RAM usage at {ram:.0f}%. Consider restarting the server.")


async def _idle_autostop_job(context) -> None:
    if not await container.running():
        state._STATE["idle_empty_since"] = None
        state._STATE["idle_warning_sent"] = False
        state.save()
        return
    active = state._STATE.get("sessions_active", {})
    now = datetime.datetime.now(datetime.timezone.utc)
    if active:
        state._STATE["idle_empty_since"] = None
        state._STATE["idle_warning_sent"] = False
        state.save()
        return
    idle_since_str = state._STATE.get("idle_empty_since")
    if idle_since_str is None:
        state._STATE["idle_empty_since"] = _now_iso()
        state.save()
        return
    try:
        idle_since = datetime.datetime.fromisoformat(idle_since_str.replace("Z", "+00:00"))
    except Exception:
        state._STATE["idle_empty_since"] = _now_iso()
        state.save()
        return
    idle_minutes = (now - idle_since).total_seconds() / 60
    timeout = config.IDLE_TIMEOUT_MINUTES
    if idle_minutes >= timeout:
        try:
            await container.stop()
        except container.ServiceControlError as exc:
            await _notify_admins(
                context,
                f"⚠️ Auto-stop failed: <code>{str(exc)[:1500]}</code>",
            )
            return
        state._STATE["idle_empty_since"] = None
        state._STATE["idle_warning_sent"] = False
        state.save()
        await _notify_admins(context,
            f"🛑 Server auto-stopped after {timeout} minutes of inactivity. Use /start to bring it back.")
    elif idle_minutes >= timeout - 5 and not state._STATE.get("idle_warning_sent"):
        state._STATE["idle_warning_sent"] = True
        state.save()
        await _notify_admins(context,
            f"⏳ Server has been idle for {int(idle_minutes)} minutes. Auto-stopping in 5 minutes unless someone joins.")


_scheduled_restart_job_handle = None


async def _scheduled_restart_job_fn(context) -> None:
    await _notify_admins(context, "🔄 Scheduled restart starting...")
    try:
        await container.stop()
    except container.ServiceControlError as exc:
        await _notify_admins(
            context,
            f"⚠️ Scheduled restart failed during stop: <code>{str(exc)[:1500]}</code>",
        )
        return
    await asyncio.sleep(5)
    proc = await asyncio.to_thread(
        subprocess.run,
        ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", config.UPDATE_SCRIPT],
        capture_output=True, text=True, timeout=600,
    )
    try:
        await container.start()
    except container.ServiceControlError as exc:
        await _notify_admins(
            context,
            f"⚠️ Scheduled restart failed during start: <code>{str(exc)[:1500]}</code>",
        )
        return
    result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
    await _notify_admins(context, f"✅ Scheduled restart complete. Update: {result}")


def register_scheduled_restart(app: Application) -> None:
    global _scheduled_restart_job_handle
    if not state._STATE.get("schedule_enabled"):
        return
    t_str = state._STATE.get("schedule_time", "03:00")
    try:
        h, m = map(int, t_str.split(":"))
        t = datetime.time(h, m, tzinfo=datetime.timezone.utc)
    except Exception:
        log.warning("Invalid schedule_time: %s", t_str)
        return
    _scheduled_restart_job_handle = app.job_queue.run_daily(
        _scheduled_restart_job_fn, time=t, name="scheduled_restart"
    )
    log.info("Scheduled restart registered at %s UTC", t_str)


def cancel_scheduled_restart() -> None:
    global _scheduled_restart_job_handle
    if _scheduled_restart_job_handle:
        _scheduled_restart_job_handle.schedule_removal()
        _scheduled_restart_job_handle = None


# ---------------------------------------------------------------------------
# Startup / composition
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
        BotCommand("cancel",   "Cancel current flow"),
    ])

    state.load()
    monitor.compile_patterns()

    jq = application.job_queue
    jq.run_repeating(_resource_alert_job,    interval=60,  first=60,  name="resource_alerts")
    jq.run_repeating(_idle_autostop_job,     interval=300, first=120, name="idle_autostop")
    jq.run_repeating(_server_state_poll_job, interval=30,  first=15,  name="server_state_poll")

    register_scheduled_restart(application)

    loop = asyncio.get_event_loop()
    mode = config.PLAYER_MONITOR_MODE
    log_path = Path(config.LOG_PATH)
    log_exists = log_path.exists()
    log_fresh = log_exists and (_time.time() - log_path.stat().st_mtime) < 600

    if mode == "watchdog" or (mode == "auto" and log_fresh):
        monitor.start_watchdog(application, loop)
    elif mode == "off":
        log.info("Player monitor: disabled")
    else:
        log.info("Player monitor: polling (mode=%s, log_exists=%s)", mode, log_exists)
        jq.run_repeating(
            monitor.poll_log_job,
            interval=timedelta(seconds=config.POLL_INTERVAL),
            first=timedelta(seconds=10),
            name="player_monitor_poll",
        )


def build_app() -> Application:
    app = ApplicationBuilder().token(config.BOT_TOKEN).post_init(post_init).build()
    app.add_error_handler(error_handler)

    # Rate limiting — runs before all feature handlers (ADR-0007)
    app.add_handler(TypeHandler(Update, _rate_limit_handler), group=-1)

    for conv in build_conversation_handlers():
        app.add_handler(conv)
    for h in build_command_handlers():
        app.add_handler(h)
    for h in build_callback_handlers():
        app.add_handler(h)

    return app


def main() -> None:
    _configure_logging()
    config.validate()
    app = build_app()
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

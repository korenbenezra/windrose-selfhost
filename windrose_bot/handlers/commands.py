"""handlers/commands.py — slash command handlers."""
from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from windrose_bot import state
from windrose_bot.core.security import is_admin, restricted
from windrose_bot.keyboards.menus import back_keyboard, confirm_keyboard, main_panel
from windrose_bot.services import container

log = logging.getLogger(__name__)


def _fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m:02d}m" if h > 0 else f"{m}m"


def _last_log_lines(n: int = 30) -> str:
    from windrose_bot.config import LOG_PATH
    try:
        with open(LOG_PATH, errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).strip() or "(no log output)"
    except Exception as exc:
        return f"(error reading log: {exc})"


@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(
        "<b>Windrose Server Control</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_panel(is_admin=is_admin(uid)),
    )


@restricted
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    svc_state = "running" if await container.running() else await container.status()
    await update.message.reply_text(
        f"<b>Server status:</b> {svc_state}", parse_mode=ParseMode.HTML
    )


@restricted
async def cmd_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    players = state.known_players()
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
    await update.message.reply_text(
        f"<b>Container uptime:</b> {container.uptime()}", parse_mode=ParseMode.HTML
    )


@restricted(admin_only=True)
async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Start a world backup now?", reply_markup=confirm_keyboard("backup")
    )


@restricted(admin_only=True)
async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Restart the server? Players will be briefly disconnected.",
        reply_markup=confirm_keyboard("restart"),
    )


@restricted(admin_only=True)
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>Stop</b> the server? All players will be disconnected.",
        parse_mode=ParseMode.HTML,
        reply_markup=confirm_keyboard("stop"),
    )


@restricted(admin_only=True)
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Run a SteamCMD update? Server will stop, update, then restart.",
        reply_markup=confirm_keyboard("update"),
    )


@restricted
async def cmd_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if await container.running():
        await update.message.reply_text("Server is already online!")
        return
    waitlist: list = state._STATE["notify_waitlist"]
    if uid not in waitlist:
        waitlist.append(uid)
        state.save()
    await update.message.reply_text("Got it! You'll be notified when the server comes online.")


@restricted
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history = state._STATE.get("sessions_history", [])[-20:]
    if not history:
        await update.message.reply_text("No session history yet.")
        return
    rows = ["<b>Session History</b>", "<pre>"]
    rows.append(f"{'Player':<20} {'Joined (UTC)':<20} {'Duration'}")
    rows.append("-" * 52)
    for entry in reversed(history):
        name = entry.get("name", "?")[:18]
        joined = entry.get("joined", "")[:16].replace("T", " ")
        dur = _fmt_duration(entry.get("duration_s", 0))
        rows.append(f"{name:<20} {joined:<20} {dur}")
    rows.append("</pre>")
    await update.message.reply_text("\n".join(rows), parse_mode=ParseMode.HTML)


@restricted
async def cmd_playtime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    totals: dict = state._STATE.get("playtime_totals", {})
    if not totals:
        await update.message.reply_text("No playtime data yet.")
        return
    sorted_players = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    lines = ["<b>Playtime Leaderboard</b>"]
    for i, (name, secs) in enumerate(sorted_players, 1):
        lines.append(f"{i}. {html.escape(name)} — {_fmt_duration(secs)}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


def build_command_handlers():
    from telegram.ext import CommandHandler
    return [
        CommandHandler("start",    cmd_start),
        CommandHandler("status",   cmd_status),
        CommandHandler("players",  cmd_players),
        CommandHandler("logs",     cmd_logs),
        CommandHandler("uptime",   cmd_uptime),
        CommandHandler("backup",   cmd_backup),
        CommandHandler("restart",  cmd_restart),
        CommandHandler("stop",     cmd_stop),
        CommandHandler("update",   cmd_update),
        CommandHandler("notify",   cmd_notify),
        CommandHandler("history",  cmd_history),
        CommandHandler("playtime", cmd_playtime),
    ]

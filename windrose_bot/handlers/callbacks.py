"""handlers/callbacks.py — non-flow inline button callbacks."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import subprocess
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from windrose_bot import state
from windrose_bot.config import BACKUP_SCRIPT, LOG_PATH, UPDATE_SCRIPT
from windrose_bot.core.security import audit, is_admin, restricted
from windrose_bot.keyboards.menus import (
    admin_menu,
    back_keyboard,
    confirm_keyboard,
    main_panel,
    monitoring_menu,
    notifications_menu,
    operations_menu,
    read_server_desc,
    schedule_menu_keyboard,
    server_menu,
    settings_menu_keyboard,
    sysinfo_keyboard,
    users_menu_keyboard,
    write_server_desc,
)
from windrose_bot.services import container
from windrose_bot.services.resources import sysinfo_text

log = logging.getLogger(__name__)


def _invite_code_from_desc(desc: dict) -> str | None:
    """Return invite code from known world/server description shapes."""
    for key in ("InviteCode", "inviteCode", "invite_code"):
        val = desc.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # Some formats may nest keys under a world description object.
    nested = desc.get("WorldDescription")
    if isinstance(nested, dict):
        for key in ("InviteCode", "inviteCode", "invite_code"):
            val = nested.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _invite_code_from_log(max_tail_chars: int = 200_000) -> str | None:
    """Extract latest invite code from recent log tail."""
    try:
        text = Path(LOG_PATH).read_text(errors="replace")
    except Exception:
        return None

    tail = text[-max_tail_chars:]
    patterns = [
        r'"InviteCode"\s*:\s*"([A-Za-z0-9_-]{4,64})"',
        r"InviteCode\s*:\s*([A-Za-z0-9_-]{4,64})",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, tail, flags=re.IGNORECASE)
        if matches:
            return matches[-1]
    return None


def _resolve_invite_code() -> str | None:
    code = _invite_code_from_desc(read_server_desc())
    if code:
        return code
    return _invite_code_from_log()


@restricted
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data: str = query.data
    uid = update.effective_user.id

    async def edit(text: str, markup=None) -> None:
        await query.answer()
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    async def admin_required() -> bool:
        if not is_admin(uid):
            await query.answer("Admin access required.", show_alert=True)
            return True
        return False

    if data == "cb_panel":
        await edit("<b>Windrose Server Control</b>", main_panel(is_admin=is_admin(uid)))

    elif data == "nav_server":
        await edit("<b>Server</b>", server_menu())

    elif data == "nav_monitoring":
        await edit("<b>Monitoring</b>", monitoring_menu())

    elif data == "nav_notifications":
        await edit("<b>Notifications</b>", notifications_menu())

    elif data == "nav_operations":
        if await admin_required(): return
        await edit("<b>Operations</b>", operations_menu())

    elif data == "nav_admin":
        if await admin_required(): return
        await edit("<b>Admin</b>", admin_menu())

    elif data == "cb_status":
        svc_state = "running" if await container.running() else await container.status()
        await edit(f"<b>Server status:</b> {svc_state}", server_menu())

    elif data == "cb_players":
        players = state.known_players()
        if players:
            names = "\n".join(f"  • {html.escape(p)}" for p in sorted(players))
            text = f"<b>Players online ({len(players)}):</b>\n{names}"
        else:
            text = "<b>No players currently online.</b>"
        await edit(text, server_menu())

    elif data == "cb_logs":
        from windrose_bot.handlers.commands import _last_log_lines
        lines = _last_log_lines(20)
        await edit(f"<pre>{html.escape(lines[-3000:])}</pre>", monitoring_menu())

    elif data == "cb_uptime":
        await edit(f"<b>Container uptime:</b> {container.uptime()}", server_menu())

    elif data == "cb_backup_ask":
        if await admin_required(): return
        await edit("Start a world backup now?", confirm_keyboard("backup"))

    elif data == "cb_restart_ask":
        if await admin_required(): return
        await edit("Restart the server? Players will be briefly disconnected.", confirm_keyboard("restart"))

    elif data == "cb_stop_ask":
        if await admin_required(): return
        await edit("<b>Stop</b> the server? All players will be disconnected.", confirm_keyboard("stop"))

    elif data == "cb_update_ask":
        if await admin_required(): return
        await edit("Run SteamCMD update? Server will stop, update, then restart.", confirm_keyboard("update"))

    elif data == "cb_confirmed_backup":
        if await admin_required(): return
        audit("backup", update)
        await edit("Backup started...")
        proc = await asyncio.to_thread(
            subprocess.run,
            ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", BACKUP_SCRIPT],
            capture_output=True, text=True, timeout=300,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        await edit(f"<b>Backup:</b> {result}", operations_menu())

    elif data == "cb_confirmed_restart":
        if await admin_required(): return
        audit("restart", update)
        await edit("Restarting...")
        try:
            await container.restart()
        except container.ServiceControlError as exc:
            audit("restart", update, result="failed", reason=str(exc))
            await edit(
                f"<b>Restart failed:</b>\n<pre>{html.escape(str(exc))[:3000]}</pre>",
                operations_menu(),
            )
            return
        await edit("<b>Restart issued.</b> Server active in ~30s.", operations_menu())

    elif data == "cb_confirmed_stop":
        if await admin_required(): return
        audit("stop", update)
        await edit("Stopping...")
        try:
            await container.stop()
        except container.ServiceControlError as exc:
            audit("stop", update, result="failed", reason=str(exc))
            await edit(
                f"<b>Stop failed:</b>\n<pre>{html.escape(str(exc))[:3000]}</pre>",
                operations_menu(),
            )
            return
        await edit("<b>Server stopped.</b>", operations_menu())

    elif data == "cb_confirmed_update":
        if await admin_required(): return
        audit("update", update)
        await edit("Update started (takes a few minutes)...")
        proc = await asyncio.to_thread(
            subprocess.run,
            ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", UPDATE_SCRIPT],
            capture_output=True, text=True, timeout=600,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        await edit(f"<b>Update:</b> {result}", operations_menu())

    elif data == "v2_sysinfo":
        await edit(await sysinfo_text(), sysinfo_keyboard())

    elif data == "v2_notify_sub":
        if await container.running():
            await edit("Server is already online!", notifications_menu())
            return
        waitlist: list = state._STATE["notify_waitlist"]
        if uid not in waitlist:
            waitlist.append(uid)
            state.save()
        await edit("🔔 You'll be notified when the server comes online.", notifications_menu())

    elif data == "v2_settings_menu":
        if await admin_required(): return
        await edit("<b>Server Settings</b>", settings_menu_keyboard())

    elif data == "v2_settings_invite":
        if await admin_required(): return
        code = _resolve_invite_code()
        if code:
            await edit(
                f"<b>Invite Code:</b> <code>{html.escape(code)}</code>",
                settings_menu_keyboard(),
            )
        else:
            await edit(
                "<b>Invite Code:</b> Not found. Start the server once and try again.",
                settings_menu_keyboard(),
            )

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
        if await container.running():
            await edit("⚠️ Server must be stopped before changing config. Stop it first.",
                       settings_menu_keyboard())
            return
        desc = read_server_desc()
        desc["ServerPassword"] = ""
        write_server_desc(desc)
        audit("remove_password", update)
        await edit("✅ Password removed.", settings_menu_keyboard())

    elif data == "v2_users_menu":
        if await admin_required(): return
        await edit("<b>User Management</b>", users_menu_keyboard())

    elif data == "v2_users_list":
        if await admin_required(): return
        from windrose_bot.core.security import all_admins, all_notify_only
        admins = list(all_admins())
        notify = list(all_notify_only())
        lines = ["<b>Users</b>\n", "<b>Admins:</b>"]
        for a in admins:
            lines.append(f"  • {a}")
        lines.append("\n<b>Notify-only:</b>")
        for n in notify:
            lines.append(f"  • {n}")
        if not notify:
            lines.append("  (none)")
        await edit("\n".join(lines), users_menu_keyboard())

    elif data == "v2_schedule_menu":
        if await admin_required(): return
        await edit("<b>Scheduled Restart</b>", schedule_menu_keyboard())

    elif data == "v2_schedule_view":
        if await admin_required(): return
        enabled = state._STATE.get("schedule_enabled", False)
        t = state._STATE.get("schedule_time", "03:00")
        sched_status = f"{t} UTC" if enabled else "Disabled"
        await edit(f"<b>Schedule:</b> {sched_status}", schedule_menu_keyboard())

    elif data == "v2_schedule_toggle":
        if await admin_required(): return
        state._STATE["schedule_enabled"] = not state._STATE.get("schedule_enabled", False)
        state.save()
        from windrose_bot.main import cancel_scheduled_restart, register_scheduled_restart
        cancel_scheduled_restart()
        if state._STATE["schedule_enabled"]:
            register_scheduled_restart(context.application)
        enabled = state._STATE["schedule_enabled"]
        audit("schedule_toggle", update, enabled=enabled)
        sched_status = "enabled" if enabled else "disabled"
        await edit(f"✅ Scheduled restart {sched_status}.", schedule_menu_keyboard())


def build_callback_handlers():
    from telegram.ext import CallbackQueryHandler
    return [CallbackQueryHandler(button_handler)]

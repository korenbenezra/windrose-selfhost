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
from windrose_bot.config import BACKUP_SCRIPT, BACKUPS_DIR, LOG_PATH, UPDATE_SCRIPT
from windrose_bot.core import audit as audit_log
from windrose_bot.core.safety import (
    attribution_line,
    check_cooldown,
    class3_instructions,
    generate_class3_token,
    set_cooldown,
)
from windrose_bot.core.security import audit, is_admin, restricted
from windrose_bot.keyboards.menus import (
    admin_menu,
    audit_menu,
    back_keyboard,
    backups_menu,
    ban_duration_menu,
    banlist_menu,
    build_status_header,
    class2_confirm_keyboard,
    combat_difficulty_menu,
    config_menu,
    config_password_menu,
    confirm_keyboard,
    coop_settings_menu,
    diagnostics_menu,
    main_panel,
    max_players_menu,
    mob_settings_menu,
    mods_menu,
    multiplier_keyboard,
    notifications_menu,
    operations_menu,
    players_menu,
    read_server_desc,
    region_menu,
    restart_delay_menu,
    schedule_menu_keyboard,
    server_settings_menu,
    settings_menu_keyboard,
    ship_settings_menu,
    sysinfo_keyboard,
    users_menu_keyboard,
    world_settings_menu,
    write_server_desc,
)
from windrose_bot.services import settings as srv_settings
from windrose_bot.services import container
from windrose_bot.services.resources import sysinfo_text

log = logging.getLogger(__name__)


def _invite_code_from_desc(desc: dict) -> str | None:
    for key in ("InviteCode", "inviteCode", "invite_code"):
        val = desc.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    nested = desc.get("WorldDescription")
    if isinstance(nested, dict):
        for key in ("InviteCode", "inviteCode", "invite_code"):
            val = nested.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _invite_code_from_log(max_tail_chars: int = 200_000) -> str | None:
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
    user = update.effective_user

    async def edit(text: str, markup=None) -> None:
        await query.answer()
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    async def edit_with_header(title: str, markup=None) -> None:
        header = await build_status_header()
        await edit(f"{header}\n\n{title}", markup)

    async def admin_required() -> bool:
        if not is_admin(uid):
            await query.answer("Admin access required.", show_alert=True)
            return True
        return False

    def cooldown_check(action: str) -> int:
        return check_cooldown(uid, action)

    # -----------------------------------------------------------------------
    # Navigation
    # -----------------------------------------------------------------------

    if data == "cb_panel":
        await edit_with_header("<b>Windrose Server Control</b>", main_panel(is_admin=is_admin(uid)))

    elif data == "nav_players":
        await edit_with_header("<b>Players</b>", players_menu(is_admin=is_admin(uid)))

    elif data == "nav_notifications":
        await edit("<b>Notifications</b>\nToggle alert channels:", notifications_menu(user_id=uid))

    elif data == "nav_operations":
        if await admin_required(): return
        await edit_with_header("<b>🎛 Operations</b>", operations_menu())

    elif data == "nav_config":
        if await admin_required(): return
        await edit("<b>⚙️ Configuration</b>", config_menu())

    elif data == "nav_mods":
        if await admin_required(): return
        await edit("<b>🧩 Mods & Workshop</b>", mods_menu())

    elif data == "nav_schedule":
        if await admin_required(): return
        await edit("<b>📅 Schedule</b>", schedule_menu_keyboard())

    elif data == "nav_backups":
        if await admin_required(): return
        await edit("<b>💾 Backups</b>", backups_menu())

    elif data == "nav_diagnostics":
        if await admin_required(): return
        await edit("<b>🩺 Diagnostics</b>", diagnostics_menu())

    elif data == "nav_audit":
        if await admin_required(): return
        await edit("<b>🛡 Audit Trail</b>", audit_menu())

    elif data == "nav_restart_delay":
        if await admin_required(): return
        await edit("<b>🔄 Restart — choose timing</b>", restart_delay_menu())

    elif data == "nav_admin":
        if await admin_required(): return
        await edit("<b>Admin</b>", admin_menu())

    # -----------------------------------------------------------------------
    # Server section
    # -----------------------------------------------------------------------

    elif data == "cb_status":
        svc_state = "running" if await container.running() else await container.status()
        await edit_with_header(f"<b>Server status:</b> {svc_state}", back_keyboard())

    elif data == "plr_online":
        players = state.known_players()
        if players:
            names = "\n".join(f"  • {html.escape(p)}" for p in sorted(players))
            text = f"<b>Players online ({len(players)}):</b>\n{names}"
        else:
            text = "<b>No players currently online.</b>"
        await edit(text, players_menu(is_admin=is_admin(uid)))

    elif data == "cb_players":
        players = state.known_players()
        if players:
            names = "\n".join(f"  • {html.escape(p)}" for p in sorted(players))
            text = f"<b>Players online ({len(players)}):</b>\n{names}"
        else:
            text = "<b>No players currently online.</b>"
        await edit(text, players_menu(is_admin=is_admin(uid)))

    elif data == "cb_logs":
        from windrose_bot.handlers.commands import _last_log_lines
        lines = _last_log_lines(20)
        await edit(f"<pre>{html.escape(lines[-3000:])}</pre>", diagnostics_menu())

    elif data == "cb_uptime":
        await edit(f"<b>Container uptime:</b> {container.uptime()}", diagnostics_menu())

    # -----------------------------------------------------------------------
    # Player Moderation (ADR-0015)
    # -----------------------------------------------------------------------

    elif data == "plr_kick_ask":
        if await admin_required(): return
        context.user_data["_pending_action"] = "kick"
        await edit(
            f"{attribution_line(user)}\n\n"
            "Send the player name to kick. /cancel to abort.",
            back_keyboard("nav_players"),
        )
        context.user_data["_fsm_name"] = "KICK_PLAYER"

    elif data == "plr_ban_ask":
        if await admin_required(): return
        await edit(
            f"{attribution_line(user)}\n\nSelect ban duration:",
            ban_duration_menu(),
        )

    elif data.startswith("plr_ban_dur_"):
        if await admin_required(): return
        dur_map = {"1h": "1 hour", "24h": "24 hours", "7d": "7 days", "perm": "Permanent"}
        dur_key = data[len("plr_ban_dur_"):]
        dur_label = dur_map.get(dur_key, "?")
        context.user_data["_ban_duration"] = dur_key
        context.user_data["_fsm_name"] = "BAN_PLAYER"
        await edit(
            f"{attribution_line(user)}\n\n"
            f"Duration: <b>{dur_label}</b>\n"
            "Send the player name to ban. /cancel to abort.",
            back_keyboard("nav_players"),
        )

    elif data == "plr_banlist":
        if await admin_required(): return
        bans = state._STATE.get("ban_list", [])
        if not bans:
            await edit("📜 Ban list is empty.", players_menu(is_admin=True))
        else:
            lines = []
            for b in bans:
                name = html.escape(b.get("name", "?"))
                exp = b.get("expires") or "Permanent"
                lines.append(f"  • <b>{name}</b> — expires: {exp}")
            await edit("<b>Ban List:</b>\n" + "\n".join(lines), banlist_menu(bans))

    elif data.startswith("plr_liftban_"):
        if await admin_required(): return
        idx = int(data[len("plr_liftban_"):])
        bans = state._STATE.get("ban_list", [])
        if 0 <= idx < len(bans):
            removed = bans.pop(idx)
            state.save()
            audit_log.record("lift_ban", update, name=removed.get("name"))
            audit("lift_ban", update)
            await edit(f"✅ Ban lifted for <b>{html.escape(removed.get('name', '?'))}</b>.",
                       players_menu(is_admin=True))
        else:
            await edit("Ban entry not found.", players_menu(is_admin=True))

    elif data == "plr_whitelist":
        if await admin_required(): return
        wl = state._STATE.get("whitelist", [])
        text = "<b>Whitelist:</b>\n" + ("\n".join(f"  • {html.escape(n)}" for n in wl) or "  (empty)")
        await edit(text, players_menu(is_admin=True))

    # -----------------------------------------------------------------------
    # Operations (ADR-0013 header, new actions)
    # -----------------------------------------------------------------------

    elif data == "cb_start":
        if await admin_required(): return
        await edit("Starting server...")
        try:
            await container.start()
        except container.ServiceControlError as exc:
            audit_log.record("start", update, result="failed", reason=str(exc))
            await edit(f"<b>Start failed:</b>\n<pre>{html.escape(str(exc))[:3000]}</pre>", operations_menu())
            return
        audit_log.record("start", update)
        audit("start", update)
        await edit("<b>Server start issued.</b>", operations_menu())

    elif data == "cb_backup_ask":
        if await admin_required(): return
        await edit(
            f"{attribution_line(user)}\n\n"
            "💾 Start a world backup now?\n<i>Class 1 — single confirmation</i>",
            confirm_keyboard("backup"),
        )

    elif data == "cb_restart_ask":
        if await admin_required(): return
        await edit(
            f"{attribution_line(user)}\n\n"
            "🔄 Restart the server? Players will be briefly disconnected.\n<i>Class 1</i>",
            confirm_keyboard("restart"),
        )

    elif data.startswith("cb_restart_delay_"):
        if await admin_required(): return
        mins = int(data.split("_")[-1])
        context.user_data["_restart_delay_mins"] = mins
        await edit(
            f"{attribution_line(user)}\n\n"
            f"🔄 Restart with <b>{mins}-minute</b> delay? A broadcast will warn players.\n<i>Class 1</i>",
            confirm_keyboard(f"restart_delay_{mins}"),
        )

    elif data.startswith("cb_confirmed_restart_delay_"):
        if await admin_required(): return
        mins = int(data.split("_")[-1])
        audit_log.record("restart_delayed", update, delay_mins=mins)
        audit("restart_delayed", update, delay_mins=mins)
        await edit(f"⏳ Restart scheduled in {mins} minute(s). Players will be warned.")
        await asyncio.sleep(mins * 60)
        try:
            await container.restart()
        except container.ServiceControlError as exc:
            await edit(f"<b>Restart failed:</b> <pre>{html.escape(str(exc))[:3000]}</pre>", operations_menu())
            return
        await edit("<b>Restart complete.</b>", operations_menu())

    elif data == "cb_stop_ask":
        if await admin_required(): return
        await edit(
            f"{attribution_line(user)}\n\n"
            "<b>Stop</b> the server? All players will be disconnected.\n<i>Class 1</i>",
            confirm_keyboard("stop"),
        )

    elif data == "cb_forcestop_ask":
        if await admin_required(): return
        remaining = cooldown_check("forcestop")
        if remaining:
            await query.answer(f"Cooldown: {remaining}s remaining.", show_alert=True)
            return
        players = state.known_players()
        player_note = f"<b>{len(players)} player(s)</b> will be dropped." if players else "No active players."
        await edit(
            f"{attribution_line(user)}\n\n"
            f"🛑 <b>FORCE STOP</b>\n{player_note}\n"
            "<i>Class 2 — two-step confirmation</i>",
            class2_confirm_keyboard("forcestop"),
        )

    elif data == "cb_c2confirmed_forcestop":
        if await admin_required(): return
        audit_log.record("forcestop", update)
        audit("forcestop", update)
        set_cooldown(uid, "forcestop")
        await edit("Force stopping...")
        try:
            await container.stop()
        except container.ServiceControlError as exc:
            audit_log.record("forcestop", update, result="failed", reason=str(exc))
            await edit(f"<b>Force stop failed:</b>\n<pre>{html.escape(str(exc))[:3000]}</pre>", operations_menu())
            return
        await edit("<b>Server force-stopped.</b>", operations_menu())

    elif data == "cb_maintenance_toggle":
        if await admin_required(): return
        current = state._STATE.get("maintenance_mode", False)
        state._STATE["maintenance_mode"] = not current
        state.save()
        audit_log.record("maintenance_toggle", update, enabled=not current)
        audit("maintenance_toggle", update, enabled=not current)
        status = "enabled" if not current else "disabled"
        await edit(f"🚧 Maintenance mode <b>{status}</b>.", operations_menu())

    elif data == "ops_broadcast_ask":
        if await admin_required(): return
        context.user_data["_fsm_name"] = "BROADCAST_MSG"
        await edit("Send the message to broadcast to all players. /cancel to abort.",
                   back_keyboard("nav_operations"))

    elif data == "cb_update_ask":
        if await admin_required(): return
        remaining = cooldown_check("update")
        if remaining:
            await query.answer(f"Cooldown: {remaining}s remaining.", show_alert=True)
            return
        await edit(
            f"{attribution_line(user)}\n\n"
            "🔃 Run SteamCMD update? Server will stop → update → restart.\n"
            "<b>Backup-First policy will run (ADR-004)</b>\n<i>Class 2</i>",
            class2_confirm_keyboard("update"),
        )

    elif data == "cb_c2confirmed_update":
        if await admin_required(): return
        audit_log.record("update", update)
        audit("update", update)
        set_cooldown(uid, "update")
        await edit("Update started (takes a few minutes)...")
        proc = await asyncio.to_thread(
            subprocess.run,
            ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", UPDATE_SCRIPT],
            capture_output=True, text=True, timeout=600,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        audit_log.record("update", update, result=result)
        await edit(f"<b>Update:</b> {result}", operations_menu())

    elif data == "cb_confirmed_update":
        # Legacy route — redirect to Class 2
        if await admin_required(): return
        await edit(
            f"{attribution_line(user)}\n\n"
            "🔃 Run SteamCMD update? (Class 2 confirm required)\n<i>ADR-004: backup runs first</i>",
            class2_confirm_keyboard("update"),
        )

    # -----------------------------------------------------------------------
    # Backups (ADR-0018)
    # -----------------------------------------------------------------------

    elif data == "bkp_list":
        if await admin_required(): return
        bkp_dir = Path(BACKUPS_DIR)
        if not bkp_dir.exists():
            await edit("No backups directory found.", backups_menu())
            return
        files = sorted(bkp_dir.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)[:10]
        if not files:
            await edit("📋 No backups found.", backups_menu())
            return
        import datetime
        lines = []
        for f in files:
            size_mb = f.stat().st_size / (1024 * 1024)
            mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  💾 <code>{html.escape(f.name)}</code> — {size_mb:.1f}MB — {mtime}")
        await edit("<b>Backups:</b>\n" + "\n".join(lines), backups_menu())

    elif data == "bkp_policy":
        if await admin_required(): return
        p = state._STATE.get("backup_policy", {})
        text = (
            "<b>🎯 Backup Policy</b>\n\n"
            f"Keep daily: <b>{p.get('keep_daily', 7)}</b>\n"
            f"Keep weekly: <b>{p.get('keep_weekly', 4)}</b>\n"
            f"Keep monthly: <b>{p.get('keep_monthly', 3)}</b>\n"
            f"Off-site mirror: <b>{'On' if p.get('mirror_enabled') else 'Off'}</b>"
        )
        await edit(text, backups_menu())

    elif data == "bkp_restore_ask":
        if await admin_required(): return
        from windrose_bot.core.security import all_admins
        # Restore is Super-Admin only — here just admins for simplicity
        bkp_dir = Path(BACKUPS_DIR)
        files = sorted(bkp_dir.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)[:5] if bkp_dir.exists() else []
        if not files:
            await edit("No backups available to restore.", backups_menu())
            return
        resource = files[0].name.replace(".zip", "")
        token = generate_class3_token("RESTORE", resource, uid)
        await edit(
            class3_instructions("RESTORE", resource),
            back_keyboard("nav_backups"),
        )
        context.user_data["_class3_action"] = "RESTORE"
        context.user_data["_class3_resource"] = resource
        context.user_data["_fsm_name"] = "CLASS3_RESTORE"

    # -----------------------------------------------------------------------
    # Configuration
    # -----------------------------------------------------------------------

    elif data == "cfg_view":
        if await admin_required(): return
        desc = read_server_desc()
        redacted = {k: ("***" if "password" in k.lower() or "secret" in k.lower() else v)
                    for k, v in desc.items()}
        text = "<b>Config (passwords redacted)</b>\n<pre>" + html.escape(
            "\n".join(f"{k}: {v}" for k, v in list(redacted.items())[:20])
        ) + "</pre>"
        await edit(text, config_menu())

    elif data == "cfg_password_menu":
        if await admin_required(): return
        await edit("<b>🔒 Password</b>", config_password_menu())

    elif data == "cfg_server_settings":
        if await admin_required(): return
        desc = read_server_desc()
        text = (
            "<b>Server Settings</b>\n\n"
            f"Name: {html.escape(str(desc.get('ServerName', '—')))}\n"
            f"Max Players: {desc.get('MaxPlayers', '—')}\n"
            f"Region: {html.escape(str(desc.get('Region', '—')))}"
        )
        await edit(text, config_menu())

    elif data == "cfg_validate":
        if await admin_required(): return
        desc = read_server_desc()
        required_keys = ["WorldIslandId", "ServerName"]
        missing = [k for k in required_keys if k not in desc]
        if missing:
            await edit(f"⚠️ Config missing keys: {', '.join(missing)}", config_menu())
        else:
            await edit("✅ Config validation passed — required keys present.", config_menu())

    elif data == "v2_settings_menu":
        if await admin_required(): return
        await edit("<b>Server Settings</b>", settings_menu_keyboard())

    elif data == "v2_settings_invite":
        if await admin_required(): return
        code = _resolve_invite_code()
        if code:
            await edit(f"<b>Invite Code:</b> <code>{html.escape(code)}</code>", config_menu())
        else:
            await edit("<b>Invite Code:</b> Not found. Start the server once and try again.", config_menu())

    elif data == "v2_settings_removepw_ask":
        if await admin_required(): return
        await edit(
            f"{attribution_line(user)}\n\n"
            "Remove the server password? Anyone with the invite code can join.\n<i>Class 1</i>",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Yes, remove", callback_data="v2_settings_removepw_confirmed"),
                InlineKeyboardButton("❌ Cancel",      callback_data="nav_config"),
            ]]),
        )

    elif data == "v2_settings_removepw_confirmed":
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", config_menu())
            return
        desc = read_server_desc()
        desc["ServerPassword"] = ""
        write_server_desc(desc)
        audit_log.record("remove_password", update)
        audit("remove_password", update)
        await edit("✅ Password removed.", config_menu())

    # -----------------------------------------------------------------------
    # Diagnostics
    # -----------------------------------------------------------------------

    elif data == "v2_sysinfo":
        await edit(await sysinfo_text(), sysinfo_keyboard())

    elif data == "diag_integrity":
        if await admin_required(): return
        await edit("🔍 Running integrity check via SteamCMD... (this may take a minute)")
        proc = await asyncio.to_thread(
            subprocess.run,
            ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", f"& '{UPDATE_SCRIPT}' -ValidateOnly"],
            capture_output=True, text=True, timeout=300,
        )
        result = "✅ Integrity OK" if proc.returncode == 0 else f"⚠️ Issues found (exit {proc.returncode})"
        audit_log.record("integrity_check", update, result=result)
        await edit(f"<b>Integrity Check:</b> {result}", diagnostics_menu())

    elif data == "diag_bundle":
        if await admin_required(): return
        audit_log.record("export_bundle", update)
        audit("export_bundle", update)
        await edit("📦 Export bundle requested. Check the server's backup directory for the zip.", diagnostics_menu())

    # -----------------------------------------------------------------------
    # Schedule (ADR-0019)
    # -----------------------------------------------------------------------

    elif data == "sch_view":
        if await admin_required(): return
        restart_enabled = state._STATE.get("schedule_enabled", False)
        restart_time = state._STATE.get("schedule_time", "03:00")
        bkp_enabled = state._STATE.get("schedule_backup_enabled", False)
        bkp_time = state._STATE.get("schedule_backup_time", "02:00")
        lines = [
            "<b>📅 Scheduled Tasks</b>\n",
            f"🔄 Restart: {'✅ ' + restart_time + ' UTC' if restart_enabled else '❌ Disabled'}",
            f"💾 Backup:  {'✅ ' + bkp_time + ' UTC' if bkp_enabled else '❌ Disabled'}",
        ]
        await edit("\n".join(lines), schedule_menu_keyboard())

    elif data == "sch_backup_toggle":
        if await admin_required(): return
        state._STATE["schedule_backup_enabled"] = not state._STATE.get("schedule_backup_enabled", False)
        state.save()
        enabled = state._STATE["schedule_backup_enabled"]
        audit_log.record("schedule_backup_toggle", update, enabled=enabled)
        await edit(f"💾 Scheduled backup {'enabled' if enabled else 'disabled'}.", schedule_menu_keyboard())

    # -----------------------------------------------------------------------
    # Mods & Workshop (ADR-0016)
    # -----------------------------------------------------------------------

    elif data == "mod_list":
        if await admin_required(): return
        mods = state._STATE.get("mods", [])
        if not mods:
            await edit("📋 No mods installed.", mods_menu())
            return
        lines = []
        for m in mods:
            pin = " 📌" if m.get("pinned") else ""
            lines.append(f"  🧩 <b>{html.escape(m.get('name', m.get('id', '?')))}</b>{pin} v{m.get('version', '?')}")
        await edit("<b>Installed Mods:</b>\n" + "\n".join(lines), mods_menu())

    elif data == "mod_sync_ask":
        if await admin_required(): return
        remaining = cooldown_check("mod_sync")
        if remaining:
            await query.answer(f"Cooldown: {remaining}s remaining.", show_alert=True)
            return
        await edit(
            f"{attribution_line(user)}\n\n"
            "🔄 Sync all mods via SteamCMD?\n<b>Backup-First policy applies.</b>\n<i>Class 2</i>",
            class2_confirm_keyboard("mod_sync"),
        )

    elif data == "cb_c2confirmed_mod_sync":
        if await admin_required(): return
        from windrose_bot.config import MODS_SYNC_SCRIPT
        set_cooldown(uid, "mod_sync")
        audit_log.record("mod_sync", update)
        await edit("🔄 Syncing mods...")
        proc = await asyncio.to_thread(
            subprocess.run,
            ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", MODS_SYNC_SCRIPT],
            capture_output=True, text=True, timeout=600,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        await edit(f"<b>Mod sync:</b> {result}", mods_menu())

    elif data == "mod_conflicts":
        if await admin_required(): return
        mods = state._STATE.get("mods", [])
        await edit(f"⚠️ Conflict check: {len(mods)} mod(s) installed. No conflicts detected (manual review recommended).", mods_menu())

    elif data == "mod_add_ask":
        if await admin_required(): return
        context.user_data["_fsm_name"] = "ADD_MOD"
        await edit("Send the Steam Workshop ID to add. /cancel to abort.", back_keyboard("nav_mods"))

    # -----------------------------------------------------------------------
    # Audit Trail (ADR-0017)
    # -----------------------------------------------------------------------

    elif data in ("aud_recent", "aud_config_history", "aud_ops_history"):
        if await admin_required(): return
        filter_map = {
            "aud_config_history": "change_password",
            "aud_ops_history": None,
        }
        action_filter = filter_map.get(data)
        entries = audit_log.load_recent(limit=10, action_filter=action_filter)
        if not entries:
            await edit("🛡 No audit records found.", audit_menu())
            return
        lines = [f"<b>Audit Trail</b> ({len(entries)} recent):\n"]
        for e in entries:
            lines.append(audit_log.format_entry(e))
        await edit("\n".join(lines)[:4000], audit_menu())

    # -----------------------------------------------------------------------
    # Notifications (ADR-0020)
    # -----------------------------------------------------------------------

    elif data.startswith("ntf_toggle_"):
        channel = data[len("ntf_toggle_"):]
        uid_key = str(uid)
        channels = state._STATE.setdefault("user_channels", {}).setdefault(uid_key, {})
        default_on = channel in ("restarts", "health")
        channels[channel] = not channels.get(channel, default_on)
        state.save()
        status = "on" if channels[channel] else "off"
        await query.answer(f"{channel.capitalize()} alerts: {status}")
        await query.edit_message_text(
            "<b>Notifications</b>\nToggle alert channels:",
            parse_mode=ParseMode.HTML,
            reply_markup=notifications_menu(user_id=uid),
        )

    # -----------------------------------------------------------------------
    # Legacy v2_notify_sub
    # -----------------------------------------------------------------------

    elif data == "v2_notify_sub":
        if await container.running():
            await edit("Server is already online!", notifications_menu(user_id=uid))
            return
        waitlist: list = state._STATE["notify_waitlist"]
        if uid not in waitlist:
            waitlist.append(uid)
            state.save()
        await edit("🔔 You'll be notified when the server comes online.", notifications_menu(user_id=uid))

    # -----------------------------------------------------------------------
    # Users & Roles
    # -----------------------------------------------------------------------

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

    # -----------------------------------------------------------------------
    # Schedule (existing flow entry points)
    # -----------------------------------------------------------------------

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
        audit_log.record("schedule_toggle", update, enabled=enabled)
        audit("schedule_toggle", update, enabled=enabled)
        sched_status = "enabled" if enabled else "disabled"
        await edit(f"✅ Scheduled restart {sched_status}.", schedule_menu_keyboard())

    # -----------------------------------------------------------------------
    # Existing confirmed actions (Class 1)
    # -----------------------------------------------------------------------

    elif data == "cb_confirmed_backup":
        if await admin_required(): return
        audit_log.record("backup", update)
        audit("backup", update)
        await edit("Backup started...")
        proc = await asyncio.to_thread(
            subprocess.run,
            ["powershell.exe", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", BACKUP_SCRIPT],
            capture_output=True, text=True, timeout=300,
        )
        result = "OK" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        audit_log.record("backup", update, result=result)
        await edit(f"<b>Backup:</b> {result}", backups_menu())

    elif data == "cb_confirmed_restart":
        if await admin_required(): return
        audit_log.record("restart", update)
        audit("restart", update)
        await edit("Restarting...")
        try:
            await container.restart()
        except container.ServiceControlError as exc:
            audit_log.record("restart", update, result="failed", reason=str(exc))
            await edit(f"<b>Restart failed:</b>\n<pre>{html.escape(str(exc))[:3000]}</pre>", operations_menu())
            return
        await edit("<b>Restart issued.</b> Server active in ~30s.", operations_menu())

    elif data == "cb_confirmed_stop":
        if await admin_required(): return
        audit_log.record("stop", update)
        audit("stop", update)
        await edit("Stopping...")
        try:
            await container.stop()
        except container.ServiceControlError as exc:
            audit_log.record("stop", update, result="failed", reason=str(exc))
            await edit(f"<b>Stop failed:</b>\n<pre>{html.escape(str(exc))[:3000]}</pre>", operations_menu())
            return
        await edit("<b>Server stopped.</b>", operations_menu())


    # -----------------------------------------------------------------------
    # Server Settings (cfg_server_menu / srv_*)
    # -----------------------------------------------------------------------

    elif data == "cfg_server_menu":
        if await admin_required(): return
        await edit(srv_settings.server_summary(), server_settings_menu())

    elif data == "srv_set_name":
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", server_settings_menu())
            return
        context.user_data["_fsm_name"] = "SET_SERVER_NAME"
        await edit("Send the new server name (or /cancel):", back_keyboard("cfg_server_menu"))

    elif data == "srv_set_maxplayers":
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", server_settings_menu())
            return
        cur = srv_settings.get_persistent("MaxPlayerCount", "?")
        await edit(f"Select max players (current: <b>{cur}</b>):", max_players_menu())

    elif data.startswith("srv_maxplayers_"):
        if await admin_required(): return
        n = int(data.split("_")[-1])
        srv_settings.set_persistent("MaxPlayerCount", n)
        audit_log.record("set_max_players", update, value=n)
        audit("set_max_players", update, value=n)
        await edit(f"✅ Max players set to <b>{n}</b>.", server_settings_menu())

    elif data == "srv_set_region":
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", server_settings_menu())
            return
        cur = srv_settings.get_persistent("UserSelectedRegion") or "Auto"
        await edit(f"Select region (current: <b>{html.escape(cur)}</b>):", region_menu())

    elif data.startswith("srv_region_"):
        if await admin_required(): return
        region = data[len("srv_region_"):]   # "" = auto, "EU", "SEA", "CIS"
        srv_settings.set_persistent("UserSelectedRegion", region)
        audit_log.record("set_region", update, region=region or "auto")
        audit("set_region", update, region=region or "auto")
        label = region or "Auto"
        await edit(f"✅ Region set to <b>{label}</b>.", server_settings_menu())

    elif data == "srv_set_directconnect":
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", server_settings_menu())
            return
        current = srv_settings.get_persistent("UseDirectConnection", False)
        srv_settings.set_persistent("UseDirectConnection", not current)
        audit_log.record("toggle_direct_connect", update, enabled=not current)
        audit("toggle_direct_connect", update)
        status = "enabled" if not current else "disabled"
        await edit(f"🔌 Direct connection <b>{status}</b>.", server_settings_menu())

    # -----------------------------------------------------------------------
    # World Settings (cfg_world_menu / wld_*)
    # -----------------------------------------------------------------------

    elif data == "cfg_world_menu":
        if await admin_required(): return
        try:
            summary = srv_settings.world_summary()
        except Exception as exc:
            summary = f"⚠️ Could not read world config: {html.escape(str(exc))}"
        await edit(summary, world_settings_menu())

    elif data == "wld_view":
        if await admin_required(): return
        try:
            await edit(srv_settings.world_summary(), world_settings_menu())
        except Exception as exc:
            await edit(f"⚠️ {html.escape(str(exc))}", world_settings_menu())

    elif data == "wld_set_name":
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", world_settings_menu())
            return
        context.user_data["_fsm_name"] = "SET_WORLD_NAME"
        await edit("Send the new world name (or /cancel):", back_keyboard("cfg_world_menu"))

    elif data.startswith("wld_preset_"):
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", world_settings_menu())
            return
        preset = data[len("wld_preset_"):]   # Easy | Medium | Hard
        remaining = check_cooldown(uid, f"preset_{preset}")
        if remaining:
            await query.answer(f"Cooldown: {remaining}s remaining.", show_alert=True)
            return
        await edit(
            f"{attribution_line(user)}\n\n"
            f"Apply <b>{preset}</b> preset? This overwrites all custom world parameters.\n<i>Class 2</i>",
            class2_confirm_keyboard(f"preset_{preset}"),
        )

    elif data.startswith("cb_c2confirmed_preset_"):
        if await admin_required(): return
        preset = data[len("cb_c2confirmed_preset_"):]
        try:
            srv_settings.set_world_preset(preset)
            set_cooldown(uid, f"preset_{preset}")
            audit_log.record("set_world_preset", update, preset=preset)
            audit("set_world_preset", update, preset=preset)
            await edit(f"✅ <b>{preset}</b> preset applied.", world_settings_menu())
        except Exception as exc:
            await edit(f"⚠️ Failed: {html.escape(str(exc))}", world_settings_menu())

    elif data == "wld_combat_menu":
        if await admin_required(): return
        cur = srv_settings.get_combat_difficulty()
        await edit(f"Combat difficulty (current: <b>{cur}</b>):", combat_difficulty_menu())

    elif data.startswith("wld_combat_"):
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", world_settings_menu())
            return
        level = data[len("wld_combat_"):]    # Easy | Normal | Hard
        try:
            srv_settings.set_combat_difficulty(level)
            audit_log.record("set_combat_difficulty", update, level=level)
            audit("set_combat_difficulty", update, level=level)
            await edit(f"✅ Combat difficulty set to <b>{level}</b>.", world_settings_menu())
        except Exception as exc:
            await edit(f"⚠️ {html.escape(str(exc))}", world_settings_menu())

    elif data == "wld_toggle_shared_quests":
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", world_settings_menu())
            return
        from windrose_bot.services.settings import _T_SHARED_QUESTS
        cur = srv_settings.get_bool_param(_T_SHARED_QUESTS)
        new_val = not bool(cur if cur is not None else True)
        srv_settings.set_bool_param(_T_SHARED_QUESTS, new_val)
        audit_log.record("toggle_shared_quests", update, value=new_val)
        status = "✅ enabled" if new_val else "❌ disabled"
        await edit(f"🤝 Shared Quests {status}.", world_settings_menu())

    elif data == "wld_toggle_easy_explore":
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", world_settings_menu())
            return
        from windrose_bot.services.settings import _T_EASY_EXPLORE
        cur = srv_settings.get_bool_param(_T_EASY_EXPLORE)
        new_val = not bool(cur if cur is not None else False)
        srv_settings.set_bool_param(_T_EASY_EXPLORE, new_val)
        audit_log.record("toggle_immersive_explore", update, value=new_val)
        status = "✅ enabled" if new_val else "❌ disabled"
        await edit(f"🗺 Immersive Exploration {status}.", world_settings_menu())

    elif data == "wld_mob_menu":
        if await admin_required(): return
        await edit("<b>🩸 Mob Settings</b>", mob_settings_menu())

    elif data == "wld_ship_menu":
        if await admin_required(): return
        await edit("<b>🚢 Ship Settings</b>", ship_settings_menu())

    elif data == "wld_coop_menu":
        if await admin_required(): return
        await edit("<b>🏴‍☠️ Boarding / Coop</b>", coop_settings_menu())

    # Multiplier pickers — each opens a grid of values
    elif data in ("wld_pick_mob_hp", "wld_pick_mob_dmg", "wld_pick_ship_hp",
                  "wld_pick_ship_dmg", "wld_pick_boarding", "wld_pick_coop_stats", "wld_pick_coop_ships"):
        if await admin_required(): return
        tag_short = data[len("wld_pick_"):]
        labels = {
            "mob_hp": "🩸 Mob HP", "mob_dmg": "⚔️ Mob Damage",
            "ship_hp": "🚢 Ship HP", "ship_dmg": "💥 Ship Damage",
            "boarding": "🏴‍☠️ Boarding", "coop_stats": "👥 Coop Stats", "coop_ships": "🚢 Coop Ships",
        }
        tag_map = {
            "mob_hp": "WDS.Parameter.MobHealthMultiplier",
            "mob_dmg": "WDS.Parameter.MobDamageMultiplier",
            "ship_hp": "WDS.Parameter.ShipsHealthMultiplier",
            "ship_dmg": "WDS.Parameter.ShipsDamageMultiplier",
            "boarding": "WDS.Parameter.BoardingDifficultyMultiplier",
            "coop_stats": "WDS.Parameter.Coop.StatsCorrectionModifier",
            "coop_ships": "WDS.Parameter.Coop.ShipStatsCorrectionModifier",
        }
        from windrose_bot.services import settings as s
        full_tag = '{"TagName": "' + tag_map[tag_short] + '"}'
        cur = s.get_float_param(full_tag)
        back = {"mob_hp": "wld_mob_menu", "mob_dmg": "wld_mob_menu",
                "ship_hp": "wld_ship_menu", "ship_dmg": "wld_ship_menu"}.get(tag_short, "wld_coop_menu")
        label = labels.get(tag_short, tag_short)
        await edit(f"{label} (current: <b>×{cur}</b>)\nSelect new value:", multiplier_keyboard(tag_short, back))

    elif data.startswith("wld_float_"):
        if await admin_required(): return
        if await container.running():
            await edit("⚠️ Stop the server before changing config.", world_settings_menu())
            return
        # format: wld_float_mob_hp_1.5
        parts = data[len("wld_float_"):].rsplit("_", 1)
        tag_short, value_str = parts[0], parts[1]
        tag_map = {
            "mob_hp": "WDS.Parameter.MobHealthMultiplier",
            "mob_dmg": "WDS.Parameter.MobDamageMultiplier",
            "ship_hp": "WDS.Parameter.ShipsHealthMultiplier",
            "ship_dmg": "WDS.Parameter.ShipsDamageMultiplier",
            "boarding": "WDS.Parameter.BoardingDifficultyMultiplier",
            "coop_stats": "WDS.Parameter.Coop.StatsCorrectionModifier",
            "coop_ships": "WDS.Parameter.Coop.ShipStatsCorrectionModifier",
        }
        try:
            value = float(value_str)
            full_tag = '{"TagName": "' + tag_map[tag_short] + '"}'
            srv_settings.set_float_param(full_tag, value)
            audit_log.record("set_float_param", update, param=tag_short, value=value)
            audit("set_float_param", update, param=tag_short, value=value)
            await edit(f"✅ <b>{tag_short.replace('_', ' ').title()}</b> set to ×{value}.", world_settings_menu())
        except Exception as exc:
            await edit(f"⚠️ {html.escape(str(exc))}", world_settings_menu())


def build_callback_handlers():
    from telegram.ext import CallbackQueryHandler
    return [CallbackQueryHandler(button_handler)]

"""keyboards/menus.py — InlineKeyboardMarkup builders."""
from __future__ import annotations

import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from windrose_bot import state
from windrose_bot.config import SERVER_DESC_PATH


def main_panel() -> InlineKeyboardMarkup:
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


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, proceed", callback_data=f"cb_confirmed_{action}"),
        InlineKeyboardButton("❌ Cancel",       callback_data="cb_panel"),
    ]])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("« Back", callback_data="cb_panel"),
    ]])


def sysinfo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="v2_sysinfo")],
        [InlineKeyboardButton("« Back",    callback_data="cb_panel")],
    ])


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 View Invite Code",  callback_data="v2_settings_invite")],
        [InlineKeyboardButton("🔒 Change Password",   callback_data="v2_settings_changepw")],
        [InlineKeyboardButton("🔓 Remove Password",   callback_data="v2_settings_removepw_ask")],
        [InlineKeyboardButton("« Back",               callback_data="cb_panel")],
    ])


def users_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Users",       callback_data="v2_users_list")],
        [InlineKeyboardButton("➕ Add Admin",         callback_data="v2_users_add_admin")],
        [InlineKeyboardButton("➕ Add Notify User",  callback_data="v2_users_add_notify")],
        [InlineKeyboardButton("➖ Remove User",       callback_data="v2_users_remove")],
        [InlineKeyboardButton("« Back",              callback_data="cb_panel")],
    ])


def schedule_menu_keyboard() -> InlineKeyboardMarkup:
    enabled = state._STATE.get("schedule_enabled", False)
    toggle_label = "✅ Enabled — Disable" if enabled else "❌ Disabled — Enable"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 View Schedule",    callback_data="v2_schedule_view")],
        [InlineKeyboardButton("⏰ Set Time",          callback_data="v2_schedule_set")],
        [InlineKeyboardButton(toggle_label,           callback_data="v2_schedule_toggle")],
        [InlineKeyboardButton("« Back",              callback_data="cb_panel")],
    ])


def read_server_desc() -> dict:
    try:
        return json.loads(SERVER_DESC_PATH.read_text())
    except Exception:
        return {}


def write_server_desc(data: dict) -> None:
    tmp = SERVER_DESC_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(SERVER_DESC_PATH)

"""keyboards/menus.py — InlineKeyboardMarkup builders and status header."""
from __future__ import annotations

import html
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from windrose_bot import state
from windrose_bot.config import SERVER_DESC_PATH


# ---------------------------------------------------------------------------
# ADR-0013 — Persistent status header
# ---------------------------------------------------------------------------

async def build_status_header() -> str:
    """Return a one-or-two-line HTML header rendered above every menu."""
    from windrose_bot.services import container

    try:
        running = await container.running()
    except Exception:
        running = None

    if running is True:
        indicator = "🟢 ONLINE"
        uptime = container.uptime()
    elif running is False:
        indicator = "🔴 OFFLINE"
        uptime = "—"
    else:
        indicator = "❔ UNKNOWN"
        uptime = "—"

    players = state.known_players()
    player_str = f"{len(players)} player{'s' if len(players) != 1 else ''}"

    desc = read_server_desc()
    world = desc.get("WorldIslandId") or desc.get("worldIslandId") or "—"

    maintenance = "🚧 Maintenance" if state._STATE.get("maintenance_mode") else ""

    line1 = f"{indicator} · {player_str} · ⏱ {uptime}"
    line2_parts = [f"🌍 {html.escape(str(world))}"]
    if maintenance:
        line2_parts.append(maintenance)
    line2 = " · ".join(line2_parts)

    return f"<b>{line1}</b>\n<i>{line2}</i>"


# ---------------------------------------------------------------------------
# Home menu (ADR-0014 icon vocabulary)
# ---------------------------------------------------------------------------

def home_menu(*, is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("👥 Players",      callback_data="nav_players"),
            InlineKeyboardButton("🔔 Notifications", callback_data="nav_notifications"),
        ],
    ]
    if is_admin:
        rows += [
            [
                InlineKeyboardButton("🎛 Operations",    callback_data="nav_operations"),
                InlineKeyboardButton("⚙️ Configuration", callback_data="nav_config"),
            ],
            [
                InlineKeyboardButton("🧩 Mods",     callback_data="nav_mods"),
                InlineKeyboardButton("📅 Schedule", callback_data="nav_schedule"),
            ],
            [
                InlineKeyboardButton("💾 Backups",     callback_data="nav_backups"),
                InlineKeyboardButton("🩺 Diagnostics", callback_data="nav_diagnostics"),
            ],
            [
                InlineKeyboardButton("🛡 Audit Trail", callback_data="nav_audit"),
                InlineKeyboardButton("👤 Users",        callback_data="v2_users_menu"),
            ],
        ]
    return InlineKeyboardMarkup(rows)


def main_panel(*, is_admin: bool = True) -> InlineKeyboardMarkup:
    return home_menu(is_admin=is_admin)


# ---------------------------------------------------------------------------
# Players (ADR-0015)
# ---------------------------------------------------------------------------

def players_menu(*, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📋 Online Players", callback_data="plr_online")],
    ]
    if is_admin:
        rows += [
            [
                InlineKeyboardButton("🚪 Kick Player", callback_data="plr_kick_ask"),
                InlineKeyboardButton("⛔ Ban Player",  callback_data="plr_ban_ask"),
            ],
            [
                InlineKeyboardButton("📜 Ban List",   callback_data="plr_banlist"),
                InlineKeyboardButton("✅ Whitelist",  callback_data="plr_whitelist"),
            ],
        ]
    rows.append([InlineKeyboardButton("« Back", callback_data="cb_panel")])
    return InlineKeyboardMarkup(rows)


def ban_duration_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 hour",    callback_data="plr_ban_dur_1h"),
            InlineKeyboardButton("24 hours",  callback_data="plr_ban_dur_24h"),
        ],
        [
            InlineKeyboardButton("7 days",    callback_data="plr_ban_dur_7d"),
            InlineKeyboardButton("Permanent", callback_data="plr_ban_dur_perm"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="nav_players")],
    ])


def banlist_menu(bans: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, b in enumerate(bans[:8]):
        name = b.get("name", "?")[:20]
        rows.append([InlineKeyboardButton(
            f"🔓 Lift: {name}", callback_data=f"plr_liftban_{i}"
        )])
    rows.append([InlineKeyboardButton("« Back", callback_data="nav_players")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Operations (ADR-0014 icon: 🎛)
# ---------------------------------------------------------------------------

def operations_menu() -> InlineKeyboardMarkup:
    maintenance = state._STATE.get("maintenance_mode", False)
    maint_label = "🚧 Disable Maintenance" if maintenance else "🚧 Maintenance Mode"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Start",       callback_data="cb_start"),
            InlineKeyboardButton("⏹ Stop",          callback_data="cb_stop_ask"),
        ],
        [
            InlineKeyboardButton("🔄 Restart...",   callback_data="nav_restart_delay"),
            InlineKeyboardButton("🛑 Force Stop",   callback_data="cb_forcestop_ask"),
        ],
        [
            InlineKeyboardButton("🔃 Update",       callback_data="cb_update_ask"),
            InlineKeyboardButton(maint_label,        callback_data="cb_maintenance_toggle"),
        ],
        [InlineKeyboardButton("📡 Broadcast",       callback_data="ops_broadcast_ask")],
        [InlineKeyboardButton("« Back",             callback_data="cb_panel")],
    ])


def restart_delay_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Restart Now",   callback_data="cb_restart_ask")],
        [
            InlineKeyboardButton("+1 min",  callback_data="cb_restart_delay_1"),
            InlineKeyboardButton("+5 min",  callback_data="cb_restart_delay_5"),
        ],
        [
            InlineKeyboardButton("+15 min", callback_data="cb_restart_delay_15"),
            InlineKeyboardButton("+30 min", callback_data="cb_restart_delay_30"),
        ],
        [InlineKeyboardButton("« Back", callback_data="nav_operations")],
    ])


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def config_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 View Config",       callback_data="cfg_view")],
        [
            InlineKeyboardButton("🔑 Invite Code",    callback_data="v2_settings_invite"),
            InlineKeyboardButton("🔒 Password",       callback_data="cfg_password_menu"),
        ],
        [InlineKeyboardButton("🌐 Server Settings",   callback_data="cfg_server_menu")],
        [InlineKeyboardButton("⚔️ World Settings",    callback_data="cfg_world_menu")],
        [InlineKeyboardButton("🔎 Validate Config",   callback_data="cfg_validate")],
        [InlineKeyboardButton("📜 Config History",    callback_data="aud_config_history")],
        [InlineKeyboardButton("« Back",               callback_data="cb_panel")],
    ])


def config_password_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Change Password",  callback_data="v2_settings_changepw")],
        [InlineKeyboardButton("🔓 Remove Password",  callback_data="v2_settings_removepw_ask")],
        [InlineKeyboardButton("« Back",              callback_data="nav_config")],
    ])


def server_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Server Name",      callback_data="srv_set_name")],
        [
            InlineKeyboardButton("👥 Max Players",   callback_data="srv_set_maxplayers"),
            InlineKeyboardButton("🌍 Region",        callback_data="srv_set_region"),
        ],
        [InlineKeyboardButton("🔌 Direct Connect",  callback_data="srv_set_directconnect")],
        [InlineKeyboardButton("« Back",             callback_data="nav_config")],
    ])


def max_players_menu() -> InlineKeyboardMarkup:
    from windrose_bot.services.settings import MAX_PLAYERS_OPTIONS
    buttons = [
        InlineKeyboardButton(str(n), callback_data=f"srv_maxplayers_{n}")
        for n in MAX_PLAYERS_OPTIONS
    ]
    rows = [buttons[i:i+4] for i in range(0, len(buttons), 4)]
    rows.append([InlineKeyboardButton("« Back", callback_data="cfg_server_menu")])
    return InlineKeyboardMarkup(rows)


def region_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 Auto",  callback_data="srv_region_"),
            InlineKeyboardButton("🇪🇺 EU",   callback_data="srv_region_EU"),
        ],
        [
            InlineKeyboardButton("🌏 SEA",   callback_data="srv_region_SEA"),
            InlineKeyboardButton("🇷🇺 CIS",  callback_data="srv_region_CIS"),
        ],
        [InlineKeyboardButton("« Back", callback_data="cfg_server_menu")],
    ])


def world_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 View World Settings",  callback_data="wld_view")],
        [InlineKeyboardButton("✏️ World Name",           callback_data="wld_set_name")],
        [
            InlineKeyboardButton("🟢 Easy",    callback_data="wld_preset_Easy"),
            InlineKeyboardButton("🟡 Medium",  callback_data="wld_preset_Medium"),
            InlineKeyboardButton("🔴 Hard",    callback_data="wld_preset_Hard"),
        ],
        [
            InlineKeyboardButton("⚔️ Combat Difficulty",  callback_data="wld_combat_menu"),
            InlineKeyboardButton("🤝 Shared Quests",      callback_data="wld_toggle_shared_quests"),
        ],
        [InlineKeyboardButton("🗺 Immersive Explore",    callback_data="wld_toggle_easy_explore")],
        [InlineKeyboardButton("🩸 Mob Settings",         callback_data="wld_mob_menu")],
        [InlineKeyboardButton("🚢 Ship Settings",        callback_data="wld_ship_menu")],
        [InlineKeyboardButton("🏴‍☠️ Boarding / Coop",    callback_data="wld_coop_menu")],
        [InlineKeyboardButton("« Back",                  callback_data="nav_config")],
    ])


def combat_difficulty_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Easy",    callback_data="wld_combat_Easy"),
            InlineKeyboardButton("🟡 Normal",  callback_data="wld_combat_Normal"),
            InlineKeyboardButton("🔴 Hard",    callback_data="wld_combat_Hard"),
        ],
        [InlineKeyboardButton("« Back", callback_data="cfg_world_menu")],
    ])


def multiplier_keyboard(tag_short: str, back: str = "cfg_world_menu") -> InlineKeyboardMarkup:
    """Inline buttons for float multiplier selection."""
    steps = [0.2, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
    buttons = [
        InlineKeyboardButton(f"×{v}", callback_data=f"wld_float_{tag_short}_{v}")
        for v in steps
    ]
    rows = [buttons[i:i+3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton("« Back", callback_data=back)])
    return InlineKeyboardMarkup(rows)


def mob_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🩸 Mob HP",     callback_data="wld_pick_mob_hp")],
        [InlineKeyboardButton("⚔️ Mob Damage", callback_data="wld_pick_mob_dmg")],
        [InlineKeyboardButton("« Back",        callback_data="cfg_world_menu")],
    ])


def ship_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚢 Ship HP",      callback_data="wld_pick_ship_hp")],
        [InlineKeyboardButton("💥 Ship Damage",  callback_data="wld_pick_ship_dmg")],
        [InlineKeyboardButton("« Back",          callback_data="cfg_world_menu")],
    ])


def coop_settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏴‍☠️ Boarding ×",    callback_data="wld_pick_boarding")],
        [InlineKeyboardButton("👥 Coop Stats ×",   callback_data="wld_pick_coop_stats")],
        [InlineKeyboardButton("🚢 Coop Ships ×",   callback_data="wld_pick_coop_ships")],
        [InlineKeyboardButton("« Back",            callback_data="cfg_world_menu")],
    ])


# ---------------------------------------------------------------------------
# Backups (ADR-0018)
# ---------------------------------------------------------------------------

def backups_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Backups",    callback_data="bkp_list")],
        [
            InlineKeyboardButton("💾 Create Backup",  callback_data="cb_backup_ask"),
            InlineKeyboardButton("🎯 Policy",         callback_data="bkp_policy"),
        ],
        [InlineKeyboardButton("⏪ Restore Backup",  callback_data="bkp_restore_ask")],
        [InlineKeyboardButton("« Back",             callback_data="cb_panel")],
    ])


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def diagnostics_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Logs",         callback_data="cb_logs"),
            InlineKeyboardButton("🖥 Sys Info",     callback_data="v2_sysinfo"),
        ],
        [
            InlineKeyboardButton("⏱ Uptime",        callback_data="cb_uptime"),
            InlineKeyboardButton("🔍 Integrity",    callback_data="diag_integrity"),
        ],
        [InlineKeyboardButton("📦 Export Bundle",  callback_data="diag_bundle")],
        [InlineKeyboardButton("« Back",            callback_data="cb_panel")],
    ])


# ---------------------------------------------------------------------------
# Schedule (ADR-0019)
# ---------------------------------------------------------------------------

def schedule_menu_keyboard() -> InlineKeyboardMarkup:
    enabled = state._STATE.get("schedule_enabled", False)
    toggle_label = "✅ Restart: ON — Disable" if enabled else "❌ Restart: OFF — Enable"
    bkp_enabled = state._STATE.get("schedule_backup_enabled", False)
    bkp_label = "💾 Backup: ON — Disable" if bkp_enabled else "💾 Backup: OFF — Enable"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 View Schedule",    callback_data="sch_view")],
        [InlineKeyboardButton("⏰ Set Restart Time", callback_data="v2_schedule_set")],
        [InlineKeyboardButton(toggle_label,          callback_data="v2_schedule_toggle")],
        [InlineKeyboardButton(bkp_label,             callback_data="sch_backup_toggle")],
        [InlineKeyboardButton("⏰ Set Backup Time",  callback_data="sch_backup_set")],
        [InlineKeyboardButton("« Back",             callback_data="cb_panel")],
    ])


# ---------------------------------------------------------------------------
# Mods & Workshop (ADR-0016)
# ---------------------------------------------------------------------------

def mods_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Installed Mods",  callback_data="mod_list")],
        [
            InlineKeyboardButton("➕ Add Mod",      callback_data="mod_add_ask"),
            InlineKeyboardButton("🔄 Sync All",     callback_data="mod_sync_ask"),
        ],
        [InlineKeyboardButton("⚠️ Conflict Check", callback_data="mod_conflicts")],
        [InlineKeyboardButton("« Back",             callback_data="cb_panel")],
    ])


# ---------------------------------------------------------------------------
# Audit Trail (ADR-0017)
# ---------------------------------------------------------------------------

def audit_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Recent Actions", callback_data="aud_recent")],
        [
            InlineKeyboardButton("🔎 Config Changes", callback_data="aud_config_history"),
            InlineKeyboardButton("🔎 Operations",     callback_data="aud_ops_history"),
        ],
        [InlineKeyboardButton("« Back", callback_data="cb_panel")],
    ])


# ---------------------------------------------------------------------------
# Notifications (ADR-0020)
# ---------------------------------------------------------------------------

def notifications_menu(user_id: int | None = None) -> InlineKeyboardMarkup:
    channels = state._STATE.get("user_channels", {}).get(str(user_id), {})

    def _label(ch: str, icon: str, name: str) -> str:
        active = channels.get(ch, ch in ("restarts", "health"))
        tick = "✅" if active else "☐"
        return f"{tick} {icon} {name}"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_label("restarts", "🔄", "Restarts"), callback_data="ntf_toggle_restarts")],
        [InlineKeyboardButton(_label("health",   "🚦", "Health"),   callback_data="ntf_toggle_health")],
        [InlineKeyboardButton(_label("players",  "👥", "Players"),  callback_data="ntf_toggle_players")],
        [InlineKeyboardButton(_label("mods",     "🧩", "Mods"),     callback_data="ntf_toggle_mods")],
        [InlineKeyboardButton(_label("backups",  "💾", "Backups"),  callback_data="ntf_toggle_backups")],
        [InlineKeyboardButton("« Back", callback_data="cb_panel")],
    ])


# ---------------------------------------------------------------------------
# Users & Roles
# ---------------------------------------------------------------------------

def users_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 List Users",       callback_data="v2_users_list")],
        [
            InlineKeyboardButton("➕ Add Admin",      callback_data="v2_users_add_admin"),
            InlineKeyboardButton("➕ Add Notify",     callback_data="v2_users_add_notify"),
        ],
        [InlineKeyboardButton("➖ Remove User",       callback_data="v2_users_remove")],
        [InlineKeyboardButton("« Back",              callback_data="cb_panel")],
    ])


# ---------------------------------------------------------------------------
# Confirmation keyboards
# ---------------------------------------------------------------------------

def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Class 1 — single inline confirm."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=f"cb_confirmed_{action}"),
        InlineKeyboardButton("❌ Cancel",  callback_data="cb_panel"),
    ]])


def class2_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Class 2 — confirm button shown after summary card."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=f"cb_c2confirmed_{action}"),
        InlineKeyboardButton("❌ Cancel",  callback_data="cb_panel"),
    ]])


def back_keyboard(dest: str = "cb_panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data=dest)]])


def sysinfo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="v2_sysinfo")],
        [InlineKeyboardButton("« Back",    callback_data="nav_diagnostics")],
    ])


# ---------------------------------------------------------------------------
# Legacy aliases (keep existing callers happy)
# ---------------------------------------------------------------------------

def server_menu() -> InlineKeyboardMarkup:
    return back_keyboard("cb_panel")


def monitoring_menu() -> InlineKeyboardMarkup:
    return diagnostics_menu()


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Users",            callback_data="v2_users_menu"),
            InlineKeyboardButton("⚙️ Server Settings",  callback_data="v2_settings_menu"),
        ],
        [InlineKeyboardButton("📅 Schedule", callback_data="nav_schedule")],
        [InlineKeyboardButton("« Back", callback_data="cb_panel")],
    ])


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    return config_password_menu()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_server_desc() -> dict:
    try:
        return json.loads(SERVER_DESC_PATH.read_text())
    except Exception:
        return {}


def write_server_desc(data: dict) -> None:
    tmp = SERVER_DESC_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(SERVER_DESC_PATH)

"""handlers/flows.py — ConversationHandler FSMs (ADR-011)."""
from __future__ import annotations

import datetime
import html
import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from windrose_bot import config, state
from windrose_bot.core import audit as audit_log
from windrose_bot.core.safety import consume_class3_token
from windrose_bot.core.security import audit, restricted
from windrose_bot.keyboards.menus import (
    back_keyboard,
    backups_menu,
    mods_menu,
    operations_menu,
    players_menu,
    schedule_menu_keyboard,
    server_settings_menu,
    settings_menu_keyboard,
    world_settings_menu,
)
from windrose_bot.services import container

log = logging.getLogger(__name__)

_WAITING = 1


async def flow_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("_fsm_name", None)
    context.user_data.pop("_fsm_sensitive", None)
    context.user_data.pop("_ban_duration", None)
    context.user_data.pop("_class3_action", None)
    context.user_data.pop("_class3_resource", None)
    if update.callback_query:
        await update.callback_query.answer("Cancelled.")
        await update.callback_query.edit_message_text("Cancelled.")
    elif update.message:
        await update.message.reply_text("Cancelled.", reply_markup=back_keyboard())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# CHANGE_PASSWORD
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_changepw_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if await container.running():
        await query.edit_message_text(
            "⚠️ Server must be stopped before changing config. Stop it first.",
            reply_markup=settings_menu_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    context.user_data["_fsm_name"] = "CHANGE_PASSWORD"
    context.user_data["_fsm_sensitive"] = True
    await query.edit_message_text("Send the new server password. /cancel to abort.")
    return _WAITING


async def flow_changepw_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_pw = (update.message.text or "").strip()
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
        )
    except Exception as e:
        log.warning("password message delete failed: %s", e)
    from windrose_bot.keyboards.menus import read_server_desc, write_server_desc
    desc = read_server_desc()
    desc["ServerPassword"] = new_pw
    write_server_desc(desc)
    audit_log.record("change_password", update)
    audit("change_password", update)
    context.user_data.pop("_fsm_name", None)
    context.user_data.pop("_fsm_sensitive", None)
    await update.message.reply_text("✅ Password updated.", reply_markup=back_keyboard())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ADD_ADMIN / ADD_NOTIFY / REMOVE_USER
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_add_admin_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "ADD_ADMIN"
    await update.callback_query.edit_message_text(
        "Send the Telegram user ID to add as admin. /cancel to abort."
    )
    return _WAITING


async def flow_add_admin_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    try:
        new_id = int(text)
    except ValueError:
        await update.message.reply_text("Invalid ID. Must be a numeric Telegram user ID.")
        return _WAITING
    admins: list = state._STATE["users"]["admins"]
    if new_id not in admins:
        admins.append(new_id)
        state.save()
    audit_log.record("add_user", update, tier="admin", target_id=new_id)
    audit("add_user", update, tier="admin", target_id=new_id)
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(f"✅ Added {new_id} as admin.", reply_markup=back_keyboard())
    return ConversationHandler.END


@restricted(admin_only=True)
async def flow_add_notify_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "ADD_NOTIFY"
    await update.callback_query.edit_message_text(
        "Send the Telegram user ID to add as notify-only user. /cancel to abort."
    )
    return _WAITING


async def flow_add_notify_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    try:
        new_id = int(text)
    except ValueError:
        await update.message.reply_text("Invalid ID. Must be a numeric Telegram user ID.")
        return _WAITING
    notify_only: list = state._STATE["users"]["notify_only"]
    if new_id not in notify_only:
        notify_only.append(new_id)
        state.save()
    audit_log.record("add_user", update, tier="notify", target_id=new_id)
    audit("add_user", update, tier="notify", target_id=new_id)
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"✅ Added {new_id} as notify-only user.", reply_markup=back_keyboard()
    )
    return ConversationHandler.END


@restricted(admin_only=True)
async def flow_remove_user_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "REMOVE_USER"
    await update.callback_query.edit_message_text(
        "Send the Telegram user ID to remove. /cancel to abort."
    )
    return _WAITING


async def flow_remove_user_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    try:
        rm_id = int(text)
    except ValueError:
        await update.message.reply_text("Invalid ID. Must be a numeric Telegram user ID.")
        return _WAITING
    removed = False
    for tier in ("admins", "notify_only"):
        lst: list = state._STATE["users"][tier]
        if rm_id in lst:
            lst.remove(rm_id)
            removed = True
    if removed:
        state.save()
        audit_log.record("remove_user", update, target_id=rm_id)
        audit("remove_user", update, target_id=rm_id)
        await update.message.reply_text(f"✅ Removed user {rm_id}.", reply_markup=back_keyboard())
    else:
        await update.message.reply_text(
            f"User {rm_id} not found in any tier.", reply_markup=back_keyboard()
        )
    context.user_data.pop("_fsm_name", None)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# SET_SCHEDULE
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_schedule_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "SET_SCHEDULE"
    await update.callback_query.edit_message_text(
        "Send the restart time in HH:MM UTC format (e.g. 03:00). /cancel to abort."
    )
    return _WAITING


async def flow_schedule_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", text):
        await update.message.reply_text("Invalid format. Use HH:MM (e.g. 03:00).")
        return _WAITING
    try:
        h, m = map(int, text.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid time. Use HH:MM between 00:00 and 23:59.")
        return _WAITING
    state._STATE["schedule_time"] = f"{h:02d}:{m:02d}"
    state.save()
    from windrose_bot.main import cancel_scheduled_restart, register_scheduled_restart
    cancel_scheduled_restart()
    if state._STATE.get("schedule_enabled"):
        register_scheduled_restart(context.application)
    audit_log.record("set_schedule", update, time=state._STATE["schedule_time"])
    audit("set_schedule", update, time=state._STATE["schedule_time"])
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"✅ Schedule time set to {state._STATE['schedule_time']} UTC.",
        reply_markup=back_keyboard(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# SET_BACKUP_TIME
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_backup_time_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "SET_BACKUP_TIME"
    await update.callback_query.edit_message_text(
        "Send the backup time in HH:MM UTC format (e.g. 02:00). /cancel to abort."
    )
    return _WAITING


async def flow_backup_time_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", text):
        await update.message.reply_text("Invalid format. Use HH:MM.")
        return _WAITING
    try:
        h, m = map(int, text.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid time.")
        return _WAITING
    state._STATE["schedule_backup_time"] = f"{h:02d}:{m:02d}"
    state.save()
    audit_log.record("set_backup_schedule", update, time=state._STATE["schedule_backup_time"])
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"✅ Backup schedule time set to {state._STATE['schedule_backup_time']} UTC.",
        reply_markup=back_keyboard(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# KICK_PLAYER (ADR-0015)
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_kick_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Entry via direct callback — handled in callbacks.py; this is the FSM receive side
    # (entry point is plr_kick_ask which sets _fsm_name directly)
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "KICK_PLAYER"
    await update.callback_query.edit_message_text(
        "Send the player name to kick. /cancel to abort."
    )
    return _WAITING


async def flow_kick_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Player name cannot be empty.")
        return _WAITING
    audit_log.record("kick_player", update, target=name)
    audit("kick_player", update, target=name)
    # In a real integration, send the kick command to the server here.
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"🚪 Kick issued for <b>{html.escape(name)}</b>.\n<i>Note: requires RCON integration to take effect.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=players_menu(is_admin=True),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# BAN_PLAYER (ADR-0015)
# ---------------------------------------------------------------------------

async def flow_ban_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Player name cannot be empty.")
        return _WAITING
    dur_key = context.user_data.pop("_ban_duration", "perm")
    dur_map = {"1h": 1, "24h": 24, "7d": 24 * 7, "perm": None}
    hours = dur_map.get(dur_key)

    expires_iso = None
    if hours is not None:
        expires_iso = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
        ).isoformat().replace("+00:00", "Z")

    ban_entry = {
        "name": name,
        "reason": "Manual ban via bot",
        "expires": expires_iso,
        "banned_by": update.effective_user.id if update.effective_user else 0,
        "banned_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    state._STATE.setdefault("ban_list", []).append(ban_entry)
    state.save()
    audit_log.record("ban_player", update, target=name, duration=dur_key)
    audit("ban_player", update, target=name, duration=dur_key)
    context.user_data.pop("_fsm_name", None)
    exp_str = f"Expires: {expires_iso[:10]}" if expires_iso else "Permanent"
    await update.message.reply_text(
        f"⛔ <b>{html.escape(name)}</b> banned. {exp_str}",
        parse_mode=ParseMode.HTML,
        reply_markup=players_menu(is_admin=True),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# BROADCAST_MSG (new in Operations)
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_broadcast_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "BROADCAST_MSG"
    await update.callback_query.edit_message_text(
        "Send the message to broadcast to all players. /cancel to abort."
    )
    return _WAITING


async def flow_broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = (update.message.text or "").strip()
    if not msg:
        await update.message.reply_text("Message cannot be empty.")
        return _WAITING
    audit_log.record("broadcast", update, message=msg[:200])
    audit("broadcast", update)
    # In production: send via RCON or server API
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"📡 Broadcast sent: <i>{html.escape(msg[:200])}</i>\n<i>Note: requires RCON integration to reach in-game.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=operations_menu(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# ADD_MOD (ADR-0016)
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_add_mod_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "ADD_MOD"
    await update.callback_query.edit_message_text(
        "Send the Steam Workshop ID to add. /cancel to abort."
    )
    return _WAITING


async def flow_add_mod_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    mod_id = (update.message.text or "").strip()
    if not mod_id.isdigit():
        await update.message.reply_text("Workshop ID must be numeric.")
        return _WAITING
    mods: list = state._STATE.setdefault("mods", [])
    if any(m.get("id") == mod_id for m in mods):
        await update.message.reply_text(f"Mod {mod_id} is already installed.")
        return ConversationHandler.END
    mods.append({"id": mod_id, "name": f"mod_{mod_id}", "version": "latest", "pinned": False, "last_sync": None})
    state.save()
    audit_log.record("add_mod", update, mod_id=mod_id)
    audit("add_mod", update, mod_id=mod_id)
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"✅ Mod <code>{mod_id}</code> added. Run <b>Sync All</b> to fetch it.",
        parse_mode=ParseMode.HTML,
        reply_markup=mods_menu(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# CLASS3_RESTORE — type token to restore backup (ADR-0021)
# ---------------------------------------------------------------------------

async def flow_class3_restore_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    typed = (update.message.text or "").strip()
    action = context.user_data.get("_class3_action", "RESTORE")
    resource = context.user_data.get("_class3_resource", "")
    uid = update.effective_user.id if update.effective_user else 0

    if not consume_class3_token(typed, action, resource, uid):
        audit_log.record("class3_token_rejected", update, action=action, resource=resource)
        await update.message.reply_text(
            "❌ Invalid, expired, or already-used token. Action aborted.",
            reply_markup=backups_menu(),
        )
        context.user_data.pop("_fsm_name", None)
        return ConversationHandler.END

    audit_log.record("restore_backup", update, resource=resource)
    audit("restore_backup", update, resource=resource)
    context.user_data.pop("_fsm_name", None)
    context.user_data.pop("_class3_action", None)
    context.user_data.pop("_class3_resource", None)
    await update.message.reply_text(
        f"✅ Restore confirmed for <code>{html.escape(resource)}</code>.\n"
        "<i>Restore in progress — server will restart.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=backups_menu(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SET_SERVER_NAME
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_server_name_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "SET_SERVER_NAME"
    await update.callback_query.edit_message_text(
        "Send the new server name (max 64 chars). /cancel to abort."
    )
    return _WAITING


async def flow_server_name_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from windrose_bot.services import settings as srv_settings
    name = (update.message.text or "").strip()[:64]
    if not name:
        await update.message.reply_text("Name cannot be empty.")
        return _WAITING
    srv_settings.set_persistent("ServerName", name)
    audit_log.record("set_server_name", update, name=name)
    audit("set_server_name", update, name=name)
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"✅ Server name set to <b>{html.escape(name)}</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=server_settings_menu(),
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# SET_WORLD_NAME
# ---------------------------------------------------------------------------

@restricted(admin_only=True)
async def flow_world_name_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    context.user_data["_fsm_name"] = "SET_WORLD_NAME"
    await update.callback_query.edit_message_text(
        "Send the new world name (max 64 chars). /cancel to abort."
    )
    return _WAITING


async def flow_world_name_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from windrose_bot.services import settings as srv_settings
    name = (update.message.text or "").strip()[:64]
    if not name:
        await update.message.reply_text("World name cannot be empty.")
        return _WAITING
    try:
        srv_settings.set_world_name(name)
        audit_log.record("set_world_name", update, name=name)
        audit("set_world_name", update, name=name)
    except Exception as exc:
        await update.message.reply_text(f"⚠️ Failed: {html.escape(str(exc))}")
        return ConversationHandler.END
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"✅ World name set to <b>{html.escape(name)}</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=world_settings_menu(),
    )
    return ConversationHandler.END


def _fallbacks():
    return [
        CommandHandler("cancel", flow_cancel),
        MessageHandler(filters.COMMAND, flow_cancel),
    ]


def build_conversation_handlers() -> list:
    timeout = config.CONVERSATION_TIMEOUT

    def _conv(ask_fn, receive_fn, pattern: str) -> ConversationHandler:
        return ConversationHandler(
            entry_points=[CallbackQueryHandler(ask_fn, pattern=f"^{pattern}$")],
            states={_WAITING: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_fn)]},
            fallbacks=_fallbacks(),
            conversation_timeout=timeout,
        )

    def _text_conv(receive_fn, fsm_name: str) -> ConversationHandler:
        """FSM where the callback handler sets _fsm_name and we listen for text."""
        async def _noop_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
            return _WAITING

        return ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & filters.Regex(f"^__never_match__{fsm_name}$"),
                    _noop_entry,
                )
            ],
            states={_WAITING: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_fn)]},
            fallbacks=_fallbacks(),
            conversation_timeout=timeout,
            name=fsm_name,
            persistent=False,
        )

    return [
        _conv(flow_changepw_ask,     flow_changepw_receive,     "v2_settings_changepw"),
        _conv(flow_add_admin_ask,    flow_add_admin_receive,    "v2_users_add_admin"),
        _conv(flow_add_notify_ask,   flow_add_notify_receive,   "v2_users_add_notify"),
        _conv(flow_remove_user_ask,  flow_remove_user_receive,  "v2_users_remove"),
        _conv(flow_schedule_ask,     flow_schedule_receive,     "v2_schedule_set"),
        _conv(flow_backup_time_ask,  flow_backup_time_receive,  "sch_backup_set"),
        _conv(flow_kick_ask,         flow_kick_receive,         "plr_kick_ask"),
        _conv(flow_broadcast_ask,    flow_broadcast_receive,    "ops_broadcast_ask"),
        _conv(flow_add_mod_ask,       flow_add_mod_receive,      "mod_add_ask"),
        _conv(flow_server_name_ask,   flow_server_name_receive,  "srv_set_name"),
        _conv(flow_world_name_ask,    flow_world_name_receive,   "wld_set_name"),
        # BAN: entry is via plr_ban_dur_* callback in callbacks.py which sets _fsm_name;
        # we wire a separate ConversationHandler whose entry matches the duration buttons.
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    lambda u, c: _WAITING,
                    pattern=r"^plr_ban_dur_(1h|24h|7d|perm)$",
                )
            ],
            states={_WAITING: [MessageHandler(filters.TEXT & ~filters.COMMAND, flow_ban_receive)]},
            fallbacks=_fallbacks(),
            conversation_timeout=timeout,
            name="BAN_PLAYER",
        ),
        # CLASS3 restore token entry
        ConversationHandler(
            entry_points=[CallbackQueryHandler(
                lambda u, c: _WAITING,
                pattern=r"^bkp_restore_ask$",
            )],
            states={_WAITING: [MessageHandler(filters.TEXT & ~filters.COMMAND, flow_class3_restore_receive)]},
            fallbacks=_fallbacks(),
            conversation_timeout=timeout,
            name="CLASS3_RESTORE",
        ),
    ]

"""handlers/flows.py — ConversationHandler FSMs (ADR-011)."""
from __future__ import annotations

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
from windrose_bot.core.security import audit, restricted
from windrose_bot.keyboards.menus import back_keyboard, schedule_menu_keyboard, settings_menu_keyboard
from windrose_bot.services import container

log = logging.getLogger(__name__)

_WAITING = 1

# ---------------------------------------------------------------------------
# Shared cancel
# ---------------------------------------------------------------------------
async def flow_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("_fsm_name", None)
    context.user_data.pop("_fsm_sensitive", None)
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
    # ADR-013: delete plaintext immediately
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
    audit("change_password", update)
    context.user_data.pop("_fsm_name", None)
    context.user_data.pop("_fsm_sensitive", None)
    await update.message.reply_text("✅ Password updated.", reply_markup=back_keyboard())
    return ConversationHandler.END

# ---------------------------------------------------------------------------
# ADD_ADMIN
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
    audit("add_user", update, tier="admin", target_id=new_id)
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(f"✅ Added {new_id} as admin.", reply_markup=back_keyboard())
    return ConversationHandler.END

# ---------------------------------------------------------------------------
# ADD_NOTIFY
# ---------------------------------------------------------------------------
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
    audit("add_user", update, tier="notify", target_id=new_id)
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"✅ Added {new_id} as notify-only user.", reply_markup=back_keyboard()
    )
    return ConversationHandler.END

# ---------------------------------------------------------------------------
# REMOVE_USER
# ---------------------------------------------------------------------------
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
    audit("set_schedule", update, time=state._STATE["schedule_time"])
    context.user_data.pop("_fsm_name", None)
    await update.message.reply_text(
        f"✅ Schedule time set to {state._STATE['schedule_time']} UTC.",
        reply_markup=back_keyboard(),
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

    return [
        _conv(flow_changepw_ask,    flow_changepw_receive,    "v2_settings_changepw"),
        _conv(flow_add_admin_ask,   flow_add_admin_receive,   "v2_users_add_admin"),
        _conv(flow_add_notify_ask,  flow_add_notify_receive,  "v2_users_add_notify"),
        _conv(flow_remove_user_ask, flow_remove_user_receive, "v2_users_remove"),
        _conv(flow_schedule_ask,    flow_schedule_receive,    "v2_schedule_set"),
    ]

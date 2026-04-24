"""core/security.py — access control decorators and audit logging."""
from __future__ import annotations

import logging
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

from windrose_bot import config
from windrose_bot import state as _state

log = logging.getLogger(__name__)
_log_audit = logging.getLogger("windrose-bot.audit")


def all_admins() -> set[int]:
    return config.ADMIN_IDS | {int(x) for x in _state._STATE["users"]["admins"]}


def all_notify_only() -> set[int]:
    return {int(x) for x in _state._STATE["users"]["notify_only"]}


def is_admin(user_id: int) -> bool:
    return user_id in all_admins()


def is_allowed(user_id: int) -> bool:
    return is_admin(user_id) or user_id in all_notify_only()


def restricted(func=None, *, admin_only: bool = False):
    """Drop updates from unknown users; optionally require admin tier."""
    def decorator(f):
        @wraps(f)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = update.effective_user
            uid = getattr(user, "id", None)
            if uid is None or not is_allowed(uid):
                log.warning(
                    "Blocked access: user_id=%s username=%s",
                    uid, getattr(user, "username", None),
                )
                return
            if admin_only and not is_admin(uid):
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


def audit(action: str, update: Update, result: str = "ok", **extra) -> None:
    u = update.effective_user
    fields = {
        "action": action,
        "user_id": u.id if u else None,
        "user_name": (u.username or u.first_name) if u else None,
        "chat_id": update.effective_chat.id if update.effective_chat else None,
        "result": result,
        **extra,
    }
    _log_audit.info(" ".join(f"{k}={v}" for k, v in fields.items()))

"""core/errors.py — global error handler (ADR-010)."""
from __future__ import annotations

import html
import json
import logging
import time
import traceback

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from windrose_bot import config

log = logging.getLogger(__name__)

_dedup: dict[tuple[str, str], float] = {}
_DEDUP_WINDOW = 60.0


def _should_emit(err: BaseException) -> bool:
    tb = err.__traceback__
    while tb and tb.tb_next:
        tb = tb.tb_next
    key = (
        type(err).__name__,
        f"{tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}" if tb else "?",
    )
    now = time.monotonic()
    if now - _dedup.get(key, 0.0) < _DEDUP_WINDOW:
        return False
    _dedup[key] = now
    return True


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    log.error("Exception while handling an update:", exc_info=err)
    if not _should_emit(err):
        return

    tb_string = "".join(traceback.format_exception(None, err, err.__traceback__))
    update_str = update.to_dict() if isinstance(update, Update) else str(update)

    sensitive = bool(
        getattr(context, "user_data", None) and context.user_data.get("_fsm_sensitive")
    )
    if sensitive and isinstance(update, Update) and getattr(update, "effective_message", None):
        update_str = {"redacted": "sensitive FSM state — message omitted"}

    message = (
        "⚠️ Exception while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )

    dev_chat = config.DEVELOPER_CHAT_ID or next(iter(config.ADMIN_IDS), None)
    if not dev_chat:
        return
    try:
        await context.bot.send_message(
            chat_id=dev_chat,
            text=message[:4000],
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        log.exception("error_handler failed to notify admin")

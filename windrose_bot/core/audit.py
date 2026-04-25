"""core/audit.py — Persistent append-only audit trail (ADR-0017)."""
from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

from telegram import Update

log = logging.getLogger(__name__)
_AUDIT_PATH = Path(os.environ.get("AUDIT_PATH", "audit.jsonl"))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def record(
    action: str,
    update: Update | None = None,
    result: str = "ok",
    **extra: Any,
) -> None:
    """Append one audit record to audit.jsonl and mirror to the audit logger."""
    entry: dict[str, Any] = {"ts": _now_iso(), "action": action, "result": result, **extra}
    if update is not None:
        u = update.effective_user
        if u:
            entry["user_id"] = u.id
            entry["user_name"] = u.username or u.first_name
        c = update.effective_chat
        if c:
            entry["chat_id"] = c.id

    try:
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        log.error("audit write failed: %s", exc)

    logging.getLogger("windrose-bot.audit").info(
        " ".join(f"{k}={v}" for k, v in entry.items())
    )


def load_recent(limit: int = 50, action_filter: str | None = None) -> list[dict]:
    """Return the most-recent `limit` audit records (newest first)."""
    if not _AUDIT_PATH.exists():
        return []
    entries: list[dict] = []
    try:
        lines = _AUDIT_PATH.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if action_filter and e.get("action") != action_filter:
                continue
            entries.append(e)
            if len(entries) >= limit:
                break
    except OSError:
        pass
    return entries


def format_entry(e: dict) -> str:
    ts = e.get("ts", "")[:19].replace("T", " ")
    action = e.get("action", "?")
    user = e.get("user_name") or e.get("user_id") or "?"
    result = e.get("result", "ok")
    icon = "✅" if result == "ok" else "❌"
    extras = {k: v for k, v in e.items() if k not in ("ts", "action", "result", "user_id", "user_name", "chat_id")}
    detail = " ".join(f"{k}={v}" for k, v in extras.items()) if extras else ""
    return f"{icon} <code>{ts}</code> <b>{action}</b> by {user}" + (f"\n   {detail}" if detail else "")

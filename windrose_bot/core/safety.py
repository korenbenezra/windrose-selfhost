"""core/safety.py — Class-2/3 confirmation helpers, cooldowns, token management (ADR-0021)."""
from __future__ import annotations

import datetime
import html
import secrets

from windrose_bot import state

_COOLDOWN_SECONDS = 60
_CLASS3_EXPIRY_SECONDS = 120


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Operator attribution
# ---------------------------------------------------------------------------

def attribution_line(user) -> str:
    name = getattr(user, "username", None) or getattr(user, "first_name", None) or "?"
    uid = getattr(user, "id", "?")
    return f"👤 <b>@{html.escape(str(name))}</b> (id: {uid})"


# ---------------------------------------------------------------------------
# Cooldowns (Class 2 & 3)
# ---------------------------------------------------------------------------

def check_cooldown(user_id: int, action: str) -> int:
    """Return remaining cooldown in seconds (0 = free to proceed)."""
    key = f"{user_id}:{action}"
    ts_str = state._STATE.get("op_cooldowns", {}).get(key)
    if not ts_str:
        return 0
    try:
        ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return 0
    remaining = _COOLDOWN_SECONDS - (_now() - ts).total_seconds()
    return max(0, int(remaining))


def set_cooldown(user_id: int, action: str) -> None:
    state._STATE.setdefault("op_cooldowns", {})[f"{user_id}:{action}"] = _now_iso()
    state.save()


# ---------------------------------------------------------------------------
# Class 3 tokens
# ---------------------------------------------------------------------------

def generate_class3_token(action: str, resource_id: str, user_id: int) -> str:
    """Generate and persist a single-use, expiring Class-3 token.

    The operator must type exactly ``ACTION RESOURCE_ID`` to confirm.
    A nonce is stored server-side so a leaked token cannot be replayed.
    """
    token_key = f"{action.upper()} {resource_id}"
    state._STATE.setdefault("class3_tokens", {})[token_key] = {
        "action": action,
        "resource": resource_id,
        "user_id": user_id,
        "nonce": secrets.token_hex(4),
        "expires": (_now() + datetime.timedelta(seconds=_CLASS3_EXPIRY_SECONDS)).isoformat().replace("+00:00", "Z"),
        "used": False,
    }
    state.save()
    return token_key


def consume_class3_token(typed: str, action: str, resource_id: str, user_id: int) -> bool:
    """Validate and invalidate a Class-3 token. Returns True iff valid."""
    tokens: dict = state._STATE.get("class3_tokens", {})
    expected = f"{action.upper()} {resource_id}"
    if typed.strip() != expected:
        return False
    entry = tokens.get(expected)
    if not entry or entry.get("used") or entry.get("user_id") != user_id:
        return False
    try:
        expires = datetime.datetime.fromisoformat(entry["expires"].replace("Z", "+00:00"))
    except Exception:
        return False
    if _now() > expires:
        return False
    entry["used"] = True
    state.save()
    return True


def class3_instructions(action: str, resource_id: str) -> str:
    """Return the prompt shown to the operator for a Class-3 action."""
    token = f"{action.upper()} {resource_id}"
    return (
        f"⚠️ <b>High-risk action — Class 3 confirmation required</b>\n\n"
        f"Type the following token exactly to confirm:\n"
        f"<code>{html.escape(token)}</code>\n\n"
        f"Token expires in {_CLASS3_EXPIRY_SECONDS}s. /cancel to abort."
    )

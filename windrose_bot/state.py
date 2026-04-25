"""state.py — JSON persistence for bot runtime state."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

STATE_PATH = Path(os.environ.get("STATE_PATH", "state.json"))

_STATE: dict[str, Any] = {
    # core
    "known_players": [],
    "users": {"admins": [], "notify_only": []},
    "notify_waitlist": [],
    "sessions_active": {},
    "sessions_history": [],
    "playtime_totals": {},
    # schedule (ADR-001 / ADR-0019)
    "schedule_enabled": False,
    "schedule_time": "03:00",
    "schedule_backup_enabled": False,
    "schedule_backup_cadence": "daily",   # hourly | daily | weekly
    "schedule_backup_time": "02:00",
    "schedule_update_enabled": False,
    "schedule_update_window_start": "04:00",
    "schedule_update_window_end": "06:00",
    # operations
    "maintenance_mode": False,
    "idle_warning_sent": False,
    "idle_empty_since": None,
    # player moderation (ADR-0015)
    "ban_list": [],   # [{name, reason, expires_iso|null, banned_by, banned_at}]
    "whitelist": [],  # [str name / steam id]
    # backup policy (ADR-0018)
    "backup_policy": {
        "keep_daily": 7,
        "keep_weekly": 4,
        "keep_monthly": 3,
        "mirror_enabled": False,
        "mirror_path": "",
    },
    # mods (ADR-0016)
    "mods": [],  # [{id, name, version, pinned, last_sync}]
    # notifications (ADR-0020)
    "user_channels": {},   # {str(user_id): {channel: bool}}
    "alert_rules": [],     # [{metric, op, threshold, sustain_m, severity, cooldown_m, _last_fired}]
    "quiet_hours": {},     # {str(user_id): {start: "HH:MM", end: "HH:MM"}}
    # safety overlays (ADR-0021)
    "op_cooldowns": {},    # {"user_id:action": iso_ts}
    "class3_tokens": {},   # {"ACTION RESOURCE": {expires, used, user_id, nonce}}
}


def load() -> None:
    if not STATE_PATH.exists():
        return
    try:
        saved = json.loads(STATE_PATH.read_text())
        for key in _STATE:
            if key in saved:
                _STATE[key] = saved[key]
    except (json.JSONDecodeError, OSError):
        log.warning("state.json unreadable; starting with defaults")


def save() -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(_STATE, indent=2, default=str))
    tmp.replace(STATE_PATH)


def known_players() -> set[str]:
    return set(_STATE["known_players"])


def set_known_players(players: set[str]) -> None:
    _STATE["known_players"] = list(players)
    save()

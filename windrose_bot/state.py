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
    "known_players": [],
    "users": {"admins": [], "notify_only": []},
    "notify_waitlist": [],
    "sessions_active": {},
    "sessions_history": [],
    "playtime_totals": {},
    "schedule_enabled": False,
    "schedule_time": "03:00",
    "idle_warning_sent": False,
    "idle_empty_since": None,
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

"""
config.py — single source of truth for all environment variables.

Only this module reads os.environ. Everything else imports named constants
from here, making config trivially monkeypatchable in tests.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

# Use utf-8-sig so BOM-prefixed .env files from Windows tools are parsed correctly.
load_dotenv(encoding="utf-8-sig")

BOT_TOKEN: str = os.environ["BOT_TOKEN"]

_admin_ids_raw = os.environ.get("ADMIN_IDS", os.environ.get("ADMIN_CHAT_ID", ""))
ADMIN_IDS: set[int] = {int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip()}

NOTIFY_IDS: list[int] = [
    int(x.strip()) for x in os.environ.get("NOTIFY_CHAT_IDS", "").split(",")
    if x.strip()
] or list(ADMIN_IDS)

SERVER_FILES_DIR: str = os.environ.get(
    "SERVER_FILES_DIR", str(Path.home() / "windrose" / "R5")
)
# Legacy alias — points to R5/Saved/ServerDescription.json (password only)
SERVER_DESC_PATH = Path(SERVER_FILES_DIR) / "Saved" / "ServerDescription.json"

LOG_PATH: str = os.environ.get("LOG_PATH", str(Path.home() / "log" / "windrose.log"))
POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
PLAYER_MONITOR_MODE: str = os.environ.get("PLAYER_MONITOR_MODE", "auto")

LOG_PATTERN_CONNECT: str = os.environ.get(
    "LOG_PATTERN_CONNECT", r"Client connected.*?([A-Za-z0-9_\- ]{3,32})$",
)
LOG_PATTERN_DISCONNECT: str = os.environ.get(
    "LOG_PATTERN_DISCONNECT", r"Client disconnected.*?([A-Za-z0-9_\- ]{3,32})$",
)

CPU_ALERT_THRESHOLD: float = float(os.environ.get("CPU_ALERT_THRESHOLD", "85"))
RAM_ALERT_THRESHOLD: float = float(os.environ.get("RAM_ALERT_THRESHOLD", "90"))
IDLE_TIMEOUT_MINUTES: int = int(os.environ.get("IDLE_TIMEOUT_MINUTES", "60"))
CONVERSATION_TIMEOUT: int = int(os.environ.get("CONVERSATION_TIMEOUT_SECONDS", "300"))
DEVELOPER_CHAT_ID: int = int(os.environ.get("DEVELOPER_CHAT_ID", "0"))
RATE_LIMIT_MESSAGES_PER_MINUTE: int = int(os.environ.get("RATE_LIMIT_MESSAGES_PER_MINUTE", "20"))

_SCRIPTS_DIR = Path(os.environ.get(
    "WINDROSE_SCRIPTS_DIR",
    str(Path(__file__).parent.parent / "scripts")
))
BACKUP_SCRIPT = str(_SCRIPTS_DIR / "backup_world.ps1")
UPDATE_SCRIPT = str(_SCRIPTS_DIR / "update_windrose.ps1")
MODS_SYNC_SCRIPT = str(_SCRIPTS_DIR / "sync_mods.ps1")

AUDIT_PATH: str = os.environ.get("AUDIT_PATH", "audit.jsonl")
BACKUPS_DIR: str = os.environ.get("BACKUPS_DIR", str(Path.home() / "windrose" / "backups"))

SVC_NAME = "Windrose"


def validate() -> None:
    token = BOT_TOKEN.strip()
    if not token or token == "your-telegram-bot-token-here":
        raise SystemExit(
            "Invalid BOT_TOKEN in .env (placeholder value detected). "
            "Set BOT_TOKEN to the real token from BotFather."
        )
    if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{20,}", token):
        raise SystemExit(
            "Invalid BOT_TOKEN format in .env. Expected '<bot_id>:<secret>'."
        )

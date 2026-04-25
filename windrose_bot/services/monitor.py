"""services/monitor.py — player monitor: file watchdog + log polling fallback."""
from __future__ import annotations

import asyncio
import datetime
import html
import logging
import re
import subprocess
from collections import deque
from pathlib import Path

from telegram.ext import ContextTypes

from windrose_bot import config, state
from windrose_bot.config import LOG_PATH, LOG_PATTERN_CONNECT, LOG_PATTERN_DISCONNECT

log = logging.getLogger(__name__)

_pat_connect: re.Pattern | None = None
_pat_disconnect: re.Pattern | None = None
_recent_log_lines: deque[str] = deque(maxlen=600)


def _sanitize_player_name(name: str) -> str:
    cleaned = "".join(ch for ch in name.strip() if ch.isprintable() and ch not in "\r\n\t")
    cleaned = cleaned[:64]

    # Some server log paths can mangle UTF-8 names into sequences like "S×©××›×'abih...".
    # If mojibake markers are present, prefer an ASCII-safe projection.
    if any(ch in cleaned for ch in ("×", "�")):
        ascii_only = re.sub(r"[^A-Za-z0-9_\- ]+", "", cleaned).strip()
        if len(ascii_only) >= 3:
            return ascii_only[:64]

    return cleaned


def _extract_player_name_from_line(line: str) -> str | None:
    """Extract a player name from native Windrose log lines."""
    for pattern in (
        r"Join succeeded:\s*(.+)$",
        r"Join request:.*?\?Name=([^?\s]+)",
        r"AccountName\s+'([^']+)'",
    ):
        m = re.search(pattern, line, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # Normalize UE token like Name=Koren-ABCDEF to Koren.
            name = _sanitize_player_name(raw.split("-", 1)[0])
            if name:
                return name
    return None


def _extract_player_name(match: re.Match[str], line: str) -> str | None:
    """Extract player name from a regex match with or without capture groups."""
    if match.lastindex and match.lastindex >= 1:
        name = _sanitize_player_name(match.group(1) or "")
        return name or None

    matched_text = match.group(0)
    for source in (matched_text, line):
        m = re.search(r"Player\s+(.+?)\s+(?:connected|disconnected)\b", source, re.IGNORECASE)
        if m:
            name = _sanitize_player_name(m.group(1))
            if name:
                return name

    return _extract_player_name_from_line(line)


def _extract_connected_accounts_snapshot(lines: list[str]) -> set[str]:
    """Parse the latest 'Connected Accounts' block and return visible account names."""
    latest: set[str] | None = None
    current: set[str] = set()
    in_block = False

    for line in lines:
        if "Connected Accounts" in line:
            in_block = True
            current = set()
            continue
        if in_block and "Disconnected Accounts" in line:
            latest = set(current)
            in_block = False
            continue
        if in_block:
            m = re.search(r"Name\s+'([^']+)'", line)
            if m:
                name = m.group(1).strip()
                if name:
                    current.add(_sanitize_player_name(name))

    return latest or set()


async def _sync_players(snapshot: set[str], context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reconcile tracked online players against a parsed log snapshot."""
    current = state.known_players()
    joined = sorted(snapshot - current)
    left = sorted(current - snapshot)

    for name in joined:
        _record_join(name)
        await _broadcast(context, f"\U0001f7e2 <b>{html.escape(name)}</b> joined the server!")

    for name in left:
        _record_leave(name)
        await _broadcast(context, f"\U0001f534 <b>{html.escape(name)}</b> left the server.")

    if joined or left:
        state.set_known_players(snapshot)

    if snapshot:
        state._STATE["idle_empty_since"] = None
        state._STATE["idle_warning_sent"] = False
        state.save()


async def _reconcile_from_log_file(context: ContextTypes.DEFAULT_TYPE, tail_lines: int = 2000) -> None:
    if not Path(LOG_PATH).exists():
        return
    with open(LOG_PATH, errors="replace") as f:
        lines = f.readlines()
    snapshot = _extract_connected_accounts_snapshot(lines[-tail_lines:])
    await _sync_players(snapshot, context)


def compile_patterns() -> None:
    global _pat_connect, _pat_disconnect
    _pat_connect = re.compile(LOG_PATTERN_CONNECT)
    _pat_disconnect = re.compile(LOG_PATTERN_DISCONNECT)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _record_join(name: str) -> None:
    state._STATE["sessions_active"][name] = _now_iso()
    state.save()


def _record_leave(name: str) -> None:
    joined_str = state._STATE["sessions_active"].pop(name, None)
    if joined_str:
        try:
            joined_dt = datetime.datetime.fromisoformat(joined_str.replace("Z", "+00:00"))
            duration_s = int((datetime.datetime.now(datetime.timezone.utc) - joined_dt).total_seconds())
        except Exception:
            duration_s = 0
        state._STATE["sessions_history"].append({
            "name": name,
            "joined": joined_str,
            "left": _now_iso(),
            "duration_s": duration_s,
        })
        state._STATE["sessions_history"] = state._STATE["sessions_history"][-500:]
        state._STATE["playtime_totals"][name] = (
            state._STATE["playtime_totals"].get(name, 0) + duration_s
        )
    state.save()


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    from windrose_bot.core.security import all_admins, all_notify_only
    targets = set(config.NOTIFY_IDS) | all_admins() | all_notify_only()
    for chat_id in targets:
        try:
            from telegram.constants import ParseMode
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        except Exception as exc:
            log.warning("broadcast failed for %s: %s", chat_id, exc)


async def handle_line(line: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert _pat_connect and _pat_disconnect
    _recent_log_lines.append(line)
    players = state.known_players()

    m = _pat_connect.search(line)
    if m:
        name = _extract_player_name(m, line)
        if name and name not in players:
            players.add(name)
            state.set_known_players(players)
            _record_join(name)
            await _broadcast(context, f"\U0001f7e2 <b>{html.escape(name)}</b> joined the server!")
            state._STATE["idle_empty_since"] = None
            state._STATE["idle_warning_sent"] = False
            state.save()
        return

    # Built-in fallback for Windrose native log lines, independent of env regex.
    name = _extract_player_name_from_line(line)
    if name and name not in players:
        players.add(name)
        state.set_known_players(players)
        _record_join(name)
        await _broadcast(context, f"\U0001f7e2 <b>{html.escape(name)}</b> joined the server!")
        state._STATE["idle_empty_since"] = None
        state._STATE["idle_warning_sent"] = False
        state.save()
        return

    m = _pat_disconnect.search(line)
    if m:
        name = _extract_player_name(m, line)
        if name and name in players:
            players.discard(name)
            state.set_known_players(players)
            _record_leave(name)
            await _broadcast(context, f"\U0001f534 <b>{html.escape(name)}</b> left the server.")

    # When account dumps appear, reconcile to authoritative connected snapshot.
    if "Connected Accounts" in line or "Disconnected Accounts" in line:
        snapshot = _extract_connected_accounts_snapshot(list(_recent_log_lines))
        await _sync_players(snapshot, context)


_watchdog_observer = None


def start_watchdog(context: ContextTypes.DEFAULT_TYPE, loop: asyncio.AbstractEventLoop) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class _Tailer(FileSystemEventHandler):
        def __init__(self) -> None:
            p = Path(LOG_PATH)
            self._pos: int = p.stat().st_size if p.exists() else 0

        def on_modified(self, event) -> None:
            if event.src_path != LOG_PATH:
                return
            try:
                with open(LOG_PATH, errors="replace") as f:
                    f.seek(self._pos)
                    chunk = f.read()
                    self._pos = f.tell()
            except FileNotFoundError:
                self._pos = 0
                return
            for line in chunk.splitlines():
                asyncio.run_coroutine_threadsafe(handle_line(line, context), loop)

    global _watchdog_observer
    handler = _Tailer()
    observer = Observer()
    observer.schedule(handler, path=str(Path(LOG_PATH).parent), recursive=False)
    observer.start()
    _watchdog_observer = observer
    log.info("Player monitor: watchdog active on %s", LOG_PATH)
    asyncio.run_coroutine_threadsafe(_reconcile_from_log_file(context), loop)


async def poll_log_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        if not Path(LOG_PATH).exists():
            return
        with open(LOG_PATH, errors="replace") as f:
            lines = f.readlines()
        for line in lines[-200:]:
            await handle_line(line, context)
        await _reconcile_from_log_file(context)
    except Exception as exc:
        log.warning("log poll error: %s", exc)

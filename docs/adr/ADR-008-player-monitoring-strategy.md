# ADR-008 — Player Join/Leave Notification Strategy

## Status
**Accepted**

## Date
2026-04-23

## Context

Players join and leave the server organically through the day. The admin and friend group want unsolicited Telegram notifications on these events — no manual `/players` poll required.

What's available as an event surface:

1. **Windrose's own log file** at `/home/$USER/log/windrose.log` (written because the launch script uses the `-log` flag). Exact format of connection/disconnection lines must be verified at deploy time — it's undocumented in the official guide.
2. **systemd journal** for `windrose.service` — captures stdout/stderr of the service, which includes the same lines (Wine forwards them). Reachable via `journalctl -u windrose`.
3. **Windrose's RocksDB save state** — not useful; written infrequently, not event-shaped.
4. **Windrose REST/RCON/WebSocket** — none of these exist as of Early Access.

The original guide picked 30-second polling of docker logs. Since we've moved off Docker (ADR-003), our options are:

## Options

### Option A — `watchdog` file tail (preferred)
Subscribe to inotify events on `~/log/windrose.log`. When the file is modified, read the new bytes, parse, emit events. Sub-second latency.

### Option B — `journalctl --since` polling
Every 30 seconds, run `journalctl -u windrose --since "35 seconds ago"` and parse its output. 30s latency but independent of file path assumptions.

### Option C — Hybrid — watchdog by default, journalctl-polling fallback
Prefer watchdog when `LOG_PATH` exists and is recently modified. Fall back to journalctl polling when it doesn't. Report the active mode in `/status`.

## Decision

**Option C — Hybrid.** Default to watchdog on `~/log/windrose.log`; fall back to journalctl polling if the file is missing or stale.

Configuration (`.env`):

```dotenv
PLAYER_MONITOR_MODE=auto          # auto | watchdog | polling | off
LOG_PATH=/home/windrose/log/windrose.log
POLL_INTERVAL_SECONDS=30
LOG_PATTERN_CONNECT=Client connected.*?([A-Za-z0-9_\- ]{3,32})$
LOG_PATTERN_DISCONNECT=Client disconnected.*?([A-Za-z0-9_\- ]{3,32})$
```

Startup sequence:
1. Compile both regexes with `re.compile()`. Invalid → refuse to start; log to stderr; Telegram-notify admin if token is available.
2. If `PLAYER_MONITOR_MODE=off`, skip the monitor entirely.
3. If `auto`:
   - If `LOG_PATH` exists and has been modified within the last 10 minutes → **watchdog mode**.
   - Else → **journalctl polling mode**, log a warning that `/status` will surface.
4. If `watchdog` or `polling` is forced, use that mode regardless.

Persist `_known_players` to `state.json` (atomic write) so restarts don't emit spurious joins/leaves.

Fan out notifications to every `NOTIFY_CHAT_IDS` entry (ADR-007).

## Rationale

- **Sub-second latency when everything is happy.** watchdog uses inotify; events arrive in milliseconds.
- **Resilience when things are not.** If `LOG_PATH` is wrong (Windrose changes the filename post-patch; the user's install is at a non-default path; the log hasn't been flushed yet on first start), journalctl polling keeps the feature working.
- **No hardcoded paths.** `LOG_PATH` and both regex patterns are env vars; a Windrose patch that changes log format or file location is a 5-minute `.env` edit, not a code deploy.
- **Startup validation.** Invalid regex doesn't silently break the monitor — the bot refuses to boot, forcing the admin to fix it before anyone notices.
- **State persistence solves the "everyone rejoined" problem** every time the bot restarts.

## Alternatives Considered

| Option | Latency | Reliability | Why Rejected / Chosen |
|---|---|---|---|
| **Hybrid auto (chosen)** | <1s watchdog / 30s fallback | High | **Chosen** |
| Watchdog-only | <1s | Medium (breaks silently on bad path) | **Rejected** — too brittle alone |
| Polling-only (journalctl or file tail) | 30s | High | Workable fallback but laggy in steady state |
| Parse RocksDB save state | N/A | Not event-shaped | **Rejected** |
| Inject a Windrose mod / in-game log hook | Real-time, rich | Breaks every patch; no mod API | **Rejected** |
| `docker logs` polling | 30s | N/A — we no longer use Docker | **Rejected** (historical) |

## Log Format — MUST VERIFY AT DEPLOY

The regex patterns ship with plausible defaults but **must be verified against a running server** on first deployment. Plausible UE5 conventions we guess with:

```
Connect:    Client connected.*?([A-Za-z0-9_\- ]{3,32})$
Disconnect: Client disconnected.*?([A-Za-z0-9_\- ]{3,32})$
```

Verification procedure (documented in `TELEGRAM_BOT_GUIDE.md`):

```bash
# Start the server, have someone join, then:
journalctl -u windrose --since "10 minutes ago" | grep -iE '(connect|client|session|player|join|disconnect)'
# OR
tail -n 300 ~/log/windrose.log | grep -iE '(connect|client|session|player|join|disconnect)'
```

Read the actual lines. Update `.env` → `LOG_PATTERN_CONNECT` / `LOG_PATTERN_DISCONNECT`. `sudo systemctl restart windrose-bot`.

Possible alternate formats to watch for:
- `[INFO] Player <name> (<steamid>) joined the game`
- `LogOnline: Session <name> joined`
- `[NetDriver] <steamid> connected as <name>`
- Unreal-style `LogNet: NotifyAcceptingConnection accepted from …`

The regex flexibility in `.env` accommodates each of these.

## Consequences

### Positive
- Sub-second notifications when the log-file path is correct.
- Graceful degradation to 30s polling when watchdog can't find the file.
- `_known_players` persistence eliminates noise at bot restart.
- Multi-recipient fan-out via `NOTIFY_CHAT_IDS`.
- Configurable regex → resilient to Windrose log-format changes.

### Negative
- Two code paths — watchdog and polling. Mitigation: both share the same parser (`handle_line()`) and the same `_known_players` update/notify logic. Only the "how do we receive new lines" differs.
- Watchdog uses inotify, which is reliable on `ext4`/`btrfs`/`xfs` on local storage (what a laptop uses). On exotic filesystems or network mounts it silently degrades. Not a concern for our deployment.
- journalctl polling invokes a subprocess every 30s. ~20ms CPU each time. Negligible.

## Implementation Guide

### Conceptual structure
```python
class PlayerMonitor:
    """Emits join/leave events via self.on_event(kind, player_name).

    Mode chosen at startup; caller doesn't know whether inotify or
    journalctl-polling is active.
    """
    async def start(self, loop): ...
    async def stop(self): ...
    def active_mode(self) -> str: ...
```

See `bot/bot.py` for the full implementation.

### State persistence
```python
import json, pathlib

STATE_PATH = pathlib.Path(os.environ.get("STATE_PATH", "state.json"))

def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"known_players": []}
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        log.warning("state.json corrupt; starting fresh")
        return {"known_players": []}

def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_PATH)    # atomic on POSIX
```

### Watchdog tailer
```python
import asyncio, os
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

class LogTailer(FileSystemEventHandler):
    def __init__(self, path: str, on_line, loop: asyncio.AbstractEventLoop):
        self.path = path
        self.on_line = on_line            # async callable(line:str)
        self.loop = loop
        self._pos = os.path.getsize(path) if os.path.exists(path) else 0

    def on_modified(self, event):
        if event.src_path != self.path:
            return
        try:
            with open(self.path, "r", errors="replace") as f:
                f.seek(self._pos)
                chunk = f.read()
                self._pos = f.tell()
        except FileNotFoundError:
            self._pos = 0
            return
        for line in chunk.splitlines():
            asyncio.run_coroutine_threadsafe(self.on_line(line), self.loop)

def start_watchdog(path, on_line, loop) -> Observer:
    handler = LogTailer(path, on_line, loop)
    observer = Observer()
    observer.schedule(handler, path=os.path.dirname(path), recursive=False)
    observer.start()
    return observer
```

### journalctl polling fallback
```python
import subprocess, asyncio

async def poll_journal(since_seconds: int = 40) -> list[str]:
    """Fetch recent journalctl output for windrose.service. Slight overlap
    (40s window vs 30s interval) — dedup happens via _known_players."""
    result = await asyncio.to_thread(
        subprocess.run,
        ["journalctl", "-u", "windrose.service",
         "--since", f"{since_seconds} seconds ago",
         "--no-pager", "-q"],
        capture_output=True, text=True, timeout=10,
    )
    return (result.stdout + result.stderr).splitlines()
```

## Code Examples

### Unified line handler (shared by both modes)
```python
import re, html

_pat_connect = None
_pat_disconnect = None
_known_players: set[str] = set()

def compile_patterns(connect: str, disconnect: str) -> None:
    global _pat_connect, _pat_disconnect
    _pat_connect = re.compile(connect)
    _pat_disconnect = re.compile(disconnect)

async def handle_line(line: str, broadcast) -> None:
    """Called with every new log line from watchdog OR polling."""
    global _known_players
    m = _pat_connect.search(line)
    if m:
        name = m.group(1).strip()
        if name and name not in _known_players:
            _known_players.add(name)
            save_state({"known_players": list(_known_players)})
            await broadcast(f"🟢 <b>{html.escape(name)}</b> joined the server!")
        return
    m = _pat_disconnect.search(line)
    if m:
        name = m.group(1).strip()
        if name and name in _known_players:
            _known_players.discard(name)
            save_state({"known_players": list(_known_players)})
            await broadcast(f"🔴 <b>{html.escape(name)}</b> left the server.")
```

## References

- `watchdog` on PyPI: https://pypi.org/project/watchdog/
- Linux `inotify(7)`: https://man7.org/linux/man-pages/man7/inotify.7.html
- `journalctl` options: `man journalctl`
- Unreal Engine logging conventions: https://docs.unrealengine.com/ (search "LogNet", "NotifyAcceptingConnection")
- Windrose dedicated-server logging flag `-log`: https://steamcommunity.com/sharedfiles/filedetails/?id=3706337486

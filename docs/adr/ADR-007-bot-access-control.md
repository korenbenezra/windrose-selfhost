# ADR-007 — Bot Access Control Strategy

## Status
**Accepted**

## Date
2026-04-23

## Context

Telegram bots have no built-in access control. Anyone who knows the bot's username can DM it. BotFather's `/setprivacy` affects only group messages.

Risks on our deployment:
- `/stop` and `/restart` cause downtime on a shared friend server.
- `/update` triggers a SteamCMD download that writes to `~/windrose/R5/Binaries/`; a malicious trigger during a patch window could cause version mismatch.
- `/backup` consumes I/O and disk; DoS-able if unrestricted.
- `/logs` exposes Wine + Windrose server output that contains player Steam IDs — minor but real PII.

Threat model for a 2–5 friend private server:

| Threat | Impact | Likelihood |
|---|---|---|
| Stranger finds bot username via Telegram search, sends `/stop` | Server down until admin notices (healthcheck would recover within 10 min) | **Realistic** |
| Friend accidentally taps 🛑 Stop on mobile | Brief unplanned downtime | **Medium** — mitigated by confirmation keyboard |
| Bot token leaks (committed to git, screenshot, compromised dev machine) | Full control by attacker; worst case is indefinite `/stop` | Low if `.env` is `gitignore`d |
| Compromised friend's Telegram account | Same as above from an authorised ID | Low |

## Decision

**User-ID whitelist via `@restricted` decorator**, applied to every command and callback handler. Two-factor for destructive actions (auth + confirmation tap).

`.env` configuration:

```dotenv
ADMIN_CHAT_ID=123456789
ALLOWED_CHAT_IDS=123456789,987654321,555666777
NOTIFY_CHAT_IDS=123456789,987654321,555666777
```

- `ADMIN_CHAT_ID` — the admin's Telegram ID. Always implicitly in the allow-list (cannot be excluded by accident).
- `ALLOWED_CHAT_IDS` — full set of users who may issue commands. Superset of `ADMIN_CHAT_ID`.
- `NOTIFY_CHAT_IDS` — who receives player join/leave and update/restart notifications. Often equal to `ALLOWED_CHAT_IDS` but separable (e.g., notifications to a Discord bridge bot ID that shouldn't be able to issue commands).

## Rationale

- **Numeric user IDs cannot be spoofed.** `update.effective_user.id` is set by Telegram's servers from the authenticated session.
- **Silent drop beats error reply.** An access-denied reply confirms the bot exists; silence leaks nothing. Logs at `WARNING` so the admin can still audit via `journalctl -u windrose-bot`.
- **Check runs before any logic.** The bot never calls `subprocess.run(["sudo", "systemctl", ...])` on behalf of an unauthenticated user.
- **Solves the prior "only admin gets notifications" limitation.** `NOTIFY_CHAT_IDS` fan-out is a simple loop in the notification helper.
- **Complements the sudoers scoping (ADR-003).** Even if the `@restricted` logic had a bug, the sudoers drop-in restricts the bot's system impact to exactly three systemctl verbs on exactly one unit.

## Alternatives Considered

| Option | Pros | Cons | Why Rejected / Chosen |
|---|---|---|---|
| **Numeric whitelist + `@restricted` (chosen)** | Unspoofable; zero friction for users; silent to probers | Admin onboards each friend once | **Chosen** |
| Password-gated commands (`/stop mysecret123`) | No ID lookup | Password appears plaintext in chat history; weaker; still reachable by probers | **Rejected** |
| BotFather `/setprivacy` | Built-in | Doesn't apply to DMs | **Rejected** |
| Group-only bot (bot refuses DMs outside the group) | Reduces surface | Friends would all need to be in a shared Telegram group; less flexible | **Rejected** — `NOTIFY_CHAT_IDS` can include a group chat if desired |
| OAuth-style token handshake | Mature pattern | No Telegram OAuth for Bot API; would roll our own | **Rejected** — overengineered for 2–5 friends |
| Rate-limiting by IP | Defensive | Telegram's Bot API already rate-limits; we don't see IPs | **Rejected** as sole control |

## Consequences

### Positive
- Unauthorised users cannot stop/restart the server or trigger updates.
- The bot's existence is not confirmed to probers.
- Onboarding a friend is a 2-minute procedure documented in `TELEGRAM_BOT_GUIDE.md`.
- Audit log via `journalctl -u windrose-bot | grep "Blocked access"`.

### Negative
- Admin must see each friend's user ID during onboarding. Procedure documented.
- Misconfigured `ADMIN_CHAT_ID` (typo) can lock the admin out of their own bot. Recovery: SSH in, edit `.env`, `sudo systemctl restart windrose-bot`.
- A compromised authorised Telegram account = full bot access. Mitigation: recommend friends enable 2FA; destructive actions require confirmation taps.

## Additional Layer: Confirmation Buttons

Destructive callbacks (`cb_stop_confirm`, `cb_restart_confirm`, `cb_update_confirm`) show:

```
⚠️ Are you sure you want to STOP the server?
All players will be disconnected.

[✅ Yes, stop it]  [❌ Cancel]
```

✅ executes; ❌ navigates back to the main panel without action (via `callback_data="cb_panel"`).

Confirmation is only for destructive actions. Information queries (`/status`, `/players`, `/logs`, `/uptime`) run immediately.

## How to Add a Friend's ID

1. Friend sends `/start` to the bot.
2. Admin opens in a browser (or with `curl`):
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find the new `update`. Read `result[N].message.from.id` — a plain integer (e.g., `987654321`).
4. SSH to the laptop:
   ```bash
   nano ~/windrose-telegram-bot/.env
   # Append to ALLOWED_CHAT_IDS:
   ALLOWED_CHAT_IDS=123456789,987654321
   # Optionally add to NOTIFY_CHAT_IDS too.
   ```
5. Restart the bot:
   ```bash
   sudo systemctl restart windrose-bot
   ```
6. Verify: friend sends `/start` — they see the control panel.

## Implementation Guide

### The `@restricted` decorator (shipped as part of `bot/bot.py`)
```python
import os, logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])
_extra = os.environ.get("ALLOWED_CHAT_IDS", "")
ALLOWED_IDS: set[int] = {ADMIN_CHAT_ID} | {
    int(x.strip()) for x in _extra.split(",") if x.strip()
}

def restricted(func):
    """Silently drop any update from a user whose ID isn't in ALLOWED_IDS.

    Silence (not 'access denied') so probers cannot confirm the bot exists.
    Logs at WARNING so the admin can audit via `journalctl -u windrose-bot`.
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      *args, **kwargs):
        user = update.effective_user
        if user is None or user.id not in ALLOWED_IDS:
            log.warning(
                "Blocked access: user_id=%s username=%s kind=%s data=%s",
                getattr(user, "id", None),
                getattr(user, "username", None),
                "command" if update.message else
                "callback" if update.callback_query else "?",
                (update.message.text if update.message else
                 update.callback_query.data if update.callback_query else None),
            )
            return
        return await func(update, context, *args, **kwargs)
    return wrapped
```

### Apply to every handler
```python
@restricted
async def cmd_start(update, context): ...

@restricted
async def cmd_stop(update, context): ...

@restricted
async def button_handler(update, context):
    # All inline-keyboard callbacks go through this one handler,
    # which dispatches on query.data. The decorator guards the entire tree.
    ...
```

### Audit trail
```bash
# Blocked attempts in the last hour:
sudo journalctl -u windrose-bot --since "1 hour ago" | grep "Blocked access"

# Count of distinct blocked user IDs since boot:
sudo journalctl -u windrose-bot --since boot \
  | grep "Blocked access" \
  | grep -oE 'user_id=[0-9]+' | sort -u | wc -l
```

## Code Examples

### Broadcasting to NOTIFY_CHAT_IDS
```python
import os, logging
from telegram.constants import ParseMode

log = logging.getLogger(__name__)

NOTIFY_IDS = [
    int(x.strip()) for x in os.environ.get("NOTIFY_CHAT_IDS", "").split(",")
    if x.strip()
] or [int(os.environ["ADMIN_CHAT_ID"])]

async def broadcast(context, text: str) -> None:
    """Send `text` to every NOTIFY_CHAT_IDS entry. Per-recipient failures logged, non-fatal."""
    for chat_id in NOTIFY_IDS:
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=text, parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.warning("broadcast failed for %s: %s", chat_id, e)
```

### Finding your own chat ID (one-liner for friends to use)
```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" \
  | python3 -c "import sys, json; d=json.load(sys.stdin); \
               [print(u['message']['from']['id'], u['message']['from'].get('username','')) \
                for u in d['result'] if 'message' in u]"
```

## References

- Telegram Bot API: https://core.telegram.org/bots/api
- `Update` object structure: https://docs.python-telegram-bot.org/en/stable/telegram.update.html
- BotFather `/setprivacy` behaviour: https://core.telegram.org/bots/features#privacy-mode
- Telegram 2FA (user recommendation for friends): https://telegram.org/blog/sessions-and-2-step-verification

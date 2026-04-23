#!/usr/bin/env bash
# install_bot.sh - Set up the Windrose Telegram bot virtualenv and config.
# Run as the bot user after install_service.sh completes.
# ADR-006 (python-telegram-bot v22), ADR-007 (access control)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

BOT_SRC="$REPO_DIR/bot"
BOT_DIR="$HOME/windrose-telegram-bot"
VENV="$BOT_DIR/venv"
BOT_ENV_SRC="$BOT_SRC/.env"
BOT_ENV_EXAMPLE="$BOT_SRC/.env.example"
BOT_ENV_DST="$BOT_DIR/.env"

echo "=== install_bot.sh $(date -Iseconds) ==="
echo "    Bot source : $BOT_SRC"
echo "    Install dir: $BOT_DIR"

# ---------------------------------------------------------------------------
# 1. Create the install directory and copy bot files
# ---------------------------------------------------------------------------
mkdir -p "$BOT_DIR"

cp "$BOT_SRC/bot.py"           "$BOT_DIR/bot.py"
cp "$BOT_SRC/requirements.txt" "$BOT_DIR/requirements.txt"

echo "Bot files copied OK"

# ---------------------------------------------------------------------------
# 2. Create .env on first install
#    Priority: bot/.env -> bot/.env.example
# ---------------------------------------------------------------------------
if [[ ! -f "$BOT_ENV_DST" ]]; then
  if [[ -f "$BOT_ENV_SRC" ]]; then
    cp "$BOT_ENV_SRC" "$BOT_ENV_DST"
    echo "Created $BOT_ENV_DST from $BOT_ENV_SRC"
  else
    cp "$BOT_ENV_EXAMPLE" "$BOT_ENV_DST"
    echo "Created $BOT_ENV_DST from $BOT_ENV_EXAMPLE"
  fi
  echo ""
  echo "  *** IMPORTANT: edit $BOT_ENV_DST now ***"
  echo "  Set BOT_TOKEN, ADMIN_CHAT_ID, ALLOWED_CHAT_IDS, and LOG_PATH"
  echo "  Then re-run this script, OR run: sudo systemctl start windrose-bot"
  echo ""
else
  echo ".env already exists - not overwriting"
fi

# ---------------------------------------------------------------------------
# 3. Create Python virtualenv
# ---------------------------------------------------------------------------
if [[ ! -d "$VENV" ]]; then
  echo "--- Creating virtualenv at $VENV ---"
  python3 -m venv "$VENV"
  echo "Virtualenv created OK"
else
  echo "Virtualenv already exists - upgrading packages"
fi

# ---------------------------------------------------------------------------
# 4. Install / upgrade dependencies
# ---------------------------------------------------------------------------
echo "--- Installing Python dependencies ---"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$BOT_DIR/requirements.txt"
echo "Dependencies installed OK"

# ---------------------------------------------------------------------------
# 5. Verify the bot module imports cleanly (catches missing deps early)
# ---------------------------------------------------------------------------
echo "--- Verifying bot module ---"
if "$VENV/bin/python" -c "import telegram, dotenv, watchdog; print('imports OK')"; then
  echo "Module check OK"
else
  echo "ERROR: import check failed - inspect the virtualenv" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=== install_bot.sh complete $(date -Iseconds) ==="
echo "Next steps:"
echo "  1. Edit $BOT_ENV_DST (BOT_TOKEN, ADMIN_CHAT_ID, ALLOWED_CHAT_IDS)"
echo "  2. sudo systemctl start windrose-bot"
echo "  3. sudo systemctl status windrose-bot"
echo "  4. journalctl -fu windrose-bot"

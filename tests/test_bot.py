"""
Unit tests for bot.py.

Tests run without a live Telegram connection — all external calls are mocked.
Run: pytest tests/test_bot.py -v
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path + env setup — must happen before bot is imported
# ---------------------------------------------------------------------------
_BOT_DIR = Path(__file__).parent.parent / "bot"
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

os.environ.setdefault("BOT_TOKEN", "123456789:AAabcdefghijklmnopqrstuvwxyz1234567")
os.environ.setdefault("ADMIN_IDS", "111,222")
os.environ.setdefault("CONTAINER_NAME", "windrose-server")

# ---------------------------------------------------------------------------
# Minimal stubs for heavy dependencies
# ---------------------------------------------------------------------------
def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _install_stubs() -> None:
    # psutil
    psutil_mod = _stub_module(
        "psutil",
        cpu_percent=lambda interval=None: 50.0,
        virtual_memory=lambda: MagicMock(percent=60.0),
        disk_usage=lambda path: MagicMock(percent=40.0),
    )
    sys.modules.setdefault("psutil", psutil_mod)

    # dotenv
    sys.modules.setdefault("dotenv", _stub_module("dotenv", load_dotenv=lambda **kw: None))

    # telegram
    tg = _stub_module("telegram")
    tg.BotCommand = MagicMock
    tg.InlineKeyboardButton = lambda text, callback_data="": MagicMock(
        text=text, callback_data=callback_data
    )
    tg.InlineKeyboardMarkup = lambda rows: MagicMock(inline_keyboard=rows)
    tg.Update = MagicMock
    sys.modules.setdefault("telegram", tg)

    sys.modules.setdefault(
        "telegram.constants",
        _stub_module("telegram.constants", ParseMode=MagicMock(HTML="HTML")),
    )
    sys.modules.setdefault(
        "telegram.error",
        _stub_module("telegram.error", InvalidToken=Exception),
    )

    # ConversationHandler stub with END = -1 (matches PTB real value)
    class _ConvHandler:
        END = -1
        def __init__(self, **kwargs):
            pass

    tg_ext = _stub_module("telegram.ext")
    tg_ext.Application = MagicMock
    tg_ext.ApplicationBuilder = MagicMock
    tg_ext.CallbackQueryHandler = MagicMock
    tg_ext.CommandHandler = MagicMock
    tg_ext.ConversationHandler = _ConvHandler
    tg_ext.ContextTypes = MagicMock(DEFAULT_TYPE=MagicMock)
    tg_ext.MessageHandler = MagicMock
    tg_ext.filters = MagicMock(TEXT=MagicMock(), COMMAND=MagicMock())
    sys.modules.setdefault("telegram.ext", tg_ext)

    sys.modules.setdefault(
        "watchdog.events",
        _stub_module("watchdog.events", FileSystemEventHandler=object),
    )
    sys.modules.setdefault(
        "watchdog.observers",
        _stub_module("watchdog.observers", Observer=MagicMock),
    )


_install_stubs()

import bot  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_DEFAULT_STATE = {
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


def _reset_state() -> None:
    import copy
    bot._STATE.update(copy.deepcopy(_DEFAULT_STATE))
    bot._cpu_high_count = 0


@pytest.fixture(autouse=True)
def reset(tmp_path):
    _reset_state()
    original_path = bot.STATE_PATH
    bot.STATE_PATH = tmp_path / "state.json"
    bot._STATE["users"]["notify_only"] = [NOTIFY_ID]
    yield
    bot.STATE_PATH = original_path
    _reset_state()


ADMIN_ID = 111
NOTIFY_ID = 444
STRANGER_ID = 999


# ---------------------------------------------------------------------------
# Update/context factories
# ---------------------------------------------------------------------------
def _make_update(uid: int, text: str = "/start") -> MagicMock:
    user = MagicMock()
    user.id = uid
    user.username = f"user_{uid}"
    user.first_name = f"User{uid}"
    message = MagicMock()
    message.text = text
    message.message_id = 42
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_chat = MagicMock()
    update.effective_chat.id = uid
    update.message = message
    update.callback_query = None
    return update


def _make_callback(uid: int, callback_data: str) -> MagicMock:
    user = MagicMock()
    user.id = uid
    user.username = f"user_{uid}"
    user.first_name = f"User{uid}"
    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_chat = MagicMock()
    update.effective_chat.id = uid
    update.message = None
    update.callback_query = query
    return update


def _make_context(user_data=None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot.send_message = AsyncMock()
    ctx.bot.delete_message = AsyncMock()
    ctx.application = MagicMock()
    return ctx


def run(coro):
    return asyncio.run(coro)


# ===========================================================================
# make_bar
# ===========================================================================
class TestMakeBar:
    def test_zero_percent(self):
        assert bot.make_bar(0) == "[░░░░░░░░░░] 0%"

    def test_hundred_percent(self):
        assert bot.make_bar(100) == "[██████████] 100%"

    def test_fifty_percent(self):
        assert bot.make_bar(50) == "[█████░░░░░] 50%"

    def test_seventy_eight_percent(self):
        result = bot.make_bar(78)
        assert "78%" in result
        assert result.count("█") == 8
        assert result.count("░") == 2


# ===========================================================================
# fmt_duration
# ===========================================================================
class TestFmtDuration:
    def test_zero(self):
        assert bot.fmt_duration(0) == "0m"

    def test_minutes_only(self):
        assert bot.fmt_duration(1800) == "30m"

    def test_hours_and_minutes(self):
        assert bot.fmt_duration(5400) == "1h 30m"

    def test_exactly_one_hour(self):
        assert bot.fmt_duration(3600) == "1h 00m"

    def test_large_value(self):
        assert bot.fmt_duration(15723) == "4h 22m"


# ===========================================================================
# State persistence
# ===========================================================================
class TestStatePersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        bot.STATE_PATH = tmp_path / "state.json"
        bot._STATE["known_players"] = ["Alice", "Bob"]
        bot._STATE["playtime_totals"] = {"Alice": 3600}
        bot._save_state()
        _reset_state()
        bot.STATE_PATH = tmp_path / "state.json"
        bot._load_state()
        assert set(bot._STATE["known_players"]) == {"Alice", "Bob"}
        assert bot._STATE["playtime_totals"]["Alice"] == 3600

    def test_load_missing_file_is_noop(self, tmp_path):
        bot.STATE_PATH = tmp_path / "nonexistent.json"
        bot._STATE["known_players"] = ["Existing"]
        bot._load_state()
        assert "Existing" in bot._STATE["known_players"]

    def test_load_partial_state_merges(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"known_players": ["Zara"], "schedule_enabled": True}))
        bot.STATE_PATH = path
        bot._load_state()
        assert bot._STATE["known_players"] == ["Zara"]
        assert bot._STATE["schedule_enabled"] is True
        assert bot._STATE["schedule_time"] == "03:00"

    def test_atomic_write_no_tmp_left(self, tmp_path):
        bot.STATE_PATH = tmp_path / "state.json"
        bot._save_state()
        assert bot.STATE_PATH.exists()
        assert not (tmp_path / "state.tmp").exists()


# ===========================================================================
# Access control
# ===========================================================================
class TestAccessControl:
    def setup_method(self):
        bot._STATE["users"]["admins"] = [333]
        bot._STATE["users"]["notify_only"] = [NOTIFY_ID]

    def test_env_admin_is_admin(self):
        assert bot._is_admin(111) and bot._is_admin(222)

    def test_state_admin_is_admin(self):
        assert bot._is_admin(333)

    def test_notify_only_not_admin(self):
        assert not bot._is_admin(NOTIFY_ID)

    def test_unknown_not_allowed(self):
        assert not bot._is_allowed(STRANGER_ID)

    def test_notify_only_is_allowed(self):
        assert bot._is_allowed(NOTIFY_ID)

    def test_admin_is_allowed(self):
        assert bot._is_allowed(ADMIN_ID)


# ===========================================================================
# Session tracking
# ===========================================================================
class TestSessionTracking:
    def test_join_records_active(self):
        bot._record_join("Alice")
        assert "Alice" in bot._STATE["sessions_active"]

    def test_leave_moves_to_history(self):
        bot._record_join("Alice")
        bot._record_leave("Alice")
        assert "Alice" not in bot._STATE["sessions_active"]
        assert len(bot._STATE["sessions_history"]) == 1
        assert bot._STATE["sessions_history"][0]["name"] == "Alice"

    def test_leave_updates_playtime(self):
        bot._record_join("Bob")
        past = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        ).isoformat().replace("+00:00", "Z")
        bot._STATE["sessions_active"]["Bob"] = past
        bot._record_leave("Bob")
        assert 3590 <= bot._STATE["playtime_totals"]["Bob"] <= 3610

    def test_leave_unknown_is_noop(self):
        bot._record_leave("Nobody")
        assert len(bot._STATE["sessions_history"]) == 0

    def test_playtime_accumulates(self):
        for _ in range(3):
            bot._record_join("Carol")
            past = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
            ).isoformat().replace("+00:00", "Z")
            bot._STATE["sessions_active"]["Carol"] = past
            bot._record_leave("Carol")
        assert 1790 <= bot._STATE["playtime_totals"]["Carol"] <= 1810

    def test_history_capped_at_500(self):
        for i in range(510):
            name = f"P{i}"
            bot._record_join(name)
            past = (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
            ).isoformat().replace("+00:00", "Z")
            bot._STATE["sessions_active"][name] = past
            bot._record_leave(name)
        assert len(bot._STATE["sessions_history"]) == 500


# ===========================================================================
# Notify waitlist
# ===========================================================================
class TestNotifyWaitlist:
    def test_flush_clears_list(self):
        bot._STATE["notify_waitlist"] = [101, 102]
        ctx = _make_context()
        run(bot._flush_waitlist(ctx))
        assert bot._STATE["notify_waitlist"] == []

    def test_flush_sends_to_all(self):
        bot._STATE["notify_waitlist"] = [101, 102, 103]
        ctx = _make_context()
        run(bot._flush_waitlist(ctx))
        assert ctx.bot.send_message.call_count == 3

    def test_flush_empty_is_noop(self):
        bot._STATE["notify_waitlist"] = []
        ctx = _make_context()
        run(bot._flush_waitlist(ctx))
        ctx.bot.send_message.assert_not_called()


# ===========================================================================
# Idle auto-stop  (ADR-009: _container_running and _docker_stop are now async)
# ===========================================================================
class TestIdleAutostop:
    def test_resets_when_players_active(self):
        bot._STATE["sessions_active"] = {"Alice": bot._now_iso()}
        bot._STATE["idle_empty_since"] = "2026-01-01T00:00:00Z"
        ctx = _make_context()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=True)):
            run(bot._idle_autostop_job(ctx))
        assert bot._STATE["idle_empty_since"] is None

    def test_sets_idle_since_when_first_empty(self):
        bot._STATE["sessions_active"] = {}
        bot._STATE["idle_empty_since"] = None
        ctx = _make_context()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=True)):
            run(bot._idle_autostop_job(ctx))
        assert bot._STATE["idle_empty_since"] is not None

    def test_sends_warning_near_timeout(self):
        bot._STATE["sessions_active"] = {}
        bot._STATE["idle_warning_sent"] = False
        timeout = bot.IDLE_TIMEOUT_MINUTES
        idle_since = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=timeout - 3)
        ).isoformat().replace("+00:00", "Z")
        bot._STATE["idle_empty_since"] = idle_since
        ctx = _make_context()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=True)):
            run(bot._idle_autostop_job(ctx))
        assert bot._STATE["idle_warning_sent"] is True
        ctx.bot.send_message.assert_awaited()

    def test_stops_at_timeout(self):
        bot._STATE["sessions_active"] = {}
        timeout = bot.IDLE_TIMEOUT_MINUTES
        idle_since = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=timeout + 1)
        ).isoformat().replace("+00:00", "Z")
        bot._STATE["idle_empty_since"] = idle_since
        ctx = _make_context()
        mock_stop = AsyncMock()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=True)), \
             patch.object(bot, "_docker_stop", mock_stop):
            run(bot._idle_autostop_job(ctx))
        mock_stop.assert_awaited_once()
        assert bot._STATE["idle_empty_since"] is None

    def test_noop_when_container_not_running(self):
        bot._STATE["sessions_active"] = {}
        ctx = _make_context()
        mock_stop = AsyncMock()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=False)), \
             patch.object(bot, "_docker_stop", mock_stop):
            run(bot._idle_autostop_job(ctx))
        mock_stop.assert_not_awaited()


# ===========================================================================
# Resource alerts
# ===========================================================================
class TestResourceAlerts:
    def test_no_alert_below_thresholds(self):
        ctx = _make_context()
        with patch("psutil.cpu_percent", return_value=50.0), \
             patch("psutil.virtual_memory", return_value=MagicMock(percent=70.0)):
            run(bot._resource_alert_job(ctx))
        ctx.bot.send_message.assert_not_called()

    def test_cpu_alert_after_3_consecutive(self):
        bot._cpu_high_count = 2
        ctx = _make_context()
        with patch("psutil.cpu_percent", return_value=90.0), \
             patch("psutil.virtual_memory", return_value=MagicMock(percent=50.0)):
            run(bot._resource_alert_job(ctx))
        ctx.bot.send_message.assert_awaited()
        assert bot._cpu_high_count == 0

    def test_cpu_counter_resets_on_low(self):
        bot._cpu_high_count = 2
        ctx = _make_context()
        with patch("psutil.cpu_percent", return_value=30.0), \
             patch("psutil.virtual_memory", return_value=MagicMock(percent=50.0)):
            run(bot._resource_alert_job(ctx))
        assert bot._cpu_high_count == 0

    def test_ram_alert_immediate(self):
        ctx = _make_context()
        with patch("psutil.cpu_percent", return_value=30.0), \
             patch("psutil.virtual_memory", return_value=MagicMock(percent=95.0)):
            run(bot._resource_alert_job(ctx))
        ctx.bot.send_message.assert_awaited()


# ===========================================================================
# Sys info text  (ADR-009: _build_sysinfo_text and _container_status are now async)
# ===========================================================================
class TestSysInfoText:
    def test_contains_all_sections(self):
        with patch("psutil.cpu_percent", return_value=78.0), \
             patch("psutil.virtual_memory", return_value=MagicMock(percent=65.0)), \
             patch("psutil.disk_usage", return_value=MagicMock(percent=42.0)), \
             patch.object(bot, "_container_status", new=AsyncMock(return_value="running")), \
             patch.object(bot, "_container_uptime", return_value="2h 15m 00s"):
            text = run(bot._build_sysinfo_text())
        assert "CPU:" in text
        assert "RAM:" in text
        assert "Disk:" in text
        assert "Container:" in text
        assert "Uptime:" in text
        assert "78%" in text
        assert "2h 15m 00s" in text


# ===========================================================================
# Token validation
# ===========================================================================
class TestValidateRuntimeConfig:
    def test_placeholder_raises(self):
        with patch.object(bot, "BOT_TOKEN", "your-telegram-bot-token-here"):
            with pytest.raises(SystemExit):
                bot._validate_runtime_config()

    def test_malformed_raises(self):
        with patch.object(bot, "BOT_TOKEN", "notavalidtoken"):
            with pytest.raises(SystemExit):
                bot._validate_runtime_config()

    def test_valid_passes(self):
        with patch.object(bot, "BOT_TOKEN", "123456789:AAabcdefghijklmnopqrstuvwxyz1234567"):
            bot._validate_runtime_config()


# ===========================================================================
# Scenario 1 — Admin opens panel with /start; stranger is blocked
# ===========================================================================
class TestScenarioAdminStart:
    def test_admin_gets_panel(self):
        update = _make_update(ADMIN_ID)
        run(bot.cmd_start(update, _make_context()))
        update.message.reply_text.assert_awaited_once()
        assert "Windrose Server Control" in update.message.reply_text.call_args[0][0]

    def test_stranger_silent(self):
        update = _make_update(STRANGER_ID)
        run(bot.cmd_start(update, _make_context()))
        update.message.reply_text.assert_not_awaited()

    def test_notify_only_gets_panel(self):
        update = _make_update(NOTIFY_ID)
        run(bot.cmd_start(update, _make_context()))
        update.message.reply_text.assert_awaited_once()


# ===========================================================================
# Scenario 2 — Notify Me button
# ===========================================================================
class TestScenarioNotifyMeButton:
    def test_subscribe_when_stopped(self):
        update = _make_callback(NOTIFY_ID, "v2_notify_sub")
        ctx = _make_context()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=False)):
            run(bot.button_handler(update, ctx))
        assert NOTIFY_ID in bot._STATE["notify_waitlist"]
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "notified" in text.lower()

    def test_already_running_message(self):
        update = _make_callback(NOTIFY_ID, "v2_notify_sub")
        ctx = _make_context()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=True)):
            run(bot.button_handler(update, ctx))
        assert NOTIFY_ID not in bot._STATE["notify_waitlist"]
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "already online" in text.lower()

    def test_subscribe_idempotent(self):
        bot._STATE["notify_waitlist"] = [NOTIFY_ID]
        update = _make_callback(NOTIFY_ID, "v2_notify_sub")
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=False)):
            run(bot.button_handler(update, _make_context()))
        assert bot._STATE["notify_waitlist"].count(NOTIFY_ID) == 1


# ===========================================================================
# Scenario 3 — Access enforcement
# ===========================================================================
class TestScenarioAccessEnforcement:
    def test_notify_only_blocked_from_settings(self):
        update = _make_callback(NOTIFY_ID, "v2_settings_menu")
        run(bot.button_handler(update, _make_context()))
        update.callback_query.answer.assert_awaited()
        update.callback_query.edit_message_text.assert_not_awaited()

    def test_notify_only_blocked_from_stop(self):
        update = _make_callback(NOTIFY_ID, "cb_stop_ask")
        run(bot.button_handler(update, _make_context()))
        update.callback_query.answer.assert_awaited()
        update.callback_query.edit_message_text.assert_not_awaited()

    def test_notify_only_blocked_from_users_menu(self):
        update = _make_callback(NOTIFY_ID, "v2_users_menu")
        run(bot.button_handler(update, _make_context()))
        update.callback_query.edit_message_text.assert_not_awaited()

    def test_stranger_completely_silent(self):
        update = _make_callback(STRANGER_ID, "cb_stop_ask")
        run(bot.button_handler(update, _make_context()))
        update.callback_query.answer.assert_not_awaited()
        update.callback_query.edit_message_text.assert_not_awaited()


# ===========================================================================
# Scenario 4 — Admin stop flow
# ===========================================================================
class TestScenarioStopFlow:
    def test_stop_ask_shows_confirmation(self):
        update = _make_callback(ADMIN_ID, "cb_stop_ask")
        run(bot.button_handler(update, _make_context()))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Stop" in text or "disconnect" in text.lower()

    def test_confirmed_stop_calls_docker(self):
        update = _make_callback(ADMIN_ID, "cb_confirmed_stop")
        mock_stop = AsyncMock()
        with patch.object(bot, "_docker_stop", mock_stop):
            run(bot.button_handler(update, _make_context()))
        mock_stop.assert_awaited_once()

    def test_cancel_returns_to_main_panel(self):
        update = _make_callback(ADMIN_ID, "cb_panel")
        run(bot.button_handler(update, _make_context()))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Windrose Server Control" in text


# ===========================================================================
# Scenario 5 — Add notify user (ADR-011: tests the ConversationHandler functions)
# ===========================================================================
class TestScenarioAddNotifyUser:
    def test_ask_sets_fsm_name(self):
        update = _make_callback(ADMIN_ID, "v2_users_add_notify")
        ctx = _make_context()
        run(bot._flow_add_notify_ask(update, ctx))
        assert ctx.user_data.get("_fsm_name") == "ADD_NOTIFY"

    def test_receive_happy_path(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="555")
        run(bot._flow_add_notify_receive(update_msg, ctx))
        assert 555 in bot._STATE["users"]["notify_only"]
        reply = update_msg.message.reply_text.call_args[0][0]
        assert "555" in reply

    def test_receive_invalid_id_rejected(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="not_a_number")
        run(bot._flow_add_notify_receive(update_msg, ctx))
        assert len(bot._STATE["users"]["notify_only"]) == 1  # only the seeded NOTIFY_ID
        reply = update_msg.message.reply_text.call_args[0][0]
        assert "Invalid" in reply

    def test_receive_invalid_stays_in_waiting(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="not_a_number")
        state = run(bot._flow_add_notify_receive(update_msg, ctx))
        assert state == bot._WAITING

    def test_receive_success_ends_conversation(self):
        from telegram.ext import ConversationHandler
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="555")
        state = run(bot._flow_add_notify_receive(update_msg, ctx))
        assert state == ConversationHandler.END

    def test_add_admin_receive(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="777")
        run(bot._flow_add_admin_receive(update_msg, ctx))
        assert 777 in bot._STATE["users"]["admins"]

    def test_add_admin_ask_sets_fsm_name(self):
        update = _make_callback(ADMIN_ID, "v2_users_add_admin")
        ctx = _make_context()
        run(bot._flow_add_admin_ask(update, ctx))
        assert ctx.user_data.get("_fsm_name") == "ADD_ADMIN"


# ===========================================================================
# Scenario 6 — Change password (ADR-011 + ADR-013)
# ===========================================================================
class TestScenarioPasswordChange:
    def test_blocked_when_running(self):
        update = _make_callback(ADMIN_ID, "v2_settings_changepw")
        ctx = _make_context()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=True)):
            run(bot._flow_changepw_ask(update, ctx))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "stop" in text.lower()
        assert ctx.user_data.get("_fsm_name") is None

    def test_prompts_when_stopped(self):
        update = _make_callback(ADMIN_ID, "v2_settings_changepw")
        ctx = _make_context()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=False)):
            run(bot._flow_changepw_ask(update, ctx))
        assert ctx.user_data.get("_fsm_name") == "CHANGE_PASSWORD"
        assert ctx.user_data.get("_fsm_sensitive") is True

    def test_password_message_writes_file(self, tmp_path):
        desc_file = tmp_path / "ServerDescription.json"
        desc_file.write_text(json.dumps({"InviteCode": "ABC", "ServerPassword": "old"}))
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="newpass123")
        with patch.object(bot, "SERVER_DESC_PATH", desc_file):
            run(bot._flow_changepw_receive(update_msg, ctx))
        assert json.loads(desc_file.read_text())["ServerPassword"] == "newpass123"

    def test_password_message_is_deleted(self, tmp_path):
        desc_file = tmp_path / "ServerDescription.json"
        desc_file.write_text(json.dumps({"InviteCode": "ABC", "ServerPassword": "old"}))
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="secret")
        with patch.object(bot, "SERVER_DESC_PATH", desc_file):
            run(bot._flow_changepw_receive(update_msg, ctx))
        ctx.bot.delete_message.assert_awaited_once()

    def test_remove_password_blocked_when_running(self):
        update = _make_callback(ADMIN_ID, "v2_settings_removepw_confirmed")
        ctx = _make_context()
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=True)):
            run(bot.button_handler(update, ctx))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "stop" in text.lower()

    def test_remove_password_clears_field(self, tmp_path):
        desc_file = tmp_path / "ServerDescription.json"
        desc_file.write_text(json.dumps({"InviteCode": "ABC", "ServerPassword": "secret"}))
        update = _make_callback(ADMIN_ID, "v2_settings_removepw_confirmed")
        with patch.object(bot, "SERVER_DESC_PATH", desc_file), \
             patch.object(bot, "_container_running", new=AsyncMock(return_value=False)):
            run(bot.button_handler(update, _make_context()))
        assert json.loads(desc_file.read_text())["ServerPassword"] == ""


# ===========================================================================
# Scenario 7 — Schedule toggle and set time (ADR-011: set time uses flow fn)
# ===========================================================================
class TestScenarioSchedule:
    def test_view_disabled(self):
        bot._STATE["schedule_enabled"] = False
        update = _make_callback(ADMIN_ID, "v2_schedule_view")
        run(bot.button_handler(update, _make_context()))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Disabled" in text

    def test_view_enabled(self):
        bot._STATE["schedule_enabled"] = True
        bot._STATE["schedule_time"] = "04:00"
        update = _make_callback(ADMIN_ID, "v2_schedule_view")
        run(bot.button_handler(update, _make_context()))
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "04:00" in text

    def test_toggle_off_to_on(self):
        bot._STATE["schedule_enabled"] = False
        update = _make_callback(ADMIN_ID, "v2_schedule_toggle")
        with patch.object(bot, "_register_scheduled_restart"), \
             patch.object(bot, "_cancel_scheduled_restart"):
            run(bot.button_handler(update, _make_context()))
        assert bot._STATE["schedule_enabled"] is True
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "enabled" in text.lower()

    def test_toggle_on_to_off(self):
        bot._STATE["schedule_enabled"] = True
        update = _make_callback(ADMIN_ID, "v2_schedule_toggle")
        with patch.object(bot, "_register_scheduled_restart"), \
             patch.object(bot, "_cancel_scheduled_restart"):
            run(bot.button_handler(update, _make_context()))
        assert bot._STATE["schedule_enabled"] is False

    def test_set_time_valid(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="04:30")
        with patch.object(bot, "_cancel_scheduled_restart"), \
             patch.object(bot, "_register_scheduled_restart"):
            run(bot._flow_schedule_receive(update_msg, ctx))
        assert bot._STATE["schedule_time"] == "04:30"
        assert "04:30" in update_msg.message.reply_text.call_args[0][0]

    def test_set_time_invalid_format(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="25:99")
        run(bot._flow_schedule_receive(update_msg, ctx))
        assert bot._STATE["schedule_time"] == "03:00"

    def test_set_time_bad_string(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="noon")
        run(bot._flow_schedule_receive(update_msg, ctx))
        assert bot._STATE["schedule_time"] == "03:00"

    def test_set_time_ask_sets_fsm_name(self):
        update = _make_callback(ADMIN_ID, "v2_schedule_set")
        ctx = _make_context()
        run(bot._flow_schedule_ask(update, ctx))
        assert ctx.user_data.get("_fsm_name") == "SET_SCHEDULE"


# ===========================================================================
# Scenario 8 — /history and /playtime
# ===========================================================================
class TestScenarioHistoryAndPlaytime:
    def test_history_empty(self):
        update = _make_update(ADMIN_ID)
        run(bot.cmd_history(update, _make_context()))
        assert "No session history" in update.message.reply_text.call_args[0][0]

    def test_history_shows_entries(self):
        bot._STATE["sessions_history"] = [
            {"name": "Alice", "joined": "2026-04-24T10:00:00Z",
             "left": "2026-04-24T11:00:00Z", "duration_s": 3600},
        ]
        update = _make_update(ADMIN_ID)
        run(bot.cmd_history(update, _make_context()))
        assert "Alice" in update.message.reply_text.call_args[0][0]

    def test_playtime_empty(self):
        update = _make_update(ADMIN_ID)
        run(bot.cmd_playtime(update, _make_context()))
        assert "No playtime" in update.message.reply_text.call_args[0][0]

    def test_playtime_sorted_descending(self):
        bot._STATE["playtime_totals"] = {"Alice": 7200, "Bob": 3600, "Carol": 14400}
        update = _make_update(ADMIN_ID)
        run(bot.cmd_playtime(update, _make_context()))
        reply = update.message.reply_text.call_args[0][0]
        assert reply.index("Carol") < reply.index("Alice") < reply.index("Bob")

    def test_notify_only_can_see_history(self):
        bot._STATE["sessions_history"] = [
            {"name": "X", "joined": "2026-04-24T10:00:00Z",
             "left": "2026-04-24T10:30:00Z", "duration_s": 1800},
        ]
        update = _make_update(NOTIFY_ID)
        run(bot.cmd_history(update, _make_context()))
        update.message.reply_text.assert_awaited()


# ===========================================================================
# Scenario 9 — /notify command
# ===========================================================================
class TestScenarioNotifyCommand:
    def test_adds_to_waitlist_when_stopped(self):
        update = _make_update(ADMIN_ID)
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=False)):
            run(bot.cmd_notify(update, _make_context()))
        assert ADMIN_ID in bot._STATE["notify_waitlist"]

    def test_replies_online_when_running(self):
        update = _make_update(ADMIN_ID)
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=True)):
            run(bot.cmd_notify(update, _make_context()))
        assert ADMIN_ID not in bot._STATE["notify_waitlist"]
        assert "already online" in update.message.reply_text.call_args[0][0].lower()

    def test_idempotent(self):
        bot._STATE["notify_waitlist"] = [ADMIN_ID]
        update = _make_update(ADMIN_ID)
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=False)):
            run(bot.cmd_notify(update, _make_context()))
        assert bot._STATE["notify_waitlist"].count(ADMIN_ID) == 1

    def test_notify_only_user_can_subscribe(self):
        update = _make_update(NOTIFY_ID)
        with patch.object(bot, "_container_running", new=AsyncMock(return_value=False)):
            run(bot.cmd_notify(update, _make_context()))
        assert NOTIFY_ID in bot._STATE["notify_waitlist"]


# ===========================================================================
# Scenario 10 — Remove user flow (ADR-011: tests the flow functions)
# ===========================================================================
class TestScenarioRemoveUser:
    def test_ask_sets_fsm_name(self):
        update = _make_callback(ADMIN_ID, "v2_users_remove")
        ctx = _make_context()
        run(bot._flow_remove_user_ask(update, ctx))
        assert ctx.user_data.get("_fsm_name") == "REMOVE_USER"

    def test_remove_existing_notify_user(self):
        bot._STATE["users"]["notify_only"] = [NOTIFY_ID, 555]
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text=str(NOTIFY_ID))
        run(bot._flow_remove_user_receive(update_msg, ctx))
        assert NOTIFY_ID not in bot._STATE["users"]["notify_only"]
        assert "Removed" in update_msg.message.reply_text.call_args[0][0]

    def test_remove_nonexistent_user(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="9999")
        run(bot._flow_remove_user_receive(update_msg, ctx))
        assert "not found" in update_msg.message.reply_text.call_args[0][0].lower()

    def test_remove_admin_from_state(self):
        bot._STATE["users"]["admins"] = [333]
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="333")
        run(bot._flow_remove_user_receive(update_msg, ctx))
        assert 333 not in bot._STATE["users"]["admins"]

    def test_invalid_id_stays_in_waiting(self):
        ctx = _make_context()
        update_msg = _make_update(ADMIN_ID, text="notanumber")
        state = run(bot._flow_remove_user_receive(update_msg, ctx))
        assert state == bot._WAITING

"""services/settings.py — Read/write helpers for Windrose server config files.

Two files govern the server:
  - SERVER_MAIN_DESC  (R5/ServerDescription.json)      — server-wide settings
  - SERVER_PASS_DESC  (R5/Saved/ServerDescription.json) — password only
  - WORLD_DESC        (R5/Saved/SaveProfiles/Default/RocksDB/<ver>/Worlds/<id>/WorldDescription.json)

All writes require the server to be stopped (caller enforces this).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from windrose_bot import config

# ── Tag-name shortcuts used in WorldDescription.WorldSettings ────────────────
_BOOL = "BoolParameters"
_FLOAT = "FloatParameters"
_TAG = "TagParameters"

_T_SHARED_QUESTS = '{"TagName": "WDS.Parameter.Coop.SharedQuests"}'
_T_EASY_EXPLORE  = '{"TagName": "WDS.Parameter.EasyExplore"}'
_T_MOB_HP        = '{"TagName": "WDS.Parameter.MobHealthMultiplier"}'
_T_MOB_DMG       = '{"TagName": "WDS.Parameter.MobDamageMultiplier"}'
_T_SHIP_HP       = '{"TagName": "WDS.Parameter.ShipsHealthMultiplier"}'
_T_SHIP_DMG      = '{"TagName": "WDS.Parameter.ShipsDamageMultiplier"}'
_T_BOARDING      = '{"TagName": "WDS.Parameter.BoardingDifficultyMultiplier"}'
_T_COOP_STATS    = '{"TagName": "WDS.Parameter.Coop.StatsCorrectionModifier"}'
_T_COOP_SHIP     = '{"TagName": "WDS.Parameter.Coop.ShipStatsCorrectionModifier"}'
_T_COMBAT_DIFF   = '{"TagName": "WDS.Parameter.CombatDifficulty"}'

# Preset values from official docs
_PRESETS: dict[str, dict] = {
    "Easy": {
        _T_MOB_HP: 0.7, _T_MOB_DMG: 0.6, _T_SHIP_HP: 0.7, _T_SHIP_DMG: 0.6,
        _T_BOARDING: 0.7, _T_COOP_STATS: 1.0, _T_COOP_SHIP: 0.0,
        "combat_difficulty": "WDS.Parameter.CombatDifficulty.Easy",
    },
    "Medium": {
        _T_MOB_HP: 1.0, _T_MOB_DMG: 1.0, _T_SHIP_HP: 1.0, _T_SHIP_DMG: 1.0,
        _T_BOARDING: 1.0, _T_COOP_STATS: 1.0, _T_COOP_SHIP: 0.0,
        "combat_difficulty": "WDS.Parameter.CombatDifficulty.Normal",
    },
    "Hard": {
        _T_MOB_HP: 1.5, _T_MOB_DMG: 1.25, _T_SHIP_HP: 1.5, _T_SHIP_DMG: 1.25,
        _T_BOARDING: 1.5, _T_COOP_STATS: 1.0, _T_COOP_SHIP: 0.0,
        "combat_difficulty": "WDS.Parameter.CombatDifficulty.Hard",
    },
}

# Multiplier step options shown in the UI (min clamps per param enforced on write)
FLOAT_STEPS = [0.2, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
REGIONS = ["", "EU", "SEA", "CIS"]
MAX_PLAYERS_OPTIONS = [2, 4, 6, 8, 10, 16, 32]


# ── Path resolution ──────────────────────────────────────────────────────────

def main_desc_path() -> Path:
    """R5/ServerDescription.json (main settings, nested structure)."""
    base = Path(config.SERVER_FILES_DIR)
    return base / "ServerDescription.json"


def pass_desc_path() -> Path:
    """R5/Saved/ServerDescription.json (password only, flat)."""
    base = Path(config.SERVER_FILES_DIR)
    return base / "Saved" / "ServerDescription.json"


def world_desc_path(world_id: str | None = None) -> Path | None:
    """Resolve WorldDescription.json for the active world.

    Finds the latest version folder under RocksDB automatically.
    """
    base = Path(config.SERVER_FILES_DIR) / "Saved" / "SaveProfiles" / "Default" / "RocksDB"
    if not base.exists():
        return None
    wid = world_id or _active_world_id()
    if not wid:
        return None
    # Latest version folder by name sort (semver-ish)
    version_dirs = [d for d in base.iterdir() if d.is_dir()]
    if not version_dirs:
        return None
    latest = sorted(version_dirs, key=lambda d: d.name)[-1]
    candidate = latest / "Worlds" / wid / "WorldDescription.json"
    return candidate if candidate.exists() else None


def _active_world_id() -> str | None:
    desc = read_main_desc()
    return (desc.get("ServerDescription_Persistent") or {}).get("WorldIslandId")


# ── ServerDescription (main) ─────────────────────────────────────────────────

def read_main_desc() -> dict:
    """Return the full ServerDescription.json dict (with Version/DeploymentId/ServerDescription_Persistent)."""
    p = main_desc_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_persistent(field: str, default: Any = None) -> Any:
    """Get a field from ServerDescription_Persistent."""
    return (read_main_desc().get("ServerDescription_Persistent") or {}).get(field, default)


def set_persistent(field: str, value: Any) -> None:
    """Set a field in ServerDescription_Persistent and write atomically."""
    data = read_main_desc()
    data.setdefault("ServerDescription_Persistent", {})[field] = value
    _write_json(main_desc_path(), data)


# ── Password file ─────────────────────────────────────────────────────────────

def read_pass_desc() -> dict:
    try:
        return json.loads(pass_desc_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_password(password: str) -> None:
    data = read_pass_desc()
    if password:
        data["ServerPassword"] = password
        set_persistent("IsPasswordProtected", True)
        set_persistent("Password", password)
    else:
        data["ServerPassword"] = ""
        set_persistent("IsPasswordProtected", False)
        set_persistent("Password", "")
    _write_json(pass_desc_path(), data)


# ── WorldDescription ─────────────────────────────────────────────────────────

def read_world_desc(world_id: str | None = None) -> dict:
    p = world_desc_path(world_id)
    if p is None:
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_wd(field: str, section: str, key: str, default: Any = None) -> Any:
    return (
        (read_world_desc().get("WorldDescription") or {})
        .get("WorldSettings", {})
        .get(section, {})
        .get(key, default)
    )


def get_bool_param(tag: str) -> bool | None:
    ws = (read_world_desc().get("WorldDescription") or {}).get("WorldSettings", {})
    return ws.get(_BOOL, {}).get(tag)


def get_float_param(tag: str) -> float | None:
    ws = (read_world_desc().get("WorldDescription") or {}).get("WorldSettings", {})
    return ws.get(_FLOAT, {}).get(tag)


def get_combat_difficulty() -> str:
    ws = (read_world_desc().get("WorldDescription") or {}).get("WorldSettings", {})
    tag_val = ws.get(_TAG, {}).get(_T_COMBAT_DIFF, {})
    return (tag_val.get("TagName") or "").replace("WDS.Parameter.CombatDifficulty.", "") or "Normal"


def get_world_preset() -> str:
    return (read_world_desc().get("WorldDescription") or {}).get("WorldPresetType", "—")


def set_world_preset(preset: str) -> None:
    """Apply an Easy/Medium/Hard preset and write WorldDescription."""
    if preset not in _PRESETS:
        raise ValueError(f"Unknown preset: {preset}")
    p = world_desc_path()
    if p is None:
        raise FileNotFoundError("WorldDescription.json not found")
    data = json.loads(p.read_text(encoding="utf-8"))
    wd = data.setdefault("WorldDescription", {})
    wd["WorldPresetType"] = preset
    vals = _PRESETS[preset]
    ws = wd.setdefault("WorldSettings", {
        _BOOL: {}, _FLOAT: {}, _TAG: {}
    })
    ws.setdefault(_BOOL, {})[_T_SHARED_QUESTS] = True
    ws.setdefault(_BOOL, {})[_T_EASY_EXPLORE] = False
    fp = ws.setdefault(_FLOAT, {})
    for tag in (_T_MOB_HP, _T_MOB_DMG, _T_SHIP_HP, _T_SHIP_DMG, _T_BOARDING, _T_COOP_STATS, _T_COOP_SHIP):
        fp[tag] = vals[tag]
    ws.setdefault(_TAG, {})[_T_COMBAT_DIFF] = {"TagName": vals["combat_difficulty"]}
    _write_json(p, data)


def set_float_param(tag: str, value: float) -> None:
    p = world_desc_path()
    if p is None:
        raise FileNotFoundError("WorldDescription.json not found")
    data = json.loads(p.read_text(encoding="utf-8"))
    wd = data.setdefault("WorldDescription", {})
    wd["WorldPresetType"] = "Custom"
    wd.setdefault("WorldSettings", {}).setdefault(_FLOAT, {})[tag] = value
    _write_json(p, data)


def set_bool_param(tag: str, value: bool) -> None:
    p = world_desc_path()
    if p is None:
        raise FileNotFoundError("WorldDescription.json not found")
    data = json.loads(p.read_text(encoding="utf-8"))
    wd = data.setdefault("WorldDescription", {})
    wd["WorldPresetType"] = "Custom"
    wd.setdefault("WorldSettings", {}).setdefault(_BOOL, {})[tag] = value
    _write_json(p, data)


def set_combat_difficulty(level: str) -> None:
    """level: Easy | Normal | Hard"""
    p = world_desc_path()
    if p is None:
        raise FileNotFoundError("WorldDescription.json not found")
    data = json.loads(p.read_text(encoding="utf-8"))
    wd = data.setdefault("WorldDescription", {})
    wd["WorldPresetType"] = "Custom"
    wd.setdefault("WorldSettings", {}).setdefault(_TAG, {})[_T_COMBAT_DIFF] = {
        "TagName": f"WDS.Parameter.CombatDifficulty.{level}"
    }
    _write_json(p, data)


def set_world_name(name: str) -> None:
    p = world_desc_path()
    if p is None:
        raise FileNotFoundError("WorldDescription.json not found")
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("WorldDescription", {})["WorldName"] = name
    _write_json(p, data)


# ── Summary helpers ───────────────────────────────────────────────────────────

def server_summary() -> str:
    ps = (read_main_desc().get("ServerDescription_Persistent") or {})
    name = ps.get("ServerName") or "—"
    max_p = ps.get("MaxPlayerCount", "—")
    region = ps.get("UserSelectedRegion") or "Auto"
    direct = "Yes" if ps.get("UseDirectConnection") else "No"
    invite = ps.get("InviteCode") or "—"
    pw = "Yes" if ps.get("IsPasswordProtected") else "No"
    return (
        f"<b>🌐 Server Settings</b>\n\n"
        f"Name: <b>{name}</b>\n"
        f"Invite Code: <code>{invite}</code>\n"
        f"Password: <b>{pw}</b>\n"
        f"Max Players: <b>{max_p}</b>\n"
        f"Region: <b>{region}</b>\n"
        f"Direct Connect: <b>{direct}</b>"
    )


def world_summary() -> str:
    wd = read_world_desc().get("WorldDescription") or {}
    ws = wd.get("WorldSettings", {})
    name = wd.get("WorldName") or "—"
    preset = wd.get("WorldPresetType", "—")
    combat = get_combat_difficulty()
    shared = ws.get(_BOOL, {}).get(_T_SHARED_QUESTS, "—")
    immersive = ws.get(_BOOL, {}).get(_T_EASY_EXPLORE, False)
    mob_hp  = ws.get(_FLOAT, {}).get(_T_MOB_HP, "—")
    mob_dmg = ws.get(_FLOAT, {}).get(_T_MOB_DMG, "—")
    shp_hp  = ws.get(_FLOAT, {}).get(_T_SHIP_HP, "—")
    shp_dmg = ws.get(_FLOAT, {}).get(_T_SHIP_DMG, "—")
    board   = ws.get(_FLOAT, {}).get(_T_BOARDING, "—")
    coop_s  = ws.get(_FLOAT, {}).get(_T_COOP_STATS, "—")
    coop_sh = ws.get(_FLOAT, {}).get(_T_COOP_SHIP, "—")

    def _tick(v) -> str:
        if v is True: return "✅"
        if v is False: return "❌"
        return str(v)

    return (
        f"<b>⚔️ World Settings</b>\n\n"
        f"World: <b>{name}</b>\n"
        f"Preset: <b>{preset}</b>\n"
        f"Combat Difficulty: <b>{combat}</b>\n"
        f"Shared Quests: {_tick(shared)}\n"
        f"Immersive Explore: {_tick(immersive)}\n\n"
        f"Mob HP: <b>×{mob_hp}</b> | Mob DMG: <b>×{mob_dmg}</b>\n"
        f"Ship HP: <b>×{shp_hp}</b> | Ship DMG: <b>×{shp_dmg}</b>\n"
        f"Boarding: <b>×{board}</b>\n"
        f"Coop Stats: <b>×{coop_s}</b> | Coop Ships: <b>×{coop_sh}</b>"
    )


# ── Internal ─────────────────────────────────────────────────────────────────

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent="\t", ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

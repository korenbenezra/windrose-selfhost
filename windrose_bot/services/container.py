"""services/container.py — async Windows service wrappers (ADR-009)."""
from __future__ import annotations

import asyncio
import datetime
import subprocess

import psutil

from windrose_bot.config import SVC_NAME


class ServiceControlError(RuntimeError):
    """Raised when Windows service control command fails."""


async def _run(*args: str) -> subprocess.CompletedProcess:
    return await asyncio.to_thread(
        subprocess.run, ["sc.exe", *args], capture_output=True, text=True
    )


def _result_text(r: subprocess.CompletedProcess) -> str:
    parts: list[str] = []
    if r.stdout:
        parts.append(r.stdout.strip())
    if r.stderr:
        parts.append(r.stderr.strip())
    return "\n".join(p for p in parts if p).strip()


async def _run_checked(*args: str, allow_patterns: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    r = await _run(*args)
    text = _result_text(r)
    if r.returncode == 0:
        return r
    lowered = text.lower()
    if any(p.lower() in lowered for p in allow_patterns):
        return r
    cmd = "sc.exe " + " ".join(args)
    if "access is denied" in lowered:
        raise ServiceControlError(
            f"{cmd} failed (exit {r.returncode}). {text or 'No output.'}\n"
            f"Run the bot as Administrator, or grant this user service-control rights for '{SVC_NAME}'."
        )
    raise ServiceControlError(
        f"{cmd} failed (exit {r.returncode}). {text or 'No output.'}"
    )


async def running() -> bool:
    r = await _run("query", SVC_NAME)
    return "RUNNING" in r.stdout


async def status() -> str:
    r = await _run("query", SVC_NAME)
    if r.returncode != 0:
        text = _result_text(r).lower()
        if "access is denied" in text:
            return "access denied"
        if "does not exist" in text or "specified service does not exist" in text:
            return "not installed"
        return "unknown"
    for line in r.stdout.splitlines():
        if "STATE" in line:
            parts = line.split()
            if len(parts) >= 4:
                return parts[3].lower()
    return "unknown"


async def stop() -> None:
    await _run_checked(
        "stop",
        SVC_NAME,
        allow_patterns=("FAILED 1062", "service has not been started"),
    )


async def start() -> None:
    await _run_checked(
        "start",
        SVC_NAME,
        allow_patterns=("FAILED 1056", "already running"),
    )


async def restart() -> None:
    await stop()
    await asyncio.sleep(8)
    await start()


def uptime() -> str:
    for proc in psutil.process_iter(["name", "create_time"]):
        try:
            if "WindroseServer" in (proc.info["name"] or ""):
                started = datetime.datetime.fromtimestamp(
                    proc.info["create_time"], tz=datetime.timezone.utc
                )
                delta = datetime.datetime.now(datetime.timezone.utc) - started
                total = int(delta.total_seconds())
                h, rem = divmod(total, 3600)
                m, s = divmod(rem, 60)
                return f"{h}h {m:02d}m {s:02d}s"
        except Exception:
            pass
    return "unknown"

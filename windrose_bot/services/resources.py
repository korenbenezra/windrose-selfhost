"""services/resources.py — non-blocking system resource helpers (ADR-009)."""
from __future__ import annotations

from pathlib import Path

import psutil

from windrose_bot.services import container


def make_bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + "] " + str(round(pct)) + "%"


async def sysinfo_text() -> str:
    cpu = psutil.cpu_percent(interval=0.0)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    temp_str = "N/A"
    temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if temp_path.exists():
        try:
            temp_str = f"{int(temp_path.read_text().strip()) / 1000:.1f}°C"
        except Exception:
            pass

    svc_status = (await container.status()).capitalize()
    svc_uptime = container.uptime()

    return (
        "<b>System Info</b>\n\n"
        f"CPU:    {make_bar(cpu)}\n"
        f"RAM:    {make_bar(ram.percent)}\n"
        f"Disk:   {make_bar(disk.percent)}\n"
        f"Temp:   {temp_str}\n"
        f"Container: {svc_status}\n"
        f"Uptime: {svc_uptime}"
    )

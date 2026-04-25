"""services/resources.py — non-blocking system resource helpers."""
from __future__ import annotations

import psutil

from windrose_bot.services import container


def make_bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + "] " + str(round(pct)) + "%"


async def sysinfo_text() -> str:
    cpu = psutil.cpu_percent(interval=0.0)
    ram = psutil.virtual_memory()

    # Use the primary Windows drive; fall back to "/" on non-Windows hosts.
    import sys
    disk_root = "C:\\" if sys.platform == "win32" else "/"
    disk = psutil.disk_usage(disk_root)

    svc_status = (await container.status()).capitalize()
    svc_uptime = container.uptime()

    return (
        "<b>System Info</b>\n\n"
        f"CPU:     {make_bar(cpu)}\n"
        f"RAM:     {make_bar(ram.percent)}\n"
        f"Disk:    {make_bar(disk.percent)}\n"
        f"Service: {svc_status}\n"
        f"Uptime:  {svc_uptime}"
    )

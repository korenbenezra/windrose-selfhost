# ADR-001 — Hosting Platform Selection

## Status
**Accepted** — supersedes prior drafts that targeted Oracle A1 ARM (rejected: Docker image is AMD64-only) and Hetzner CX32 (rejected: user has existing hardware).

## Date
2026-04-23

## Context

We need a 24/7 host for a Windrose dedicated server serving 2–5 friends. The project owner has an existing Ubuntu Server laptop (x86_64) that meets Windrose's requirements. The question becomes whether to host on that laptop or rent a VPS.

Hard requirements from the official Windrose system-requirements table:

| Players | CPU | RAM | Storage |
|---|---|---|---|
| 2 | 2 cores @ 3.2 GHz | 8 GB | 35 GB SSD |
| 4 | 2 cores @ 3.2 GHz | 12 GB | 35 GB SSD |
| 10 | 2 cores @ 3.2 GHz | 16 GB | 35 GB SSD |

Additional requirements surfaced during ADR research:
- **CPU must support AVX2** (Windrose uses AVX2 intrinsics; the server refuses to start on CPUs that only have AVX)
- **x86_64 architecture** — no ARM binary exists, and the community Docker image is AMD64-pinned
- **IPv6 must be kernel-enabled** — Windrose's P2P proxy listens on a dual-stack socket; `ipv6.disable=1` produces a `SetDataInconsistent` crashloop
- **UPnP-capable router** (or willingness to manually port-forward) for NAT punch-through

## Decision

**Self-hosted Ubuntu Server 24.04 on the user's existing laptop**, running `WindroseServer.exe` under **Wine natively via systemd** (not under Docker).

This decision deliberately breaks with the earlier assumption that Docker was mandatory. The official Windrose Steam community guide (by `williamwolfen`, with Ubuntu 24.04 fixes from `Muldfox`) documents the native-Wine-on-Linux path end-to-end. The community-verified path is:

1. Install SteamCMD, Wine, `winbind`, and `xvfb` via `apt`
2. Run SteamCMD with `+@sSteamCmdForcePlatformType windows` to fetch the Windows server binary
3. Launch `WindroseServer-Win64-Shipping.exe` under `xvfb-run wine …` as a systemd service

No Docker, no container image pinning risk, no AMD64-platform fights. The binary runs directly on the host.

## Rationale

- **€0 additional cost.** The laptop is already paid for and already running.
- **AVX2 hardware is almost certainly present.** Any laptop from 2014 onward has AVX2; the verification step (`grep avx2 /proc/cpuinfo`) is a 1-second check the user runs before proceeding. If it fails, the whole project is a non-starter regardless of hosting choice.
- **No ARM, no emulation layer.** Running the Windows binary under Wine on x86_64 Linux is the single emulation boundary. ARM would add `box64`/`FEX-emu` as a second layer on top of Wine, which for a UE5 game is a non-starter.
- **Official community path.** The Wine-on-Linux instructions are published in the official Windrose Steam community guide (authored by a community member but hosted under the game's official Steam page). This is as close to supported as "run a Windows binary on Linux" ever gets.
- **Full control.** SSH, filesystem, systemd, cron, UPnP router pairing — all directly accessible.
- **Matches user's stated setup.** They have an Ubuntu laptop sitting there; using it is the natural path.

## Alternatives Considered

| Option | Monthly | RAM | CPU | Why Rejected / Chosen |
|---|---|---|---|---|
| **Self-hosted Ubuntu laptop (chosen)** | €0 | User-provided (≥8 GB required) | Existing x86_64 AVX2 | **Chosen.** Meets all requirements, zero recurring cost |
| Oracle A1 ARM (Always Free) | €0 | 24 GB | 4 ARM OCPU | **Rejected.** Windrose has no ARM binary; community Docker image is AMD64-pinned; AVX2 absent on ARM |
| Oracle E2.1.Micro (Always Free) | €0 | 1 GB | 1 AMD OCPU | **Rejected.** 1 GB RAM is below the 8 GB floor for 2 players |
| Hetzner CX32 | €8.46 | 8 GB | 4 vCPU shared | **Rejected** on grounds of cost when a suitable laptop exists. Viable fallback if laptop fails |
| Hetzner CCX13 (dedicated vCPU) | €14.86 | 8 GB | 2 vCPU dedicated | **Rejected.** Unnecessary at this scale |
| Managed host (Indifferent Broccoli, Host Havoc) | $8.99+ | managed | managed | **Rejected.** Zero-ops defeats the self-managed bot-controlled goal |
| Dedicated desktop PC | €0 (existing) or hardware cost | any | any | **Rejected in favour of laptop** — laptop is the specifically-mentioned existing hardware; a desktop would be identical architecturally |

## Consequences

### Positive
- **Zero ongoing cost.**
- **Full filesystem control** — no provider-imposed UID games, no surprise volume detachments.
- **All changes are reversible** — if the laptop dies, the world saves are backed up and can be restored to a Hetzner VPS within an hour (the `bootstrap.sh` and scripts are VPS-compatible; only the host inventory changes).
- **Wine-on-x86_64 is a well-travelled path** — unlike the never-tried ARM-Wine-Docker combination earlier ADRs proposed.

### Negative
- **Single point of failure.** No hypervisor SLA, no remote console. If the laptop hangs, someone physically touches it to recover.
- **Home-ISP constraints.** Public IP is dynamic (handled by P2P/Invite Code — see ADR-004), upstream bandwidth is typically 20–50 Mbps (fine for 2–5 players), ISP TOS may theoretically forbid servers (rarely enforced, but real).
- **Power and thermal.** A laptop running a UE5 game server 24/7 throttles under the lid. Mitigations: lid-open operation, good ventilation, periodic thermal monitoring. Documented below.
- **Noise.** Fans will run. Not a technical problem, but worth calling out for a home environment.
- **No redundancy.** Power cut = server down. UPS optional but recommended.

### Risks & Mitigations
- **Risk:** Laptop disk fails → **Mitigation:** nightly world-save backups (ADR-005, `backup_world.sh`). Optional weekly off-host rsync to a second machine or cloud storage.
- **Risk:** Home IP change interrupts sessions → **Mitigation:** P2P/Invite Code mode is IP-agnostic (ADR-004). Direct Connection mode documented as a fallback with DDNS recommendation.
- **Risk:** ISP blocks UPnP → **Mitigation:** Direct Connection mode with manual port forward, or (last resort) move to a VPS.
- **Risk:** Thermal throttling degrades server performance during combat-heavy sessions → **Mitigation:** operate with lid open, clean fans, monitor via `sensors`. If chronic, undervolt or replace thermal paste.

## Implementation Guide

### Step 1 — Verify the laptop meets requirements
```bash
# Architecture
uname -m                                      # must be: x86_64

# CPU features — AVX2 is required
grep -o 'avx2' /proc/cpuinfo | head -1        # must print: avx2

# RAM
free -h                                       # must have ≥8 GB, prefer ≥12 GB

# Disk (free space on the partition that'll hold /home/$USER/windrose)
df -h $HOME                                   # must have ≥40 GB free

# IPv6 enabled?
cat /sys/module/ipv6/parameters/disable       # must print: 0
sysctl net.ipv6.conf.all.disable_ipv6         # must print: 0
```

If any check fails, stop. Fixes:
- `x86_64` fail → wrong hardware; this laptop cannot host Windrose.
- `avx2` empty → CPU too old (pre-Haswell / pre-Excavator). Not recoverable.
- RAM low → close other processes, or upgrade.
- IPv6 disabled → remove `ipv6.disable=1` from `/etc/default/grub`, `sudo update-grub`, reboot.

### Step 2 — Configure laptop for 24/7 unattended operation
```bash
# 2a. Disable automatic sleep / suspend / hibernate at the systemd level
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

# 2b. Ignore the lid switch — laptop keeps running when closed
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
sudo sed -i 's/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo sed -i 's/^#\?HandleLidSwitchDocked=.*/HandleLidSwitchDocked=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind

# 2c. Set to "Always on AC" power profile (no screen-off-triggered sleep)
# On a headless Ubuntu Server, gnome-power-manager isn't installed — the
# logind settings above are sufficient. If you're on Ubuntu Desktop:
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
```

### Step 3 — Recommended hardware hygiene
- **Keep the lid open.** Even with `HandleLidSwitch=ignore`, most laptops have intake vents under the keyboard. Closed-lid operation traps heat.
- **Keep it on AC power.** Batteries age faster at 24/7 full-charge; some users remove the battery entirely for a perma-plugged laptop. ISP/hardware-dependent decision.
- **Clean the fans.** A cannister of compressed air once a quarter. Obvious, often skipped.
- **Install `lm-sensors` and monitor CPU temp:**
  ```bash
  sudo apt install lm-sensors
  sudo sensors-detect --auto
  sensors | grep -i 'Core 0\|Package'
  # Sustained temps >85°C during idle = clean fans or replace thermal paste.
  ```

### Step 4 — Network prep (UPnP on the router)
Log into the router's web UI. Find the UPnP or "NAT-PMP" / "IGD" setting. Enable it. Save. Reboot the router if needed.

Verify from the laptop:
```bash
sudo apt install miniupnpc
upnpc -s                                      # should list your router's external IP
```

If UPnP is unavailable or your ISP uses Carrier-Grade NAT (CGNAT), see ADR-004 — you'll need to switch to Direct Connection mode and port-forward TCP+UDP 7777 manually.

### Step 5 — Proceed with provisioning
Run `scripts/bootstrap.sh` to install SteamCMD, Wine, and dependencies. See AGENT_GUIDE.md.

## Code Examples

### One-shot preflight script (paste into a terminal)
```bash
set -e
echo "=== Preflight checks ==="
arch=$(uname -m)                    && echo "arch: $arch"    && [[ "$arch" == "x86_64" ]]
grep -q avx2 /proc/cpuinfo          && echo "avx2: yes"      || { echo "avx2 MISSING" >&2; exit 1; }
ram_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo) && echo "ram_mb: $ram_mb"
[[ "$ram_mb" -ge 8000 ]]            || { echo "RAM <8GB — may OOM" >&2; }
free_gb=$(df --output=avail -BG "$HOME" | tail -1 | tr -dc 0-9) && echo "disk_gb_free: $free_gb"
[[ "$free_gb" -ge 40 ]]             || { echo "Disk <40GB free" >&2; exit 1; }
[[ "$(cat /sys/module/ipv6/parameters/disable 2>/dev/null)" != "1" ]] && echo "ipv6: enabled"
echo "=== ✅ Host is suitable for Windrose ==="
```

## References

- Windrose official dedicated server guide (Linux/Wine section authored by `williamwolfen`): https://steamcommunity.com/sharedfiles/filedetails/?id=3706337486
- Ubuntu 24.04 Wine package fix (`Muldfox` comment in the above guide)
- Official system requirements: https://playwindrose.com/dedicated-server-guide/
- SteamCMD `@sSteamCmdForcePlatformType` documentation: https://developer.valvesoftware.com/wiki/SteamCMD
- systemd-logind lid-switch handling: `man logind.conf`
- UPnP / miniupnpc: https://miniupnp.tuxfamily.org/

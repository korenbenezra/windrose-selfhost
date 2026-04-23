# ADR-002 — Wine (Linux) vs. Native Windows Execution

## Status
**Accepted**

## Date
2026-04-23

## Context

`WindroseServer-Win64-Shipping.exe` is the dedicated server binary. Upstream ships **only a Windows build**. The host is an Ubuntu Server 24.04 laptop (ADR-001). To run a Windows binary on Linux we have three paths:

1. **Wine on Linux (host-level, native)** — install Wine via `apt`, run the `.exe` under `wine` inside `xvfb-run`. No containerisation. This is the path the official Windrose Steam community guide documents for Linux hosts (section authored by `williamwolfen`, Ubuntu 24.04 adjustments by `Muldfox`).
2. **Wine on Linux (containerised)** — run `indifferentbroccoli/windrose-server-docker`, which packages Wine + SteamCMD in a container.
3. **Dual-boot or swap to Windows** — reinstall the laptop with Windows Server / Windows 11, run the server natively.

## Decision

**Wine on Linux, host-level, systemd-managed.**

Concretely:
- Install `wine wine32 wine64 libwine libwine:i386 fonts-wine` (the Ubuntu 24.04 correction from the community guide — `wine-installer` is broken on 24.04)
- Install `winbind` (NTLM auth Windrose needs) and `xvfb` (virtual display for headless Wine)
- SteamCMD downloads the Windows binary with `+@sSteamCmdForcePlatformType windows`
- A systemd service supervises `xvfb-run wine WindroseServer-Win64-Shipping.exe -log`

## Rationale

- **Community-validated.** The Linux/Wine section of the official Steam guide has been updated through multiple Windrose Early Access patches. Not a workaround — a first-class (if unofficial-from-the-studio) path.
- **Simpler than the container path on this host.** On a VPS the container's self-contained Wine environment is worth the abstraction. On the user's own laptop with an already-existing `apt` package manager and systemd, adding Docker + an AMD64-pinned image is extra moving parts for no benefit.
- **Direct filesystem access.** Saves live at `/home/$USER/windrose/R5/Saved/…` on the host — no bind-mount semantics, no UID alignment puzzles, no "don't run `docker compose down -v`" landmines. Backup and restore scripts operate directly on host paths.
- **Native systemd supervision.** `Restart=always`, journaled logs, `systemctl status`, resource-accounting via cgroups — all free. No need to learn `docker compose` semantics for the game supervisor.
- **Bot control is trivial.** The Telegram bot runs `sudo systemctl start/stop/restart windrose` via a tightly-scoped sudoers drop-in. No docker group, no docker socket exposure.
- **Wine works.** Windrose is a UE5 game; UE5 games run well under Wine (Proton tracks UE5 compatibility actively). The 10–20% CPU overhead quoted by commercial Linux hosts (LOW.MS) is real but acceptable for 2–5 players on an x86_64 laptop.

## Alternatives Considered

| Option | Pros | Cons | Why Rejected / Chosen |
|---|---|---|---|
| **Native Wine + systemd (chosen)** | Simple; community-documented; no Docker overhead; direct fs access | 10–20% CPU overhead vs native Windows; unsupported by Kraken Express | **Chosen** |
| **Docker (`indifferentbroccoli/...`)** | Single-command deploy; update-on-start | Extra layer; AMD64-pin already satisfied by host; obscures fs; bot needs docker group | **Rejected** — no advantage on a user-owned host with apt available |
| **Bare Wine without systemd** | Minimal | No crash restart; no log rotation; no boot-time start | **Rejected** |
| **Install Windows on the laptop** | Official path; no Wine | Reimage the machine; lose Linux tooling; Windows licensing cost | **Rejected** — disproportionate |
| **Proton (via Steam client)** | Wine + Valve's patches | Requires Steam client running; headless setup fiddly; licensing restrictions | **Rejected** — `wine-stable` from `apt` is simpler |
| **Dual boot** | Flexibility | Manual reboot to switch modes — incompatible with 24/7 server goal | **Rejected** |

## Consequences

### Positive
- Standard Linux tooling (`systemctl`, `journalctl`, `crontab`, `ssh`) applies end-to-end.
- World saves are at a normal filesystem path — trivially backed up with `tar`.
- Bot integration is a systemd subprocess call — no privileged Docker socket exposed.
- Wine updates come through `apt` alongside the rest of the OS — no separate image-tag pinning strategy needed.

### Negative
- **Unsupported by Kraken Express.** If a Windrose patch breaks Wine compatibility (rare for UE5 games, but possible), we're on our own. Mitigation: pin an older Wine version via apt; maintain rollback notes.
- **Save corruption risk (unverified but warned).** Host Havoc explicitly cautions that "Proton or Wine can cause save file corruption" with Windrose. We mitigate with nightly backups (ADR-005). This warning predates the Steam community guide's Linux section and may be obsolete; we treat it as a possibility, not a certainty.
- **Wine version drift.** An Ubuntu security update could upgrade Wine to a version that breaks Windrose. Mitigation: `apt-mark hold wine-stable wine32 wine64` after initial install confirms the server runs, unpin only during scheduled maintenance windows.
- **No vendor escalation path.** If anything breaks, the Windrose Discord and Steam forum are the support channels.

### Fallback Plan — "Wine broke after a patch"
1. Check the Windrose Discord `#server-hosting-linux` channel for known regressions.
2. Downgrade the Wine packages:
   ```bash
   sudo apt install wine-stable=<old-version> wine32=<old-version> wine64=<old-version>
   sudo apt-mark hold wine-stable wine32 wine64
   sudo systemctl restart windrose
   ```
3. If that fails, the escape hatch is: provision a Hetzner CX32 VPS with the same Wine config (the scripts are VPS-compatible — only the hostname changes), rsync the world saves, point friends at the new Invite Code.

## Implementation Guide

### Required packages (Ubuntu 24.04)
```bash
# i386 multi-arch is needed for 32-bit Wine support (even though the game
# binary is 64-bit, Wine itself pulls in 32-bit runtime deps).
sudo dpkg --add-architecture i386

# Enable the multiverse repo (contains steamcmd):
sudo add-apt-repository multiverse
sudo apt update

# Install SteamCMD (accept the SteamCMD EULA when prompted):
sudo apt install steamcmd lib32gcc-s1

# Install Wine + the two extras needed for headless UE5 servers:
#   winbind — NTLM authentication (Windrose uses this)
#   xvfb    — virtual framebuffer (Wine needs *some* X display, even headless)
sudo apt install wine wine32 wine64 libwine libwine:i386 fonts-wine winbind xvfb

# Verify Wine is 9.x or 10.x (Ubuntu 24.04 ships 9.0 in main):
wine --version
# Expected: wine-9.0 (Ubuntu 9.0~repack-4build3) or similar
```

### SteamCMD — download the server
```bash
# As the windrose-server user:
steamcmd \
  +@sSteamCmdForcePlatformType windows \
  +force_install_dir /home/$USER/windrose \
  +login anonymous \
  +app_update 4129620 validate \
  +quit
```

The `+@sSteamCmdForcePlatformType windows` flag is **required**. Without it, SteamCMD sees a Linux host and tries to download a Linux version of app 4129620 that doesn't exist, producing an opaque "Invalid platform" error.

### Launch script
```bash
#!/usr/bin/env bash
# start_windrose.sh — launched by the systemd unit
set -e
export WINEPREFIX="$HOME/windrose/pfx"
exec xvfb-run -a -s "-screen 0 1024x768x24" \
  wine "$HOME/windrose/R5/Binaries/Win64/WindroseServer-Win64-Shipping.exe" -log
```

The `-log` flag tells the Windrose server to write its own log file (in addition to stdout/stderr). This is what the Telegram bot's player monitor watches (see ADR-008).

### Verifying Wine works (one-time, post-install)
```bash
# With WINEPREFIX set, run a trivial Windows program:
WINEPREFIX=$HOME/windrose/pfx wine cmd.exe /c 'echo hello from wine'
# Expected: "hello from wine"
# First run takes ~30s — Wine initialises the prefix.
```

## Code Examples

### Pinning Wine versions to prevent drift
```bash
# After the server is confirmed working, pin:
sudo apt-mark hold wine-stable wine wine32 wine64 libwine libwine:i386 fonts-wine

# Check holds:
apt-mark showhold | grep wine

# Before an intentional upgrade:
sudo apt-mark unhold wine-stable wine wine32 wine64 libwine libwine:i386 fonts-wine
sudo apt update && sudo apt upgrade -y wine-stable wine wine32 wine64
sudo systemctl restart windrose
# If OK, re-hold. If not, re-hold to the previous version you know works.
```

### Diagnosing a Wine crash
```bash
# Stop the service, run manually with verbose logging:
sudo systemctl stop windrose
su - $WINDROSE_USER -c '
  export WINEDEBUG=+seh,+unwind,+tid
  export WINEPREFIX=$HOME/windrose/pfx
  xvfb-run -a -s "-screen 0 1024x768x24" \
    wine $HOME/windrose/R5/Binaries/Win64/WindroseServer-Win64-Shipping.exe -log \
    2>&1 | tee /tmp/windrose-wine-debug.log
'
# Look for the last "trace" or "err:" line before the crash.
```

## References

- Official Windrose Steam community guide (Linux section): https://steamcommunity.com/sharedfiles/filedetails/?id=3706337486
- Wine project: https://gitlab.winehq.org/wine/wine/-/wikis/home
- SteamCMD `@sSteamCmdForcePlatformType`: https://developer.valvesoftware.com/wiki/SteamCMD
- `xvfb-run` manpage: `man xvfb-run`
- winbind (Samba): https://www.samba.org/samba/docs/old/Samba3-HOWTO/winbind.html
- Host Havoc save-corruption warning (historical reference): https://hosthavoc.com/blog/how-to-create-a-windrose-dedicated-server

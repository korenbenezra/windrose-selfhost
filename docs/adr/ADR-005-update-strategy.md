# ADR-005 — Server Update Strategy

## Status
**Accepted**

## Date
2026-04-23

## Context

Windrose is in Early Access. Steam pushes patches every 2–3 weeks with occasional hotfixes. Clients and server must run the **same** Windrose build — a mismatched client sees the server via Invite Code but fails to join with a generic "can't connect" error (no version mismatch diagnostic is surfaced in the UI).

Three moving parts may need updating:

1. **Windrose game files** — delivered via SteamCMD (`app_update 4129620 validate`). We own the timing.
2. **Wine + dependencies** — delivered via `apt`. Changes can silently break compatibility with the Windrose binary.
3. **Host OS + kernel** — delivered via `apt` unattended-upgrades. Security patches must apply without us babysitting them; reboots must happen, but at a predictable time.

## Decision

Three independent loops, staggered:

1. **Nightly SteamCMD update at 03:00**, followed by systemd restart at 03:15 (15-minute gap lets SteamCMD finish its download before the service restarts on the fresh binary).
2. **Weekly `apt` security upgrades** via `unattended-upgrades`, with automatic reboot at **Sunday 04:00 only**. The 03:00/03:15 Windrose cycle must run first so we don't collide.
3. **Wine packages pinned** via `apt-mark hold` after the initial working install. Unpinning is a deliberate, scheduled maintenance action — never automatic.

All updates are preceded by a **world-save backup** at 02:30 (30 min before the SteamCMD run). If the update is destructive, we can roll back to a known-good snapshot.

## Cron Schedule

```cron
# Nightly world backup (02:30) — protects against a bad update
30 2 * * * /home/YOUR_USER/scripts/backup_world.sh >> /var/log/windrose-backup.log 2>&1

# Nightly SteamCMD update pull (03:00) — server still running; SteamCMD
# writes into the install dir but a running Windrose does not re-read its
# binaries without a restart
00 3 * * * /home/YOUR_USER/scripts/update_windrose.sh >> /var/log/windrose-cron.log 2>&1

# Service restart (03:15) — 15 min after SteamCMD starts, by which time
# SteamCMD has either completed (no-op if no new build) or downloaded the
# new build
15 3 * * * /usr/bin/sudo /bin/systemctl restart windrose.service >> /var/log/windrose-cron.log 2>&1

# Every-10-minute healthcheck — notices if a restart hangs or Wine crashes
*/10 * * * * /home/YOUR_USER/scripts/healthcheck.sh >> /var/log/windrose-health.log 2>&1
```

The `sudo systemctl restart` line requires the invoking user to be in the bot's sudoers drop-in (`/etc/sudoers.d/windrose-bot`), or a separate sudoers rule for the `YOUR_USER` account. See ADR-003 for the sudoers scoping rationale. Typically the bot user and the cron-owner user are the same account.

## World Save Safety

World data lives at `/home/$USER/windrose/R5/Saved/`. Operations that do **not** touch saves:

- `sudo systemctl restart windrose`, `stop`, `start`
- SteamCMD `app_update 4129620 validate` — updates binaries in `R5/Binaries/` and leaves `R5/Saved/` alone

Operations that **would** destroy saves (never run):

- `rm -rf ~/windrose/R5/Saved/`
- Running SteamCMD with a wrong `force_install_dir` pointing at the saves path
- `steamcmd … +app_update 4129620 validate` with a `+force_install_dir` that is not `~/windrose/` — always verify the path in `update_windrose.sh`

Defense in depth:
- **Nightly `tar.zst` snapshots** of `~/windrose/R5/Saved/` to `~/windrose-backups/`, 7-day rolling retention (`scripts/backup_world.sh`).
- **Before every manual update**, `update_windrose.sh` takes an additional tagged backup (`saves-*-pre-update.tar.zst`).
- **Optional weekly off-laptop copy** via `rsync` to another machine or cloud storage — documented, not automated by default.

## Rationale

- **Nightly restart prevents memory bloat.** UE5 dedicated servers leak slowly; a daily restart is cheap insurance against multi-day instability.
- **Separating SteamCMD and restart by 15 minutes** avoids the race where SteamCMD is mid-download and the service restart fails because the binary is being rewritten in place.
- **Wine pinning** is the single highest-leverage safety control. Without it, a routine `apt upgrade` could push Wine 9 → Wine 11 with a Windrose regression we'd only notice the next morning.
- **Scheduled reboot on Sunday 04:00** means we have 4 hours/week of predictable downtime for kernel patches. For a 2–5 player casual server, losing Sunday-at-dawn is a non-event; friends don't play at 04:00 local.
- **Backups run before updates, not after**, so even if the update corrupts the world mid-write, we have a pre-update snapshot to restore.

## Alternatives Considered

| Option | Pros | Cons | Why Rejected / Chosen |
|---|---|---|---|
| **Staggered nightly cron (chosen)** | Predictable; layered safety nets | Accepts 1–3 min downtime at 03:15 | **Chosen** |
| `UPDATE_ON_START` style (restart always runs update) | Simple | Update happens during a restart window; if SteamCMD is slow, restart is slow | **Rejected** given the Docker path is gone |
| Single combined cron: stop → update → start | Serialised | Longer downtime window; harder to isolate failures | **Rejected** |
| No scheduled restart | Zero routine downtime | Memory bloat; update lag indefinite | **Rejected** |
| Auto `apt upgrade` everything (no Wine pin) | Zero-maintenance | One bad Wine upgrade = broken server at 3am | **Rejected** |
| Watchtower-style automated SteamCMD on new-build detection | Reactive | No public "Steam has a new build of 4129620" feed without polling SteamDB; complexity unjustified | **Rejected** |

## Consequences

### Positive
- Predictable maintenance window: 02:30 (backup), 03:00 (update), 03:15 (restart). Friends know the server is briefly down at that time; they don't play at 3am.
- Backups are always fresh.
- A broken Windrose patch gets caught by the healthcheck within 10 minutes and reported to Telegram.
- Wine pinning insulates us from Ubuntu security updates that touch Wine.

### Negative
- A broken Windrose patch that drops between 03:00 and 03:15 will briefly take the server offline. Healthcheck + bot notification make the admin aware within 10 minutes.
- Wine pinning means we miss Wine bugfixes until we consciously unpin. Mitigation: quarterly review of Wine release notes, scheduled unpin/pin cycle.
- `unattended-upgrades`'s Sunday 04:00 reboot means ~1 hour of no "friends-might-be-online" window is unavailable weekly. Documented, acceptable.

### After a major Windrose version bump (e.g., 0.9 → 0.10)
Windrose organises world data into a new `<game_version>` subfolder inside `R5/Saved/SaveProfiles/Default/RocksDB/`. The update does **not** migrate the world automatically. After such a patch:

1. Stop the server: `sudo systemctl stop windrose`
2. Check the new RocksDB subfolder was created: `ls ~/windrose/R5/Saved/SaveProfiles/Default/RocksDB/`
3. Copy the world folder from the old version subfolder to the new:
   ```bash
   OLD=0.9.0; NEW=0.10.0
   cp -r ~/windrose/R5/Saved/SaveProfiles/Default/RocksDB/$OLD/Worlds/* \
         ~/windrose/R5/Saved/SaveProfiles/Default/RocksDB/$NEW/Worlds/
   ```
4. Verify the `WorldIslandId` in `ServerDescription.json` still matches the folder name (unchanged) and the `islandId` inside `WorldDescription.json` (unchanged). The triple-match rule still holds.
5. Restart: `sudo systemctl start windrose`.

This is documented in `AGENT_GUIDE.md` under "Handling major version bumps".

## Implementation Guide

### Step 1 — Schedule cron jobs
Edit crontab for the windrose user:
```bash
crontab -e
```
Paste the four lines from "Cron Schedule" above, replacing `YOUR_USER`.

### Step 2 — Logrotate
Handled by `bootstrap.sh`. Creates `/etc/logrotate.d/windrose` with weekly rotation, 8-week retention, gzip compression.

### Step 3 — Unattended security upgrades
```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades   # yes to security-only

# Configure weekly reboot at 04:00 (after our 03:15 Windrose restart):
sudo tee /etc/apt/apt.conf.d/51windrose-reboot >/dev/null <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
Unattended-Upgrade::Automatic-Reboot-WithUsers "false";
EOF
```

### Step 4 — Pin Wine after first verified run
```bash
# After the server successfully runs for 24 hours:
sudo apt-mark hold wine wine32 wine64 libwine libwine:i386 fonts-wine winbind xvfb

# Verify:
apt-mark showhold | grep -E 'wine|winbind|xvfb'
```

### Step 5 — Manual update workflow (when you *want* to force an update)
```bash
# From any terminal as the windrose user:
bash ~/scripts/update_windrose.sh

# What it does:
#   1. Take a tagged pre-update backup
#   2. Stop the Windrose service
#   3. Run steamcmd +app_update 4129620 validate
#   4. Restart the service
#   5. Wait up to 120s for 'active (running)' state
#   6. Telegram-notify admin on success or failure
#   7. On failure: restore the pre-update backup and Telegram-notify
```

## Code Examples

### Core of `update_windrose.sh` — the SteamCMD call
```bash
STEAMCMD_BIN=/usr/games/steamcmd    # Ubuntu's apt-installed path
INSTALL_DIR="$HOME/windrose"
APP_ID=4129620

# Pre-backup
ts=$(date +%Y%m%dT%H%M%S)
tar --zstd -cf "$HOME/windrose-backups/saves-${ts}-pre-update.tar.zst" \
    -C "$INSTALL_DIR" R5/Saved

# Stop the service (safe to edit files now)
sudo -n systemctl stop windrose.service

# Run SteamCMD — the windows-platform flag is REQUIRED on Linux
"$STEAMCMD_BIN" \
  +@sSteamCmdForcePlatformType windows \
  +force_install_dir "$INSTALL_DIR" \
  +login anonymous \
  +app_update "$APP_ID" validate \
  +quit

# Restart
sudo -n systemctl start windrose.service

# Wait up to 120s for active
for i in $(seq 1 60); do
  if systemctl is-active --quiet windrose.service; then
    echo "Running after ${i}s"; exit 0
  fi
  sleep 2
done
echo "Did not come up"; exit 1
```

The real `scripts/update_windrose.sh` wraps this with Telegram notifications and rollback-on-failure — see the file itself.

### Manually restoring from a backup
```bash
# Stop the service:
sudo systemctl stop windrose

# Identify the backup you want to restore:
ls -lht ~/windrose-backups/
# e.g., saves-20260423T023000.tar.zst

# Restore:
cd ~/windrose
rm -rf R5/Saved/     # remove current (potentially corrupt) saves
tar --zstd -xf ~/windrose-backups/saves-20260423T023000.tar.zst

# Restart:
sudo systemctl start windrose
# Verify world loads correctly via journalctl -fu windrose
```

## References

- SteamCMD docs: https://developer.valvesoftware.com/wiki/SteamCMD
- `+@sSteamCmdForcePlatformType` flag usage for cross-platform downloads: community-documented in the Windrose guide
- Windrose app ID: 4129620 (confirmed anonymous)
- Ubuntu `unattended-upgrades` wiki: https://wiki.debian.org/UnattendedUpgrades
- `apt-mark` manpage: `man apt-mark`
- `logrotate` manpage: `man logrotate`

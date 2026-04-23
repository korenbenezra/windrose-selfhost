# ADR-003 — systemd Service vs. Docker Container

## Status
**Accepted** — supersedes the original ADR-003 which decided in favour of Docker. Reversal driven by ADR-001 (host is now a user-owned laptop, not a cloud VPS) and ADR-002 (native Wine is the community-validated path).

## Date
2026-04-23

## Context

With native Wine as the execution model (ADR-002), the server process is a regular Linux long-running process. We need to decide how it's supervised:

1. **systemd service** — `[Unit]/[Service]/[Install]` unit file, `systemctl enable --now windrose`. Native Linux supervisor, journaled logs, cgroup-based resource accounting.
2. **Docker** — run Wine inside a container (`indifferentbroccoli/windrose-server-docker`), supervised by the Docker daemon.
3. **Tmux / screen + nohup** — launch once manually, hope it doesn't die.
4. **Supervisor / runit / s6** — third-party process supervisors.

## Decision

**systemd service** — one `windrose.service` unit in `/etc/systemd/system/`.

The Telegram bot also runs as a separate systemd unit (`windrose-bot.service`). Both are user-mode processes supervised by the system-level systemd instance.

## Rationale

- **systemd is already on the host.** Ubuntu 24.04 ships it. Zero extra installation.
- **Clean integration with the bot.** The bot calls `sudo systemctl start/stop/restart windrose` via subprocess. A tightly-scoped sudoers drop-in (`/etc/sudoers.d/windrose-bot`) grants the bot user passwordless access to exactly those three `systemctl` verbs on exactly that one unit — no broader sudo, no docker group membership, no socket exposure.
- **journald captures all output.** The game's stdout, Wine's stderr, the launch script's bash — everything — is in `journalctl -u windrose`. Rotation is built in. No ad-hoc log files to worry about.
- **Automatic restart.** `Restart=on-failure RestartSec=5` handles transient Wine crashes without human intervention.
- **Boot-time start.** `WantedBy=multi-user.target` means the server comes up when the laptop boots — no extra init script.
- **Resource caps via cgroups.** `MemoryMax=`, `CPUQuota=` in the unit file give us resource accounting for free. Handy if we later add other services on the same host.
- **Standard Linux ops.** Every Linux admin already knows `systemctl status` / `journalctl -fu`. No docker-specific mental model required.

Docker was the right answer when the host was a VPS with no installed tooling and we wanted a single-command deploy. On a user's own laptop with apt + systemd already present, Docker adds a layer and subtracts nothing.

## Alternatives Considered

| Option | Pros | Cons | Why Rejected / Chosen |
|---|---|---|---|
| **systemd service (chosen)** | Built-in; journald; sudoers-scoped bot control; standard ops | None relevant to this use case | **Chosen** |
| **Docker container** | Image-pinning discipline; "single command" deploy | Extra layer; docker group = broader bot privilege; bind-mount UID fights; `docker compose down -v` footgun | **Rejected** given native Wine host |
| **tmux / screen + nohup** | No config | No supervision; dies on laptop reboot; logs unmanaged | **Rejected** |
| **supervisor / runit / s6** | Mature third-party supervisors | Extra install; nothing they do that systemd doesn't | **Rejected** — reinventing systemd |
| **PM2** | Popular for Node | Aimed at Node/long-running web apps; overkill | **Rejected** |

## Consequences

### Positive
- Boot-time start: `sudo systemctl enable windrose` → server comes up after a power cut.
- `journalctl -u windrose -f` is a live tail of everything.
- `systemctl restart windrose` is the canonical restart path, whether run by human, cron, or bot.
- Security: `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`, `ProtectHome=` can harden the service unit beyond what Docker gives us by default. See the unit file in `systemd/windrose.service`.

### Negative
- **sudo grant to the bot user is real privilege, however scoped.** A bug in the bot that accepts arbitrary input and passes it to `systemctl` could stop/start arbitrary units. Mitigation: the bot never composes `systemctl` command-lines from user input — every call is a hard-coded verb on a hard-coded unit name. Audited line-by-line.
- **No image pinning.** Wine version is whatever `apt` gives us. Mitigation: `apt-mark hold wine*` after verified-working install (see ADR-002).
- **Laptop-reboot requires the service to be enabled.** Easy to forget; the `bootstrap.sh` + `install_service.sh` scripts enable it explicitly.

## Filesystem Layout

```
/home/$WINDROSE_USER/
├── windrose/                                    ← SteamCMD install target
│   ├── R5/
│   │   ├── Binaries/Win64/
│   │   │   └── WindroseServer-Win64-Shipping.exe
│   │   ├── ServerDescription.json               ← edited manually when server stopped
│   │   └── Saved/
│   │       └── SaveProfiles/Default/RocksDB/<version>/Worlds/<id>/
│   │           └── WorldDescription.json
│   ├── pfx/                                     ← WINEPREFIX
│   └── start_windrose.sh                        ← the launch script systemd calls
├── log/
│   └── windrose.log                             ← written by server -log flag
└── windrose-backups/                            ← daily tar.zst snapshots

/etc/systemd/system/
├── windrose.service                             ← the server unit
└── windrose-bot.service                         ← the bot unit

/etc/sudoers.d/
└── windrose-bot                                 ← bot's scoped systemctl grant

/var/log/
├── windrose-cron.log
├── windrose-health.log
└── windrose-backup.log
```

Note: the server has TWO places logs can land:

1. **systemd journal** (everything — stdout + stderr of the entire service invocation, captured via `StandardOutput=journal`).
2. **`~/log/windrose.log`** (written by the `-log` flag inside Windrose itself — game-level events).

The bot's player monitor watches the second file (ADR-008). The admin watches both.

## Implementation Guide

### The systemd unit (shipped as `systemd/windrose.service`)
```ini
[Unit]
Description=Windrose Dedicated Server (Wine)
Wants=network-online.target
After=syslog.target network-online.target

[Service]
Type=simple
User=WINDROSE_USER_PLACEHOLDER
WorkingDirectory=/home/WINDROSE_USER_PLACEHOLDER/windrose

# Make sure WINEPREFIX is set for both the script and anything it spawns
Environment=WINEPREFIX=/home/WINDROSE_USER_PLACEHOLDER/windrose/pfx
Environment=DISPLAY=:99

ExecStart=/home/WINDROSE_USER_PLACEHOLDER/windrose/start_windrose.sh

# Restart on any exit code except clean 0 (don't fight intentional stops)
Restart=on-failure
RestartSec=5

# Resource caps — generous for 2–5 players, protects the rest of the laptop
MemoryMax=10G
CPUQuota=350%               # 3.5 cores

# Log to both journald AND the server's own -log file
StandardOutput=journal
StandardError=journal
SyslogIdentifier=windrose

# Hardening — these are safe for a Wine/UE5 workload
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=tmpfs
BindPaths=/home/WINDROSE_USER_PLACEHOLDER/windrose /home/WINDROSE_USER_PLACEHOLDER/log

[Install]
WantedBy=multi-user.target
```

`install_service.sh` performs the `WINDROSE_USER_PLACEHOLDER` substitution with the real invoking user before `cp`'ing into `/etc/systemd/system/`.

### Sudoers drop-in (shipped as `systemd/sudoers-windrose-bot`)
```sudoers
# /etc/sudoers.d/windrose-bot
# Bot user may control exactly the windrose.service, nothing else.
# File must be mode 0440 — installed via visudo -c first for safety.

BOT_USER_PLACEHOLDER ALL=(root) NOPASSWD: \
    /bin/systemctl start windrose.service, \
    /bin/systemctl stop windrose.service, \
    /bin/systemctl restart windrose.service, \
    /bin/systemctl status windrose.service, \
    /bin/systemctl is-active windrose.service, \
    /bin/systemctl show windrose.service
```

### Commands the bot issues
```python
# in bot.py, via subprocess:
subprocess.run(["sudo", "-n", "systemctl", "start",   "windrose.service"], ...)
subprocess.run(["sudo", "-n", "systemctl", "stop",    "windrose.service"], ...)
subprocess.run(["sudo", "-n", "systemctl", "restart", "windrose.service"], ...)
subprocess.run(["sudo", "-n", "systemctl", "is-active", "windrose.service"], ...)

# Read-only calls that don't need sudo:
subprocess.run(["systemctl", "show", "windrose.service",
                "-p", "ActiveState,SubState,ActiveEnterTimestamp"], ...)
subprocess.run(["journalctl", "-u", "windrose.service", "-n", "30", "--no-pager"], ...)
```

`sudo -n` = non-interactive; fails fast if the sudoers rule isn't matching (e.g., user typo), rather than hanging for a password prompt.

## Code Examples

### Inspecting current state
```bash
# Service up?
systemctl is-active windrose              # "active" or "inactive"/"failed"

# Full status
systemctl status windrose                 # human-readable summary

# When did it start?
systemctl show windrose -p ActiveEnterTimestamp

# Live logs
journalctl -fu windrose

# Last 100 lines, no pager
journalctl -u windrose -n 100 --no-pager

# Everything since yesterday 3AM
journalctl -u windrose --since "yesterday 03:00"
```

### Restart workflow (what the 3AM cron does)
```bash
sudo systemctl restart windrose
# Behind the scenes: SIGTERM → wait 90s for clean shutdown → if still alive, SIGKILL → start fresh
# Windrose takes ~30s to initialise (WINEPREFIX setup + world load)
# Total outage window: typically 45–60s
```

### Validating a new version of `start_windrose.sh` without affecting the running service
```bash
# Edit and test the script directly as the windrose user, with the real env:
sudo -u windrose WINEPREFIX=/home/windrose/windrose/pfx \
  /home/windrose/windrose/start_windrose.sh
# Ctrl-C to stop. Service is unaffected because it was already stopped
# (or because systemd has its own instance that doesn't conflict with this
# foreground run on the same WINEPREFIX — don't run both at once).
```

## References

- systemd.service manpage: `man systemd.service`
- systemd.exec hardening options: `man systemd.exec` — the `Protect*`, `NoNewPrivileges`, `PrivateTmp` family
- journalctl: `man journalctl`
- sudoers manpage: `man sudoers` — especially the "NOPASSWD" and command-path-whitelist sections
- `visudo -c` syntax check before installing a drop-in: always.

# ADR-004 — Networking: P2P (Invite Code) vs. Direct Connection

## Status
**Accepted**

## Date
2026-04-23

## Context

Windrose supports two join modes:

1. **P2P / NAT punch-through via Invite Code** — server registers with Windrose's signalling service on startup; friends paste an 8-character code; a peer-to-peer session is negotiated via ICE/UPnP. The official FAQ is explicit: *"Ports are dynamically assigned via NAT punch-through. You cannot specify fixed ports manually."* and *"Ensure your network router supports UPnP or NAT punching."*
2. **Direct Connection** — set `UseDirectConnection: true` and `DirectConnectionServerPort: 7777`; friends connect to `<public-ip>:7777`. Requires manual port forward on the router.

The host is a home laptop behind a consumer router (ADR-001). This changes the picture relative to a cloud VPS:

- **Public IP is dynamic.** ISPs rotate the WAN IP every few days to weeks. In P2P mode this doesn't matter (Invite Code is stable); in direct mode it breaks every join when the IP changes.
- **Router UPnP is either present (most consumer routers) or ISP-locked (rare).** If UPnP works, P2P "just works" without any manual port forwarding.
- **CGNAT (Carrier-Grade NAT)** is increasingly common on mobile and some budget fixed-line ISPs. Under CGNAT, neither UPnP nor manual port forwarding works for inbound connections — P2P's punch-through still has a fighting chance.

## Decision

**Default: P2P / Invite Code mode** (`UseDirectConnection: false` in `ServerDescription.json`).

**Documented fallback: Direct Connection** — switchable via a `ServerDescription.json` edit + UPnP/manual port forward, for networks where P2P fails.

**No inbound ports are opened in the host firewall by default** — `ufw` allows SSH only. Opening 7777 TCP+UDP and 7778 UDP is a deliberate step tied to switching to Direct Connection.

## Rationale

- **It's what the game's UI assumes.** "Enter Invite Code" is the primary UX. Sharing a stable short string in Discord is friction-free.
- **IP-change-proof.** Home ISP flips the WAN IP at 3am → Invite Code still works, no one notices. Direct mode would break.
- **UPnP handles port mapping automatically** on the huge majority of consumer routers. No manual config, no router admin login.
- **Smaller attack surface.** A home laptop with *no* inbound ports open to the internet is dramatically less exposed than one with UDP 7777 permanently open. UPnP opens the port only for the active session and tears it down when the server stops.
- **Official guidance.** The Windrose team explicitly says "Ports are dynamically assigned via NAT punch-through." Going against this is swimming upstream.

## Alternatives Considered

| Option | Pros | Cons | Why Rejected / Chosen |
|---|---|---|---|
| **P2P / Invite Code (chosen default)** | Matches game UX; IP-change-proof; no permanent ports | Depends on Windrose signalling uptime; UPnP must be enabled on router | **Chosen** |
| **Direct Connection (permanent)** | Deterministic; no dependency on signalling service | Home IP changes break it; port scanner attraction; requires manual router config | **Fallback only** |
| **Dynamic DNS (DDNS) + Direct Connection** | Stable hostname even with dynamic IP | Still requires port forward; solves only half the problem | **Rejected as primary**; optional if user wants direct mode |
| **Cloudflare Tunnel / zerotrust** | Stable hostname; encrypted | **Does not support raw UDP** — Windrose game traffic is UDP-heavy, would not work | **Rejected** |
| **WireGuard VPN for friends** | Full encryption; bypasses NAT | Every friend must install a VPN client + onboarding overhead | **Rejected** — too much friction |
| **Tailscale for friends** | Zero-config mesh VPN | Same as above; also costs if >3 users on paid tier | **Rejected** as default; interesting advanced option |

## Port Matrix

### P2P mode (default)

| Direction | Protocol | Port | Source | Notes |
|---|---|---|---|---|
| Outbound | TCP/UDP | 443, others | Server → Windrose signalling | Initiated by server, firewall allows automatically |
| Outbound → Inbound | UDP | dynamic | Server ↔ each client | UPnP opens/closes on demand |
| Inbound | TCP | 22 | SSH from admin's IP | Home laptop — can tighten to LAN-only if never SSH'd from outside |

**No permanent inbound ports** from the internet to the host.

### Direct Connection mode (opt-in fallback)

| Direction | Protocol | Port | Source |
|---|---|---|---|
| Inbound | TCP | 7777 | `0.0.0.0/0` |
| Inbound | UDP | 7777 | `0.0.0.0/0` |
| Inbound | UDP | 7778 | `0.0.0.0/0` |
| Inbound | TCP | 22 | SSH — keep restricted |

Configure both the **router** (port forward `7777/tcp`, `7777/udp`, `7778/udp` → laptop's LAN IP) **and** the **host `ufw`** (allow the same three).

## Consequences

### Positive
- Zero firewall config on happy path.
- Friends use an 8-character string; no technical explanation required.
- Defensive by default — a scan against the home IP gets no Windrose signal.

### Negative
- If Windrose's signalling service goes down, the server is unreachable. Historically this has happened during Steam-wide outages; uncommon.
- If the router's UPnP is buggy or off, friends get vague "can't connect" errors and we switch to Direct Connection mode as a workaround.
- P2P works through typical consumer NAT but fails under CGNAT or strict-symmetric NAT. If any friend reports persistent connection failures from a specific ISP, that friend likely needs direct mode (or a VPN).

### Risks & Mitigations
- **Risk:** Router UPnP is disabled by default on the user's router.
  **Mitigation:** Documented as step in `AGENT_GUIDE.md` Phase 0. Verified with `upnpc -s` during `bootstrap.sh`.
- **Risk:** ISP upgrades the user to CGNAT without notice.
  **Mitigation:** The bot's `/status` command reports external IP and tests P2P reachability. Degraded P2P triggers a documented switch to WireGuard/Tailscale or an ISP call.
- **Risk:** Home IP changes mid-session during Direct Connection mode.
  **Mitigation:** P2P is the default, so this only matters if the admin chose direct. DDNS (duckdns.org, no-ip.com) is the documented remediation.

## Docker-related note (no longer relevant)

Earlier drafts included a long section on `iptables MASQUERADE` breaking LAN ICE inside Docker. Since we abandoned Docker (ADR-003), this issue no longer applies to our stack. Kept for archival reference only:

> Running Windrose in Docker on the same LAN as the clients causes Docker's default bridge NAT to MASQUERADE container traffic. The ICE consent check compares the sending IP to the signalling-declared IP; when those differ, consent fails and clients see an unsolvable "connection rejected" loop. Native Wine on the host sidesteps this entirely.

## Implementation Guide

### Step 1 — Configure `ServerDescription.json` for P2P (default)

The server creates this file on first launch. Edit it **only while the service is stopped**:

```bash
sudo systemctl stop windrose
nano ~/windrose/R5/ServerDescription.json
```

Key fields for P2P:
```json
{
  "InviteCode": "",
  "IsPasswordProtected": false,
  "Password": "",
  "ServerName": "The Windrose",
  "MaxPlayerCount": 4,
  "UserSelectedRegion": "EU",
  "UseDirectConnection": false,
  "P2pProxyAddress": "192.168.1.42"
}
```

- `InviteCode`: leave empty on first run; the server generates one and writes it back. After that, you can copy the value here to freeze it across clean installs.
- `P2pProxyAddress`: the laptop's **LAN IP**, not public IP. Find with `hostname -I | awk '{print $1}'`. Used by the P2P proxy for LAN-relative addressing.
- `UserSelectedRegion`: `EU` covers EU + NA (good enough for most mixed groups). `SEA` for East Asia, `CIS` for Russia/CIS states.

Restart: `sudo systemctl start windrose`. Watch `journalctl -fu windrose` for the `InviteCode: <code>` line.

### Step 2 — Verify UPnP on the router

From the laptop:
```bash
sudo apt install miniupnpc
upnpc -s
# Expected: prints the router's external IP and "UPnP Device Found"
# If output is "No IGD UPnP Device found" → UPnP is off or unsupported.
```

If UPnP is off, log into the router's web UI, find "UPnP" (usually under "Advanced" / "NAT"), enable it, save. Re-run `upnpc -s`.

### Step 3 — Verifying P2P reachability end-to-end

The simplest test is a real game client on a phone tethered to cellular (outside your LAN):
1. Server running, `journalctl` shows an Invite Code.
2. Friend (or admin's second account) opens Windrose → **Play → Connect to Server**.
3. Pastes the Invite Code → clicks Find → should see the server in the list.
4. Clicks Join → enters password if set → in-game.

If step 3 fails: Windrose signalling service outage, UPnP misconfig, or CGNAT. Next step is to switch to Direct Connection temporarily to distinguish.

### Step 4 — Switching to Direct Connection (fallback)

```bash
# Stop the server
sudo systemctl stop windrose

# Edit ServerDescription.json
sed -i 's/"UseDirectConnection": false/"UseDirectConnection": true/' \
  ~/windrose/R5/ServerDescription.json

# Open host firewall
sudo ufw allow 7777/tcp comment 'windrose-direct'
sudo ufw allow 7777/udp comment 'windrose-direct'
sudo ufw allow 7778/udp comment 'windrose-direct-aux'

# Port-forward on the router's web UI:
#   External 7777/TCP → 192.168.x.y:7777/TCP
#   External 7777/UDP → 192.168.x.y:7777/UDP
#   External 7778/UDP → 192.168.x.y:7778/UDP

# Restart the server
sudo systemctl start windrose

# Find the public IP to share with friends:
curl -4 ifconfig.me
# Share: <that-ip>:7777 in Discord
```

### Step 5 — Switching back to P2P

Reverse Step 4:
```bash
sudo systemctl stop windrose
sed -i 's/"UseDirectConnection": true/"UseDirectConnection": false/' \
  ~/windrose/R5/ServerDescription.json
sudo ufw delete allow 7777/tcp
sudo ufw delete allow 7777/udp
sudo ufw delete allow 7778/udp
# Also remove the router port forwards via its web UI.
sudo systemctl start windrose
```

## Code Examples

### Bot snippet — expose the current Invite Code via `/status`
```python
import json, pathlib

SERVER_DESC = pathlib.Path("/home/windrose/windrose/R5/ServerDescription.json")

def current_invite_code() -> str | None:
    try:
        data = json.loads(SERVER_DESC.read_text())
        persistent = data.get("ServerDescription_Persistent", {})
        return persistent.get("InviteCode") or None
    except Exception:
        return None
```

### Shell one-liner to get the Invite Code into the clipboard
```bash
cat ~/windrose/R5/ServerDescription.json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["ServerDescription_Persistent"]["InviteCode"])' \
  | xclip -selection clipboard 2>/dev/null || \
  cat ~/windrose/R5/ServerDescription.json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["ServerDescription_Persistent"]["InviteCode"])'
```

## References

- Windrose dedicated server guide, networking FAQ: https://playwindrose.com/dedicated-server-guide/
- Official Steam community guide (Linux section, networking): https://steamcommunity.com/sharedfiles/filedetails/?id=3706337486
- miniupnpc (client-side UPnP testing): https://miniupnp.tuxfamily.org/
- ICE / NAT punch-through RFC: https://datatracker.ietf.org/doc/html/rfc8445
- CGNAT background: https://en.wikipedia.org/wiki/Carrier-grade_NAT

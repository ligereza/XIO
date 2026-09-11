# xio FACES — two networks, never on the same wire

The xio system (Xiaomi Termux server + plugin stack) operates in **two mutually exclusive configurations**
that serve different purposes. Confusion between them has led to false security concerns; this doc fixes that.

**Core rule:** The MAK Linux box (codex, research, micelio) and the team hotspot (32 clients, no AP
isolation) NEVER coexist on the same network. Code-execution services are architecture-gated by design.

---

## CURRENT FIELD SURFACE CONTRACT — 2026-09-11

This is the current contract for the two field surfaces. It takes precedence over old IP examples,
old APK notes, and historical deployment notes elsewhere in the repository.

### Hosts, listeners, and boundaries

| Surface | Host and listener | Client form | Persistence and identity |
|---|---|---|---|
| FLUJO engine | Windows portable `C:\IA\flujo` or MAK stationary copy `:8765` | Existing desktop FLUJO UI | Existing engine remains intact; XIO products are not copied into the whole hub |
| XIO field host | Xiaomi (currently Termux) `:5000` | One HTTP server with two namespaced web surfaces | State belongs to the device running XIO; the event key is supplied by the host catalog |
| XIO-RD | `:5000` under `rd_field` | Native RD APK measures; `/view` is the RD hub for browsers | Exact `eventRef`; host-owned RD field data; no implicit event creation |
| XIO-FOH | `:5000` under `foh_monitor` | XIO host listens to FOH signals; `/view` is the ISKVW/FOH hub for browsers | Exact `eventKey`; host-owned FOH/VJ context and evidence |

There are therefore two separated XIO products, but not four APKs or four HTTP servers. RD and FOH
share the XIO listener and host storage while remaining separate namespaces and workflows. FOH signal
inputs such as Art-Net `:6454`, sACN `:5568`, OSC/timecode `:7000`, Chataigne/show-kit UDP, and the
existing Mapping LED tool are tools or protocols, not extra XIO HTTP services.

### Host modes: offline Xiaomi or PC server

The database belongs to the machine that is running the XIO server; the browser is only a client.
These are equivalent supported deployments:

| Mode | Server and storage | Xiaomi/client URL |
|---|---|---|
| Field/offline | Xiaomi Termux `:5000`; RD/FOH data survives without mobile internet | `http://<IP-XIAOMI>:5000` or the configured host in the RD client |
| Studio/PC | PC XIO `:5000`; the PC owns the active DB/logs | `http://<IP-PC>:5000`; the Xiaomi opens the same browser/PWA as any other client |

Moving the host moves the active data authority; it does not copy or merge databases implicitly. The
RD APK is a field client and may be pointed at either host. FOH remains browser/PWA: its active signal
listener must run on the selected host, while every other phone/tablet only visualizes the host's data.

`127.0.0.1:8765` is a local/FLUJO address only. It must never be used as the hotspot URL for RD or
FOH. A hotspot client must use the Xiaomi's current `wlan1` address and port `5000`.

### Dynamic hotspot rule

The Xiaomi currently shares mobile data through its hotspot. Its address is session state and may
change every time the hotspot is restarted or Android reallocates the subnet. The observed address
must be discovered live (`ip addr show wlan1` on the phone, or the existing ADB/gateway discovery
tools); no operational file may promote an observed address to a permanent XIO URL. Broadcast and
show-kit discovery must likewise derive the current interface/network rather than reuse an old
`192.168.*` address.

The hotspot password is the field access boundary. RD and FOH do not add a login, token, or extra
security layer. A future memoryless router can replace the Xiaomi, but one connected device must then
run the same XIO server and own the host data; clients still connect to the current router-host address.

### Product separation

- **XIO-RD** is the Reduciendo Daño field/assistance surface: the native APK measures photos,
  silhouettes, timestamps, samples and results. `FLUJO-RD` is its separate RD-only browser hub: it
  visualizes the host database, producer/event ficha and descriptive result graphs.
- **XIO-FOH** is the personal VJ/ISKVW field surface: its host listens to live-show event context,
  artist/client, venue/layout, setlist, Mapping LED, Resolume/Chataigne/Showkit inputs, OSC/Art-Net,
  timecode and timestamps. `FLUJO-ISKVW` is the separate browser hub for those tools and FOH data.
  It does not collect RD samples or apply the RD flyer rule.
- **FLUJO** remains the existing engine/backend; these two reduced surfaces are delivered beside it,
  not as extra tabs in the main engine and not as a copy of the whole repository on Xiaomi.

---

## FACE A — Home / Studio (dev)

**Setting:** A fully private LAN. Owner's machines only. Geographically: the studio.
The MAK Linux box and the Windows PC are joined by WiFi AND a direct Ethernet
cable between them -- a two-machine private link, no third party on the wire.

### Membership
| Device | Role | Network | Notes |
|---|---|---|---|
| MAK Linux box | Hub humano + servicios internos Research/Codex | 192.168.50.2 | Solo el Hub :8900 es alcanzable por la LAN; Research/Codex quedan en loopback |
| Windows PC (this repo / Cauce dev) | Repo operations, airdrop, xio PC-side tooling | 192.168.50.x | Develops, verifies, deploys to the show |
| Xiaomi phone (docked at home) | Termux server development, hotspot testing | 192.168.50.x | Runs xio plugins; reaches the Hub routes for testing |

### Services reachable
- `plataforma:8900` (Hub humano, backups, resource guard, `/research/` and `/codex/`)
- `research:8890` and `codex:8891` are loopback-only service ports
- `xio:5000` (phone server, with MAK on the LAN for testing)

### Trust model
- All devices are owner-controlled machines with no third parties present
- Network is fully private (owner's home LAN, wifi + direct ethernet, no venue exposure)
- The internal codex and research services run without a token because they are
  loopback-only; the LAN reaches them through the Hub boundary.

---

## FACE B — Live Show (field)

**Setting:** An event venue (studio, stage, outdoor, etc.). Team present, audience possible. The ONLY
network interface is the Xiaomi phone's hotspot.

### Membership
| Device | Role | Network | Notes |
|---|---|---|---|
| Xiaomi phone | Standalone Termux server (xio:5000), on-device route/hub | Subred dinámica del hotspot | Everything runs ON the phone. NO external codex dependency. |
| Team clients (~32 devices) | FOH phones, tablets, laptops, mixing board controllers, lights | Misma subred dinámica | Zero AP isolation; any client can sniff other clients' traffic. NO code execution on these. |
| Windows PC | NOT present | (disconnected) | Remains at studio; cannot reach or control the show hotspot |
| MAK Linux box | NOT present | (disconnected) | Stays home; codex/research unreachable from the venue |

### Services reachable
- `xio:5000` (phone server ONLY — no external codex/research)
- `showcontrol` plugin (OSC/Art-Net/sACN, if wired with XIO_SHOWCONTROL_TOKEN)
- `charge_control`, `connectivity_supervisor`, `hotspot_watch` (on-device only)

### Trust model
- The Xiaomi is the single point of internet and control
- 32-client hotspot with no AP isolation means team members can intercept each other's traffic
- **codex does NOT exist on this network** — all code-execution is sandboxed on MAK (Face A, offline)
- Authentication (tokens, permits) guards dangerous endpoints. The management
  surface is read-only by design, while `showcontrol` is an explicitly active
  signal surface when installed, enabled and authorized.

---

## Security consequence

This separation **intentionally avoids the risk of code-execution exposure on a multi-client show network**:

| Threat | Face A | Face B |
|---|---|---|
| LLM box compromise (stolen model, malicious script) | Mitigated: confined to owner's LAN (xio denies MAK unless explicitly trusted in the future) | Not applicable: codex never runs on Face B |
| 32-client hotspot sniffing | Not applicable: only owner's trusted machines | Acceptable only for declared show-control traffic; no code generation |
| Network isolation / client broadcast | Not applicable: private home network | Expected: a show is inherently open; team coordinates via the hotspot |

**In short:** The false concern (32-client exposure to codex) cannot happen because codex is not on Face B.

---

## How xio knows which face it is

At startup (`run_server.sh`), the phone's current IP (or the hotspot subnet, if visible) determines context:

- **Face A indicators:** IP in range `192.168.50.x` OR the phone is connected via USB to a PC with `tcpip 5555` active.
  - xio server may call the Hub on the private LAN; direct MAK research/codex
    ports are not part of the LAN contract.
  - Watchdogs + Shizuku run to support the studio dev loop.
  
- **Face B indicators:** Hotspot is ON (checked with `dumpsys wifi` or `ip addr show wlan1`); the actual interface address is session state and must be read live.
  - xio server disables MAK-facing endpoints (codex is unreachable).
  - Showcontrol plugin wires XIO_SHOWCONTROL_TOKEN if set (public show security).
  - Watchdogs focus on keeping the show alive (hotspot, battery, server restart).

---

## Network subnet history

Observed in production / logs:

| Subnet | Face | Notes |
|---|---|---|
| `192.168.50.x` | A (home) | Stable, configured in router. MAK + Windows + phone (docked). |
| `192.168.127.x` | B (show) | Primary hotspot range (seen consistently). |
| `192.168.198.x` | B (show) | Secondary hotspot range (observed in one session, 2026-07-16). |
| `192.168.69.x` | Unknown | Mentioned in audit notes; no verified production log. If seen, flag to user. |

**Subnet drift is expected:** Android hotspot subnet allocation is not guaranteed. Always verify before each
show with `ip addr show wlan1` (on phone) or `dumpsys wifi` (from PC via adb).

---

## Why this distinction matters

**Before this doc:** agents asked "isn't 32-client exposure a vulnerability for codex?" — conflating Face B's hotspot with Face A's LLM box.

**After this doc:** it's clear that (1) codex never runs on the show hotspot, (2) the show hotspot never reaches codex, and (3) code execution happens offline in the studio, not in the field.

This lets us design each face independently:
- Face A: tight integration, optional auth (owner's machines), codex + research always available.
- Face B: read-only management plus guarded active show-control traffic; codex absent by architecture.

---

**See also:**
- `xio/RUNBOOK.md` section 5 (Security -- aislar MAK) for on-phone source denylist + guarded endpoints
- `xio/HOTSPOT_SHOW_RUNBOOK.md` for full Face B show-day architecture and self-heal loops
- `xio/CAPACIDADES.md` for the distinction between repository capability and Xiaomi runtime verification
- `cultura/mak_plataforma/GENESIS.md` "Las reglas de vida" rule 2 (El teléfono es sagrado) — describes Face A's relationship to MAK

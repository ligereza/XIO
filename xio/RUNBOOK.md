# xio RUNBOOK -- operator manual (index)

Single entry point for running the phone (Xiaomi, Termux+Shizuku, no root) as the
show's router/hub. Compressed, operator-facing -- built for reading on a phone
mid-show. Each section is the ESSENTIAL commands; the "source" line points to the
original doc/script for depth (do not delete those, they stay as the deep-dive).

Written 2026-07-16 by consolidating xio/**/*.md + the real scripts under xio/new/.

**ESSENTIAL FIRST READ: [xio/FACES.md](FACES.md) — two-network architecture (studio LAN vs. show hotspot). Codex and MAK never run on the show. Read this to avoid misunderstanding the security model.**

Capability boundary: this runbook covers both the passive `foh_monitor` and the
active `showcontrol` plugin. The former observes UDP traffic; the latter can
send or receive show-control traffic when installed, enabled and authorized.
Repository code is not runtime proof. Use [CAPACIDADES.md](CAPACIDADES.md) as
the status matrix before a show.

## Index

1. [Variables](#1-variables) -- IPs/ports, verify per show
2. [Show-day](#2-show-day) -- pre-show / during-show / checklist
3. [Reboot recovery](#3-reboot-recovery) -- the one gap that needs a human or an APK
4. [Hotspot self-heal](#4-hotspot-self-heal) -- watchdogs that run without you
5. [Security -- aislar MAK](#5-security----aislar-mak) -- deny the LLM box, guarded endpoints
6. [Charge control](#6-charge-control) -- battery cap/floor via USB role, no root
6b. [FOH monitor](#6b-foh-monitor-cabina) -- vigia pasivo Art-Net/sACN/OSC + setlist + JSONL
7. [Install / deploy](#7-install--deploy) -- one-time setup + redeploy
8. [Source docs](#8-source-docs) -- where each section's depth lives

## 1. Variables

Fill in / verify before each show -- the hotspot subnet's 3rd octet is NOT stable
across sessions (seen as `.127.x` in the main watcher, `.198.x` for the MAK box in
a different session). Do not assume a value cold: run `ip addr show wlan1` (on
device) or check `dumpsys wifi` for the live subnet, then update these.

```bash
PHONE_SERIAL=8299e66f                              # USB serial, stable across reboots
PHONE_WIFI_ADB=192.168.127.125:5555                # wifi-adb target -- VERIFY subnet each show
LOOPBACK_ADB=127.0.0.1:5555                        # on-device loopback target (watchdogs use this)
XIO_PORT=5000                                       # Flask server port
ADB=/c/IA/flujo/xio/actual/platform-tools/adb.exe   # PC-side adb.exe
XIO_DENY_IPS=192.168.198.85                         # MAK/dell-11m LLM box -- denied source (see 5)
```
Source: `xio/new/pc_reboot_watch.sh` (SERIAL, WIFI, ADB), `xio/new/server.py`
(port 5000, `app.run(host="0.0.0.0", port=5000)`), `xio/new/run_server.sh`
(XIO_DENY_IPS). NOTE: could not find a documented `127 -> 69 -> 198` subnet
history anywhere in xio/*.md or scripts -- only `.127.x` and `.198.x` are
verified in the sources above. If a `.69.x` session happened, it is not written
down; flag to the user rather than guess.

## 2. Show-day

Architecture (3 layers, only layer 1 has to survive):
```
Capa 1  LAN offline (hotspot AP 192.168.127.x)  <- carga el show. Sin senal 5G funciona.
Capa 2  server xio (Flask, Termux+Shizuku)       <- control/management. Nice-to-have.
Capa 3  internet 5G + LLM operador (futuro)       <- solo cuando hay senal (venue-dependiente).
```

Pre-show (with PC):
1. Shizuku armed + tcpip 5555 up (normal setup; PC watcher does it).
2. `sh /sdcard/xio_termux/run_server.sh` -- launches server + shizuku_watchdog +
   server_supervisor + hotspot_watch (idempotent, safe to re-run).
3. Confirm hotspot has clients (PC + FOH phone).
4. Confirm the API answers from the FOH phone: `curl http://<phone>:5000/api/plugins`
5. Power: put the Xiaomi on a PD source / power bank (closes the reboot gap, see 3).

During show (self-heals without Windows):
- Hotspot glitch (phone stays ON) -> `hotspot_watch.sh` revives it, ~30-90s (see 4).
- Shizuku dies -> `shizuku_watchdog.sh` re-arms it, ~20s (see 4).
- server.py dies -> `server_supervisor.sh` relaunches it, ~90s (see 4).
- Live status while it runs: `curl http://<phone>:5000/api/plugins/connectivity_supervisor/status`
  or open `http://<phone>:5000/api/plugins/connectivity_supervisor/ui` on a tablet
  (self-contained dashboard: hotspot/internet/clients/battery/watchdog liveness).

Does NOT self-heal: a physical reboot (battery to 0). See section 3.

Checklist:
- [ ] Pre-show with PC: Shizuku + tcpip + run_server.sh + hotspot with clients.
- [ ] Xiaomi on PD source / power bank (avoids reboot = closes the only gap).
- [ ] iPhone has its own cellular data (to receive ntfy if hotspot drops).
- [ ] Isolation test in venue (2 phones, ping) if the show uses peer-to-peer traffic.
- [ ] (Optional) AccessibilityService from section 3 installed.

Source: `xio/HOTSPOT_SHOW_RUNBOOK.md` (full arch discussion, verified
`MaximumSupportedClientNumber=32`, `AutoShutdownEnabled=false`, no client
isolation on the softap).

## 3. Reboot recovery

The ONE failure that does not self-heal without a human or a boot-time APK: a
physical reboot drops adbd back to USB-only (loses tcpip 5555), which kills
Shizuku, which blinds the on-device watchdogs.

**Automatic (already wired):**
- Termux:Boot entry `~/.termux/boot/00-xio-boot.sh` runs `sh /sdcard/xio_termux/reboot_recover.sh`
  on every boot. It tries loopback `127.0.0.1:5555`, then wireless-debug via mDNS;
  normalizes back to tcpip 5555; re-arms Shizuku (`setsid <libshizuku.so path>`);
  relaunches `run_server.sh`; and sends an ntfy alert (topic read from
  `/sdcard/xio_termux/ntfy_topic.txt`, never hardcoded) reporting hotspot state.
- PC-side watcher (independent process, USB-based, survives hotspot being down):
  ```bash
  bash /c/IA/flujo/xio/new/pc_reboot_watch.sh &
  ```
  Polls every 15s over USB; on a fresh boot (uptime < 240s) or a sustained outage
  it re-arms Shizuku, restores tcpip 5555, re-enables the hotspot by screen-tap if
  down, and drives Termux to (re)launch `run_server.sh`. Single-instance lock at
  `xio/new/.pc_watch.pid`. Log: `xio/new/pc_reboot_watch.log`.

**The honest gap:** if the phone reboots with NO PC/host adb attached, neither
watcher above has a transport. `reboot_recover.sh` then sends an actionable ntfy:
"Reboot SIN host: server NO recuperable sin PC/accesibilidad. Hotspot: DOWN. Si
DOWN, toca el hotspot en el telefono." No PIN on the phone -> one tap on the
hotspot toggle fixes it (iPhone needs its OWN cellular data to receive this).

**Close the gap for real -- AccessibilityService (source written, NOT built/tested):**
```bash
cd xio/hotspot_boot_service
./gradlew assembleDebug        # -> app/build/outputs/apk/debug/app-debug.apk

ADB=/c/IA/flujo/xio/actual/platform-tools/adb.exe
S=8299e66f
"$ADB" -s "$S" install -r app/build/outputs/apk/debug/app-debug.apk
SVC=com.xio.hotspotboot/.HotspotAccessibilityService
"$ADB" -s "$S" shell "settings put secure enabled_accessibility_services $SVC"
"$ADB" -s "$S" shell "settings put secure accessibility_enabled 1"
"$ADB" -s "$S" shell "settings get secure enabled_accessibility_services"   # verify
```
Disable: same two `settings put` commands with `''` and `0`. Double-gate design
(same as `hotspot_watch.sh`): only clicks the toggle if it reads OFF, never
touches a healthy hotspot. Fallback tap coordinate `540,583` is tuned for HyperOS
on the Mi 11 Lite 5G NE -- verify on the real device if the text-search fallback
doesn't fire.

**One-time installs** (see section 7 for the full setup sequence):
`setup_boot.sh` installs the Termux:Boot launcher; `setup_runcommand.sh` allows
headless `RUN_COMMAND` (screen may be PIN-locked post-reboot).

Source: `xio/HOTSPOT_SHOW_RUNBOOK.md` ("El unico hueco"),
`xio/hotspot_boot_service/README.md`, `xio/new/reboot_recover.sh`,
`xio/new/pc_reboot_watch.sh`, `xio/new/00-xio-boot.sh`, `xio/new/setup_boot.sh`.

## 4. Hotspot self-heal

Three independent on-device loops, all started by `run_server.sh` (idempotent via
their `*_start.sh` launchers -- safe to call directly too):

| Loop | Launcher | Log | Heals | Cadence |
|---|---|---|---|---|
| `hotspot_watch.sh` | `sh /sdcard/xio_termux/hs_start.sh` | `.../hotspot_watch.log` | hotspot glitch (phone stays ON) | poll 15s, acts after 2 down cycles (~30s) |
| `shizuku_watchdog.sh` | `sh /sdcard/xio_termux/wd_start.sh` | `.../shizuku_watchdog.log` | Shizuku dies | poll 20s |
| `server_supervisor.sh` | `sh /sdcard/xio_termux/sup_start.sh` | `.../server_supervisor.log` | server.py dies | poll 15s, restarts after 3 fails (~45s) |

Restart hotspot_watch + server_supervisor with fresh intervals WITHOUT touching
server.py (no full redeploy):
```bash
sh /sdcard/xio_termux/relaunch_watchdogs.sh
```

Safety design (both `hotspot_watch.sh` and the AccessibilityService in section 3
share it): double-gate -- only acts if `wlan1` has no IPv4 AND the settings
toggle reads `checked="false"`. NEVER flips a healthy hotspot off.

Live telemetry (read-only, never touches a radio): `connectivity_supervisor`
plugin polls hotspot clients (`ip neigh show dev wlan1`) + watchdog pgrep
liveness every 20s (default), tracks device join/drop by MAC, and cross-checks
Bluetooth as an informational side-channel.
```bash
curl http://<phone>:5000/api/plugins/connectivity_supervisor/status
curl http://<phone>:5000/api/plugins/connectivity_supervisor/events?limit=25
curl http://<phone>:5000/api/plugins/connectivity_supervisor/clients
```
Its one state-changing route is guarded (HTTP 423 without confirm, see section 5):
```bash
curl -X POST "http://<phone>:5000/api/plugins/connectivity_supervisor/reassert-hotspot?confirm=1"
```
Honest limits: non-root HyperOS cannot reliably restart a configured tether from
a service call -- this is best-effort and reports its raw result, no fake success.

Source: `xio/HOTSPOT_SHOW_RUNBOOK.md`, `xio/new/hotspot_watch.sh`,
`xio/new/shizuku_watchdog.sh`, `xio/new/server_supervisor.sh`,
`xio/new/relaunch_watchdogs.sh`, `xio/new/hs_start.sh`, `xio/new/wd_start.sh`,
`xio/new/sup_start.sh`, `xio/new-plugins/connectivity_supervisor/__init__.py`.

## 5. Security -- aislar MAK

Two independent layers on the phone (server.py), plus a separate plugin-level
sandbox.

**Layer A -- source denylist (isolate the MAK/dell-11m LLM box):** untrusted
hosts on the hotspot (e.g. a local-LLM box that could pull a poisoned
model/script and scan the LAN) must never drive xio, not even for reads.
Enforced ON THE PHONE (a compromise of the denied host cannot lift it, unlike a
firewall rule living on that host itself); DNS/internet stay separate services
so a denied host keeps its own connectivity, it just cannot reach xio:
```bash
export XIO_DENY_IPS="192.168.198.85"     # set in run_server.sh before launch
```
A request from a denied source gets `403 {"error":"forbidden","reason":"This
source is denied by the xio controller."}` before any handler runs.

**Layer B -- guarded dangerous endpoints:** these plugin actions can drop the
only internet or sever the USB-ADB link, so they LOAD fine but refuse to execute
(`HTTP 423`) unless the request carries `confirm=1` (query/JSON body/header
`X-Confirm-Dangerous: 1`), or the server was started with `PLUGINS_ALLOW_UNSAFE=1`:

| Plugin | Guarded endpoints |
|---|---|
| `usb_controller` | set-function, data-toggle, secure-mode (kills ADB itself) |
| `dns_shield` | set-provider |
| `quick_actions` | wifi, hotspot, data, airplane, bluetooth |
| `wifi_intelligence` | toggle, forget, connect, disconnect |
| `network_controller` | block, block-wifi, block-data |
| `prop_editor` | set, reset |
| `connectivity_supervisor` | reassert-hotspot |
| `charge_control` | charge, powerbank, dock |

Example: `curl -X POST "http://<phone>:5000/api/plugins/charge_control/charge?confirm=1" -d '{"on":false}'`

Plugins that never even load (auto-fire on load, judged too risky): `automation_rules`,
`clipboard_monitor`, `display_profiles`, `app_freezer`.

**Layer C -- plugin_guardian (separate sandbox/audit system, not MAK-specific):**
permission-per-plugin enforcement + command-pattern blocklist + full audit log.
```bash
curl http://localhost:5000/api/plugins/plugin_guardian/status
curl "http://localhost:5000/api/plugins/plugin_guardian/audit-log?limit=100"
curl http://localhost:5000/api/plugins/plugin_guardian/blocked-commands
curl -X POST http://localhost:5000/api/plugins/plugin_guardian/toggle-review-mode \
  -H "Content-Type: application/json" -d '{"enabled": true}'
```
RESOLVED 2026-07-18: `plugin_guardian` used to exist as two byte-identical
copies. Canonical copy = `xio/new-plugins/plugin_guardian/` (the path
`run_server.sh` actually deploys: `PLUGINS_DIR=$HOME/xioplugins` <-
`/sdcard/xio_termux/new-plugins`). The stale duplicate at
`xio/seguridad/pluginseguridad/plugin_guardian/` was archived via git mv to
`_archive/legacy_20260717_2015/xio_seguridad_plugin_guardian/`.

**Layer D -- showcontrol XIO_SHOWCONTROL_TOKEN (public-hotspot shows):** the
showcontrol plugin (OSC/Art-Net/sACN sender, see
`xio/new-plugins/showcontrol/README.md`) sends real DMX/OSC to a live rig, so
when the hotspot is shared with an audience it needs its own lock. Optional,
off by default (open, same as today) -- set it to require a header on EVERY
showcontrol route, GET included:
```bash
export XIO_SHOWCONTROL_TOKEN="your-show-secret"   # set in run_server.sh before launch
curl -H "X-Xio-Token: your-show-secret" http://<phone>:5000/api/plugins/showcontrol/status
```
Without the header (or with a wrong one) every showcontrol route returns
`401 {"error":"token requerido o invalido"}`. Comparison is constant-time
(`hmac.compare_digest`). This is separate from the plugin's own `muros` show
token (POST-only, config-persisted, rotated via `/auth/set` -- see that
README's "Show token" section): XIO_SHOWCONTROL_TOKEN is an env var read
fresh on every request, so exporting it and restarting the server is enough,
no API call needed, and it also locks down read-only GETs like `/status` and
`/obs` that the muros token leaves open.

Source: `xio/new/server.py` (`_DENY_IPS`, `DANGEROUS_ENDPOINTS`,
`_request_confirmed`, `UNSAFE_PLUGINS`), `xio/new/run_server.sh` (XIO_DENY_IPS
setting), `xio/PLAN_SERVICIOS_SIN_ROOT.md` (MAK context),
`xio/new-plugins/plugin_guardian/README.md`, `xio/seguridad/INSTALL_SECURITY.md`,
`xio/new-plugins/showcontrol/__init__.py` (`_xio_token_required`,
`XIO_SHOWCONTROL_TOKEN`).

## 6. Charge control

No-root battery cap/floor via USB power ROLE (not the blocked `/sys` charge
node) -- `dumpsys usb set-port-roles port0 <sink|source> <device|host>` as shell
uid via Shizuku/rish:
- `sink device` -> phone RECEIVES charge.
- `source host` -> phone is OTG source -> does NOT charge (powerbank mode).
- `sink host` -> receives charge AND hosts peripherals at once (dock mode, hub
  with PD passthrough).

Defaults: limiter OFF by default (must charge free until enabled), `cap=80`,
`floor=77` (hysteresis, resumes charging), `hard_floor=20` (NEVER let the phone
die: below this, charge is FORCED and everything else is ignored).

```bash
curl http://<phone>:5000/api/plugins/charge_control/status
curl http://<phone>:5000/api/plugins/charge_control/config
curl -X POST http://<phone>:5000/api/plugins/charge_control/config \
  -d '{"limiter_enabled": true, "cap": 80, "floor": 77}'
# guarded (HTTP 423 without confirm -- see section 5):
curl -X POST "http://<phone>:5000/api/plugins/charge_control/charge?confirm=1"    -d '{"on": false}'
curl -X POST "http://<phone>:5000/api/plugins/charge_control/powerbank?confirm=1" -d '{"on": true}'
curl -X POST "http://<phone>:5000/api/plugins/charge_control/dock?confirm=1"
```
`/charge {"on":false}` and `/powerbank {"on":true}` are both REJECTED (HTTP 409)
if battery level <= hard_floor -- never cut the only internet's power on a
near-dead phone, even with confirm=1.

Source: `xio/PLAN_SERVICIOS_SIN_ROOT.md` (discovery + rationale),
`xio/new-plugins/charge_control/__init__.py` (actual endpoints/defaults),
`xio/HOTSPOT_SHOW_RUNBOOK.md` (power-bank-avoids-reboot framing).

## 6b. FOH monitor (cabina)

Plugin `foh_monitor` (`xio/new-plugins/foh_monitor/`): vigia PASIVO de cabina.
Listeners UDP read-only (jamas envia): Art-Net :6454, sACN :5568, OSC :7000.
Registra todo el show a JSONL y sirve un panel touch pa la pantalla del Xiaomi.

This section does not describe `showcontrol`. That plugin is a separate active
surface documented in `xio/new-plugins/showcontrol/README.md`, with its own
token and live-route risk.

**Panel (abrir en el Xiaomi mismo o en cualquier cliente del hotspot):**
```
http://<phone>:5000/api/plugins/foh_monitor/panel
```
3 tiles LUCES (artnet|sacn) / VISUAL (osc) / AUDIO, tema actual + boton NEXT,
feed de eventos, bateria. Auto-refresh 2s; wake-lock best-effort (tocar la
pantalla una vez lo arma; igual sube el timeout de pantalla en Ajustes pa show).

**Apuntar las consolas al telefono:**
- Art-Net: output del nodo/consola -> IP del telefono (o broadcast de la subred
  del hotspot, p.ej. `192.168.x.255`), puerto 6454.
- sACN: UNICAST a la IP del telefono es lo garantizado. El plugin hace join
  multicast 239.255.u.u (universos config `sacn_universes`, default 1-16)
  best-effort; Android sin MulticastLock puede no entregar multicast -- el modo
  real queda anotado en `/status` (`sacn_mode`).
- OSC: Resolume -> Preferences -> OSC -> OSC Output: IP del telefono, puerto 7000.

**Setlist:**
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"text":"Tema 1\nTema 2\nTema 3"}' \
  http://<phone>:5000/api/plugins/foh_monitor/setlist
curl -X POST http://<phone>:5000/api/plugins/foh_monitor/next   # o boton NEXT del panel
```

**Status / registro:**
```bash
curl http://<phone>:5000/api/plugins/foh_monitor/status
curl http://<phone>:5000/api/plugins/foh_monitor/events?limit=20
# post-show: bajar el JSONL del dia (eventos senal_on/off, setlist, bateria, heartbeat)
curl -O http://<phone>:5000/api/plugins/foh_monitor/log          # hoy
curl "http://<phone>:5000/api/plugins/foh_monitor/log?date=20260723" > show.jsonl
curl http://<phone>:5000/api/plugins/foh_monitor/logs            # listar dias
```
Registro en el telefono: `/sdcard/xio_termux/foh_logs/show_YYYYMMDD.jsonl`
(rotacion por dia, un JSON por linea).

**Timecode (LTC -> Chataigne -> OSC):** el canal TC es OSC con address
`/timecode` (config `tc_address`; primer arg string "HH:MM:SS:FF" o float).
Estados: corriendo / congelado (mismo valor > `tc_freeze_seconds` con paquetes
llegando) / caido (sin paquetes > `active_window`); congelado y caido emiten
`tc_freeze` al JSONL, la vuelta emite `tc_resume`, y CADA evento del registro
lleva campo `tc` con el timecode vigente (null si no hay) pa correlacion
post-show. IMPORTANTE: `/timecode` NO cuenta como actividad del canal
osc/VISUAL (un show con solo TC no marca visuales activos). Tiles del panel:
canal nunca visto = gris N/D (esperado si no se cablea); visto y perdido =
rojo OFF (alerta real).

Config Chataigne (5 min): abrir `xio/show_kit/festival_sentir.noisette`
(generado con el builder validado del repo: modulo OSC -> 192.168.127.125:7000
+ Sound Card con LTC on). Manual restante: elegir la M-Audio como input del
Sound Card y agregar un Mapping `Sound Card > LTC > Time` -> `OSC Custom
Message /timecode`. Paso a paso + kit completo del dia (check GO/NO-GO,
setlist doble-click, relay de luces por cable, playbook de fallas):
`xio/show_kit/DIA_DEL_SHOW.md`.

**Audio:** requiere `pkg install termux-api ffmpeg` + app Termux:API instalada.
Si faltan, el tile AUDIO queda "N/D" con el motivo en `/status` -- el resto del
plugin funciona igual. Umbral: config `audio_threshold_db` (default -50 dBFS).

Sin endpoints peligrosos: todo es lectura + next de setlist (inocuo).

Source: `xio/new-plugins/foh_monitor/__init__.py`.

## 7. Install / deploy

**One-time on-device setup (run once in Termux):**
```bash
sh setup_watchdog.sh      # installs adb client in Termux, authorizes loopback,
                           # whitelists Termux+Shizuku from doze, wake-lock
sh setup_boot.sh          # installs Termux:Boot launcher -> ~/.termux/boot/00-xio-boot.sh
sh setup_runcommand.sh    # allow-external-apps=true (headless RUN_COMMAND post-reboot)
```

**Deploy / redeploy the server (idempotent, re-run any time):**
```bash
sh /sdcard/xio_termux/run_server.sh
```
This kills any running `python server.py`, wipes and re-copies
`/sdcard/xio_termux/new` -> `$HOME/xioserver` and
`/sdcard/xio_termux/new-plugins` -> `$HOME/xioplugins`, exports
`XIO_BACKEND=rish`, `RISH_PATH=$HOME/rish`, `PLUGINS_DIR=$HOME/xioplugins`,
`XIO_DENY_IPS` (section 5), launches `server.py` (log:
`/sdcard/xio_termux/server.log`), then starts the 3 watchdogs from section 4.

CONTRADICTION FLAGGED: `xio/new/README.md` documents a SINGLE `plugins/`
directory (dashboard architecture diagram + "Estructura del Proyecto"), and
`xio/new/plugins/` on disk only holds `_template`, `battery_care`,
`example_tool` (3 dirs). The ACTUAL deploy path is split: server code from
`xio/new/` and the full 25+ plugin set from the SEPARATE `xio/new-plugins/`
directory, wired via `PLUGINS_DIR=$HOME/xioplugins` in `run_server.sh`. Treat
`xio/new/plugins/` as stale/legacy, not what ships; `xio/new-plugins/` is live.

**Quick local dev run (off-device, PC only, not the show path):**
```bash
pip install flask
python server.py            # xio/new/ -- opens http://localhost:5000
```

**Extra (optional, unrelated to the server):** `flujo_ondevice.sh` installs a
pure-stdlib subset of the `flujo` CLI in Termux (`flujo --help` / `flujo
version` only -- pydantic/jsonschema commands need Rust toolchain, not set up).

Source: `xio/new/README.md`, `xio/new/run_server.sh`, `xio/new/setup_watchdog.sh`,
`xio/new/setup_boot.sh`, `xio/new/setup_runcommand.sh`, `xio/new/flujo_ondevice.sh`.

## 7b. Airdrop al repo SIN PC (desde este telefono)

El Xiaomi puede entregar un ZIP de airdrop al repo y disparar el gate de
GitHub Actions (validate + suite + PR automatico). Setup una vez en Termux:
```bash
pkg install gh
# token fine-grained SOLO repo vibecodeine SOLO contents:write:
printf '%s' "TU_TOKEN" > ~/.airdrop_token && chmod 600 ~/.airdrop_token
```
Disparo:
```bash
bash airdrop_push.sh /sdcard/Download/entrega.zip "mensaje corto"
```
Verde = PR `airdrop/<tag>` lista para mergear desde el navegador del telefono.
Detalle del canal: docs/AGENT_AIRDROP_PROTOCOL.md, seccion "Canal sin PC".
Source: xio/new/airdrop_push.sh + .github/workflows/airdrop_gate.yml

## 8. Source docs

| Doc | Depth on |
|---|---|
| `xio/HOTSPOT_SHOW_RUNBOOK.md` | full show-day architecture, pre/during-show reasoning, energy strategy |
| `xio/PLAN_SERVICIOS_SIN_ROOT.md` | the "attack the service, not the sysfs" discovery behind charge_control |
| `xio/hotspot_boot_service/README.md` | AccessibilityService source, build, install/activate, honest limits |
| `xio/new/README.md` | plugin framework architecture, PluginBase API, core (non-plugin) endpoints |
| `xio/new-plugins/plugin_guardian/README.md` | full security-sandbox API (audit, alerts, review mode) |
| `xio/new-plugins/showcontrol/README.md` | OSC/Art-Net/sACN show-control plugin -- cues, timeline, fabric, discovery |
| `xio/seguridad/INSTALL_SECURITY.md` | plugin_guardian install/verify/troubleshoot steps |

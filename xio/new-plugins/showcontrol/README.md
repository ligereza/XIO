> Indice operativo: ver xio/RUNBOOK.md

# showcontrol -- the phone as a network show-control node

This is the active control surface, not the read-only `foh_monitor` or
`mak_xio_puente/monitor.py`. Its code being present in the repository does not
prove that the plugin is installed or enabled on the Xiaomi; verify the runtime
state and token before using any route in a live show.

Turns the on-device xio server (Termux + Shizuku) into a **VJ / lighting / show
control** node on the LAN. Sends **OSC**, **Art-Net** and **sACN/E1.31 DMX**;
runs a **cue engine** with timed fades; plays a show against a **timecode
timeline**; routes one signal to many sinks (**fabric**); **discovers** Art-Net
nodes; **auto-maps** DMX fixtures optically; and exposes **live telemetry**.

Everything is **pure stdlib** (`socket` + `struct`) -- no pip, no shell, so there
is **zero command-injection surface**. Every capability is unit-tested off-device
(69 tests). This README is the operating manual; you do not need Claude to run it.

## Run the tests (off-device, any machine)

```bash
cd xio/new-plugins/showcontrol
for t in protocols cueengine fabric discovery automap obs timeline auth oscin integration; do
  py test_$t.py
done
# each prints "ALL N PASSED"
```

## Files (the concept graph of xio-concept.html, made code)

| File | Graph node | What it is |
|---|---|---|
| `protocols.py` | `orq` (osc+dmx) | OSC 1.0 / Art-Net ArtDMX / sACN packet builders + Wake-on-LAN |
| `cueengine.py` | `orq` (cues) | cue list, timed crossfades, GO/STOP/RELEASE, follow, keep-alive |
| `timeline.py` | `orq` (capstone) | fire cues at absolute clock positions -- the show plays itself |
| `fabric.py` | `fabric` | one 0..1 signal fans out to many DMX channels / OSC faders |
| `discovery.py` | `sonda` | ArtPoll/ArtPollReply -- find live Art-Net nodes on the LAN |
| `automap.py` | `sonda`/`p_inv` | optical DMX patch via light-transport matrix (dual photography) |
| `obs.py` | `obs` | pull-based telemetry: send rates, thread health, state |
| `oscin.py` | `orq` (input) | OSC parser + closed /xio/* action table -- the phone receives cues |
| `auth.py` | `muros` | optional show token: TOFU set/rotate, constant-time check |
| `panel.py` | -- | self-contained browser control panel (`/panel`), zero external assets |
| `__init__.py` | -- | the plugin: HTTP routes + tick threads wiring it all together |

## HTTP API

All routes are under `http://<phone>:5000/api/plugins/showcontrol`. POST bodies
are JSON. Errors return `{"ok": false, "error": ...}` with 400 (bad input) /
423 (guarded) / 502 (send failed).

### Direct senders
```bash
POST /osc     {"host":"1.2.3.4","port":9000,"address":"/x","args":[1,0.5,"go"]}
POST /artnet  {"host":"1.2.3.4","universe":0,"channels":{"1":255,"2":128}}
POST /sacn    {"universe":1,"channels":{"1":255}}          # multicast unless "host" given
GET  /status                                               # sent counters + last error
```

### Cue engine (`orq`)
```bash
POST /cues  {"output":{"protocol":"artnet","host":"1.2.3.4"},
             "cues":[{"label":"open","fade":3,"levels":{"0":{"1":255}},
                      "osc":[{"address":"/scene/open","args":[1]}]},
                     {"label":"mid","fade":5,"levels":{"0":{"1":100}},"follow":10},
                     {"label":"end","fade":2,"levels":{"0":{"3":255}}}]}
POST /cue/go            # next cue     (or {"index": 2} to jump)
POST /cue/stop          # freeze
POST /cue/release       # fade to black + stop the tick thread   ({"fade":3})
GET  /cue/state
```
A cue is a **complete look**: channels absent from a cue's `levels` track to 0.
`follow` auto-advances. `output.protocol` is `artnet` or `sacn`; `osc_host` is
optional for cue OSC. The 30 Hz tick thread runs only during a show (battery
discipline); a 1 Hz keep-alive holds Art-Net/sACN nodes between changes.

### Timeline (`orq` capstone -- the show plays itself)
```bash
POST /timeline        {"events":[{"at":0,"cue":0},{"at":5,"cue":1},{"at":20,"cue":2}]}
POST /timeline/play
POST /timeline/pause
POST /timeline/locate {"t":11}          # jump the playhead; earlier cues count as passed
GET  /timeline/state
```
`at` is seconds on the transport clock; `cue` is an index into the loaded cue
list. Playing the timeline advances it inside the cue loop and GOes each cue as
its time arrives.

### Fabric (`fabric` -- one signal, many sinks)
```bash
POST /fabric      {"output":{"protocol":"artnet","host":"1.2.3.4"},
                   "signals":["master","hue"],
                   "routes":[{"signal":"master","sink":"dmx","universe":0,"channel":1},
                             {"signal":"master","sink":"dmx","universe":0,"channel":5,"max":200,"curve":2.2},
                             {"signal":"hue","sink":"osc","host":"1.2.3.5","port":9000,"address":"/hue","kind":"float"}]}
POST /fabric/set  {"signal":"master","value":0.5}      # updates every route bound to master
GET  /fabric/state
```
Each route maps `v in [0,1]` to `min + (max-min) * v**curve`. DMX routes need an
`output` target; OSC routes carry their own `host`/`port`. A 2 Hz keep-alive
re-emits standing DMX frames.

### Discovery (`sonda`) + auto-map (`sonda`/`p_inv`)
```bash
POST /discover        {"timeout":3}          # broadcast ArtPoll, list nodes (ip/name/mac/ports)
POST /automap/plan    {"channels":[1,2,3,4,5],"level":255,"mode":"hadamard"}
POST /automap/solve   {"channels":[1,2,3,4,5],"mode":"hadamard","level":255,"measurements":[...]}
```
Auto-map: emit each `plan.steps[i].emit` frame (as `/artnet` `channels`), measure
the scene with a camera/sensor, feed one reading per step (same order) to
`/automap/solve` -> per-channel optical response. `hadamard` mode multiplexes for
SNR + cancels ambient; `single` is one channel per frame. The camera is your
hardware; the sequencing and the math are the plugin's.

### Telemetry (`obs`) + panel + Wake-on-LAN
```bash
GET  /obs                                    # health, uptime, send rates, thread liveness, state
GET  /panel                                  # the browser control panel (open on a tablet)
POST /wol  {"mac":"AA:BB:CC:DD:EE:FF","verify_host":"1.2.3.4","verify_port":22,"timeout":30}
```

### OSC input (`orq` bidirectional -- the phone receives cues)
```bash
POST /oscin        {"port":9001}                       # start listening (opt-in, off by default)
POST /oscin        {"port":9001,"allow":["192.168.127.20"]}   # scope to source IPs
POST /oscin/stop
GET  /oscin                                            # listening?, port, rx/acted/ignored stats
```
Point QLab / Ableton / TouchOSC at `<phone>:9001` and send to the **closed
address table** (nothing else is mapped -- a fixed table is not an injection
surface, a mapping language would be):

| Address | Args | Action |
|---|---|---|
| `/xio/go` | `[index]` optional | GO (next cue, or jump to index) |
| `/xio/stop` | | freeze |
| `/xio/release` | `[fade]` optional | fade to black |
| `/xio/timeline/play` / `pause` | | transport |
| `/xio/timeline/locate` | `[seconds]` | jump the playhead |
| `/xio/signal/<name>` | `[0..1]` | set a fabric signal (fader) |

OSC itself is unauthenticated, so the listener is **opt-in**, its start/stop
endpoints are behind the show token, and `allow` scopes datagrams to known
source IPs. Unknown addresses are counted and ignored.

### Show token (`muros` -- lock the rig on a shared LAN)
```bash
GET  /auth                                   # {"protected": true|false}
POST /auth/set {"generate":true}             # TOFU: free while no token exists; returns the token ONCE
POST /auth/set {"token":"my-show-secret1"}   # or set your own (8..128 printable ASCII)
POST /auth/set {"token":"new1","current":"old1"}   # rotate (or X-Show-Token header for current)
POST /auth/set {"token":""}  -H "X-Show-Token: old1"  # clear -> open mode
```
Once a token is set, **every mutating POST** (senders, cues, timeline, fabric,
discover, automap, WoL) requires it -- `X-Show-Token` header, or `token` in the
JSON body / query string. Read-only GETs (state, `/obs`, `/panel`) stay open.
Comparison is constant-time; the token persists in the plugin's on-device
config (never in the repo). The panel stores it in browser localStorage
("token de show" section).

## Panel

Open `http://<phone>:5000/api/plugins/showcontrol/panel` on any tablet/browser on
the LAN: big GO, STOP, RELEASE, tap-to-jump cue list, timeline transport
(PLAY/PAUSE/locate), JSON loaders, a **SCAN LAN** button that lists discovered
Art-Net nodes (tap one to drop its IP into the show output), a live telemetry
strip, and Wake-on-LAN. Self-contained -- works with no internet.

## Deploy to the phone

The code lives in the repo; deploy is manual over USB per the xio runbook (copy
`xio/new-plugins/showcontrol/` into the on-device plugins dir and restart the
server, or use `run_server.sh`). No pip install needed (pure stdlib).

## Security (read before a live show)

The xio server binds `0.0.0.0:5000` with open CORS, so **any device on the
hotspot can reach these endpoints**. Default is **open** (trusted crew-only
LAN). If audience devices share the hotspot, **set a show token before the
show** (see "Show token" above): one `POST /auth/set {"generate":true}`, paste
the returned token into the panel's "token de show" box on your control tablet,
and every mutating endpoint is locked to holders of the token. Rotating or
clearing later requires the current token (TOFU). (Physical DMX512 via a USB
dongle is out of scope non-root -- drive a network Art-Net/sACN node instead.)

### Whole-server lock: XIO_SHOWCONTROL_TOKEN (public hotspot, GETs included)

For shows where the hotspot is shared with the public, set an env var instead
(or in addition): `export XIO_SHOWCONTROL_TOKEN="your-show-secret"` in
`run_server.sh`'s env before launching the server. Every showcontrol route --
GET included, e.g. `/status`, `/obs`, `/panel`, not just the mutating POSTs
the show token above covers -- then requires a matching header:
```bash
curl -H "X-Xio-Token: your-show-secret" http://<phone>:5000/api/plugins/showcontrol/status
```
Missing or wrong header -> `401 {"error":"token requerido o invalido"}`.
Compared with `hmac.compare_digest` (constant-time). Unset (default) -> no
change from today, fully open. See `xio/RUNBOOK.md` section 5, Layer D.

"""
Connectivity Supervisor -- active-router awareness for a live show.

Turns the phone into a supervisor that KNOWS its own network without ever
silently touching the radios that carry the only internet:
  - polls hotspot clients (ip neigh + cmd wifi list-tethered-clients) READ-ONLY
  - tracks labelled devices (iPhone / iPad) by MAC; detects join / drop / rejoin
  - cross-checks Bluetooth (dumpsys bluetooth_manager) as an INFORMATIONAL side
    channel (bonded/known devices; non-root cannot guarantee live proximity)
  - records read-only radio, data-registration and tethering diagnostics
  - logs events + (best effort) posts an on-device notification
  - exposes ONE guarded remediation: /reassert-hotspot (touches the only internet)

Safety design:
  * The background poll is strictly READ-ONLY -- it never toggles a radio -- so
    this plugin is NOT load-quarantined (same posture as wifi_intelligence).
  * The only state-changing route, /reassert-hotspot, is registered in
    server.py DANGEROUS_ENDPOINTS -> HTTP 423 unless the request is confirmed.
  * Shell-command triggers are gated behind config `triggers_enabled` (default
    False) so no arbitrary command auto-runs from a network event.

iOS reality: Apple devices cannot be FORCED to reconnect Wi-Fi/BT from here.
This plugin DETECTS and ALERTS on drop-offs; it does not (cannot) puppet an
iPhone. The honest lever for a live show is: know instantly when a device
leaves, and keep the phone's own hotspot from silently dying.
"""

from plugins.base import PluginBase
import json
import ipaddress
import os
import re
import subprocess
import threading
import time
from datetime import datetime

_MAC_RE = re.compile(r'([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})')

# Self-contained live operator console. No external assets (works offline on the
# hotspot). Fetches the plugin's own JSON via RELATIVE urls so host/IP is moot.
_DASHBOARD_HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Active Router</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font:15px/1.4 -apple-system,system-ui,Segoe UI,Roboto,sans-serif;background:#0b0d12;color:#e8eaed;padding:14px;max-width:640px;margin:0 auto}
h1{font-size:19px;font-weight:700}
.sub{color:#8a92a6;font-size:12px;margin:2px 0 14px}
.banner{display:flex;gap:9px;margin-bottom:6px}
.chip{flex:1;border-radius:12px;padding:11px;background:#161a22;border:1px solid #232838}
.chip .k{font-size:11px;color:#8a92a6;text-transform:uppercase;letter-spacing:.04em}
.chip .v{font-size:17px;font-weight:700;margin-top:3px}
.ok{color:#4ade80}.bad{color:#f87171}
.batt{font-size:13px;color:#9aa0b0;margin:8px 2px 0}.batt .hot{color:#f87171;font-weight:700}
.sec{font-size:12px;color:#8a92a6;text-transform:uppercase;letter-spacing:.05em;margin:16px 0 8px}
.dev{display:flex;align-items:center;gap:10px;background:#141821;border:1px solid #232838;border-radius:10px;padding:10px 12px;margin-bottom:8px}
.dev .nm{font-weight:600}.dev .meta{font-size:12px;color:#8a92a6}
.badge{font-size:10px;padding:2px 7px;border-radius:20px;margin-left:auto;font-weight:700}
.b-random{background:#3b2f10;color:#fbbf24}.b-hardware{background:#10261a;color:#4ade80}.b-unknown{background:#26262e;color:#9aa0b0}
.ev{font-size:13px;padding:7px 10px;border-left:3px solid #333;margin-bottom:5px;background:#12151d;border-radius:0 8px 8px 0}
.ev .t{color:#6b7280;font-size:11px}
.e-join{border-color:#4ade80}.e-drop{border-color:#f87171}.e-net{border-color:#fbbf24}
.empty{color:#6b7280;font-size:13px;padding:8px}
</style></head><body>
<h1>Active Router</h1><div class=sub id=sub>connectivity supervisor</div>
<div class=banner>
<div class=chip><div class=k>Hotspot</div><div class="v" id=hs>--</div></div>
<div class=chip><div class=k>Internet</div><div class="v" id=net>--</div></div>
<div class=chip><div class=k>Clients</div><div class="v" id=cl>--</div></div>
</div>
<div class=batt id=batt></div>
<div class=batt id=wd></div><div class=batt id=radio></div>
<div class=sec>Present devices</div><div id=devs></div>
<div class=sec>Recent events</div><div id=evs></div>
<script>
var sub=document.getElementById('sub');sub.textContent='starting...';
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function evcls(e){var k=(e&&e.event)||'';return k.indexOf('join')>=0?'e-join':(k.indexOf('drop')>=0?'e-drop':'e-net')}
function set(id,h){var el=document.getElementById(id);if(el)el.innerHTML=h}
function tick(){
 fetch('status',{cache:'no-store'}).then(function(r){return r.json()}).then(function(s){
  set('hs',s.hotspot_up==null?'<span>n/a</span>':(s.hotspot_up?'<span class=ok>UP</span>':'<span class=bad>DOWN</span>'));
  set('net',(s.internet&&s.internet.iface)?'<span class=ok>'+esc(s.internet.iface)+'</span>':'<span class=bad>none</span>');
  document.getElementById('cl').textContent=s.clients_present;
  var b=s.health||{};var p=[];
  if(b.level!=null)p.push(b.level+'%');
  if(b.temp_c!=null)p.push('<span class="'+(b.temp_c>=45?'hot':'')+'">'+b.temp_c+'&deg;C</span>');
  if(b.charging)p.push('charging');else if(b.status)p.push(esc(b.status));
  set('batt',p.length?('Battery &middot; '+p.join(' &middot; ')):'');
  var w=s.watchdogs||{};var wn={shizuku:'Shizuku',server:'Server',hotspot:'Hotspot'};var wp=[];
  for(var wk in wn){var wu=w[wk]>0;wp.push('<span class="'+(wu?'ok':'bad')+'">'+wn[wk]+(wu?' UP':' DOWN')+'</span>')}
  var r=s.radio||{},t=s.tethering||{},rp=[];
  if(r.network_type)rp.push(esc(r.network_type));
  if(r.data_registered===false)rp.push('<span class=bad>data not registered</span>');
  if(r.lte_rsrp!=null)rp.push('RSRP '+esc(r.lte_rsrp)+' dBm');
  if(t.active===true)rp.push('<span class=ok>tether UP</span>');
  else if(t.active===false)rp.push('<span class=bad>tether DOWN</span>');
  set('radio',rp.length?('Radio &middot; '+rp.join(' &middot; ')):'' );
  set('wd',wp.length?('Watchdogs &middot; '+wp.join(' &middot; ')):'');
  set('devs',(s.present&&s.present.length)?s.present.map(function(p){return '<div class=dev><div><div class=nm>'+esc(p.name)+'</div><div class=meta>'+esc(p.ip||'')+' &middot; '+esc(p.mac)+'</div></div><span class="badge b-'+esc(p.mac_type||'unknown')+'">'+esc(p.mac_type||'?')+'</span></div>'}).join(''):'<div class=empty>no clients on the hotspot</div>');
  return fetch('events?limit=25',{cache:'no-store'});
 }).then(function(r){return r.json()}).then(function(ev){
  set('evs',(ev&&ev.length)?ev.slice().reverse().map(function(x){return '<div class="ev '+evcls(x)+'"><span class=t>'+esc(x.ts)+'</span> '+esc(x.detail)+'</div>'}).join(''):'<div class=empty>no events yet</div>');
  sub.textContent='updated '+new Date().toLocaleTimeString();
 }).catch(function(err){sub.textContent='ERR: '+err});
}
tick();setInterval(tick,3000);
</script></body></html>"""


class ConnectivitySupervisorPlugin(PluginBase):
    plugin_id = "connectivity_supervisor"
    name = "Connectivity Supervisor"
    version = "1.0.0"
    description = "Active-router awareness: watch hotspot clients, detect iPhone/iPad drop-offs, keep the only internet alive."
    author = "Cauce"
    icon = "network"
    category = "network"
    permissions = ["network", "system"]

    # ── defaults (overridable via /config) ───────────────────────────
    DEFAULTS = {
        "poll_interval": 20,      # seconds between read-only sweeps
        "stale_after": 60,        # no sighting for this long => "dropped"
        "ap_iface": "wlan1",      # hotspot LAN interface (see `ip addr`)
        # Empty means derive the network from the current IPv4 on ap_iface.
        # Android may allocate a different hotspot subnet on every session;
        # keep an explicit value only as a diagnostic override.
        "ap_prefix": "",
        "bt_watch": False,        # poll BT too (slow dumpsys); /bt endpoint works on-demand regardless
        "radio_watch": True,      # read-only telephony/radio diagnostics
        "tethering_watch": True,  # read-only dumpsys tethering diagnostics
        "notify": False,          # opt-in only; Android notification Binder can stall on some builds
        "triggers_enabled": False,  # gate for shell-command triggers (OFF by default)
        "on_drop_cmd": "",        # shell run on drop  (only if triggers_enabled)
        "on_join_cmd": "",        # shell run on join  (only if triggers_enabled)
        "batt_hot_c": 45,         # alert when battery temp reaches this (deg C)
        "batt_low_pct": 20,       # alert when battery drops to this and not charging
    }
    _BATT_STATUS = {"2": "charging", "3": "discharging", "4": "not charging", "5": "full", "1": "unknown"}

    def __init__(self, context):
        super().__init__(context)
        # Guards self._devices against the poll thread inserting new MACs while a
        # Flask handler iterates the dict ('dictionary changed size during iteration').
        self._lock = threading.Lock()
        self._devices = {}   # mac -> device record
        self._events = []    # ring buffer of events
        self._net_state = {"hotspot_up": None, "internet": None, "radio_type": None,
                           "data_registered": None, "tethering_active": None}  # infra change tracking
        self._infra = {"hotspot": {"address": "", "network_text": "", "broadcast": ""},
                       "hotspot_up": False, "internet": {"iface": "", "addr": ""},
                       "backend": {}, "radio": {}, "tethering": {}}  # cached for /status (poll refreshes)
        self._health = {}  # cached battery health (level/temp_c/status/charging) from the poll
        self._watchdogs = {}  # cached self-heal loop liveness (native pgrep) from the poll
        self._notify_lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────
    def on_load(self):
        self._load_state()
        # every known device starts "absent"; the first poll re-detects who is
        # actually present now (so a fresh server start emits clean join events).
        for dev in self._devices.values():
            dev["present"] = False

        self.register_route("/ui", self._api_ui, methods=["GET"])
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/clients", self._api_clients, methods=["GET"])
        self.register_route("/watch", self._api_watch, methods=["GET"])
        self.register_route("/events", self._api_events, methods=["GET"])
        self.register_route("/bt", self._api_bt, methods=["GET"])
        self.register_route("/label", self._api_label, methods=["POST"])
        self.register_route("/config", self._api_get_config, methods=["GET"])
        self.register_route("/config", self._api_set_config, methods=["POST"])
        # GUARDED in server.py DANGEROUS_ENDPOINTS (touches the only internet):
        self.register_route("/reassert-hotspot", self._api_reassert, methods=["POST"])

        interval = int(self._cfg("poll_interval"))
        self.context.schedule("connsup_poll", self._poll, interval_seconds=interval)
        self.logger.info(f"Connectivity Supervisor loaded (poll every {interval}s, iface {self._cfg('ap_iface')})")

    def on_unload(self):
        self.context.cancel_schedule("connsup_poll")
        self._save_state()

    # ── small helpers ────────────────────────────────────────────────
    def _cfg(self, key):
        return self.get_config(key, self.DEFAULTS.get(key))

    def _backend_info(self):
        """Return whether the controller can currently read Android state.

        A failed rish call can leave the shared output file containing an older
        command's result. Never present that stale text as current radio or
        tethering evidence; mark the backend unavailable instead.
        """
        backend = str(getattr(self.controller, "backend", "unknown") or "unknown")
        if backend != "rish":
            return {"type": backend, "connected": True}
        try:
            return {"type": backend, "connected": bool(self.controller.is_connected())}
        except Exception:
            return {"type": backend, "connected": False}

    def _sh(self, cmdstr, timeout=25):
        """One shell string via the controller (rish on-device / adb on PC)."""
        try:
            return self.controller._shell(cmdstr, timeout=timeout)
        except Exception as e:
            self.logger.error(f"connsup shell failed [{cmdstr!r}]: {e}")
            return ""

    @staticmethod
    def _now():
        return datetime.now().isoformat(timespec="seconds")

    def _fresh(self, ts, seconds):
        if not ts:
            return False
        try:
            age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
            return age <= seconds
        except Exception:
            return False

    def _pfile(self, name):
        """Path for persisted state OUTSIDE the server tree, which run_server.sh
        wipes on each restart. Defaults to /sdcard so device labels + event
        history survive restarts; falls back to the plugin data_dir if that
        location isn't writable (e.g. running under the adb backend on a PC)."""
        d = os.environ.get("XIO_PERSIST", "/sdcard/xio_termux/connsup")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            d = str(self.data_dir)
        return os.path.join(d, name)

    def _load_state(self):
        try:
            with open(self._pfile("devices.json")) as f:
                self._devices = json.load(f)
        except Exception:
            self._devices = {}
        try:
            with open(self._pfile("events.json")) as f:
                self._events = json.load(f)[-500:]
        except Exception:
            self._events = []

    def _save_state(self):
        try:
            with self._lock:
                devices_snapshot = dict(self._devices)
            with open(self._pfile("devices.json"), "w") as f:
                json.dump(devices_snapshot, f, indent=2)
            with open(self._pfile("events.json"), "w") as f:
                json.dump(self._events[-500:], f, indent=2)
        except Exception as e:
            self.logger.error(f"connsup save failed: {e}")

    # ── read-only scanners (never touch a radio) ─────────────────────
    @staticmethod
    def _mac_kind(mac):
        """'random' if the locally-administered bit (0x02) is set -- an iOS/Android
        privacy MAC -- else 'hardware'. iOS keeps ONE random MAC per network,
        stable through a whole session (fine for a live show); it only rotates on
        the daily/OS-update cycle, which is when a device reappears as new."""
        try:
            return "random" if int(mac.split(":")[0], 16) & 0x02 else "hardware"
        except Exception:
            return "unknown"

    def _scan_wifi_clients(self, hotspot=None):
        """Current hotspot clients: {mac -> {ip, state, mac_type}} from the neighbor
        cache. `ip neigh` is the ONLY client source available to uid 2000 --
        `cmd wifi list-tethered-clients` throws SecurityException (denied) and the
        dnsmasq lease file is SELinux-walled, so neither is used."""
        iface = self._cfg("ap_iface")
        hotspot = hotspot or self._hotspot_details()
        network = hotspot["network"]
        # If wlan1 has no current IPv4, its neighbor cache may still contain
        # stale entries. Treat it as no active hotspot clients.
        if network is None:
            return {}
        clients = {}
        for line in self._sh(f"ip neigh show dev {iface}").splitlines():
            parts = line.split()
            if not parts:
                continue
            ip = parts[0]
            try:
                if ipaddress.ip_address(ip) not in network:
                    continue
            except ValueError:
                continue
            mac = None
            if "lladdr" in parts:
                i = parts.index("lladdr")
                if i + 1 < len(parts):
                    mac = parts[i + 1].lower()
            state = parts[-1]
            if mac and state not in ("FAILED", "INCOMPLETE"):
                clients[mac] = {"ip": ip, "state": state, "mac_type": self._mac_kind(mac)}
        return clients

    def _hotspot_details(self, netmap=None):
        """Return the live hotspot IPv4/network/broadcast, never a stale default.

        The interface address is session state on Android.  An old persisted
        ``ap_prefix`` is ignored when it does not contain the current address,
        so a previous show's subnet cannot hide clients on today's hotspot.
        """
        iface = self._cfg("ap_iface")
        netmap = netmap if netmap is not None else self._ipv4_map()
        raw = netmap.get(iface, "")
        if not raw:
            return self._remember_hotspot({"address": "", "network": None, "network_text": "", "broadcast": ""})
        try:
            interface = ipaddress.ip_interface(raw)
        except ValueError:
            return self._remember_hotspot({"address": "", "network": None, "network_text": "", "broadcast": ""})

        network = interface.network
        configured = str(self._cfg("ap_prefix") or "").strip()
        if configured:
            try:
                candidate = ipaddress.ip_network(configured, strict=False)
                if interface.ip in candidate:
                    network = candidate
            except ValueError:
                # Backward-compatible prefix form, but only while it matches
                # this session's address. A stale 192.168.* value is ignored.
                if str(interface.ip).startswith(configured):
                    network = interface.network
        return self._remember_hotspot({
            "address": str(interface.ip),
            "network": network,
            "network_text": str(network),
            "broadcast": str(network.broadcast_address),
        })

    def _remember_hotspot(self, details):
        """Cache display-safe hotspot fields; /status must never call rish."""
        self._infra["hotspot"] = {
            key: details.get(key, "") for key in ("address", "network_text", "broadcast")
        }
        return details

    def _scan_bt(self):
        """Informational: MACs/names seen in the BT manager dump (bonded/known).

        Non-root cannot guarantee live proximity, so this annotates devices; it
        does NOT drive drop detection (Wi-Fi is authoritative for that). Always
        scans when called (the /bt endpoint); the POLL only calls it when the
        bt_watch config is on, to keep drop-detection fast.
        """
        found = {}
        out = self._sh("dumpsys bluetooth_manager 2>/dev/null | grep -iE 'address|name|connect' | head -80")
        for line in out.splitlines():
            for m in _MAC_RE.findall(line):
                mac = m.lower()
                nm = ""
                mnm = re.search(r'name\s*[:=]\s*([^,\]]+)', line, re.I)
                if mnm:
                    nm = mnm.group(1).strip()
                connected = "connect" in line.lower()
                rec = found.setdefault(mac, {"name": nm, "connected": False})
                if nm and not rec["name"]:
                    rec["name"] = nm
                if connected:
                    rec["connected"] = True
        return found

    def _ipv4_map(self):
        """{base_iface -> 'a.b.c.d/n'} for every interface holding an IPv4.

        Parses the FULL `ip addr` table (toybox `ip` rejects the `-4` flag and
        mishandles per-interface name filters, so we read all and slice here).
        """
        out = ""
        for attempt in range(3):
            out = self._sh("ip addr show 2>/dev/null")
            if out.strip() or attempt == 2:
                break
            time.sleep(0.2)
        result = {}
        cur = None
        for line in out.splitlines():
            m = re.match(r'\d+:\s*(\S+?):', line)
            if m:
                cur = m.group(1).split('@')[0]   # 'rmnet_data1@rmnet_ipa0' -> 'rmnet_data1'
            m2 = re.search(r'\binet\s+(\d+\.\d+\.\d+\.\d+\S*)', line)
            if m2 and cur:
                result[cur] = m2.group(1)
        return result

    def _ap_up(self):
        """Whether the hotspot LAN interface currently carries an IPv4."""
        return self._cfg("ap_iface") in self._ipv4_map()

    def _internet_iface(self):
        """Which mobile-data interface currently carries an IPv4 (the internet)."""
        for name, addr in self._ipv4_map().items():
            if name.startswith("rmnet"):
                return {"iface": name, "addr": addr}
        return {"iface": "", "addr": ""}

    def _read_radio(self):
        """Read radio/data state without changing the modem or preferred RAT.

        The exact fields exposed by ``dumpsys telephony.registry`` vary across
        Android/HyperOS builds. Missing fields deliberately stay ``None`` or
        empty instead of being guessed, so this is useful evidence rather than
        a false diagnosis.
        """
        def prop(command):
            value = self._sh(command).strip()
            lines = value.splitlines()
            return lines[0].strip() if len(lines) == 1 and len(lines[0]) <= 64 else ""

        radio = {
            "available": True,
            "network_type": prop("getprop gsm.network.type 2>/dev/null"),
            "data_network_type": prop("getprop gsm.data.network.type 2>/dev/null"),
            "operator": prop("getprop gsm.operator.alpha 2>/dev/null"),
            "data_reg_state": "",
            "data_registered": None,
            "lte_rssi": None,
            "lte_rsrp": None,
            "lte_rsrq": None,
            "lte_rssnr": None,
            "nr_available": None,
            "endc_available": None,
        }
        registry = self._sh("dumpsys telephony.registry 2>/dev/null")

        reg = re.search(r"\bmDataRegState\s*=\s*(-?\d+)(?:\s*\(([^)]+)\))?", registry, re.I)
        if reg:
            state_number = int(reg.group(1))
            state_name = (reg.group(2) or {
                0: "IN_SERVICE", 1: "OUT_OF_SERVICE", 2: "EMERGENCY_ONLY",
                3: "POWER_OFF", 4: "UNKNOWN",
            }.get(state_number, str(state_number))).strip()
            radio["data_reg_state"] = state_name
            radio["data_registered"] = state_number == 0 or state_name.upper() in {"IN_SERVICE", "HOME"}

        for key, pattern in {
            "lte_rssi": r"CellSignalStrengthLte:.*?\brssi\s*=\s*(-?\d+)",
            "lte_rsrp": r"CellSignalStrengthLte:.*?\brsrp\s*=\s*(-?\d+)",
            "lte_rsrq": r"CellSignalStrengthLte:.*?\brsrq\s*=\s*(-?\d+)",
            "lte_rssnr": r"CellSignalStrengthLte:.*?\brssnr\s*=\s*(-?\d+)",
        }.items():
            match = re.search(pattern, registry, re.I)
            if match:
                try:
                    radio[key] = int(match.group(1))
                except (TypeError, ValueError):
                    pass

        for key, field in (("nr_available", "isNrAvailable"), ("endc_available", "isEnDcAvailable")):
            match = re.search(rf"\b{field}\s*[:=]\s*(true|false)", registry, re.I)
            if match:
                radio[key] = match.group(1).lower() == "true"
        return radio

    def _read_tethering(self):
        """Read tethering/BPF state; never starts, stops or reconfigures tethering."""
        dump = self._sh("dumpsys tethering 2>/dev/null")
        iface = str(self._cfg("ap_iface") or "wlan1")
        if not dump.strip() or not re.search(r"tether", dump, re.I):
            return {"available": False, "active": None, "bpf_enabled": None,
                    "hardware_offload": None, "conntrack_error_count": None,
                    "conntrack_error_codes": [], "reason": "backend_unavailable_or_unrecognized"}
        active = bool(re.search(rf"\b{re.escape(iface)}\s*-\s*TetheredState\b", dump, re.I))
        if not active:
            active = bool(re.search(rf"\btethered[^\n]*\b{re.escape(iface)}\b", dump, re.I))

        error_lines = [
            line for line in dump.splitlines()
            if re.search(r"conntrack|netlink", line, re.I)
            and re.search(r"\b(?:ENOENT|ESRCH|EPERM|EACCES|EINVAL)\b", line, re.I)
        ]
        codes = re.findall(r"\b(?:ENOENT|ESRCH|EPERM|EACCES|EINVAL)\b", "\n".join(error_lines), re.I)
        bpf = re.search(r"\bmIsBpfEnabled\s*[:=]\s*(true|false)", dump, re.I)
        if not bpf:
            bpf = re.search(r"\bbpf[^\n]*(?:enabled|enable)\s*[:=]\s*(true|false)", dump, re.I)
        if re.search(r"offload hal[s]? started", dump, re.I):
            hardware_offload = True
        elif re.search(r"(?:hardware|hal).*offload[^\n]*(?:disabled|false)", dump, re.I):
            hardware_offload = False
        else:
            hardware_offload = None
        return {
            "available": True,
            "active": active,
            "bpf_enabled": (bpf.group(1).lower() == "true") if bpf else None,
            "hardware_offload": hardware_offload,
            "conntrack_error_count": len(error_lines),
            "conntrack_error_codes": sorted({code.upper() for code in codes}),
        }

    # ── the poll: read, diff, emit (no radio writes) ─────────────────
    def _poll(self):
        try:
            backend = self._backend_info()
            if not backend["connected"]:
                # Do not scan clients or emit drops from stale rish output.
                self._infra = {
                    "hotspot": {"address": "", "network_text": "", "broadcast": ""},
                    "hotspot_up": None,
                    "internet": {"iface": "", "addr": ""},
                    "backend": backend,
                    "radio": {"available": False, "reason": "backend_unavailable"},
                    "tethering": {"available": False, "active": None, "reason": "backend_unavailable"},
                }
                self._check_watchdogs()
                self._save_state()
                return
            stale = int(self._cfg("stale_after"))
            now = self._now()
            # One interface snapshot keeps hotspot_up, mobile upstream and
            # client-subnet parsing consistent when other plugins use rish too.
            netmap = self._ipv4_map()
            hotspot = self._hotspot_details(netmap)
            wifi = self._scan_wifi_clients(hotspot)
            bt = self._scan_bt() if self._cfg("bt_watch") else {}

            # record sightings
            for mac, info in wifi.items():
                dev = self._devices.get(mac)
                if dev is None:
                    kind = info.get("mac_type", self._mac_kind(mac))
                    label = "privacy" if kind == "random" else "device"
                    # Only the dict-size-changing insertion is locked; the rest of
                    # the poll (shell diffs) stays outside the lock so it can't stall.
                    with self._lock:
                        dev = self._devices[mac] = {
                            "mac": mac,
                            "name": f"{label}-{mac.replace(':', '')[-4:]}",
                            "type": "unknown",
                            "mac_type": kind,
                            "first_seen": now,
                            "last_seen_wifi": None,
                            "last_seen_bt": None,
                            "ip": "",
                            "present": False,
                            "bt_present": False,
                        }
                dev["last_seen_wifi"] = now
                dev.setdefault("mac_type", info.get("mac_type", self._mac_kind(mac)))
                if info.get("ip"):
                    dev["ip"] = info["ip"]
            for mac in bt:
                dev = self._devices.get(mac)
                if dev is not None:
                    dev["last_seen_bt"] = now

            # diff presence & emit events (Wi-Fi authoritative)
            for mac, dev in self._devices.items():
                wifi_fresh = self._fresh(dev.get("last_seen_wifi"), stale)
                bt_fresh = bool(bt.get(mac, {}).get("connected")) or self._fresh(dev.get("last_seen_bt"), stale)
                dev["bt_present"] = bt_fresh
                was = dev.get("present", False)
                if wifi_fresh and not was:
                    self._emit(dev, "joined", f"{dev['name']} on hotspot ({dev.get('ip','')})")
                    self._trigger(self._cfg("on_join_cmd"), dev)
                elif not wifi_fresh and was:
                    if bt_fresh:
                        self._emit(dev, "dropped_wifi_bt_near", f"{dev['name']} left Wi-Fi (still near via BT)")
                    else:
                        self._emit(dev, "dropped", f"{dev['name']} left the hotspot")
                    self._trigger(self._cfg("on_drop_cmd"), dev)
                dev["present"] = wifi_fresh

            # infrastructure health: alert on hotspot/internet state changes
            hs_up = self._cfg("ap_iface") in netmap
            inet = next((n for n in netmap if n.startswith("rmnet")), "")
            radio = self._read_radio() if self._cfg("radio_watch") else {}
            tethering = self._read_tethering() if self._cfg("tethering_watch") else {}
            if tethering:
                tethering["upstream_iface"] = inet
            self._check_infra(hs_up, inet, radio, tethering)
            # cache for /status so the hot path never touches rish (no pileup)
            self._infra = {
                "hotspot": dict(self._infra.get("hotspot", {
                    "address": "", "network_text": "", "broadcast": ""
                })),
                "hotspot_up": hs_up,
                "internet": {"iface": inet, "addr": netmap.get(inet, "")},
                "backend": backend,
                "radio": radio,
                "tethering": tethering,
            }

            # battery health (cheap single dumpsys) + overheat/low alerts
            self._check_battery(self._read_battery())
            # self-heal loop liveness (native pgrep -- see _check_watchdogs)
            self._check_watchdogs()

            self._save_state()
        except Exception as e:
            self.logger.error(f"connsup poll error: {e}")

    def _check_infra(self, hs_up, inet_iface, radio=None, tethering=None):
        """Emit events for real connectivity transitions, never signal noise.
        First poll (prev is None) never alerts -- only real transitions do."""
        radio = radio or {}
        tethering = tethering or {}
        prev = self._net_state
        if prev.get("hotspot_up") is not None and hs_up != prev["hotspot_up"]:
            self._emit_sys("hotspot_up" if hs_up else "hotspot_down",
                           "Hotspot interface UP" if hs_up else "HOTSPOT DOWN -- clients lose the LAN")
        if prev.get("internet") is not None and bool(inet_iface) != bool(prev["internet"]):
            self._emit_sys("internet_up" if inet_iface else "internet_down",
                           f"Internet restored via {inet_iface}" if inet_iface else "INTERNET DOWN -- no mobile-data IPv4")
        if self._cfg("radio_watch"):
            radio_type = radio.get("network_type") or radio.get("data_network_type") or ""
            if prev.get("radio_type") and radio_type and radio_type != prev["radio_type"]:
                self._emit_sys("radio_changed", f"Radio changed {prev['radio_type']} -> {radio_type}")
            registered = radio.get("data_registered")
            if prev.get("data_registered") is not None and registered is not None and registered != prev["data_registered"]:
                self._emit_sys("data_registered" if registered else "data_unregistered",
                               "Mobile data registered" if registered else "Mobile data not registered")
        else:
            radio_type, registered = "", None
        tether_active = tethering.get("active") if self._cfg("tethering_watch") else None
        if prev.get("tethering_active") is not None and tether_active is not None and tether_active != prev["tethering_active"]:
            self._emit_sys("tethering_up" if tether_active else "tethering_down",
                           "Tethering interface active" if tether_active else "Tethering interface inactive")
        self._net_state = {"hotspot_up": hs_up, "internet": inet_iface,
                           "radio_type": radio_type, "data_registered": registered,
                           "tethering_active": tether_active}

    def _read_battery(self):
        """Cheap single `dumpsys battery` read -> {level, temp_c, status, charging}."""
        h = {"level": None, "temp_c": None, "status": "", "charging": False}
        for line in self._sh("dumpsys battery 2>/dev/null").splitlines():
            s = line.strip()
            if s.startswith("level:"):
                try: h["level"] = int(s.split(":", 1)[1])
                except Exception: pass
            elif s.startswith("temperature:"):
                try: h["temp_c"] = round(int(s.split(":", 1)[1]) / 10.0, 1)
                except Exception: pass
            elif s.startswith("status:"):
                h["status"] = self._BATT_STATUS.get(s.split(":", 1)[1].strip(), s.split(":", 1)[1].strip())
            elif s.endswith("powered: true"):
                h["charging"] = True
        return h

    def _check_battery(self, h):
        """Alert once when the phone crosses into overheating / low-battery."""
        hot_th = self._cfg("batt_hot_c")
        low_th = self._cfg("batt_low_pct")
        t, lvl = h.get("temp_c"), h.get("level")
        now_hot = bool(t is not None and t >= hot_th)
        now_low = bool(lvl is not None and lvl <= low_th and not h.get("charging"))
        if now_hot and not self._health.get("hot"):
            self._emit_sys("battery_hot", f"Battery {t}C -- overheating (>= {hot_th}C)")
        if now_low and not self._health.get("low"):
            self._emit_sys("battery_low", f"Battery {lvl}% -- low (<= {low_th}%), not charging")
        h["hot"], h["low"] = now_hot, now_low
        self._health = h

    _WATCHDOGS = {"shizuku": "shizuku_watchdog.sh", "server": "server_supervisor.sh", "hotspot": "hotspot_watch.sh"}

    def _check_watchdogs(self):
        """Native pgrep of the on-device self-heal loops. The server runs under the
        Termux uid (same as the loops), so a native pgrep SEES them -- rish/_shell
        (shell uid 2000) would NOT. Cached for /status; never on the hot path.
        Also emits an event on any transition (down / revived / restarted) so a live
        show has an audit trail of every self-heal in the /router feed + iPhone."""
        prev = self._watchdogs
        out = {}
        for key, pat in self._WATCHDOGS.items():
            try:
                r = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=5)
                first = (r.stdout or "").strip().split("\n")[0].strip()
                out[key] = int(first) if first.isdigit() else 0
            except Exception:
                out[key] = 0
        # transitions (skip first run when prev is empty -> just baseline, no alarm)
        if prev:
            for k in out:
                old, new = prev.get(k, 0), out[k]
                if old and not new:
                    self._emit_sys("watchdog_down", f"Watchdog {k} CAIDO (era pid {old})")
                elif not old and new:
                    self._emit_sys("watchdog_up", f"Watchdog {k} revivido (pid {new})")
                elif old and new and old != new:
                    self._emit_sys("watchdog_restart", f"Watchdog {k} reiniciado ({old} -> {new})")
        self._watchdogs = out

    def _emit_sys(self, event, detail):
        """Log a network (non-device) event."""
        ev = {"ts": self._now(), "mac": "", "name": "network", "event": event, "detail": detail}
        self._events.append(ev)
        self._events = self._events[-500:]
        self.logger.info(f"[connsup] {event}: {detail}")
        if self._cfg("notify"):
            self._notify("Network", detail)

    def _emit(self, dev, event, detail):
        ev = {"ts": self._now(), "mac": dev["mac"], "name": dev["name"], "event": event, "detail": detail}
        self._events.append(ev)
        self._events = self._events[-500:]
        self.logger.info(f"[connsup] {event}: {detail}")
        if self._cfg("notify"):
            self._notify("Connectivity", detail)

    def _notify(self, title, body):
        """Post a best-effort notification without blocking the network poll."""
        if not self._notify_lock.acquire(blocking=False):
            return  # one slow Binder notification must not queue a storm
        t = title.replace("'", "")[:40]
        b = body.replace("'", "")[:180]

        def _send():
            try:
                # Do not use XiaomiController._shell here: it serializes on the
                # same rish lock as the telemetry sweep. A notification is
                # optional and must never delay radio/tethering evidence.
                if getattr(self.controller, "backend", "") != "rish":
                    return
                command = f"cmd notification post -S bigtext -t '{t}' xio_connsup '{b}'"
                subprocess.run(
                    ["sh", self.controller.rish, "-c", command],
                    cwd="/sdcard",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
            except Exception:
                pass  # notification is a bonus, never critical
            finally:
                self._notify_lock.release()

        threading.Thread(target=_send, daemon=True, name="connsup-notify").start()

    def _trigger(self, cmd, dev):
        """Run a user-configured shell trigger -- only when explicitly enabled."""
        if not cmd or not self._cfg("triggers_enabled"):
            return
        expanded = cmd.replace("{mac}", dev["mac"]).replace("{name}", dev["name"]).replace("{ip}", dev.get("ip", ""))
        self.logger.info(f"[connsup] trigger: {expanded}")
        self._sh(expanded, timeout=20)

    # ── API handlers ─────────────────────────────────────────────────
    def _api_status(self):
        from flask import jsonify
        hotspot = self._infra.get("hotspot", {})
        with self._lock:
            devs = list(self._devices.values())
            tracked = len(self._devices)
        present = [d for d in devs if d.get("present")]
        return jsonify({
            "hotspot_iface": self._cfg("ap_iface"),
            "hotspot_up": self._infra["hotspot_up"],       # cached from last poll -- no rish, no lock
            "hotspot_address": hotspot.get("address", ""),
            "hotspot_network": hotspot.get("network_text", ""),
            "hotspot_broadcast": hotspot.get("broadcast", ""),
            "internet": self._infra["internet"],
            "backend": self._infra.get("backend", {}),
            "radio": self._infra.get("radio", {}),
            "tethering": self._infra.get("tethering", {}),
            "health": {k: self._health.get(k) for k in ("level", "temp_c", "status", "charging")},
            "watchdogs": self._watchdogs,
            "clients_present": len(present),
            "present": [{"name": d["name"], "type": d["type"], "mac": d["mac"], "mac_type": d.get("mac_type", ""), "ip": d.get("ip", ""), "bt_present": d.get("bt_present", False)} for d in present],
            "tracked_total": tracked,
            "poll_interval": int(self._cfg("poll_interval")),
        })

    def _api_ui(self):
        """GET /ui -- self-contained live operator console (open on a phone/tablet
        joined to the hotspot). Auto-refreshes from the plugin's own JSON via
        relative fetch, so it works regardless of host/IP."""
        from flask import Response
        return Response(_DASHBOARD_HTML, mimetype="text/html")

    def _api_clients(self):
        from flask import jsonify
        return jsonify(self._scan_wifi_clients())

    def _api_watch(self):
        from flask import jsonify
        with self._lock:
            devs = list(self._devices.values())
        return jsonify(devs)

    def _api_events(self):
        from flask import request, jsonify
        limit = int(request.args.get("limit", 50))
        return jsonify(self._events[-limit:])

    def _api_bt(self):
        from flask import jsonify
        return jsonify({
            "note": "bonded/known devices from dumpsys; non-root cannot guarantee live proximity",
            "devices": self._scan_bt(),
        })

    def _api_label(self):
        """POST {mac, name, type} -- name a device so drop events read clearly."""
        from flask import request, jsonify
        data = request.get_json(force=True) or {}
        mac = (data.get("mac") or "").lower().strip()
        if not _MAC_RE.fullmatch(mac):
            return jsonify({"ok": False, "error": "valid 'mac' (aa:bb:cc:dd:ee:ff) required"}), 400
        dev = self._devices.get(mac) or {
            "mac": mac, "first_seen": self._now(), "last_seen_wifi": None,
            "last_seen_bt": None, "ip": "", "present": False, "bt_present": False,
        }
        dev["name"] = data.get("name", dev.get("name", mac))
        dev["type"] = data.get("type", dev.get("type", "device"))
        with self._lock:
            self._devices[mac] = dev
        self._save_state()
        return jsonify({"ok": True, "device": dev})

    def _api_get_config(self):
        from flask import jsonify
        merged = dict(self.DEFAULTS)
        merged.update(self._config)
        return jsonify(merged)

    def _api_set_config(self):
        from flask import request, jsonify
        data = request.get_json(force=True) or {}
        for k, v in data.items():
            if k in self.DEFAULTS:
                self.set_config(k, v)
        return jsonify({"ok": True, "config": {**self.DEFAULTS, **self._config}})

    def _api_reassert(self):
        """GUARDED. Diagnose the hotspot and BEST-EFFORT re-enable it if down.

        Touches the only-internet radio, so server.py refuses this route with
        HTTP 423 unless confirmed. Non-root cannot reliably restart a user's
        configured tether, so every attempt's raw result is reported honestly --
        no fake success.
        """
        from flask import jsonify
        up = self._ap_up()
        result = {"hotspot_up_before": up, "attempts": [], "note": ""}
        if up:
            result["note"] = "Hotspot interface already has an IPv4; no action taken."
            return jsonify(result)
        # best-effort, honestly reported (may fail without root on HyperOS)
        for cmd in ("svc wifi enable", "cmd wifi start-softap 2>&1", "cmd -w wifi force-country-code disabled 2>&1"):
            out = self._sh(cmd, timeout=15)
            result["attempts"].append({"cmd": cmd, "output": out[:300]})
        result["hotspot_up_after"] = self._ap_up()
        result["note"] = ("Best-effort only. If still down, re-enable the hotspot manually in "
                          "Settings -> Portable hotspot; non-root HyperOS blocks reliable programmatic restart.")
        return jsonify(result)


plugin_class = ConnectivitySupervisorPlugin

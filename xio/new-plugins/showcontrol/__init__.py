"""
showcontrol -- OSC + Art-Net + sACN (E1.31) network show control from the phone.

Turns the on-device xio server into a network show-control node: it emits OSC
messages (Resolume/QLab/consoles), Art-Net DMX and sACN/E1.31 DMX over the hotspot
LAN. Pure stdlib (socket + struct): no pip on Termux, and no shell is ever invoked
-- zero command-injection surface. Packet builders live in protocols.py and are
unit-tested off-device (test_protocols.py).

v1 is SEND-only (the core need to drive lights/VJ from the phone). Receiving OSC to
trigger xio actions is a deliberate v2 (needs a guarded background listener).
Physical DMX512 out (USB-DMX dongle) is out of scope on non-root Android -- drive a
network Art-Net/sACN node instead.

v1.1 adds the CUE ENGINE (cueengine.py): a cue list with timed crossfades and
GO / STOP / RELEASE transport -- the `orq` grow point of cultura/xio-concept.html.
The 30 Hz tick thread only runs while a show is live (battery discipline) and
stops itself once RELEASE lands at black.
"""

import functools
import hmac
import os
import socket
import threading
import time

from plugins.base import PluginBase

from .auth import check_token, new_token, valid_token_format
from .automap import plan as automap_plan, solve as automap_solve
from .cueengine import CueEngine, CueError
from .discovery import discover as artnet_discover
from .fabric import Fabric, FabricError
from .obs import Telemetry, health as obs_health
from .oscin import OscParseError, map_action, parse_packet
from .panel import PANEL_HTML
from .timeline import Timeline, TimelineError
from .protocols import (
    ARTNET_PORT,
    SACN_PORT,
    build_artnet_dmx,
    build_magic_packet,
    build_osc_message,
    build_sacn_dmx,
    sacn_multicast_ip,
    valid_host,
)

TICK_HZ = 30.0            # cue engine: smooth fades need a fast tick
FABRIC_KEEPALIVE_HZ = 2.0  # fabric has no fades: only re-emit DMX inside the 1s Art-Net timeout


# ── xio: env-based token gate (whole-server, public-hotspot shows) ─────────
# The xio server binds 0.0.0.0 on the show hotspot: ANY client joined to it
# can hit every showcontrol route, GET included. This is separate from the
# muros `_guard`/`_token` wall below (a config-persisted secret, POST-only,
# rotated via /auth/set): this one is a single operator-set env var that --
# when present -- locks EVERY route behind one shared header, reads included
# (/status, /obs, /panel...). Off by default so nothing changes for existing
# trusted-crew setups. Read at REQUEST time (not import time) so an operator
# can `export XIO_SHOWCONTROL_TOKEN=...` and only restart the server, and so
# tests can monkeypatch os.environ without reimporting this module.
def _xio_token_required(handler):
    """Wrap a Flask view: if XIO_SHOWCONTROL_TOKEN is set (non-empty), the
    request must carry a matching X-Xio-Token header, compared in constant
    time (hmac.compare_digest). Unset env -> pass-through, unchanged from
    before this gate existed."""
    @functools.wraps(handler)
    def wrapper(*args, **kwargs):
        expected = os.environ.get("XIO_SHOWCONTROL_TOKEN", "")
        if expected:
            from flask import request, jsonify
            presented = request.headers.get("X-Xio-Token", "")
            if not hmac.compare_digest(expected.encode("utf-8"), presented.encode("utf-8")):
                return jsonify({"error": "token requerido o invalido"}), 401
        return handler(*args, **kwargs)
    return wrapper


class ShowControlPlugin(PluginBase):
    """OSC / Art-Net / sACN sender exposed over the xio HTTP API."""

    plugin_id = "showcontrol"
    name = "Show Control"
    version = "1.8.0"
    description = "Send OSC, Art-Net and sACN/E1.31 DMX from the phone over the LAN"
    author = "Cauce"
    icon = "network"
    category = "network"
    permissions = ["network"]

    def register_route(self, rule, view_func, methods=None, **options):
        """Every showcontrol route (GET and POST alike) passes through the
        optional XIO_SHOWCONTROL_TOKEN gate before reaching PluginBase's
        registration -- applied once here so on_load's ~25 register_route()
        calls don't each need wrapping by hand, and so xio/new/server.py and
        every other plugin stay untouched."""
        return super().register_route(rule, _xio_token_required(view_func),
                                       methods=methods, **options)

    def on_load(self):
        self._sent = {"osc": 0, "artnet": 0, "sacn": 0}
        self._last_error = None
        self._loaded_at = time.monotonic()
        self._telemetry = Telemetry()
        self._engine = CueEngine()
        self._cue_output = None
        self._seq = {}                      # {universe: last sequence 1..255}
        self._seq_lock = threading.Lock()   # cue + fabric + Flask threads all sequence
        self._cue_stop = threading.Event()
        self._cue_thread = None
        self._cue_thread_lock = threading.Lock()
        self._timeline = Timeline()
        # muros: optional show token -- once set, every mutating POST needs it
        self._token = self.get_config("show_token") or None
        g = self._guard
        self.register_route("/status", self._api_status, methods=["GET"])
        self.register_route("/osc", g(self._api_osc), methods=["POST"])
        self.register_route("/artnet", g(self._api_artnet), methods=["POST"])
        self.register_route("/sacn", g(self._api_sacn), methods=["POST"])
        self.register_route("/cues", g(self._api_cues), methods=["GET", "POST"])
        self.register_route("/cue/go", g(self._api_cue_go), methods=["POST"])
        self.register_route("/cue/stop", g(self._api_cue_stop), methods=["POST"])
        self.register_route("/cue/release", g(self._api_cue_release), methods=["POST"])
        self.register_route("/cue/state", self._api_cue_state, methods=["GET"])
        self.register_route("/timeline", g(self._api_timeline), methods=["GET", "POST"])
        self.register_route("/timeline/play", g(self._api_timeline_play), methods=["POST"])
        self.register_route("/timeline/pause", g(self._api_timeline_pause), methods=["POST"])
        self.register_route("/timeline/locate", g(self._api_timeline_locate), methods=["POST"])
        self.register_route("/timeline/state", self._api_timeline_state, methods=["GET"])
        self.register_route("/panel", self._api_panel, methods=["GET"])
        self.register_route("/wol", g(self._api_wol), methods=["POST"])
        self._fabric = Fabric()
        self._fabric_output = None
        self._fabric_stop = threading.Event()
        self._fabric_thread = None
        self._fabric_thread_lock = threading.Lock()
        self.register_route("/fabric", g(self._api_fabric), methods=["GET", "POST"])
        self.register_route("/fabric/set", g(self._api_fabric_set), methods=["POST"])
        self.register_route("/fabric/state", self._api_fabric_state, methods=["GET"])
        self.register_route("/discover", g(self._api_discover), methods=["GET", "POST"])
        self.register_route("/automap/plan", g(self._api_automap_plan), methods=["POST"])
        self.register_route("/automap/solve", g(self._api_automap_solve), methods=["POST"])
        self.register_route("/obs", self._api_obs, methods=["GET"])
        # /auth/set is NOT wrapped: it does its own TOFU current-token check
        self.register_route("/auth", self._api_auth, methods=["GET"])
        self.register_route("/auth/set", self._api_auth_set, methods=["POST"])
        # oscin: opt-in OSC listener (orq bidirectional); start/stop behind the token
        self._oscin_sock = None
        self._oscin_thread = None
        self._oscin_stop = threading.Event()
        self._oscin_lock = threading.Lock()
        self._oscin_allow = None            # optional source-IP allowlist
        self._oscin_port = None
        self._oscin_wanted = False
        self._oscin_stats = {"received": 0, "acted": 0, "ignored": 0, "denied": 0,
                             "last_address": None}
        self.register_route("/oscin", g(self._api_oscin), methods=["GET", "POST"])
        self.register_route("/oscin/stop", g(self._api_oscin_stop), methods=["POST"])
        # Re-arm a persisted show (list only -- never auto-runs anything).
        saved = self.get_config("cuelist")
        if saved:
            try:
                self._engine.load(saved)
                self._cue_output = self._valid_output(self.get_config("cue_output") or {})
            except (CueError, ValueError) as e:
                self.logger.warning("showcontrol: persisted cue list ignored: %s" % e)
        self.logger.info("%s loaded (OSC/Art-Net/sACN + cue engine)" % self.name)

    def on_unload(self):
        self._cue_stop.set()
        self._fabric_stop.set()
        self._oscin_shutdown()

    # last_error is a property so every existing assignment site also stamps a
    # timestamp -- /obs then ages errors out of the health grade instead of
    # reporting "error" forever after one transient hiccup during a show.
    ERROR_FRESH_S = 60.0

    @property
    def _last_error(self):
        return self.__last_error

    @_last_error.setter
    def _last_error(self, value):
        self.__last_error = value
        self.__last_error_t = time.monotonic()

    def _last_error_age(self):
        """Seconds since the last error was recorded, or None if there is none."""
        if self.__last_error is None:
            return None
        return time.monotonic() - self.__last_error_t

    # ── muros: show token gate ────────────────────────────────────────────
    def _presented_token(self, request):
        """Token from header (preferred), JSON body, or query param."""
        t = request.headers.get("X-Show-Token")
        if t is not None:
            return t
        d = request.get_json(force=True, silent=True) or {}
        if isinstance(d, dict) and "token" in d:
            return d.get("token")
        return request.args.get("token")

    def _guard(self, handler):
        """Require the show token on mutating (POST) requests when one is set.
        GETs pass through -- read-only state stays open for panels/telemetry."""
        @functools.wraps(handler)
        def wrapper(*a, **kw):
            from flask import request, jsonify
            if request.method == "POST" and self._token:
                if not check_token(self._token, self._presented_token(request)):
                    return jsonify({"ok": False,
                                    "error": "show token required (X-Show-Token header)"}), 401
            return handler(*a, **kw)
        return wrapper

    def _api_auth(self):
        from flask import jsonify
        return jsonify({"ok": True, "protected": bool(self._token)})

    def _api_auth_set(self):
        """TOFU: free while no token exists; afterwards, rotating or clearing
        requires the current token ('current' field or X-Show-Token header)."""
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        if self._token:
            current = request.headers.get("X-Show-Token", d.get("current"))
            if not check_token(self._token, current):
                return jsonify({"ok": False, "error": "current token required"}), 401
        if d.get("generate"):
            token = new_token()
        else:
            token = d.get("token")
            if token in ("", None):                     # explicit clear -> open mode
                self._token = None
                self.set_config("show_token", "")
                return jsonify({"ok": True, "protected": False})
            if not valid_token_format(token):
                return jsonify({"ok": False,
                                "error": "token must be 8..128 printable ASCII chars, no spaces"}), 400
        self._token = token
        self.set_config("show_token", token)
        # the generated token is returned ONCE, here -- it is never readable again
        out = {"ok": True, "protected": True}
        if d.get("generate"):
            out["token"] = token
        return jsonify(out)

    # ── sender ────────────────────────────────────────────────────────────
    def _send_udp(self, packet, host, port, multicast=False):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if multicast:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 8)
            sock.sendto(packet, (host, port))
        finally:
            sock.close()

    # ── API ───────────────────────────────────────────────────────────────
    def _api_status(self):
        from flask import jsonify
        return jsonify({
            "name": self.name,
            "version": self.version,
            "protocols": ["osc", "artnet", "sacn", "cues"],
            "sent": self._sent,
            "last_error": self._last_error,
            "artnet_port": ARTNET_PORT,
            "sacn_port": SACN_PORT,
            "cue": self._engine.status(),
        })

    def _api_osc(self):
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        host, port = d.get("host"), d.get("port", 9000)
        address, args = d.get("address", ""), d.get("args", [])
        if not valid_host(host):
            return jsonify({"ok": False, "error": "invalid host (need IPv4)"}), 400
        if not isinstance(port, int) or not (1 <= port <= 65535):
            return jsonify({"ok": False, "error": "invalid port"}), 400
        if not isinstance(args, list):
            return jsonify({"ok": False, "error": "args must be a list"}), 400
        try:
            pkt = build_osc_message(address, args)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        try:
            self._send_udp(pkt, host, port)
        except OSError as e:
            self._last_error = "osc: %s" % e
            return jsonify({"ok": False, "error": str(e)}), 502
        self._sent["osc"] += 1
        return jsonify({"ok": True, "sent_bytes": len(pkt), "to": "%s:%d" % (host, port)})

    def _api_artnet(self):
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        host, port = d.get("host"), d.get("port", ARTNET_PORT)
        universe = d.get("universe", 0)
        data = d.get("data", d.get("channels"))
        if not valid_host(host):
            return jsonify({"ok": False, "error": "invalid host (need IPv4)"}), 400
        if not isinstance(port, int) or not (1 <= port <= 65535):
            return jsonify({"ok": False, "error": "invalid port"}), 400
        if data is None:
            return jsonify({"ok": False, "error": "missing 'data' (list) or 'channels' (object)"}), 400
        try:
            pkt = build_artnet_dmx(int(universe), data)
        except (ValueError, TypeError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        try:
            self._send_udp(pkt, host, port)
        except OSError as e:
            self._last_error = "artnet: %s" % e
            return jsonify({"ok": False, "error": str(e)}), 502
        self._sent["artnet"] += 1
        return jsonify({"ok": True, "sent_bytes": len(pkt), "universe": int(universe),
                        "to": "%s:%d" % (host, port)})

    def _api_sacn(self):
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        universe = d.get("universe")
        data = d.get("data", d.get("channels"))
        host = d.get("host")            # optional: unicast; default is multicast
        priority, source = d.get("priority", 100), d.get("source", "xio")
        if universe is None or data is None:
            return jsonify({"ok": False, "error": "missing 'universe' or 'data'"}), 400
        if host is not None and not valid_host(host):
            return jsonify({"ok": False, "error": "invalid host (need IPv4)"}), 400
        try:
            pkt = build_sacn_dmx(int(universe), data, source_name=str(source), priority=int(priority))
        except (ValueError, TypeError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        target = host or sacn_multicast_ip(int(universe))
        try:
            self._send_udp(pkt, target, SACN_PORT, multicast=(host is None))
        except OSError as e:
            self._last_error = "sacn: %s" % e
            return jsonify({"ok": False, "error": str(e)}), 502
        self._sent["sacn"] += 1
        return jsonify({"ok": True, "sent_bytes": len(pkt), "universe": int(universe),
                        "to": "%s:%d" % (target, SACN_PORT),
                        "mode": "unicast" if host else "multicast"})

    # ── cue engine: output config ─────────────────────────────────────────
    def _valid_output(self, d):
        """Validate {protocol, host, port, osc_host, osc_port}; raise ValueError."""
        if not isinstance(d, dict):
            raise ValueError("output must be an object")
        proto = d.get("protocol", "artnet")
        if proto not in ("artnet", "sacn"):
            raise ValueError("output.protocol must be 'artnet' or 'sacn'")
        host = d.get("host")
        if proto == "artnet" and not valid_host(host):
            raise ValueError("output.host (IPv4) is required for artnet")
        if proto == "sacn" and host is not None and not valid_host(host):
            raise ValueError("output.host must be IPv4 (omit for sACN multicast)")
        port = d.get("port", ARTNET_PORT if proto == "artnet" else SACN_PORT)
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError("output.port invalid")
        osc_host, osc_port = d.get("osc_host"), d.get("osc_port", 9000)
        if osc_host is not None and not valid_host(osc_host):
            raise ValueError("output.osc_host must be IPv4")
        if not isinstance(osc_port, int) or not (1 <= osc_port <= 65535):
            raise ValueError("output.osc_port invalid")
        return {"protocol": proto, "host": host, "port": port,
                "osc_host": osc_host, "osc_port": osc_port}

    # ── cue engine: emitter + tick thread ─────────────────────────────────
    def _next_seq(self, universe):
        with self._seq_lock:
            s = self._seq.get(universe, 0) + 1
            if s > 255:
                s = 1
            self._seq[universe] = s
            return s

    def _emit_events(self, events):
        out = self._cue_output
        for ev in events:
            try:
                if ev[0] == "osc":
                    if not out or not out.get("osc_host"):
                        continue                        # no OSC target configured
                    pkt = build_osc_message(ev[1], ev[2])
                    self._send_udp(pkt, out["osc_host"], out["osc_port"])
                    self._sent["osc"] += 1
                elif ev[0] == "dmx":
                    if not out:
                        continue
                    universe, levels = ev[1], ev[2]
                    seq = self._next_seq(universe)
                    if out["protocol"] == "artnet":
                        pkt = build_artnet_dmx(universe, levels, sequence=seq)
                        self._send_udp(pkt, out["host"], out["port"])
                        self._sent["artnet"] += 1
                    else:
                        pkt = build_sacn_dmx(universe, levels, sequence=seq)
                        target = out["host"] or sacn_multicast_ip(universe)
                        self._send_udp(pkt, target, out["port"],
                                       multicast=(out["host"] is None))
                        self._sent["sacn"] += 1
            except (ValueError, OSError) as e:
                self._last_error = "cue emit: %s" % e

    def _cue_loop(self):
        while not self._cue_stop.is_set():
            now = time.monotonic()
            try:
                # timeline drives the show: fire any cues that just came due
                for cue in self._timeline.due(now):
                    self._engine.go(now, index=cue)
            except Exception as e:                       # bad index etc. -- log, don't die
                self._last_error = "timeline: %s" % e
            try:
                self._emit_events(self._engine.tick(now))
            except Exception as e:                       # never kill the thread
                self._last_error = "cue tick: %s" % e
            if not self._engine.active and not self._timeline.playing:
                # show over AND timeline stopped -> save battery; recheck under
                # the lock so a GO/play racing this exit can't orphan the thread
                with self._cue_thread_lock:
                    if not self._engine.active and not self._timeline.playing:
                        self._cue_thread = None
                        return
            self._cue_stop.wait(1.0 / TICK_HZ)
        with self._cue_thread_lock:
            self._cue_thread = None

    def _ensure_cue_thread(self):
        with self._cue_thread_lock:
            if self._cue_thread is not None and self._cue_thread.is_alive():
                return
            self._cue_stop.clear()
            t = threading.Thread(target=self._cue_loop, daemon=True,
                                 name="showcontrol-cue")
            self._cue_thread = t
            t.start()

    # ── cue engine: API ───────────────────────────────────────────────────
    def _api_cues(self):
        from flask import request, jsonify
        if request.method == "GET":
            return jsonify({"ok": True,
                            "cues": [c.to_dict() for c in self._engine.cues],
                            "output": self._cue_output,
                            "state": self._engine.status()})
        d = request.get_json(force=True, silent=True) or {}
        try:
            output = self._valid_output(d.get("output") or {})
            count = self._engine.load(d.get("cues"))
        except (CueError, ValueError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        self._cue_output = output
        self.set_config("cuelist", d.get("cues"))
        self.set_config("cue_output", output)
        return jsonify({"ok": True, "loaded": count, "output": output})

    def _api_cue_go(self):
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        index = d.get("index")
        if index is not None and not isinstance(index, int):
            return jsonify({"ok": False, "error": "index must be an integer"}), 400
        if self._cue_output is None:
            return jsonify({"ok": False, "error": "no output configured (POST /cues first)"}), 400
        try:
            label = self._engine.go(time.monotonic(), index)
        except CueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        self._ensure_cue_thread()
        return jsonify({"ok": True, "cue": label, "state": self._engine.status()})

    def _api_cue_stop(self):
        from flask import jsonify
        self._engine.stop(time.monotonic())
        return jsonify({"ok": True, "state": self._engine.status()})

    def _api_cue_release(self):
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        try:
            self._engine.release(time.monotonic(), d.get("fade", 2.0))
        except CueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        self._ensure_cue_thread()                       # ticks the fade-to-black
        return jsonify({"ok": True, "state": self._engine.status()})

    def _api_cue_state(self):
        from flask import jsonify
        return jsonify({"ok": True, "state": self._engine.status(),
                        "output": self._cue_output, "sent": self._sent})

    # ── timecode timeline (orq capstone: the show plays itself) ───────────
    def _api_timeline(self):
        from flask import request, jsonify
        if request.method == "GET":
            return jsonify({"ok": True, "state": self._timeline.status(time.monotonic())})
        d = request.get_json(force=True, silent=True) or {}
        try:
            info = self._timeline.load(d.get("events"))
        except TimelineError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "loaded": info})

    def _api_timeline_play(self):
        from flask import jsonify
        try:
            st = self._timeline.play(time.monotonic())
        except TimelineError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        self._ensure_cue_thread()               # the cue loop advances the timeline
        return jsonify({"ok": True, "state": st})

    def _api_timeline_pause(self):
        from flask import jsonify
        return jsonify({"ok": True, "state": self._timeline.pause(time.monotonic())})

    def _api_timeline_locate(self):
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        try:
            st = self._timeline.locate(d.get("t", 0), now=time.monotonic())
        except TimelineError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "state": st})

    def _api_timeline_state(self):
        from flask import jsonify
        return jsonify({"ok": True, "state": self._timeline.status(time.monotonic())})

    # ── signal fabric (the `fabric` node) ─────────────────────────────────
    def _emit_fabric(self, events):
        out = self._fabric_output
        for ev in events:
            try:
                if ev[0] == "osc":                       # route-local host/port
                    _, host, port, address, args = ev
                    self._send_udp(build_osc_message(address, args), host, port)
                    self._sent["osc"] += 1
                elif ev[0] == "dmx":
                    if not out:
                        continue
                    universe, levels = ev[1], ev[2]
                    seq = self._next_seq(universe)
                    if out["protocol"] == "artnet":
                        self._send_udp(build_artnet_dmx(universe, levels, sequence=seq),
                                       out["host"], out["port"])
                        self._sent["artnet"] += 1
                    else:
                        tgt = out["host"] or sacn_multicast_ip(universe)
                        self._send_udp(build_sacn_dmx(universe, levels, sequence=seq),
                                       tgt, out["port"], multicast=(out["host"] is None))
                        self._sent["sacn"] += 1
            except (ValueError, OSError) as e:
                self._last_error = "fabric emit: %s" % e

    def _fabric_loop(self):
        while not self._fabric_stop.is_set():
            now = time.monotonic()
            try:
                self._emit_fabric(self._fabric.keepalive(now))
            except Exception as e:
                self._last_error = "fabric tick: %s" % e
            if not self._fabric.active:
                with self._fabric_thread_lock:
                    if not self._fabric.active:
                        self._fabric_thread = None
                        return
            self._fabric_stop.wait(1.0 / FABRIC_KEEPALIVE_HZ)
        with self._fabric_thread_lock:
            self._fabric_thread = None

    def _ensure_fabric_thread(self):
        with self._fabric_thread_lock:
            if self._fabric_thread is not None and self._fabric_thread.is_alive():
                return
            self._fabric_stop.clear()
            t = threading.Thread(target=self._fabric_loop, daemon=True,
                                 name="showcontrol-fabric")
            self._fabric_thread = t
            t.start()

    def _api_fabric(self):
        from flask import request, jsonify
        if request.method == "GET":
            return jsonify({"ok": True, "output": self._fabric_output,
                            "state": self._fabric.status()})
        d = request.get_json(force=True, silent=True) or {}
        # Validate BEFORE load() so a bad request never leaves a half-loaded fabric.
        try:
            output = self._valid_output(d.get("output") or {}) if d.get("output") else None
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        routes = d.get("routes")
        needs_output = isinstance(routes, list) and any(
            isinstance(r, dict) and r.get("sink") == "dmx" for r in routes)
        if needs_output and output is None:
            return jsonify({"ok": False, "error": "DMX routes need an 'output' {protocol,host}"}), 400
        try:
            info = self._fabric.load(d)
        except (FabricError, ValueError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        self._fabric_output = output
        self._ensure_fabric_thread()
        return jsonify({"ok": True, "loaded": info, "output": output})

    def _api_fabric_set(self):
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        name, value = d.get("signal"), d.get("value")
        try:
            self._emit_fabric(self._fabric.set(name, value))
        except FabricError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        self._ensure_fabric_thread()
        return jsonify({"ok": True, "signal": name, "value": self._fabric.signals.get(name)})

    def _api_fabric_state(self):
        from flask import jsonify
        return jsonify({"ok": True, "state": self._fabric.status(),
                        "output": self._fabric_output, "sent": self._sent})

    # ── sonda: Art-Net node discovery ─────────────────────────────────────
    def _api_discover(self):
        """Broadcast an ArtPoll and list the Art-Net nodes that answer."""
        from flask import request, jsonify
        d = (request.get_json(force=True, silent=True) or {}) if request.method == "POST" else {}
        timeout = d.get("timeout", request.args.get("timeout", 2.0))
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "timeout must be a number"}), 400
        bcast = d.get("broadcast", "255.255.255.255")
        if not valid_host(bcast):
            return jsonify({"ok": False, "error": "broadcast must be IPv4"}), 400
        try:
            nodes = artnet_discover(timeout=timeout, broadcast_host=bcast)
        except OSError as e:
            self._last_error = "discover: %s" % e
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "count": len(nodes), "nodes": nodes})

    # ── sonda/p_inv: optical DMX auto-mapping (transport matrix) ───────────
    def _api_automap_plan(self):
        """Return the actuation sweep. Emit each step's frame (as /artnet
        channels), measure the scene, feed the readings back to /automap/solve."""
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        try:
            p = automap_plan(d.get("channels"), level=d.get("level", 255),
                             mode=d.get("mode", "single"))
        except (ValueError, TypeError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "plan": p, "steps": len(p["steps"]),
                        "note": "POST each step.emit to /artnet as 'channels'; "
                                "collect one measurement per step in order"})

    def _api_automap_solve(self):
        """Turn measurements (aligned to plan.steps) into per-channel response."""
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        try:
            out = automap_solve(d.get("channels"), d.get("measurements") or [],
                                level=d.get("level", 255), mode=d.get("mode", "single"))
        except (ValueError, TypeError) as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "response": out["response"], "residual": out["residual"]})

    # ── obs: unified telemetry ────────────────────────────────────────────
    def _api_obs(self):
        """Live telemetry: uptime, send rates, thread liveness, standing state."""
        from flask import jsonify
        now = time.monotonic()
        cue_alive = self._cue_thread is not None and self._cue_thread.is_alive()
        fab_alive = self._fabric_thread is not None and self._fabric_thread.is_alive()
        cue_state = self._engine.status()
        fab_state = self._fabric.status()
        # a tick thread is *expected* alive only while its engine is active
        oscin_alive = self._oscin_thread is not None and self._oscin_thread.is_alive()
        threads = {"cue": (bool(cue_state.get("active")), cue_alive),
                   "fabric": (bool(fab_state.get("active")), fab_alive),
                   "oscin": (self._oscin_wanted, oscin_alive)}
        # only a FRESH error degrades health; stale ones stay visible with their age
        age = self._last_error_age()
        fresh_error = self._last_error if (age is not None and age < self.ERROR_FRESH_S) else None
        return jsonify({
            "ok": True,
            "health": obs_health(threads, fresh_error),
            "uptime_s": round(now - self._loaded_at, 1),
            "sent": self._sent,
            "rates_per_s": {k: round(v, 2)
                            for k, v in self._telemetry.rates(self._sent, now).items()},
            "threads": {k: {"expected": exp, "alive": alive}
                        for k, (exp, alive) in threads.items()},
            "cue": cue_state,
            "fabric": fab_state,
            "last_error": self._last_error,
            "last_error_age_s": round(age, 1) if age is not None else None,
        })

    # ── oscin: opt-in OSC listener (orq bidirectional) ─────────────────────
    def _exec_osc_action(self, act):
        now = time.monotonic()
        kind = act[0]
        if kind == "go":
            self._engine.go(now, index=act[1])
            self._ensure_cue_thread()
        elif kind == "stop":
            self._engine.stop(now)
        elif kind == "release":
            self._engine.release(now, fade=act[1])
            self._ensure_cue_thread()
        elif kind == "tl_play":
            self._timeline.play(now)
            self._ensure_cue_thread()
        elif kind == "tl_pause":
            self._timeline.pause(now)
        elif kind == "tl_locate":
            self._timeline.locate(act[1], now=now)
        elif kind == "signal":
            self._emit_fabric(self._fabric.set(act[1], act[2]))
            self._ensure_fabric_thread()

    def _oscin_loop(self, sock):
        while not self._oscin_stop.is_set():
            try:
                data, addr = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break                                # socket closed by stop
            if self._oscin_allow and addr[0] not in self._oscin_allow:
                self._oscin_stats["denied"] += 1
                continue
            self._oscin_stats["received"] += 1
            try:
                msgs = parse_packet(data)
            except (OscParseError, UnicodeDecodeError):
                self._oscin_stats["ignored"] += 1
                continue
            for address, args in msgs:
                self._oscin_stats["last_address"] = address
                act = map_action(address, args)
                if act is None:
                    self._oscin_stats["ignored"] += 1
                    continue
                try:
                    self._exec_osc_action(act)
                    self._oscin_stats["acted"] += 1
                except (CueError, FabricError, TimelineError, ValueError, OSError) as e:
                    self._oscin_stats["ignored"] += 1
                    self._last_error = "oscin: %s" % e
        try:
            sock.close()
        except OSError:
            pass

    def _oscin_shutdown(self):
        with self._oscin_lock:
            self._oscin_wanted = False
            self._oscin_stop.set()
            s, self._oscin_sock = self._oscin_sock, None
            if s:
                try:
                    s.close()
                except OSError:
                    pass
            self._oscin_thread = None
            self._oscin_port = None

    def _oscin_state(self):
        alive = self._oscin_thread is not None and self._oscin_thread.is_alive()
        return {"listening": alive,
                "port": self._oscin_port if alive else None,
                "allow": sorted(self._oscin_allow) if self._oscin_allow else None,
                "stats": dict(self._oscin_stats)}

    def _api_oscin(self):
        """GET: listener state. POST {port?, allow?: [ips]}: start listening.
        The fixed action table lives in oscin.map_action (/xio/* only)."""
        from flask import request, jsonify
        if request.method == "GET":
            return jsonify({"ok": True, "state": self._oscin_state()})
        d = request.get_json(force=True, silent=True) or {}
        port = d.get("port", 9001)
        if not isinstance(port, int) or not (1024 <= port <= 65535):
            return jsonify({"ok": False, "error": "port must be 1024..65535"}), 400
        allow = d.get("allow")
        if allow is not None:
            if (not isinstance(allow, list) or not allow
                    or not all(valid_host(h) for h in allow)):
                return jsonify({"ok": False, "error": "allow must be a non-empty list of IPv4 sources"}), 400
        with self._oscin_lock:
            if self._oscin_thread is not None and self._oscin_thread.is_alive():
                return jsonify({"ok": False, "error": "listener already running (POST /oscin/stop first)"}), 409
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
            except OSError as e:
                return jsonify({"ok": False, "error": "bind failed: %s" % e}), 400
            sock.settimeout(1.0)
            self._oscin_stop.clear()
            self._oscin_allow = set(allow) if allow else None
            self._oscin_port = port
            self._oscin_wanted = True
            self._oscin_stats = {"received": 0, "acted": 0, "ignored": 0, "denied": 0,
                                 "last_address": None}
            t = threading.Thread(target=self._oscin_loop, args=(sock,), daemon=True,
                                 name="showcontrol-oscin")
            self._oscin_sock = sock
            self._oscin_thread = t
            t.start()
        return jsonify({"ok": True, "state": self._oscin_state()})

    def _api_oscin_stop(self):
        from flask import jsonify
        self._oscin_shutdown()
        return jsonify({"ok": True, "state": self._oscin_state()})

    # ── panel + wake-on-lan (xiotech M2) ──────────────────────────────────
    def _api_panel(self):
        from flask import Response
        return Response(PANEL_HTML, mimetype="text/html")

    def _api_wol(self):
        """Send a WoL magic packet; optionally verify a TCP service comes up
        (xiotech M2: 'verificacion de puerto de servicio, no solo ping')."""
        from flask import request, jsonify
        d = request.get_json(force=True, silent=True) or {}
        broadcast = d.get("broadcast", "255.255.255.255")
        verify_host, verify_port = d.get("verify_host"), d.get("verify_port")
        timeout = d.get("timeout", 20)
        try:
            pkt = build_magic_packet(d.get("mac"))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if not valid_host(broadcast):
            return jsonify({"ok": False, "error": "invalid broadcast address"}), 400
        if verify_port is not None:
            if not isinstance(verify_port, int) or not (1 <= verify_port <= 65535):
                return jsonify({"ok": False, "error": "invalid verify_port"}), 400
            if not valid_host(verify_host):
                return jsonify({"ok": False, "error": "verify_port needs a valid verify_host"}), 400
        if not isinstance(timeout, (int, float)) or not (1 <= timeout <= 120):
            return jsonify({"ok": False, "error": "timeout out of range 1..120 s"}), 400
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for _ in range(3):                       # WoL is fire-and-forget; repeat
                sock.sendto(pkt, (broadcast, 9))
        except OSError as e:
            self._last_error = "wol: %s" % e
            return jsonify({"ok": False, "error": str(e)}), 502
        finally:
            sock.close()
        if verify_port is None:
            return jsonify({"ok": True, "sent": 3, "verified": None})
        deadline = time.monotonic() + float(timeout)
        up = False
        while time.monotonic() < deadline and not up:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            try:
                up = s.connect_ex((verify_host, verify_port)) == 0
            finally:
                s.close()
            if not up:
                time.sleep(1.0)
        return jsonify({"ok": True, "sent": 3, "verified": up,
                        "service": "%s:%d" % (verify_host, verify_port)})


# The plugin loader (xio/new-plugins/__init__.py) requires this export.
plugin_class = ShowControlPlugin

"""
Signal fabric -- the `fabric` node of xio-concept.html made real.

One logical signal (a normalized 0..1 control value) fans out to many concrete
sinks -- DMX channels across universes, OSC faders -- through a routing table.
Hub-and-spoke, O(N + M): N signals, M routes, no N*M mesh. Setting `master`
once updates every channel and fader bound to it, atomically, and returns the
minimal set of packets to emit.

Pure stdlib, no plugin/Flask imports -- unit-tested off-device (test_fabric.py).
No shell, no I/O here: set()/pending() return events; the plugin sends them.

Route spec (JSON):
  {
    "signals": ["master", "hue"],
    "routes": [
      {"signal":"master","sink":"dmx","universe":0,"channel":1},
      {"signal":"master","sink":"dmx","universe":0,"channel":5,"min":0,"max":180,"curve":2.2},
      {"signal":"hue","sink":"osc","host":"192.168.1.20","port":9000,
       "address":"/hue","kind":"float","min":0,"max":1}
    ]
  }
A route maps signal v in [0,1] -> min + (max-min) * v**curve.
"""

import threading

MAX_UNIVERSE = 63999
KEEPALIVE_S = 1.0


class FabricError(ValueError):
    """Invalid fabric spec."""


def _num(v, name, lo, hi):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise FabricError("%s must be a number: %r" % (name, v))
    if not (lo <= f <= hi):
        raise FabricError("%s out of range %s..%s: %s" % (name, lo, hi, f))
    return f


def _valid_ipv4(host):
    parts = str(host).split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


class Route(object):
    """One signal -> sink mapping with a min/max/curve transform."""

    def __init__(self, spec, idx):
        if not isinstance(spec, dict):
            raise FabricError("route %d must be an object" % idx)
        self.signal = spec.get("signal")
        if not isinstance(self.signal, str) or not self.signal:
            raise FabricError("route %d: signal must be a non-empty string" % idx)
        self.sink = spec.get("sink")
        self.curve = _num(spec.get("curve", 1.0), "curve", 0.01, 10.0)
        if self.sink == "dmx":
            self.universe = int(_num(spec.get("universe", 0), "universe", 0, MAX_UNIVERSE))
            self.channel = int(_num(spec.get("channel"), "channel", 1, 512))
            self.min = _num(spec.get("min", 0), "min", 0, 255)
            self.max = _num(spec.get("max", 255), "max", 0, 255)
        elif self.sink == "osc":
            self.host = spec.get("host")
            if not _valid_ipv4(self.host):
                raise FabricError("route %d: osc host must be IPv4" % idx)
            self.port = int(_num(spec.get("port", 9000), "port", 1, 65535))
            self.address = spec.get("address")
            if not isinstance(self.address, str) or not self.address.startswith("/"):
                raise FabricError("route %d: osc address must start with '/'" % idx)
            self.kind = spec.get("kind", "float")
            if self.kind not in ("float", "int", "bool"):
                raise FabricError("route %d: osc kind must be float/int/bool" % idx)
            self.min = _num(spec.get("min", 0.0), "min", -1e6, 1e6)
            self.max = _num(spec.get("max", 1.0), "max", -1e6, 1e6)
        else:
            raise FabricError("route %d: sink must be 'dmx' or 'osc'" % idx)

    def apply(self, v):
        """v in [0,1] -> transformed scalar."""
        return self.min + (self.max - self.min) * (v ** self.curve)

    def osc_arg(self, v):
        s = self.apply(v)
        if self.kind == "int":
            return int(round(s))
        if self.kind == "bool":
            return s >= 0.5
        return float(s)


class Fabric(object):
    """Signal bus. Thread-safe. set() returns packets to emit."""

    def __init__(self):
        self._lock = threading.RLock()
        self.signals = {}                 # name -> value 0..1
        self.routes = []
        self._by_signal = {}              # name -> [Route]
        self._dmx = {}                    # universe -> {channel: value}
        self._width = {}                  # universe -> max channel
        self._last_emit = {}
        self.active = False

    def load(self, spec):
        if not isinstance(spec, dict):
            raise FabricError("spec must be an object")
        names = spec.get("signals", [])
        if not isinstance(names, list) or not names:
            raise FabricError("signals must be a non-empty list")
        routes_spec = spec.get("routes", [])
        if not isinstance(routes_spec, list):
            raise FabricError("routes must be a list")
        if len(routes_spec) > 4096:
            raise FabricError("too many routes (max 4096)")
        routes = [Route(r, i) for i, r in enumerate(routes_spec)]
        declared = set(names)
        for i, r in enumerate(routes):
            if r.signal not in declared:
                raise FabricError("route %d references undeclared signal %r" % (i, r.signal))
        with self._lock:
            self.signals = {n: 0.0 for n in names}
            self.routes = routes
            self._by_signal = {}
            for r in routes:
                self._by_signal.setdefault(r.signal, []).append(r)
            self._dmx = {}
            self._width = {}
            for r in routes:
                if r.sink == "dmx":
                    self._width[r.universe] = max(self._width.get(r.universe, 0), r.channel)
                    self._dmx.setdefault(r.universe, {})[r.channel] = 0.0
            self._last_emit = {}
            self.active = bool(routes)
        return {"signals": len(names), "routes": len(routes),
                "universes": sorted(self._width)}

    def _frame(self, universe):
        width = self._width.get(universe, 0)
        chans = self._dmx.get(universe, {})
        return [int(round(chans.get(c, 0.0))) for c in range(1, width + 1)]

    def set(self, name, value):
        """Update one signal; return [('dmx',u,[..]), ('osc',host,port,addr,[arg])]."""
        with self._lock:
            if name not in self.signals:
                raise FabricError("unknown signal: %r" % name)
            v = _num(value, "value", 0.0, 1.0)
            self.signals[name] = v
            events = []
            touched = set()
            for r in self._by_signal.get(name, []):
                if r.sink == "dmx":
                    self._dmx[r.universe][r.channel] = max(0.0, min(255.0, r.apply(v)))
                    touched.add(r.universe)
                else:
                    events.append(("osc", r.host, r.port, r.address, [r.osc_arg(v)]))
            for u in sorted(touched):
                events.append(("dmx", u, self._frame(u)))
                self._last_emit[u] = None      # force emit; plugin stamps time
            return events

    def keepalive(self, now):
        """Re-emit standing DMX frames that have gone stale (Art-Net timeout guard)."""
        with self._lock:
            out = []
            if not self.active:
                return out
            for u in self._width:
                last = self._last_emit.get(u)
                if last is None or now - last >= KEEPALIVE_S:
                    out.append(("dmx", u, self._frame(u)))
                    self._last_emit[u] = now
            return out

    def status(self):
        with self._lock:
            return {"active": self.active,
                    "signals": dict(self.signals),
                    "route_count": len(self.routes),
                    "universes": sorted(self._width)}

"""
Theatrical cue engine for showcontrol -- GO / STOP / RELEASE with timed fades.

This is the `orq` grow point from cultura/xio-concept.html ("Art-Net/DMX + fades,
cue engine"): a cue list where each cue is a complete lighting look (DMX levels per
universe) plus optional OSC triggers, crossfaded over `fade` seconds.

Design rules (same as protocols.py):
  * Pure stdlib, no plugin-framework / Flask imports -- importable and unit-testable
    off-device (test_cueengine.py).
  * Deterministic: tick(now)/go(now) take an explicit monotonic timestamp, so tests
    never sleep. The plugin passes time.monotonic().
  * No shell is ever invoked -- zero command-injection surface.
  * Battery discipline (the `lazo` reading): the engine reports `active`; the plugin
    only runs its tick thread while a show is live and stops it once RELEASE lands
    at black.

Semantics (v1, tracking OFF):
  * A cue defines the FULL look for its universes: channels present in the previous
    look but absent from the new cue fade to 0.
  * GO advances to the next cue (or `goto` index) and starts its fade.
  * STOP freezes the output mid-fade; the next GO advances to the following cue.
  * RELEASE fades everything to black, resets position, then deactivates.
  * `follow`: seconds after a fade completes until the next cue fires automatically.
  * DMX frames are emitted as full-width channel lists per universe (never dicts):
    a shorter ArtDMX frame would leave dropped channels frozen on the node.
  * Standing looks re-emit every KEEPALIVE_S so Art-Net/sACN nodes do not time out.
"""

import threading

KEEPALIVE_S = 1.0
MAX_CUES = 512
MAX_UNIVERSE = 63999          # sACN upper bound; Art-Net re-validates at build time


class CueError(ValueError):
    """Invalid cue list / cue payload."""


def _validate_levels(levels):
    """{universe: {channel: value}} -> {int: {int: int}} with range checks."""
    if not isinstance(levels, dict):
        raise CueError("levels must be an object {universe: {channel: value}}")
    out = {}
    for u_key, chans in levels.items():
        try:
            u = int(u_key)
        except (TypeError, ValueError):
            raise CueError("universe must be an integer: %r" % (u_key,))
        if not (0 <= u <= MAX_UNIVERSE):
            raise CueError("universe out of range 0..%d: %d" % (MAX_UNIVERSE, u))
        if not isinstance(chans, dict):
            raise CueError("universe %d levels must be {channel: value}" % u)
        cmap = {}
        for c_key, val in chans.items():
            try:
                ch = int(c_key)
                v = int(val)
            except (TypeError, ValueError):
                raise CueError("bad channel/value in universe %d: %r=%r" % (u, c_key, val))
            if not (1 <= ch <= 512):
                raise CueError("DMX channel out of range 1..512: %d" % ch)
            if not (0 <= v <= 255):
                raise CueError("DMX value out of range 0..255: %d" % v)
            cmap[ch] = v
        out[u] = cmap
    return out


def _validate_osc(osc):
    if osc is None:
        return []
    if not isinstance(osc, list):
        raise CueError("osc must be a list of {address, args}")
    out = []
    for m in osc:
        if not isinstance(m, dict):
            raise CueError("each osc entry must be an object")
        addr = m.get("address")
        if not isinstance(addr, str) or not addr.startswith("/"):
            raise CueError("OSC address must be a string starting with '/'")
        args = m.get("args", [])
        if not isinstance(args, list):
            raise CueError("OSC args must be a list")
        for a in args:
            if not isinstance(a, (bool, int, float, str)):
                raise CueError("OSC arg must be int/float/str/bool: %r" % (a,))
        out.append({"address": addr, "args": args})
    return out


class Cue(object):
    """One cue: label + full look + fade time + OSC triggers + optional follow."""

    def __init__(self, spec, index):
        if not isinstance(spec, dict):
            raise CueError("cue %d must be an object" % index)
        self.label = str(spec.get("label", "cue %d" % index))
        fade = spec.get("fade", 0)
        try:
            self.fade = float(fade)
        except (TypeError, ValueError):
            raise CueError("cue %d: fade must be a number" % index)
        if not (0 <= self.fade <= 3600):
            raise CueError("cue %d: fade out of range 0..3600 s" % index)
        follow = spec.get("follow", None)
        if follow is not None:
            try:
                follow = float(follow)
            except (TypeError, ValueError):
                raise CueError("cue %d: follow must be a number or null" % index)
            if not (0 <= follow <= 86400):
                raise CueError("cue %d: follow out of range" % index)
        self.follow = follow
        self.levels = _validate_levels(spec.get("levels", {}))
        self.osc = _validate_osc(spec.get("osc"))

    def to_dict(self):
        return {"label": self.label, "fade": self.fade, "follow": self.follow,
                "levels": {str(u): {str(c): v for c, v in cm.items()}
                           for u, cm in self.levels.items()},
                "osc": self.osc}


class CueEngine(object):
    """Cue list transport. All public methods are thread-safe (one RLock)."""

    def __init__(self):
        self._lock = threading.RLock()
        self.cues = []
        self.pos = -1                 # index of the cue we are in / fading to
        self.state = "idle"           # idle | fading | stopped
        self._live = {}               # {universe: [float]*width} current output
        self._width = {}              # {universe: max channel ever used}
        self._fade_from = {}
        self._fade_to = {}
        self._fade_t0 = 0.0
        self._fade_dur = 0.0
        self._fade_end = None         # monotonic time the last fade completed
        self._pending_osc = []
        self._last_emit = {}          # {universe: last emit time}
        self.active = False

    # ── cue list ─────────────────────────────────────────────────────────
    def load(self, cue_specs):
        if not isinstance(cue_specs, list):
            raise CueError("cues must be a list")
        if not (1 <= len(cue_specs) <= MAX_CUES):
            raise CueError("cue list must have 1..%d cues" % MAX_CUES)
        cues = [Cue(spec, i) for i, spec in enumerate(cue_specs)]
        with self._lock:
            self.cues = cues
            self.pos = -1
            self.state = "idle"
            # a new list is a new show: drop all live/fade state so stale
            # levels from the previous list never keep transmitting
            self._live = {}
            self._width = {}
            self._fade_from = {}
            self._fade_to = {}
            self._fade_end = None
            self._pending_osc = []
            self._last_emit = {}
            self.active = False
        return len(cues)

    # ── helpers ──────────────────────────────────────────────────────────
    def _target_for(self, cue):
        """Full look: cue levels expanded over every universe seen so far.
        Channels absent from the cue go to 0 (tracking OFF)."""
        target = {}
        universes = set(self._width) | set(cue.levels)
        for u in universes:
            cue_max = max(cue.levels.get(u, {}) or {0: 0})
            width = max(self._width.get(u, 0), cue_max, 1)
            arr = [0.0] * width
            for ch, v in cue.levels.get(u, {}).items():
                arr[ch - 1] = float(v)
            target[u] = arr
            self._width[u] = width
        return target

    def _snapshot_live(self):
        snap = {}
        for u, width in self._width.items():
            cur = self._live.get(u, [])
            arr = list(cur) + [0.0] * (width - len(cur))
            snap[u] = arr
        return snap

    # ── transport ────────────────────────────────────────────────────────
    def go(self, now, index=None):
        with self._lock:
            if not self.cues:
                raise CueError("no cue list loaded")
            nxt = self.pos + 1 if index is None else int(index)
            if not (0 <= nxt < len(self.cues)):
                raise CueError("cue index out of range 0..%d: %d"
                               % (len(self.cues) - 1, nxt))
            cue = self.cues[nxt]
            if self.state == "fading":                 # GO mid-fade: catch up first
                self._live = self._interpolate(now)
            self._fade_to = self._target_for(cue)      # extends _width first
            self._fade_from = self._snapshot_live()
            self.pos = nxt
            self._fade_t0 = now
            self._fade_dur = cue.fade
            self._fade_end = None
            self.state = "fading"
            self.active = True
            self._pending_osc.extend(cue.osc)
            return cue.label

    def stop(self, now):
        """Freeze the output where it is. Next go() advances to the next cue."""
        with self._lock:
            if self.state == "fading":
                self._live = self._interpolate(now)
            self.state = "stopped"
            self._fade_end = None

    def release(self, now, fade=2.0):
        """Fade everything to black, reset position, deactivate on arrival."""
        with self._lock:
            try:
                fade = float(fade)
            except (TypeError, ValueError):
                raise CueError("release fade must be a number")
            if not (0 <= fade <= 3600):
                raise CueError("release fade out of range 0..3600 s")
            if self.state == "fading":
                self._live = self._interpolate(now)
            self._fade_from = self._snapshot_live()
            self._fade_to = {u: [0.0] * w for u, w in self._width.items()}
            self._fade_t0 = now
            self._fade_dur = fade
            self._fade_end = None
            self.pos = -1
            self.state = "fading"
            self.active = True
            self._pending_osc = []

    # ── clock ────────────────────────────────────────────────────────────
    def _interpolate(self, now):
        if self._fade_dur <= 0:
            k = 1.0
        else:
            k = min(1.0, max(0.0, (now - self._fade_t0) / self._fade_dur))
        out = {}
        for u in self._fade_to:
            frm = self._fade_from.get(u, [0.0] * len(self._fade_to[u]))
            out[u] = [a + (b - a) * k for a, b in zip(frm, self._fade_to[u])]
        return out

    def tick(self, now):
        """Advance the clock; return events to emit:
        ("osc", address, args) and ("dmx", universe, [int levels])."""
        with self._lock:
            events = [("osc", m["address"], m["args"]) for m in self._pending_osc]
            self._pending_osc = []
            changed = set()

            if self.state == "fading":
                new_live = self._interpolate(now)
                for u, arr in new_live.items():
                    if arr != self._live.get(u):
                        changed.add(u)
                self._live = new_live
                done = (self._fade_dur <= 0) or (now - self._fade_t0 >= self._fade_dur)
                if done:
                    self.state = "idle"
                    self._fade_end = now
                    if self.pos < 0:                      # release arrived at black
                        if not any(any(arr) for arr in self._live.values()):
                            self.active = False

            elif self.state == "idle" and self.pos >= 0:
                cue = self.cues[self.pos]
                if (cue.follow is not None and self._fade_end is not None
                        and now - self._fade_end >= cue.follow
                        and self.pos + 1 < len(self.cues)):
                    self.go(now, self.pos + 1)
                    events.extend(("osc", m["address"], m["args"])
                                  for m in self._pending_osc)
                    self._pending_osc = []
                    # emit the new cue's instantaneous look on THIS tick,
                    # including universes the new cue introduces
                    self._live = self._interpolate(now)
                    changed |= set(self._live)

            for u, arr in self._live.items():
                stale = now - self._last_emit.get(u, -1e9) >= KEEPALIVE_S
                if u in changed or (stale and self.active):
                    events.append(("dmx", u, [int(round(v)) for v in arr]))
                    self._last_emit[u] = now
            return events

    # ── introspection ────────────────────────────────────────────────────
    def status(self):
        with self._lock:
            return {
                "state": self.state,
                "active": self.active,
                "cue_count": len(self.cues),
                "position": self.pos,
                "label": self.cues[self.pos].label if 0 <= self.pos < len(self.cues) else None,
                "universes": sorted(self._width),
            }

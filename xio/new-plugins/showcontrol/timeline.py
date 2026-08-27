"""
Timecode timeline -- the capstone of the `orq` node: the show plays itself.

The cue engine can auto-advance (follow), but a timeline fires cues at ABSOLUTE
positions on a transport clock: at 0:05 GO cue 2, at 0:20 GO cue 5. play / pause
/ locate like a media transport. Pure scheduler -- no clock of its own: the
caller injects `now` (monotonic seconds), the timeline tracks an anchor and an
offset. Deterministic and unit-tested off-device (test_timeline.py); the plugin
drives self._engine.go() for each due event inside the existing 30 Hz cue loop.

Firing is edge-triggered (a _fired set), so a cue never double-fires if the loop
ticks twice at the same playhead. locate(t) marks everything at <= t as already
passed, so play-from-a-point doesn't retrigger the intro.

Thread-safe (one RLock): due() runs on the cue tick thread while load/play/
pause/locate arrive from Flask or the OSC-in listener.
"""

import threading

MAX_EVENTS = 4096


class TimelineError(ValueError):
    """Invalid timeline spec or transport call."""


class Timeline(object):
    """Absolute-position cue scheduler. play/pause/locate + due(now)."""

    def __init__(self):
        self._lock = threading.RLock()
        self._events = []          # sorted [(at_seconds, cue_index, label)]
        self._playing = False
        self._t0 = None            # monotonic anchor when playback (re)started
        self._pos = 0.0            # playhead offset at that anchor
        self._fired = set()        # indices into _events already fired this run

    @property
    def playing(self):
        return self._playing

    def load(self, events):
        """events: [{'at': seconds, 'cue': index, 'label'?: str}] -> sorted schedule."""
        if not isinstance(events, list) or not events:
            raise TimelineError("events must be a non-empty list")
        if len(events) > MAX_EVENTS:
            raise TimelineError("too many events (max %d)" % MAX_EVENTS)
        parsed = []
        for i, e in enumerate(events):
            if not isinstance(e, dict):
                raise TimelineError("event %d must be an object" % i)
            try:
                at = float(e.get("at"))
            except (TypeError, ValueError):
                raise TimelineError("event %d: 'at' must be a number (seconds)" % i)
            if at < 0:
                raise TimelineError("event %d: 'at' must be >= 0" % i)
            try:
                cue = int(e.get("cue"))
            except (TypeError, ValueError):
                raise TimelineError("event %d: 'cue' must be an integer index" % i)
            if cue < 0:
                raise TimelineError("event %d: 'cue' must be >= 0" % i)
            parsed.append((at, cue, str(e.get("label", ""))))
        parsed.sort(key=lambda t: t[0])
        with self._lock:
            self._events = parsed
            self._playing = False
            self._t0 = None
            self._pos = 0.0
            self._fired = set()
        return {"events": len(parsed), "duration": parsed[-1][0] if parsed else 0.0}

    def position(self, now):
        with self._lock:
            if self._playing and self._t0 is not None:
                return self._pos + (now - self._t0)
            return self._pos

    def play(self, now):
        with self._lock:
            if not self._events:
                raise TimelineError("no timeline loaded")
            if not self._playing:
                self._t0 = now
                self._playing = True
            return self.status(now)

    def pause(self, now):
        with self._lock:
            if self._playing:
                self._pos = self.position(now)
                self._playing = False
            return self.status(now)

    def locate(self, t, now=None):
        """Jump the playhead to t seconds; events at <= t count as already passed."""
        t = float(t)
        if t < 0:
            raise TimelineError("locate position must be >= 0")
        with self._lock:
            self._pos = t
            if self._playing and now is not None:
                self._t0 = now                          # re-anchor so position == t now
            self._fired = {i for i, (at, _c, _l) in enumerate(self._events) if at <= t}
            return self.status(now if now is not None else t)

    def due(self, now):
        """Advance the playhead to `now`; return cue indices that just came due, in order."""
        with self._lock:
            if not self._playing:
                return []
            cur = self.position(now)
            out = []
            for i, (at, cue, _label) in enumerate(self._events):
                if i in self._fired:
                    continue
                if at <= cur:
                    self._fired.add(i)
                    out.append(cue)
                elif at > cur:
                    break                               # events are sorted; nothing later is due
            return out

    def status(self, now=None):
        with self._lock:
            pos = self.position(now) if now is not None else self._pos
            return {"playing": self._playing,
                    "position": round(pos, 3),
                    "events": len(self._events),
                    "fired": len(self._fired),
                    "duration": self._events[-1][0] if self._events else 0.0}

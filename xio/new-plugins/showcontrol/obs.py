"""
Observability -- the `obs` node ("observar antes de calcular") made real.

A live telemetry surface for showcontrol: you should be able to SEE what the
plugin is doing (packet rates per protocol, thread liveness, standing state)
without re-deriving it from logs. The graph's point -- observation compresses
computation, and sometimes reveals it was the wrong computation -- applies to
running the plugin too: measure the actual emit behaviour before tuning blind.

Pull-based rates (like Prometheus): rate = d(count)/d(t) between two scrapes, no
background sampler thread. The pure, testable part lives here (Telemetry); the
plugin assembles the live snapshot around it. Unit-tested off-device (test_obs.py).
"""


class Telemetry:
    """Counter deltas -> per-second rates between successive scrapes."""

    def __init__(self):
        self._last_t = None
        self._last = {}

    def rates(self, counts, now):
        """Return {key: per-second rate} since the previous call.

        First call (or a non-advancing/backward clock) returns zeros and just
        arms the baseline. A counter that went backwards (reset) clamps to 0.0
        rather than reporting a huge negative spike.
        """
        counts = {k: float(v) for k, v in dict(counts).items()}
        if self._last_t is None or now <= self._last_t:
            self._last_t, self._last = now, counts
            return {k: 0.0 for k in counts}
        dt = now - self._last_t
        out = {k: max(0.0, (counts[k] - self._last.get(k, 0.0)) / dt) for k in counts}
        self._last_t, self._last = now, counts
        return out


def health(threads, last_error):
    """Grade the plugin: ok | degraded | error.

    threads: {name: (expected_alive_bool, actual_alive_bool)}. A thread that
    should be running but isn't is 'degraded'; a recorded last_error is 'error'.
    """
    for _name, (expected, alive) in threads.items():
        if expected and not alive:
            return "degraded"
    if last_error:
        return "error"
    return "ok"

"""
Off-device tests for the obs telemetry math (pull-based rates + health grade).
    py xio/new-plugins/showcontrol/test_obs.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obs import Telemetry, health  # noqa: E402


def test_first_scrape_arms_baseline():
    t = Telemetry()
    r = t.rates({"artnet": 100, "osc": 5}, now=10.0)
    assert r == {"artnet": 0.0, "osc": 0.0}, r      # no rate without a prior sample
    print("OK first scrape returns zeros, arms baseline")


def test_rate_between_scrapes():
    t = Telemetry()
    t.rates({"artnet": 0}, now=0.0)
    r = t.rates({"artnet": 60}, now=2.0)            # +60 over 2s = 30/s
    assert abs(r["artnet"] - 30.0) < 1e-9, r
    print("OK rate = d(count)/d(t) between scrapes")


def test_nonadvancing_clock_is_safe():
    t = Telemetry()
    t.rates({"x": 5}, now=100.0)
    assert t.rates({"x": 9}, now=100.0) == {"x": 0.0}   # dt == 0 -> no divide, zeros
    assert t.rates({"x": 9}, now=99.0) == {"x": 0.0}    # clock went backwards
    print("OK non-advancing / backward clock returns zeros, no crash")


def test_counter_reset_clamps_to_zero():
    t = Telemetry()
    t.rates({"x": 1000}, now=0.0)
    r = t.rates({"x": 3}, now=1.0)                  # reset (e.g. reload) -> not negative
    assert r["x"] == 0.0, r
    print("OK counter reset clamps to 0.0 (no negative spike)")


def test_new_key_appears():
    t = Telemetry()
    t.rates({"a": 0}, now=0.0)
    r = t.rates({"a": 10, "b": 4}, now=1.0)         # 'b' unseen before -> rate vs 0
    assert abs(r["a"] - 10.0) < 1e-9 and abs(r["b"] - 4.0) < 1e-9, r
    print("OK a newly-appearing counter rates against zero baseline")


def test_health_grade():
    assert health({"cue": (True, True)}, None) == "ok"
    assert health({"cue": (True, False)}, None) == "degraded"   # should run, isn't
    assert health({"cue": (False, False)}, None) == "ok"        # idle by design
    assert health({"cue": (True, True)}, "boom") == "error"
    assert health({"cue": (True, False)}, "boom") == "degraded"  # dead thread wins
    print("OK health grades ok/degraded/error")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

"""
Off-device tests for the signal fabric (canonical hub-and-spoke routing).
    py xio/new-plugins/showcontrol/test_fabric.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fabric import Fabric, FabricError  # noqa: E402


SPEC = {
    "signals": ["master", "hue"],
    "routes": [
        {"signal": "master", "sink": "dmx", "universe": 0, "channel": 1},
        {"signal": "master", "sink": "dmx", "universe": 0, "channel": 5, "max": 200},
        {"signal": "master", "sink": "dmx", "universe": 2, "channel": 3},
        {"signal": "hue", "sink": "osc", "host": "192.168.1.20", "port": 9000,
         "address": "/hue", "kind": "float"},
    ],
}


def dmx(events, u):
    for e in events:
        if e[0] == "dmx" and e[1] == u:
            return e[2]
    return None


def osc(events):
    return [(h, p, a, args) for k, h, p, a, args in [e for e in events if e[0] == "osc"]]


def test_load_and_status():
    f = Fabric()
    info = f.load(SPEC)
    assert info == {"signals": 2, "routes": 4, "universes": [0, 2]}, info
    st = f.status()
    assert st["active"] and st["signals"] == {"master": 0.0, "hue": 0.0}
    print("OK load + status")


def test_fanout_one_signal_many_sinks():
    f = Fabric()
    f.load(SPEC)
    ev = f.set("master", 0.5)
    # universe 0: ch1 = 0.5*255=127.5->128, ch5 = 0.5*200=100
    assert dmx(ev, 0) == [128, 0, 0, 0, 100], dmx(ev, 0)
    # universe 2: ch3 = 128, width 3
    assert dmx(ev, 2) == [0, 0, 128], dmx(ev, 2)
    # master doesn't touch OSC (that's hue) -> no osc events
    assert osc(ev) == []
    print("OK fan-out: one signal -> many DMX channels across universes")


def test_curve_and_range():
    f = Fabric()
    f.load({"signals": ["x"], "routes": [
        {"signal": "x", "sink": "dmx", "universe": 0, "channel": 1, "min": 0, "max": 255, "curve": 2.0}]})
    ev = f.set("x", 0.5)                 # 0.5**2 = 0.25 -> 63.75 -> 64
    assert dmx(ev, 0) == [64], dmx(ev, 0)
    ev = f.set("x", 1.0)
    assert dmx(ev, 0) == [255], dmx(ev, 0)
    print("OK curve + range mapping")


def test_osc_kinds():
    f = Fabric()
    f.load({"signals": ["a", "b", "c"], "routes": [
        {"signal": "a", "sink": "osc", "host": "10.0.0.1", "address": "/f", "kind": "float"},
        {"signal": "b", "sink": "osc", "host": "10.0.0.1", "address": "/i", "kind": "int", "max": 127},
        {"signal": "c", "sink": "osc", "host": "10.0.0.1", "address": "/t", "kind": "bool"}]})
    assert osc(f.set("a", 0.25))[0][3] == [0.25]
    assert osc(f.set("b", 1.0))[0][3] == [127]
    assert osc(f.set("c", 0.9))[0][3] == [True]
    assert osc(f.set("c", 0.1))[0][3] == [False]
    print("OK osc kinds float/int/bool")


def test_keepalive_reemits_only_when_stale():
    f = Fabric()
    f.load(SPEC)
    f.set("master", 0.4)                 # marks universes 0,2 for emit
    a = f.keepalive(100.0)               # both stale (never stamped) -> emit
    assert {e[1] for e in a} == {0, 2}, a
    assert f.keepalive(100.2) == []      # too soon
    b = f.keepalive(101.5)               # >1s later -> re-emit
    assert {e[1] for e in b} == {0, 2}, b
    print("OK keep-alive re-emits standing frames only when stale")


def test_validation():
    for bad in (
        "x",                                                    # not object
        {"signals": []},                                        # empty signals
        {"signals": ["a"], "routes": [{"signal": "b", "sink": "dmx", "channel": 1}]},  # undeclared
        {"signals": ["a"], "routes": [{"signal": "a", "sink": "dmx", "channel": 0}]},  # ch 0
        {"signals": ["a"], "routes": [{"signal": "a", "sink": "dmx", "channel": 513}]},
        {"signals": ["a"], "routes": [{"signal": "a", "sink": "midi", "channel": 1}]}, # bad sink
        {"signals": ["a"], "routes": [{"signal": "a", "sink": "osc", "host": "nope", "address": "/x"}]},
        {"signals": ["a"], "routes": [{"signal": "a", "sink": "osc", "host": "1.2.3.4", "address": "x"}]},
        {"signals": ["a"], "routes": [{"signal": "a", "sink": "dmx", "channel": 1, "curve": 0}]},
    ):
        try:
            Fabric().load(bad)
            raise AssertionError("should have rejected %r" % (bad,))
        except FabricError:
            pass
    f = Fabric(); f.load(SPEC)
    try:
        f.set("nope", 0.5); raise AssertionError("unknown signal accepted")
    except FabricError:
        pass
    try:
        f.set("master", 2.0); raise AssertionError("value>1 accepted")
    except FabricError:
        pass
    print("OK validation rejects garbage")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

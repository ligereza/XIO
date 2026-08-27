"""
Off-device tests for the cue engine (GO / STOP / RELEASE / follow / keep-alive).

Standalone like test_protocols.py -- xio is not part of the repo pytest suite:
    py xio/new-plugins/showcontrol/test_cueengine.py
Time is injected (tick(now)), so no test ever sleeps.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cueengine import CueEngine, CueError, KEEPALIVE_S  # noqa: E402


CUELIST = [
    {"label": "open", "fade": 2.0,
     "levels": {"0": {"1": 200, "2": 100}},
     "osc": [{"address": "/scene/open", "args": [1]}]},
    {"label": "mid", "fade": 4.0,
     "levels": {"0": {"1": 100}}},                     # ch2 must fade to 0
    {"label": "snap", "fade": 0,
     "levels": {"0": {"3": 255}}, "follow": 1.0},
    {"label": "end", "fade": 1.0,
     "levels": {"0": {"1": 255}}},
]


def dmx(events, universe=0):
    for kind, u, arr in [e for e in events if e[0] == "dmx"]:
        if u == universe:
            return arr
    return None


def osc(events):
    return [(a, args) for kind, a, args in [e for e in events if e[0] == "osc"]]


def test_validation_rejects_garbage():
    e = CueEngine()
    for bad in (
        "x",                                            # not a list
        [],                                             # empty
        [{"levels": {"0": {"0": 1}}}],                  # channel 0
        [{"levels": {"0": {"513": 1}}}],                # channel 513
        [{"levels": {"0": {"1": 256}}}],                # value 256
        [{"levels": {"64000": {"1": 1}}}],              # universe too big
        [{"levels": {"0": {"1": 1}}, "fade": -1}],      # negative fade
        [{"levels": {"0": {"1": 1}}, "fade": "x"}],     # non-numeric fade
        [{"osc": [{"address": "noslash"}]}],            # bad OSC address
        [{"osc": "x"}],                                 # osc not a list
    ):
        try:
            e.load(bad)
            raise AssertionError("should have rejected %r" % (bad,))
        except CueError:
            pass
    print("OK validation rejects garbage")


def test_go_fade_midpoint_and_completion():
    e = CueEngine()
    e.load(CUELIST)
    assert e.go(0.0) == "open"
    ev = e.tick(0.0)
    assert osc(ev) == [("/scene/open", [1])]            # OSC fires at cue start
    assert dmx(ev) == [0, 0]                            # k=0, still black
    arr = dmx(e.tick(1.0))                              # halfway through 2 s fade
    assert arr == [100, 50], arr
    arr = dmx(e.tick(2.0))                              # fade complete
    assert arr == [200, 100], arr
    assert e.status()["state"] == "idle"
    print("OK go fade midpoint + completion")


def test_tracking_off_channels_fade_to_zero():
    e = CueEngine()
    e.load(CUELIST)
    e.go(0.0); e.tick(2.0)                              # land on "open": [200, 100]
    e.go(10.0)                                          # "mid": only ch1=100
    arr = dmx(e.tick(12.0))                             # halfway through 4 s fade
    assert arr == [150, 50], arr                        # ch1 200->100, ch2 100->0
    arr = dmx(e.tick(14.0))
    assert arr == [100, 0], arr                         # full-width, ch2 zeroed
    print("OK tracking off: dropped channels fade to zero")


def test_zero_fade_snaps():
    e = CueEngine()
    e.load(CUELIST)
    e.go(0.0); e.tick(2.0)
    e.go(5.0); e.tick(9.0)                              # land on "mid"
    e.go(20.0, index=2)                                 # "snap", fade 0
    arr = dmx(e.tick(20.0))
    assert arr == [0, 0, 255], arr                      # instant, width grew to 3
    assert e.status()["state"] == "idle"
    print("OK zero fade snaps")


def test_stop_freezes_midfade():
    e = CueEngine()
    e.load(CUELIST)
    e.go(0.0)
    e.tick(1.0)                                         # [100, 50]
    e.stop(1.0)
    arr = dmx(e.tick(5.0))                              # long after; still frozen
    assert arr == [100, 50], arr
    assert e.status()["state"] == "stopped"
    assert e.go(6.0) == "mid"                           # next GO -> next cue
    print("OK stop freezes mid-fade")


def test_release_fades_to_black_and_deactivates():
    e = CueEngine()
    e.load(CUELIST)
    e.go(0.0); e.tick(2.0)                              # [200, 100] standing
    e.release(10.0, fade=2.0)
    arr = dmx(e.tick(11.0))
    assert arr == [100, 50], arr
    arr = dmx(e.tick(12.0))
    assert arr == [0, 0], arr
    st = e.status()
    assert st["position"] == -1 and st["active"] is False, st
    assert dmx(e.tick(15.0)) is None                    # inactive: no keep-alive
    print("OK release fades to black + deactivates")


def test_follow_auto_advances():
    e = CueEngine()
    e.load(CUELIST)
    e.go(0.0, index=2)                                  # "snap", fade 0, follow 1.0
    e.tick(0.0)                                         # completes instantly
    assert e.status()["label"] == "snap"
    e.tick(0.5)                                         # follow not yet due
    assert e.status()["label"] == "snap"
    e.tick(1.0)                                         # follow due -> auto GO
    st = e.status()
    assert st["label"] == "end" and st["state"] == "fading", st
    print("OK follow auto-advances")


def test_keepalive_reemits_standing_look():
    e = CueEngine()
    e.load(CUELIST)
    e.go(0.0)
    e.tick(2.0)                                         # fade done, emitted
    assert dmx(e.tick(2.1)) is None                     # unchanged, too soon
    arr = dmx(e.tick(2.0 + KEEPALIVE_S))                # stale -> keep-alive
    assert arr == [200, 100], arr
    print("OK keep-alive re-emits standing look")


def test_go_midfade_starts_from_true_position():
    # audit fix: GO during a fade must snapshot the interpolated NOW value,
    # not whatever the last tick left in _live
    e = CueEngine()
    e.load([{"label": "a", "fade": 10.0, "levels": {"0": {"1": 100}}},
            {"label": "b", "fade": 10.0, "levels": {"0": {"1": 0}}}])
    e.go(0.0)
    e.tick(1.0)                                         # live = [10]
    e.go(9.0)                                           # no tick since 1.0!
    arr = dmx(e.tick(9.0))                              # new fade starts at k=0
    assert arr == [90], arr                             # 90, not stale 10
    print("OK go mid-fade starts from true position")


def test_follow_tick_emits_new_cue_frame():
    # audit fix: the tick where follow fires must emit the NEW cue's look,
    # including universes it introduces
    e = CueEngine()
    e.load([{"label": "a", "fade": 0, "levels": {"0": {"1": 50}}, "follow": 1.0},
            {"label": "b", "fade": 0, "levels": {"1": {"1": 200}}}])
    e.go(0.0)
    e.tick(0.0)
    ev = e.tick(1.0)                                    # follow fires here
    got = {u: arr for k, u, arr in [x for x in ev if x[0] == "dmx"]}
    assert got.get(0) == [0], got                       # tracking off: u0 drops
    assert got.get(1) == [200], got                     # new universe emitted NOW
    print("OK follow tick emits new cue frame")


def test_load_resets_previous_show():
    # audit fix: loading a new list must not keep transmitting the old look
    e = CueEngine()
    e.load(CUELIST)
    e.go(0.0); e.tick(2.0)                              # standing look, active
    e.load([{"label": "x", "fade": 0, "levels": {"5": {"1": 10}}}])
    assert e.active is False
    assert e.tick(10.0) == [], "no stale emission after load"
    st = e.status()
    assert st["position"] == -1 and st["universes"] == [], st
    print("OK load resets previous show")


def test_go_requires_cuelist_and_valid_index():
    e = CueEngine()
    try:
        e.go(0.0)
        raise AssertionError("go without cues should fail")
    except CueError:
        pass
    e.load(CUELIST)
    for bad in (-1, 99):
        try:
            e.go(0.0, index=bad)
            raise AssertionError("index %r should fail" % bad)
        except CueError:
            pass
    print("OK go guards cuelist + index")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

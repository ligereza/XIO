"""
Off-device tests for the timecode timeline (pure transport scheduler).
    py xio/new-plugins/showcontrol/test_timeline.py

An injected clock stands in for wall time: feed play/pause/locate/due explicit
`now` values and assert which cues come due.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timeline import Timeline, TimelineError  # noqa: E402


EVENTS = [
    {"at": 0.0, "cue": 0, "label": "open"},
    {"at": 5.0, "cue": 1, "label": "build"},
    {"at": 12.0, "cue": 2, "label": "peak"},
    {"at": 20.0, "cue": 3, "label": "out"},
]


def test_load_sorts_and_reports():
    t = Timeline()
    info = t.load([{"at": 12, "cue": 2}, {"at": 0, "cue": 0}, {"at": 5, "cue": 1}])
    assert info == {"events": 3, "duration": 12.0}, info
    assert not t.playing
    print("OK load sorts by time, reports duration")


def test_fires_cues_as_playhead_passes():
    t = Timeline()
    t.load(EVENTS)
    t.play(now=100.0)                       # anchor at monotonic 100
    assert t.due(now=100.0) == [0]          # t=0 event fires immediately
    assert t.due(now=104.0) == []           # nothing between 0 and 5
    assert t.due(now=106.0) == [1]          # crossed 5s
    assert t.due(now=125.0) == [2, 3]       # crossed both 12 and 20 in one tick
    assert t.due(now=130.0) == []           # all fired
    print("OK cues fire once as the playhead passes their time")


def test_pause_freezes_and_resumes():
    t = Timeline()
    t.load(EVENTS)
    t.play(now=0.0)
    t.due(now=0.0)                          # fires cue 0
    t.pause(now=3.0)                        # playhead frozen at 3.0
    assert abs(t.status()["position"] - 3.0) < 1e-9
    assert t.due(now=999.0) == []           # paused: no firing regardless of clock
    t.play(now=50.0)                        # resume: playhead continues from 3.0
    assert abs(t.position(now=52.0) - 5.0) < 1e-9   # 3 + (52-50) = 5
    assert t.due(now=52.0) == [1]           # cue at 5s now due
    print("OK pause freezes the playhead; resume continues from there")


def test_no_double_fire_on_repeated_tick():
    t = Timeline()
    t.load(EVENTS)
    t.play(now=0.0)
    assert t.due(now=6.0) == [0, 1]
    assert t.due(now=6.0) == []             # same playhead, edge-triggered
    assert t.due(now=6.0) == []
    print("OK a cue never double-fires at the same playhead")


def test_locate_marks_past_as_fired():
    t = Timeline()
    t.load(EVENTS)
    t.locate(13.0)                          # jump past cues 0,1,2
    t.play(now=0.0)
    assert t.due(now=0.0) == []             # 0,1,2 already passed -> not retriggered
    assert t.due(now=8.0) == [3]            # position 13 -> 21 crosses the 20s cue
    print("OK locate marks earlier cues passed; only later ones fire")


def test_locate_while_playing_reanchors():
    t = Timeline()
    t.load(EVENTS)
    t.play(now=100.0)
    t.locate(11.0, now=100.0)               # jump to 11s while rolling
    assert abs(t.position(now=100.0) - 11.0) < 1e-9
    assert t.due(now=102.0) == [2]          # 11 -> 13 crosses the 12s cue
    print("OK locate while playing re-anchors the clock")


def test_validation():
    for bad in ([], "x", [{"cue": 1}], [{"at": -1, "cue": 0}],
                [{"at": 1, "cue": "z"}], [{"at": 1, "cue": -2}]):
        try:
            Timeline().load(bad)
            raise AssertionError("accepted bad events %r" % (bad,))
        except TimelineError:
            pass
    t = Timeline()
    try:
        t.play(now=0.0); raise AssertionError("played with nothing loaded")
    except TimelineError:
        pass
    print("OK validation rejects bad events / play-without-load")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

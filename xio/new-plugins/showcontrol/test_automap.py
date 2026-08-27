"""
Off-device tests for optical DMX auto-mapping (the sonda/p_inv estimator).
    py xio/new-plugins/showcontrol/test_automap.py

A synthetic linear transport stands in for the camera: each frame's measurement
is ambient + level * sum(response of the actuated channels). We check that both
sweep modes recover the per-channel response, that Hadamard rejects ambient, and
that multiplexing beats one-channel-at-a-time under measurement noise.
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import automap as A  # noqa: E402


def measure(emit, resp, ambient, level, noise=0.0, rng=None):
    """Synthetic sensor: linear light transport + ambient (+ optional noise)."""
    val = ambient + level * sum(resp.get(ch, 0.0) for ch in emit)
    if noise and rng is not None:
        val += rng.gauss(0.0, noise)
    return val


def run_sweep(p, resp, ambient, level, noise=0.0, rng=None):
    return [measure(step["emit"], resp, ambient, level, noise, rng) for step in p["steps"]]


def test_hadamard_orthogonal():
    for order in (1, 2, 4, 8, 16):
        H = A.hadamard(order)
        assert len(H) == order and all(len(r) == order for r in H)
        for i in range(order):           # rows orthogonal, H.H^T = n*I
            for j in range(order):
                dot = sum(H[i][k] * H[j][k] for k in range(order))
                assert dot == (order if i == j else 0), (order, i, j, dot)
    print("OK hadamard is orthogonal (H.H^T = n*I) up to order 16")


def test_next_pow2():
    assert [A.next_pow2(x) for x in (1, 2, 3, 5, 8, 9, 33)] == [1, 2, 4, 8, 8, 16, 64]
    print("OK next_pow2")


def test_plan_single():
    p = A.plan([1, 5, 10], level=200, mode="single")
    assert p["n"] == 3 and len(p["steps"]) == 3
    assert p["steps"][1]["emit"] == {5: 200}
    print("OK plan single: one frame per channel")


def test_plan_hadamard_partitions():
    p = A.plan([1, 5, 10], level=255, mode="hadamard")
    assert p["n"] == 4 and len(p["steps"]) == 8       # 2 frames per code row, n=4
    # row 0 is all +1 -> minus frame empty (a pure ambient/dark read)
    assert p["steps"][0]["emit"] and p["steps"][1]["emit"] == {}
    # every non-empty frame only actuates declared channels at the given level
    for step in p["steps"]:
        for ch, lv in step["emit"].items():
            assert ch in (1, 5, 10) and lv == 255
    print("OK plan hadamard: 2n frames, row0 minus is the dark frame")


def test_solve_single_recovers():
    chans = [1, 5, 10, 3]
    resp = {1: 0.5, 5: 0.2, 10: 0.9, 3: 0.05}
    level, ambient = 255, 12.0
    p = A.plan(chans, level=level, mode="single")
    m = run_sweep(p, resp, ambient, level)
    out = A.solve(chans, m, level=level, mode="single")
    # single mode returns raw brightness = ambient + level*response (patch signal)
    for ch in chans:
        assert abs(out["response"][ch] - (ambient + level * resp[ch])) < 1e-6
    assert out["residual"] == 0.0
    print("OK solve single recovers raw per-channel brightness")


def test_solve_hadamard_recovers_and_rejects_ambient():
    chans = [2, 7, 11, 4, 9]              # k=5 -> n=8
    resp = {2: 0.5, 7: 0.9, 11: 0.1, 4: 0.7, 9: 0.3}
    level, ambient = 255, 40.0            # big ambient: must cancel out
    p = A.plan(chans, level=level, mode="hadamard")
    m = run_sweep(p, resp, ambient, level)
    out = A.solve(chans, m, level=level, mode="hadamard")
    for ch in chans:
        assert abs(out["response"][ch] - resp[ch]) < 1e-9, (ch, out["response"][ch])
    assert out["residual"] < 1e-9        # no energy leaked into padding channels
    print("OK solve hadamard recovers response exactly, ambient cancels, residual~0")


def test_hadamard_beats_single_under_noise():
    chans = list(range(1, 9))            # 8 channels, n=8
    resp = {c: (c % 5) / 5.0 + 0.1 for c in chans}
    level, ambient, noise = 255, 30.0, 6.0
    single_err = had_err = 0.0
    trials = 40
    for seed in range(trials):
        rng = random.Random(seed)
        ps = A.plan(chans, level=level, mode="single")
        ms = run_sweep(ps, resp, ambient, level, noise, rng)
        os_ = A.solve(chans, ms, level=level, mode="single")
        # fair single estimate of response: remove known ambient, de-scale
        for ch in chans:
            est = (os_["response"][ch] - ambient) / level
            single_err += (est - resp[ch]) ** 2
        ph = A.plan(chans, level=level, mode="hadamard")
        mh = run_sweep(ph, resp, ambient, level, noise, rng)
        oh = A.solve(chans, mh, level=level, mode="hadamard")
        for ch in chans:
            had_err += (oh["response"][ch] - resp[ch]) ** 2
    # multiplex advantage: variance ~ 2/n of single -> clearly lower total error
    assert had_err < single_err * 0.6, (had_err, single_err)
    print("OK multiplexed (hadamard) error %.4f < single %.4f under noise"
          % (had_err, single_err))


def test_validation():
    for chans, mode in (([], "single"), ([1, 1], "single"),
                        ([0], "single"), ([513], "single"), ([1], "midi")):
        try:
            A.plan(chans, mode=mode)
            raise AssertionError("plan accepted bad %r/%s" % (chans, mode))
        except ValueError:
            pass
    try:
        A.solve([1, 2], [1.0], mode="single")   # wrong count
        raise AssertionError("solve accepted wrong measurement count")
    except ValueError:
        pass
    print("OK validation rejects bad channels/mode/measurement-count")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

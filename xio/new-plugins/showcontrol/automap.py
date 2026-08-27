"""
Optical DMX auto-mapping -- the `sonda`/p_inv node of xio-concept.html made real.

Light transport is linear in the DMX level: measured_light = T . dmx. So if you
actuate a *basis* of channels and measure the response, you recover T column by
column -- and T IS the patch: which channel drives which fixture, learned
optically, no manual addressing. (Sen et al. 2005, dual photography.)

Two sweep modes:
  - "single": actuate one channel at a time (n frames, simplest, no SNR gain).
  - "hadamard": actuate Hadamard-coded groups (Schechner et al. 2007, multiplexed
    illumination). Because light can't be negative, each +-1 code row is emitted
    as two frames -- the +1 channels, then the -1 channels -- and subtracted. The
    differential cancels ambient light exactly and, since Sylvester Hadamard is
    symmetric with H.H = n.I, recovery is simply t = (1/n) H . d.

Pure stdlib, no numpy, no sockets: plan() returns the frames to emit, solve()
turns the caller's measurements back into per-channel responses. The camera /
sensor is the operator's hardware; the sequencing and the estimator are ours.
Unit-tested off-device against a synthetic transport (test_automap.py).
"""

MAX_CHANNELS = 256               # keeps hadamard n <= 512 (one Art-Net universe)


def next_pow2(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


def hadamard(order: int):
    """Sylvester-Hadamard matrix of a power-of-two order (entries +-1).

    Doubling rule:  H_2m = [[H_m,  H_m],
                            [H_m, -H_m]].
    """
    if order < 1 or (order & (order - 1)) != 0:
        raise ValueError("hadamard order must be a power of two, got %d" % order)
    H = [[1]]
    while len(H) < order:
        H = ([row + row for row in H] +                 # top:    [H_m   H_m]
             [row + [-x for x in row] for row in H])     # bottom: [H_m  -H_m]
    return H


def _check_channels(channels):
    if not isinstance(channels, (list, tuple)) or not channels:
        raise ValueError("channels must be a non-empty list")
    if len(channels) > MAX_CHANNELS:
        raise ValueError("too many channels (max %d)" % MAX_CHANNELS)
    out = []
    seen = set()
    for c in channels:
        ci = int(c)
        if not (1 <= ci <= 512):
            raise ValueError("channel out of range 1..512: %r" % c)
        if ci in seen:
            raise ValueError("duplicate channel: %d" % ci)
        seen.add(ci)
        out.append(ci)
    return out


def plan(channels, level: int = 255, mode: str = "single"):
    """Return the ordered sweep: {mode, level, n, channels, steps:[{id, emit:{ch:level}}]}.

    The caller emits each step's `emit` frame, measures the scene, and feeds the
    per-step scalar back to solve() in the SAME order.
    """
    channels = _check_channels(channels)
    level = int(level)
    if not (1 <= level <= 255):
        raise ValueError("level out of range 1..255")
    if mode == "single":
        steps = [{"id": "c%d" % c, "emit": {c: level}} for c in channels]
        return {"mode": "single", "level": level, "n": len(channels),
                "channels": channels, "steps": steps}
    if mode == "hadamard":
        n = next_pow2(len(channels))
        H = hadamard(n)
        steps = []
        for j in range(n):
            plus = {channels[i]: level for i in range(len(channels)) if H[j][i] > 0}
            minus = {channels[i]: level for i in range(len(channels)) if H[j][i] < 0}
            steps.append({"id": "h%d+" % j, "emit": plus})
            steps.append({"id": "h%d-" % j, "emit": minus})
        return {"mode": "hadamard", "level": level, "n": n,
                "channels": channels, "steps": steps}
    raise ValueError("mode must be 'single' or 'hadamard'")


def solve(channels, measurements, level: int = 255, mode: str = "single"):
    """Recover per-channel optical response from measurements aligned to plan().steps.

    Returns {"response": {channel: value}, "residual": float}. `residual` is the
    energy that leaked into Hadamard padding channels (should be ~0 for a clean
    linear measurement); it's a self-check on the estimate (0.0 for single mode).
    """
    channels = _check_channels(channels)
    level = int(level)
    if level <= 0:
        raise ValueError("level must be positive")
    meas = [float(m) for m in measurements]
    k = len(channels)
    if mode == "single":
        if len(meas) != k:
            raise ValueError("expected %d measurements, got %d" % (k, len(meas)))
        return {"response": {channels[i]: meas[i] for i in range(k)}, "residual": 0.0}
    if mode == "hadamard":
        n = next_pow2(k)
        if len(meas) != 2 * n:
            raise ValueError("expected %d measurements (2 per code row), got %d"
                             % (2 * n, len(meas)))
        H = hadamard(n)
        d = [(meas[2 * j] - meas[2 * j + 1]) / level for j in range(n)]   # ambient cancels
        t = [sum(H[i][j] * d[j] for j in range(n)) / n for i in range(n)]  # t = (1/n) H d
        residual = sum(t[i] * t[i] for i in range(k, n)) ** 0.5
        return {"response": {channels[i]: t[i] for i in range(k)}, "residual": residual}
    raise ValueError("mode must be 'single' or 'hadamard'")

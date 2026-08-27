"""
Off-device tests for OSC input (parser + closed action table).
    py xio/new-plugins/showcontrol/test_oscin.py

Key property: parse(build_osc_message(x)) round-trips -- the send path
(protocols.py) and the receive path validate each other.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oscin as O  # noqa: E402
import protocols as P  # noqa: E402


def test_roundtrip_against_builder():
    cases = [
        ("/xio/go", []),
        ("/xio/go", [3]),
        ("/xio/release", [2.5]),
        ("/xio/signal/master", [0.75]),
        ("/mixed", [1, 2.0, "text", True, False]),
        ("/blob", [b"\x01\x02\x03"]),
    ]
    for addr, args in cases:
        got_addr, got_args = O.parse_message(P.build_osc_message(addr, args))
        assert got_addr == addr, (addr, got_addr)
        assert len(got_args) == len(args)
        for a, b in zip(args, got_args):
            if isinstance(a, float):
                assert abs(a - b) < 1e-6, (a, b)
            elif isinstance(a, (bytes, bytearray)):
                assert bytes(a) == b, (a, b)
            else:
                assert a == b and type(a) is type(b), (a, b)
    print("OK parse(build(x)) round-trips: send and receive paths agree")


def test_bundle_flattens():
    m1 = P.build_osc_message("/xio/go", [])
    m2 = P.build_osc_message("/xio/signal/hue", [0.5])
    bundle = b"#bundle\x00" + b"\x00" * 8
    for m in (m1, m2):
        bundle += struct.pack(">i", len(m)) + m
    out = O.parse_packet(bundle)
    assert [a for a, _ in out] == ["/xio/go", "/xio/signal/hue"], out
    print("OK #bundle flattens to its messages (timetag ignored)")


def test_parse_rejects_garbage():
    for bad in (b"no-slash\x00\x00", b"/x\x00\x00,i\x00\x00",  # truncated int
                b"/x\x00\x00,q\x00\x00AAAA",                    # unknown tag
                b"#bundle\x00" + b"\x00" * 8 + struct.pack(">i", 999) + b"xx",
                b"\xff\xfe\xfd"):
        try:
            O.parse_packet(bad)
            raise AssertionError("accepted %r" % (bad[:16],))
        except (O.OscParseError, UnicodeDecodeError):
            pass
    print("OK malformed packets rejected")


def test_map_action_table():
    assert O.map_action("/xio/go", []) == ("go", None)
    assert O.map_action("/xio/go", [2]) == ("go", 2)
    assert O.map_action("/xio/go", [-1]) == ("go", None)       # bad index -> plain GO
    assert O.map_action("/xio/stop", []) == ("stop",)
    assert O.map_action("/xio/release", []) == ("release", 2.0)
    assert O.map_action("/xio/release", [5]) == ("release", 5.0)
    assert O.map_action("/xio/release", [9999]) == ("release", 300.0)  # clamped
    assert O.map_action("/xio/timeline/play", []) == ("tl_play",)
    assert O.map_action("/xio/timeline/pause", []) == ("tl_pause",)
    assert O.map_action("/xio/timeline/locate", [11.5]) == ("tl_locate", 11.5)
    assert O.map_action("/xio/timeline/locate", []) is None
    assert O.map_action("/xio/timeline/locate", [-2]) is None
    assert O.map_action("/xio/signal/master", [0.5]) == ("signal", "master", 0.5)
    assert O.map_action("/xio/signal/master", [1.5]) is None   # out of 0..1
    assert O.map_action("/xio/signal/master", []) is None
    assert O.map_action("/xio/signal/", [0.5]) is None         # empty name
    assert O.map_action("/xio/signal/a/b", [0.5]) is None      # nested -> rejected
    print("OK closed action table maps and clamps correctly")


def test_unknown_addresses_ignored():
    for addr in ("/other/thing", "/xio/unknown", "/", "/xio"):
        assert O.map_action(addr, [1]) is None, addr
    # booleans must not masquerade as numbers (bool is a subclass of int)
    assert O.map_action("/xio/go", [True]) == ("go", None)
    assert O.map_action("/xio/release", [True]) == ("release", 2.0)
    print("OK unknown addresses -> None; bools don't pose as numbers")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

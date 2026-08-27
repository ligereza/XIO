"""
Off-device byte-layout tests for the OSC / Art-Net / sACN builders.

xio is not part of the repo pytest suite (it targets on-device), so this runs
standalone: `py xio/new-plugins/showcontrol/test_protocols.py` (or in Termux).
It asserts the packets against the public specs -- no hardware needed.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protocols as P  # noqa: E402


def test_osc_int():
    pkt = P.build_osc_message("/ch", [255])
    # "/ch\0" (4) + ",i\0\0" (4) + int32(255) big-endian (4)
    assert pkt == b"/ch\x00,i\x00\x00\x00\x00\x00\xff", pkt
    print("OK osc int")


def test_osc_mixed():
    pkt = P.build_osc_message("/x", [1, 2.5, "hi", True, False])
    addr = P._osc_string("/x")
    tags = P._osc_string(",ifsTF")
    assert pkt.startswith(addr + tags), pkt
    body = pkt[len(addr) + len(tags):]
    assert body[:4] == struct.pack(">i", 1)
    assert body[4:8] == struct.pack(">f", 2.5)
    assert body[8:12] == b"hi\x00\x00"          # "hi" padded to 4
    assert len(body) == 12                       # bools carry no bytes
    print("OK osc mixed")


def test_osc_rejects_bad_address():
    for bad in ["noslash", 42, ""]:
        try:
            P.build_osc_message(bad, [])
            raise AssertionError("should have rejected %r" % bad)
        except ValueError:
            pass
    print("OK osc rejects bad address")


def test_artnet_header():
    pkt = P.build_artnet_dmx(0, [255, 0])
    assert pkt[:8] == b"Art-Net\x00", pkt[:8]
    assert pkt[8:10] == struct.pack("<H", 0x5000)     # OpCode LE
    assert pkt[10:12] == struct.pack(">H", 14)        # ProtVer BE
    assert pkt[12] == 0 and pkt[13] == 0              # seq, physical
    assert pkt[14] == 0 and pkt[15] == 0              # subuni, net
    assert pkt[16:18] == struct.pack(">H", 2)         # length BE
    assert pkt[18:] == b"\xff\x00"
    print("OK artnet header")


def test_artnet_universe_split():
    pkt = P.build_artnet_dmx((3 << 8) | 5, [1])       # net=3, subuni=5
    assert pkt[14] == 5 and pkt[15] == 3
    assert pkt[16:18] == struct.pack(">H", 2)         # 1 ch padded to even 2
    print("OK artnet universe split")


def test_artnet_channels_dict():
    pkt = P.build_artnet_dmx(0, {"1": 255, "4": 128})
    assert pkt[18:] == b"\xff\x00\x00\x80"            # ch1=255, ch4=128
    print("OK artnet channels dict")


def test_sacn_structure():
    pkt = P.build_sacn_dmx(1, [255])
    assert pkt[0:4] == b"\x00\x10\x00\x00"            # preamble/postamble
    assert pkt[4:16] == b"ASC-E1.17\x00\x00\x00"      # ACN identifier
    # root flags+length: low 12 bits == remaining length after this 2-byte field
    flen = struct.unpack(">H", pkt[16:18])[0]
    assert (flen & 0xF000) == 0x7000
    assert (flen & 0x0FFF) == len(pkt) - 16
    assert pkt[18:22] == struct.pack(">I", 0x00000004)  # root vector
    assert pkt.endswith(b"\x00\xff")                  # DMX start code + ch1=255
    print("OK sacn structure")


def test_sacn_multicast_ip():
    assert P.sacn_multicast_ip(1) == "239.255.0.1"
    assert P.sacn_multicast_ip(0x0102) == "239.255.1.2"
    print("OK sacn multicast ip")


def test_wol_magic_packet():
    pkt = P.build_magic_packet("AA:BB:CC:DD:EE:FF")
    assert len(pkt) == 102, len(pkt)                  # 6 + 16*6
    assert pkt[:6] == b"\xff" * 6
    assert pkt[6:12] == bytes.fromhex("aabbccddeeff")
    assert pkt[96:102] == bytes.fromhex("aabbccddeeff")
    # same MAC, other notations
    assert P.build_magic_packet("aa-bb-cc-dd-ee-ff") == pkt
    assert P.build_magic_packet("aabbccddeeff") == pkt
    print("OK wol magic packet")


def test_wol_rejects_bad_mac():
    for bad in ("zz:bb:cc:dd:ee:ff", "aabbcc", "", 42, "aa:bb:cc:dd:ee:ff:00"):
        try:
            P.build_magic_packet(bad)
            raise AssertionError("should have rejected %r" % (bad,))
        except ValueError:
            pass
    print("OK wol rejects bad mac")


def test_dmx_validation():
    for bad in ([256], [-1], list(range(513)), "x", {"0": 1}, {"513": 1}):
        try:
            P.normalize_dmx(bad)
            raise AssertionError("should have rejected %r" % (bad,))
        except (ValueError, TypeError):
            pass
    print("OK dmx validation")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

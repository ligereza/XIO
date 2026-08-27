"""
Off-device tests for the `sonda` node: Art-Net discovery.
    py xio/new-plugins/showcontrol/test_discovery.py

Pure build/parse against hand-crafted bytes, plus one over-the-wire pass where a
virtual Art-Net node (a localhost UDP socket in a thread) answers a real ArtPoll.
"""

import os
import socket
import struct
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discovery as D  # noqa: E402


def make_poll_reply(ip="192.168.1.50", short="xio-node",
                    long_name="XIO Virtual Art-Net Node", mac=(0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF),
                    oem=0x00FF, ports=1, sw_out=(3, 0, 0, 0), report="#0001 [0000] OK"):
    """Build a spec-shaped 239-byte ArtPollReply by writing fields at fixed offsets."""
    p = bytearray(239)
    p[0:8] = D.ARTNET_ID
    p[8:10] = struct.pack("<H", D.OP_POLL_REPLY)
    p[10:14] = bytes(int(o) for o in ip.split("."))
    p[14:16] = struct.pack("<H", D.ARTNET_PORT)
    p[16:18] = struct.pack(">H", 0x0001)
    p[18] = 0                                   # net
    p[19] = 0                                   # subnet
    p[20:22] = struct.pack(">H", oem)
    p[23] = 0xD2                                # status1
    sn = short.encode("ascii")[:17]
    p[26:26 + len(sn)] = sn
    ln = long_name.encode("ascii")[:63]
    p[44:44 + len(ln)] = ln
    rep = report.encode("ascii")[:63]
    p[108:108 + len(rep)] = rep
    p[172:174] = struct.pack(">H", ports)
    p[190:194] = bytes(sw_out)
    p[201:207] = bytes(mac)
    return bytes(p)


def test_build_artpoll():
    pkt = D.build_artpoll()
    assert len(pkt) == 14, len(pkt)
    assert pkt[:8] == D.ARTNET_ID
    assert struct.unpack("<H", pkt[8:10])[0] == D.OP_POLL
    assert struct.unpack(">H", pkt[10:12])[0] == D.PROT_VER
    assert pkt[12] == 0 and pkt[13] == 0        # talk_to_me, priority
    print("OK build_artpoll: 14 bytes, opcode 0x2000")


def test_is_poll_reply():
    assert D.is_poll_reply(make_poll_reply())
    assert not D.is_poll_reply(D.build_artpoll())          # that's a poll, not a reply
    assert not D.is_poll_reply(b"Art-Net\x00\x00\x50")     # ArtDMX opcode
    assert not D.is_poll_reply(b"nope")
    print("OK is_poll_reply gates on id + opcode")


def test_parse_poll_reply():
    node = D.parse_poll_reply(make_poll_reply(ip="10.0.0.7", short="rig-A",
                                              mac=(0x01, 0x23, 0x45, 0x67, 0x89, 0xAB),
                                              oem=0x1234, ports=2, sw_out=(5, 6, 0, 0)))
    assert node["ip"] == "10.0.0.7", node["ip"]
    assert node["port"] == 6454
    assert node["short_name"] == "rig-A", node["short_name"]
    assert node["long_name"] == "XIO Virtual Art-Net Node"
    assert node["oem"] == 0x1234
    assert node["ports"] == 2
    assert node["sw_out"] == [5, 6], node["sw_out"]        # trimmed to port count
    assert node["mac"] == "01:23:45:67:89:AB", node["mac"]
    print("OK parse_poll_reply extracts ip/name/oem/mac/sw_out")


def test_parse_rejects_garbage():
    for bad in (b"", b"Art-Net\x00", b"Art-Net\x00\x00\x50" + b"\x00" * 20,  # ArtDMX
                make_poll_reply()[:20]):                                      # truncated
        try:
            D.parse_poll_reply(bad)
            raise AssertionError("should have rejected %r" % (bad[:12],))
        except ValueError:
            pass
    print("OK parse rejects short/wrong-opcode packets")


def test_discover_over_the_wire():
    """A virtual node answers a real ArtPoll; discover() collects and dedups it."""
    node = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    node.bind(("127.0.0.1", 0))
    node.settimeout(3.0)
    node_port = node.getsockname()[1]
    reply = make_poll_reply(ip="127.0.0.1", short="virt-node")

    def serve():
        try:
            _, sender = node.recvfrom(64)      # the ArtPoll
            node.sendto(reply, sender)         # ... answer twice to prove dedup
            node.sendto(reply, sender)
        except OSError:
            pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    # bind_port=0: ephemeral local port so the node's unicast reply reaches us
    # (real hardware broadcasts to 6454; discover() binds 6454 by default for that)
    nodes = D.discover(timeout=2.0, broadcast_host="127.0.0.1", port=node_port, bind_port=0)
    t.join(1.0)
    node.close()

    assert len(nodes) == 1, [n["ip"] for n in nodes]       # two replies -> one node
    assert nodes[0]["ip"] == "127.0.0.1"
    assert nodes[0]["short_name"] == "virt-node", nodes[0]
    print("OK discover over the wire (ArtPoll -> reply -> parsed + deduped)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

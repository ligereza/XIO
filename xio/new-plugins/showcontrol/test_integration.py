"""
Integration test: cue engine -> packet builders -> real UDP -> virtual node.

The xiotech M2 acceptance item ("nodo Art-Net virtual + servidor OSC dummy")
without hardware: two localhost UDP listeners play Art-Net node and OSC server,
the engine runs a 3-cue show, and we assert the actual bytes on the wire.
Standalone like the other tests:  py xio/new-plugins/showcontrol/test_integration.py
"""

import os
import socket
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protocols as P            # noqa: E402
from cueengine import CueEngine  # noqa: E402


def make_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(2.0)
    return s, s.getsockname()[1]


def send_events(events, artnet_addr, osc_addr, seq_state):
    """Mirror of the plugin's _emit_events, Flask-free."""
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for ev in events:
            if ev[0] == "osc":
                out.sendto(P.build_osc_message(ev[1], ev[2]), osc_addr)
            elif ev[0] == "dmx":
                u = ev[1]
                seq_state[u] = seq_state.get(u, 0) % 255 + 1
                out.sendto(P.build_artnet_dmx(u, ev[2], sequence=seq_state[u]),
                           artnet_addr)
    finally:
        out.close()


def parse_artnet(pkt):
    assert pkt[:8] == b"Art-Net\x00"
    (op,) = struct.unpack("<H", pkt[8:10])
    assert op == 0x5000
    seq = pkt[12]
    universe = pkt[14] | (pkt[15] << 8)
    (length,) = struct.unpack(">H", pkt[16:18])
    return seq, universe, pkt[18:18 + length]


def test_show_over_the_wire():
    node, node_port = make_listener()      # virtual Art-Net node
    oscsrv, osc_port = make_listener()     # dummy OSC server
    artnet_addr = ("127.0.0.1", node_port)
    osc_addr = ("127.0.0.1", osc_port)

    e = CueEngine()
    e.load([
        {"label": "open", "fade": 2.0, "levels": {"0": {"1": 200, "2": 100}},
         "osc": [{"address": "/scene/open", "args": [1, 0.5]}]},
        {"label": "cross", "fade": 2.0, "levels": {"0": {"2": 255}}},
    ])
    seq_state = {}

    # GO cue 1: first tick carries the OSC trigger + the k=0 DMX frame
    e.go(0.0)
    send_events(e.tick(0.0), artnet_addr, osc_addr, seq_state)
    osc_pkt = oscsrv.recv(2048)
    assert osc_pkt.startswith(P._osc_string("/scene/open") + P._osc_string(",if"))
    seq, uni, dmx = parse_artnet(node.recv(2048))
    assert (seq, uni) == (1, 0) and dmx[:2] == b"\x00\x00", (seq, uni, dmx[:2])

    # halfway through the 2 s fade: ch1=100, ch2=50, sequence advanced
    send_events(e.tick(1.0), artnet_addr, osc_addr, seq_state)
    seq, uni, dmx = parse_artnet(node.recv(2048))
    assert (seq, uni) == (2, 0) and dmx[:2] == b"\x64\x32", (seq, dmx[:2])

    # fade complete: the full look
    send_events(e.tick(2.0), artnet_addr, osc_addr, seq_state)
    seq, _, dmx = parse_artnet(node.recv(2048))
    assert dmx[:2] == b"\xc8\x64", dmx[:2]

    # GO cue 2, land it: ch1 drops to 0 (tracking off), ch2 rises to 255
    e.go(10.0)
    send_events(e.tick(12.0), artnet_addr, osc_addr, seq_state)
    _, _, dmx = parse_artnet(node.recv(2048))
    assert dmx[:2] == b"\x00\xff", dmx[:2]

    # RELEASE to black
    e.release(20.0, fade=1.0)
    send_events(e.tick(21.0), artnet_addr, osc_addr, seq_state)
    _, _, dmx = parse_artnet(node.recv(2048))
    assert dmx[:2] == b"\x00\x00", dmx[:2]
    assert e.active is False

    node.close(); oscsrv.close()
    print("OK show over the wire (OSC + Art-Net virtual node)")


def test_sequence_wraps_at_255():
    seq_state = {0: 254}
    node, port = make_listener()
    send_events([("dmx", 0, [1])], ("127.0.0.1", port), None, seq_state)
    send_events([("dmx", 0, [1])], ("127.0.0.1", port), None, seq_state)
    s1, _, _ = parse_artnet(node.recv(2048))
    s2, _, _ = parse_artnet(node.recv(2048))
    assert (s1, s2) == (255, 1), (s1, s2)   # wraps 255 -> 1, never 0
    node.close()
    print("OK sequence wraps 255 -> 1")


def send_fabric_events(events, artnet_addr, seq_state):
    """Mirror of the plugin's _emit_fabric: DMX -> the fabric output target,
    OSC -> the route-local host/port carried in the event itself."""
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for ev in events:
            if ev[0] == "osc":                       # (osc, host, port, addr, args)
                _, host, port, addr, args = ev
                out.sendto(P.build_osc_message(addr, args), (host, port))
            elif ev[0] == "dmx":                     # (dmx, universe, levels)
                u = ev[1]
                seq_state[u] = seq_state.get(u, 0) % 255 + 1
                out.sendto(P.build_artnet_dmx(u, ev[2], sequence=seq_state[u]),
                           artnet_addr)
    finally:
        out.close()


def test_timeline_drives_cues_over_the_wire():
    """The orq capstone: a timeline fires cues on a clock, cues hit the Art-Net
    node -- the show plays itself. Mirrors _cue_loop (due -> go -> tick -> emit)
    with an injected clock so it's deterministic."""
    from timeline import Timeline

    node, node_port = make_listener()
    artnet_addr = ("127.0.0.1", node_port)
    e = CueEngine()
    e.load([
        {"label": "open", "fade": 0.0, "levels": {"0": {"1": 200}}},
        {"label": "peak", "fade": 0.0, "levels": {"0": {"2": 255}}},
    ])
    tl = Timeline()
    tl.load([{"at": 0.0, "cue": 0}, {"at": 5.0, "cue": 1}])
    seq_state = {}

    def loop_step(now):                        # exactly what _cue_loop does per tick
        for cue in tl.due(now):
            e.go(now, index=cue)
        send_events(e.tick(now), artnet_addr, None, seq_state)

    tl.play(now=0.0)
    loop_step(0.0)                             # t=0 -> cue 0 fires
    _, _, dmx = parse_artnet(node.recv(2048))
    assert dmx[:2] == b"\xc8\x00", dmx[:2]     # cue0: ch1=200 (0xc8)
    loop_step(6.0)                             # crossed 5s -> cue 1 fires
    _, _, dmx = parse_artnet(node.recv(2048))
    assert dmx[:2] == b"\x00\xff", dmx[:2]     # cue1: ch1->0 (tracking off), ch2=255

    node.close()
    print("OK timeline drives cues over the wire (show plays itself)")


def test_oscin_drives_engine_over_the_wire():
    """orq bidirectional: a real OSC datagram (same builder QLab-style senders
    use) arrives over UDP, runs the closed action table, and fires GO on the
    engine -- whose next tick emits the look as DMX."""
    from oscin import map_action, parse_packet

    rx, rx_port = make_listener()          # the "phone" listener socket
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    e = CueEngine()
    e.load([{"label": "open", "fade": 0.0, "levels": {"0": {"1": 255}}}])

    tx.sendto(P.build_osc_message("/xio/go", []), ("127.0.0.1", rx_port))
    data, _ = rx.recvfrom(8192)
    (act,) = [map_action(a, ar) for a, ar in parse_packet(data)]
    assert act == ("go", None), act
    e.go(5.0, index=act[1])
    assert e.active
    frame = [ev for ev in e.tick(5.0) if ev[0] == "dmx"][0]
    assert frame[2][0] == 255, frame       # the look landed: ch1=255

    tx.close(); rx.close()
    print("OK OSC-in datagram -> action table -> engine GO -> DMX frame")


def test_fabric_over_the_wire():
    """One `master` signal fans out to a DMX node AND an OSC fader in a single
    set() -- the routing-bus contract the plugin's _emit_fabric depends on."""
    from fabric import Fabric

    node, node_port = make_listener()      # virtual Art-Net node
    oscsrv, osc_port = make_listener()     # dummy OSC fader endpoint
    artnet_addr = ("127.0.0.1", node_port)

    f = Fabric()
    f.load({"signals": ["master"], "routes": [
        {"signal": "master", "sink": "dmx", "universe": 0, "channel": 1},
        {"signal": "master", "sink": "dmx", "universe": 0, "channel": 3, "max": 200},
        {"signal": "master", "sink": "osc", "host": "127.0.0.1", "port": osc_port,
         "address": "/master", "kind": "float"}]})
    seq_state = {}

    # one set() -> the OSC fader AND the fanned-out DMX frame both leave the wire
    send_fabric_events(f.set("master", 0.5), artnet_addr, seq_state)

    osc_pkt = oscsrv.recv(2048)
    assert osc_pkt.startswith(P._osc_string("/master") + P._osc_string(",f")), osc_pkt
    (val,) = struct.unpack(">f", osc_pkt[-4:])
    assert abs(val - 0.5) < 1e-6, val

    seq, uni, dmx = parse_artnet(node.recv(2048))
    # ch1 = round(0.5*255)=128 (0x80); ch3 = 0.5*200=100 (0x64); ch2 untouched
    assert (seq, uni) == (1, 0) and dmx[:3] == b"\x80\x00\x64", (seq, uni, dmx[:3])

    # keep-alive re-emits the standing DMX frame (Art-Net timeout guard), same levels
    send_fabric_events(f.keepalive(100.0), artnet_addr, seq_state)
    seq2, _, dmx2 = parse_artnet(node.recv(2048))
    assert seq2 == 2 and dmx2[:3] == b"\x80\x00\x64", (seq2, dmx2[:3])

    node.close(); oscsrv.close()
    print("OK fabric over the wire (one signal -> DMX node + OSC fader + keep-alive)")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))

"""
Art-Net node discovery -- the `sonda` node of xio-concept.html made real.

Before a show you want to SEE which fixtures are alive on the LAN, not send DMX
blind. Art-Net discovery is active: the controller broadcasts an ArtPoll
(OpCode 0x2000) to UDP 6454 and every node answers with an ArtPollReply
(0x2100) carrying its IP, names, MAC, OEM code and port map at fixed offsets.

Discipline mirrors protocols.py: the packet builder and the reply parser are
pure (no sockets, unit-tested against hand-crafted bytes in test_discovery.py);
only discover() touches the network -- one SO_BROADCAST send + a bounded recv
loop -- so there is no shell and no injection surface.

Layout references: Art-Net 4 spec, ArtPoll (14 bytes) and ArtPollReply (>=207).
"""

import socket
import struct
import time

ARTNET_ID = b"Art-Net\x00"
ARTNET_PORT = 6454
OP_POLL = 0x2000
OP_POLL_REPLY = 0x2100
PROT_VER = 14

MAX_NODES = 512          # hard cap so a hostile/broken LAN can't exhaust memory
MAX_REPLY = 1024         # ArtPollReply is <=239 bytes; anything longer is bogus


def build_artpoll(talk_to_me: int = 0x00, priority: int = 0x00) -> bytes:
    """ArtPoll (OpCode 0x2000): 8-byte id, opcode LE, ProtVer BE, TalkToMe, Priority."""
    if not (0 <= talk_to_me <= 0xFF):
        raise ValueError("talk_to_me out of range 0..255")
    if not (0 <= priority <= 0xFF):
        raise ValueError("priority out of range 0..255")
    pkt = ARTNET_ID
    pkt += struct.pack("<H", OP_POLL)        # OpCode, little-endian
    pkt += struct.pack(">H", PROT_VER)       # ProtVerHi/Lo, big-endian
    pkt += struct.pack("BB", talk_to_me, priority)
    return pkt


def is_poll_reply(pkt: bytes) -> bool:
    """Cheap gate: right id + ArtPollReply opcode."""
    return (len(pkt) >= 10 and pkt[:8] == ARTNET_ID
            and struct.unpack("<H", pkt[8:10])[0] == OP_POLL_REPLY)


def _cstr(raw: bytes) -> str:
    """Null-terminated ASCII field -> str, control bytes stripped."""
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


def parse_poll_reply(pkt: bytes) -> dict:
    """Parse an ArtPollReply into a node dict. Raises ValueError if malformed."""
    if not is_poll_reply(pkt):
        raise ValueError("not an ArtPollReply")
    if len(pkt) < 26:                        # need at least through EstaMan
        raise ValueError("ArtPollReply too short: %d bytes" % len(pkt))
    node = {
        "ip": "%d.%d.%d.%d" % (pkt[10], pkt[11], pkt[12], pkt[13]),
        "port": struct.unpack("<H", pkt[14:16])[0],
        "version": struct.unpack(">H", pkt[16:18])[0],
        "net": pkt[18],
        "subnet": pkt[19],
        "oem": struct.unpack(">H", pkt[20:22])[0],
        "status1": pkt[23],
    }
    node["short_name"] = _cstr(pkt[26:44]) if len(pkt) >= 44 else ""
    node["long_name"] = _cstr(pkt[44:108]) if len(pkt) >= 108 else ""
    node["report"] = _cstr(pkt[108:172]) if len(pkt) >= 172 else ""
    node["ports"] = struct.unpack(">H", pkt[172:174])[0] if len(pkt) >= 174 else 0
    if len(pkt) >= 190:                      # SwOut: the universe each output port emits
        node["sw_out"] = list(pkt[190:194][:min(node["ports"], 4)])
    if len(pkt) >= 207:
        node["mac"] = ":".join("%02X" % b for b in pkt[201:207])
    return node


def discover(timeout: float = 2.0, bind_host: str = "0.0.0.0",
             broadcast_host: str = "255.255.255.255", port: int = ARTNET_PORT,
             bind_port: int = ARTNET_PORT):
    """Broadcast one ArtPoll and collect ArtPollReply nodes until `timeout`.

    Returns a list of node dicts (deduped by IP, first reply wins), sorted by IP.
    Pure-Python UDP; no shell. Caller controls timeout so it can stay snappy on a
    phone. `bind_host`/`broadcast_host` scope to one interface.

    We bind the Art-Net port (6454) because a spec-compliant node BROADCASTS its
    ArtPollReply to 6454 -- an ephemeral bind would miss those. SO_REUSEADDR lets
    this coexist; if the port is taken we fall back to an ephemeral bind (still
    catches nodes that unicast their reply to the sender). Tests pass bind_port=0.
    """
    timeout = max(0.1, min(float(timeout), 10.0))
    deadline = time.monotonic() + timeout
    seen = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        try:
            sock.bind((bind_host, bind_port))
        except OSError:
            sock.bind((bind_host, 0))        # port busy -> ephemeral (unicast replies only)
        sock.sendto(build_artpoll(), (broadcast_host, port))
        while len(seen) < MAX_NODES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, addr = sock.recvfrom(MAX_REPLY)
            except socket.timeout:
                break
            except OSError:
                continue
            if not is_poll_reply(data):
                continue
            try:
                node = parse_poll_reply(data)
            except ValueError:
                continue
            node.setdefault("src", addr[0])  # who the packet actually came from
            seen.setdefault(node["ip"] or addr[0], node)
    finally:
        sock.close()
    return sorted(seen.values(), key=lambda n: _ip_key(n["ip"]))


def _ip_key(ip: str):
    try:
        return tuple(int(p) for p in ip.split("."))
    except ValueError:
        return (0, 0, 0, 0)

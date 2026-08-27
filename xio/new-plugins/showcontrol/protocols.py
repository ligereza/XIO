"""
Pure-stdlib packet builders for OSC, Art-Net and sACN/E1.31.

No dependency on the plugin framework -- importable and unit-testable off-device
(see test_protocols.py). This is the "nucleo duro": the byte layouts follow the
public specs exactly (OSC 1.0; Art-Net 4 ArtDMX OpCode 0x5000; ANSI E1.31 / sACN).
No shell is ever invoked here, so there is no command-injection surface.
"""

import socket
import struct

ARTNET_PORT = 6454
SACN_PORT = 5568


# ── OSC 1.0 ─────────────────────────────────────────────────────────────────
def _osc_string(s: str) -> bytes:
    b = s.encode("utf-8") + b"\x00"
    pad = (4 - (len(b) % 4)) % 4
    return b + (b"\x00" * pad)


def _osc_blob(data: bytes) -> bytes:
    pad = (4 - (len(data) % 4)) % 4
    return struct.pack(">i", len(data)) + data + (b"\x00" * pad)


def build_osc_message(address: str, args) -> bytes:
    """Build one OSC message. args: int->i, float->f, str->s, bool->T/F, bytes->b."""
    if not isinstance(address, str) or not address.startswith("/"):
        raise ValueError("OSC address must be a string starting with '/'")
    typetags = ","
    payload = b""
    for a in args or []:
        if isinstance(a, bool):
            typetags += "T" if a else "F"  # booleans carry no data bytes in OSC 1.0
        elif isinstance(a, int):
            typetags += "i"
            payload += struct.pack(">i", a)
        elif isinstance(a, float):
            typetags += "f"
            payload += struct.pack(">f", a)
        elif isinstance(a, str):
            typetags += "s"
            payload += _osc_string(a)
        elif isinstance(a, (bytes, bytearray)):
            typetags += "b"
            payload += _osc_blob(bytes(a))
        else:
            raise ValueError("unsupported OSC arg type: %s" % type(a).__name__)
    return _osc_string(address) + _osc_string(typetags) + payload


# ── Art-Net (ArtDMX, OpCode 0x5000) ─────────────────────────────────────────
def build_artnet_dmx(universe: int, data, sequence: int = 0) -> bytes:
    if not (0 <= universe <= 0x7FFF):
        raise ValueError("Art-Net universe out of range 0..32767")
    dmx = normalize_dmx(data)
    if len(dmx) % 2:            # ArtDMX length must be even
        dmx += b"\x00"
    length = len(dmx)
    pkt = b"Art-Net\x00"
    pkt += struct.pack("<H", 0x5000)                # OpCode, little-endian
    pkt += struct.pack(">H", 14)                    # ProtVer, big-endian
    pkt += struct.pack("BB", sequence & 0xFF, 0)    # Sequence, Physical
    pkt += struct.pack("BB", universe & 0xFF, (universe >> 8) & 0x7F)  # SubUni, Net
    pkt += struct.pack(">H", length)                # Length, big-endian
    pkt += dmx
    return pkt


# ── sACN / E1.31 ────────────────────────────────────────────────────────────
def sacn_multicast_ip(universe: int) -> str:
    return "239.255.%d.%d" % ((universe >> 8) & 0xFF, universe & 0xFF)


def _flags_len(pdu_body: bytes) -> bytes:
    """PDU: 0x7 flags in the top nibble + 12-bit length of (this 2-byte field + body)."""
    total = len(pdu_body) + 2
    return struct.pack(">H", 0x7000 | (total & 0x0FFF)) + pdu_body


def build_sacn_dmx(universe, data, source_name="xio", priority=100, sequence=0, cid=None) -> bytes:
    if not (1 <= universe <= 63999):
        raise ValueError("sACN universe out of range 1..63999")
    if not (0 <= priority <= 200):
        raise ValueError("sACN priority out of range 0..200")
    dmx = normalize_dmx(data)
    prop_values = b"\x00" + dmx                 # DMX start code (0x00) + channel data
    if cid is None:
        cid = b"xio-showcontrol"[:16].ljust(16, b"\x00")
    name = source_name.encode("utf-8")[:63].ljust(64, b"\x00")

    dmp = b"\x02\xa1"                            # vector (set property) + address/data type
    dmp += struct.pack(">H", 0x0000)            # first property address
    dmp += struct.pack(">H", 0x0001)            # address increment
    dmp += struct.pack(">H", len(prop_values))  # property value count (1 + channels)
    dmp += prop_values
    dmp = _flags_len(dmp)

    framing = struct.pack(">I", 0x00000002)     # vector: E1.31 data packet
    framing += name
    framing += struct.pack("B", priority)
    framing += struct.pack(">H", 0)             # sync universe
    framing += struct.pack("B", sequence & 0xFF)
    framing += struct.pack("B", 0)              # options
    framing += struct.pack(">H", universe)
    framing += dmp
    framing = _flags_len(framing)

    root = struct.pack(">H", 0x0010)            # preamble size
    root += struct.pack(">H", 0x0000)           # postamble size
    root += b"ASC-E1.17\x00\x00\x00"            # ACN packet identifier (12 bytes)
    root_pdu = struct.pack(">I", 0x00000004)    # vector: root E1.31
    root_pdu += cid
    root_pdu += framing
    root += _flags_len(root_pdu)
    return root


# ── Wake-on-LAN (AMD Magic Packet) ──────────────────────────────────────────
def parse_mac(mac) -> bytes:
    """Accept AA:BB:CC:DD:EE:FF / AA-BB-.. / bare 12-hex; return 6 raw bytes."""
    if not isinstance(mac, str):
        raise ValueError("MAC must be a string")
    hexstr = mac.replace(":", "").replace("-", "").strip().lower()
    if len(hexstr) != 12 or any(c not in "0123456789abcdef" for c in hexstr):
        raise ValueError("invalid MAC address: %r" % mac)
    return bytes.fromhex(hexstr)


def build_magic_packet(mac) -> bytes:
    """WoL magic packet: 6 x 0xFF + 16 repetitions of the MAC."""
    raw = parse_mac(mac)
    return b"\xff" * 6 + raw * 16


# ── shared helpers ──────────────────────────────────────────────────────────
def normalize_dmx(data) -> bytes:
    """Accept a list of 0..255 ints (<=512) or a {channel: value} dict (1-indexed)."""
    if isinstance(data, dict):
        arr = [0] * 512
        last = 0
        for k, v in data.items():
            ch = int(k)
            if not (1 <= ch <= 512):
                raise ValueError("DMX channel out of range 1..512: %s" % k)
            arr[ch - 1] = _dmx_val(v)
            last = max(last, ch)
        return bytes(arr[: max(last, 2)])
    if isinstance(data, (list, tuple)):
        if len(data) > 512:
            raise ValueError("DMX frame longer than 512 channels")
        return bytes(_dmx_val(v) for v in data)
    raise ValueError("DMX data must be a list of ints or a {channel: value} object")


def _dmx_val(v) -> int:
    iv = int(v)
    if not (0 <= iv <= 255):
        raise ValueError("DMX value out of range 0..255: %s" % v)
    return iv


def valid_host(host) -> bool:
    try:
        socket.inet_aton(str(host))
        return True
    except OSError:
        return False

"""
OSC input -- orq goes bidirectional: the phone RECEIVES cues.

QLab / Ableton / TouchOSC on a laptop or tablet sends OSC to the phone and the
phone fires its own engine: /xio/go, /xio/stop, /xio/timeline/play,
/xio/signal/master 0.5. The inverse of protocols.build_osc_message -- and tested
against it: parse(build(x)) must round-trip, so the send and receive paths
validate each other.

This module is pure (no sockets, no Flask): parse_message()/parse_packet()
decode OSC 1.0 bytes, map_action() translates an address+args into a fixed
action tuple. The plugin owns the UDP listener thread and executes the actions.

Dispatch is a CLOSED table under /xio/* on purpose: user-configurable mapping
languages are an injection surface, a fixed table is not. Unknown addresses are
ignored (and counted). OSC has no authentication, so the listener is opt-in,
its start/stop is behind the show token, and datagrams can be scoped with a
source-IP allowlist.
"""

import struct

MAX_PACKET = 8192
MAX_BUNDLE_DEPTH = 4
MAX_ELEMENTS = 64


class OscParseError(ValueError):
    """Malformed OSC packet."""


def _read_string(data, pos):
    end = data.find(b"\x00", pos)
    if end < 0:
        raise OscParseError("unterminated OSC string")
    s = data[pos:end].decode("utf-8", "strict")
    # strings are padded with NULs to a 4-byte boundary (including the terminator)
    return s, pos + ((end - pos) // 4 + 1) * 4


def _read_blob(data, pos):
    if pos + 4 > len(data):
        raise OscParseError("truncated blob length")
    (n,) = struct.unpack(">i", data[pos:pos + 4])
    if n < 0 or pos + 4 + n > len(data):
        raise OscParseError("blob length out of range")
    end = pos + 4 + n
    return data[pos + 4:end], end + ((4 - (n % 4)) % 4)


def parse_message(data):
    """One OSC message -> (address, [args]). Types: i f s b T F (as built by protocols)."""
    if len(data) > MAX_PACKET:
        raise OscParseError("packet too large")
    address, pos = _read_string(data, 0)
    if not address.startswith("/"):
        raise OscParseError("address must start with '/'")
    if pos >= len(data):                       # no typetags: zero-arg message
        return address, []
    tags, pos = _read_string(data, pos)
    if not tags.startswith(","):
        raise OscParseError("typetags must start with ','")
    args = []
    for t in tags[1:]:
        if t == "i":
            if pos + 4 > len(data):
                raise OscParseError("truncated int32")
            args.append(struct.unpack(">i", data[pos:pos + 4])[0]); pos += 4
        elif t == "f":
            if pos + 4 > len(data):
                raise OscParseError("truncated float32")
            args.append(struct.unpack(">f", data[pos:pos + 4])[0]); pos += 4
        elif t == "s":
            s, pos = _read_string(data, pos)
            args.append(s)
        elif t == "b":
            b, pos = _read_blob(data, pos)
            args.append(b)
        elif t == "T":
            args.append(True)
        elif t == "F":
            args.append(False)
        else:
            raise OscParseError("unsupported typetag: %r" % t)
    return address, args


def parse_packet(data, _depth=0):
    """OSC packet -> [(address, args)]. Flattens #bundle recursively (timetags
    are ignored: live control wants now, not scheduled delivery)."""
    if _depth > MAX_BUNDLE_DEPTH:
        raise OscParseError("bundle nested too deep")
    if data[:8] == b"#bundle\x00":
        pos, out = 16, []                      # skip 8-byte timetag
        while pos < len(data):
            if pos + 4 > len(data):
                raise OscParseError("truncated bundle element size")
            (n,) = struct.unpack(">i", data[pos:pos + 4])
            pos += 4
            if n <= 0 or pos + n > len(data):
                raise OscParseError("bundle element size out of range")
            out.extend(parse_packet(data[pos:pos + n], _depth + 1))
            if len(out) > MAX_ELEMENTS:
                raise OscParseError("too many bundle elements")
            pos += n
        return out
    return [parse_message(data)]


# ── dispatch: the closed /xio/* action table ─────────────────────────────────
def _num01(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0.0 <= f <= 1.0 else None


def map_action(address, args):
    """(address, args) -> action tuple, or None if the address isn't ours.

    Actions:
      ("go", index|None)  ("stop",)  ("release", fade)
      ("tl_play",) ("tl_pause",) ("tl_locate", t)
      ("signal", name, value01)
    """
    if address == "/xio/go":
        idx = None
        if args and isinstance(args[0], (int, float)) and not isinstance(args[0], bool):
            i = int(args[0])
            if i >= 0:
                idx = i
        return ("go", idx)
    if address == "/xio/stop":
        return ("stop",)
    if address == "/xio/release":
        fade = 2.0
        if args and isinstance(args[0], (int, float)) and not isinstance(args[0], bool):
            fade = max(0.0, min(float(args[0]), 300.0))
        return ("release", fade)
    if address == "/xio/timeline/play":
        return ("tl_play",)
    if address == "/xio/timeline/pause":
        return ("tl_pause",)
    if address == "/xio/timeline/locate":
        if args and isinstance(args[0], (int, float)) and not isinstance(args[0], bool):
            t = float(args[0])
            if t >= 0:
                return ("tl_locate", t)
        return None
    if address.startswith("/xio/signal/"):
        name = address[len("/xio/signal/"):]
        if not name or "/" in name:
            return None
        v = _num01(args[0]) if args else None
        if v is None:
            return None
        return ("signal", name, v)
    return None

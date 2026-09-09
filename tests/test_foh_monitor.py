import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "xio" / "new"))
sys.path.insert(0, str(ROOT / "xio" / "new-plugins"))

from foh_monitor import FohMonitorPlugin  # noqa: E402


def _osc_message(address: str, value: str) -> bytes:
    address_bytes = address.encode() + b"\0"
    address_bytes += b"\0" * ((4 - len(address_bytes) % 4) % 4)
    tags = b",s\0\0"
    value_bytes = value.encode() + b"\0"
    value_bytes += b"\0" * ((4 - len(value_bytes) % 4) % 4)
    return address_bytes + tags + value_bytes


def _osc_bundle(*messages: bytes) -> bytes:
    body = b"#bundle\0" + (b"\0" * 8)
    return body + b"".join(struct.pack(">I", len(message)) + message for message in messages)


def _plugin():
    plugin = FohMonitorPlugin.__new__(FohMonitorPlugin)
    plugin._cfg = lambda key: "/timecode" if key == "tc_address" else 30
    plugin._tc = {
        "value": None,
        "last_seen": 0.0,
        "last_change": 0.0,
        "total": 0,
    }
    plugin._tc_buckets = {}
    plugin._auto_setlist_por_tc = lambda value: None
    return plugin


def test_timecode_only_bundle_updates_timecode_without_visual_activity():
    plugin = _plugin()
    packet = _osc_bundle(_osc_message("/timecode", "12.5"))

    assert plugin._parse_osc_pkt(packet) is False
    assert plugin._tc["value"] == "12.5"
    assert plugin._tc["total"] == 1


def test_mixed_bundle_updates_timecode_and_counts_visual_address():
    plugin = _plugin()
    packet = _osc_bundle(
        _osc_message("/timecode", "13.0"),
        _osc_message("/composition/1/clip", "ready"),
    )

    assert plugin._parse_osc_pkt(packet) == "/composition/1/clip"
    assert plugin._tc["value"] == "13.0"


def test_malformed_bundle_is_ignored():
    plugin = _plugin()

    assert plugin._parse_osc_pkt(b"#bundle\0" + b"\0" * 8 + b"\0\0\0\x10bad") is None
    assert plugin._tc["total"] == 0

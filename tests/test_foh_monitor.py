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


def test_apk_timecode_bridge_updates_tc_without_marking_visual_channel():
    plugin = _plugin()
    plugin._record_tc_value("00:00:12:00")

    assert plugin._tc["value"] == "00:00:12:00"
    assert plugin._tc["total"] == 1
    assert plugin._tc_buckets


def test_exact_context_binds_unowned_setlist_without_resetting_show_state():
    plugin = _plugin()
    saved = []
    logged = []
    plugin._setlist = {
        "songs": ["00:00:00:00 intro", "00:01:00:00 tema"],
        "durations": [60.0, 90.0],
        "index": 1,
        "loaded_at": "2026-09-11T10:00:00",
        "advanced_at": "2026-09-11T10:05:00",
        "fohEventKey": None,
    }
    plugin._foh_context_current = {"eventKey": "vj_show:test-2026-09-11"}
    plugin._save_setlist = lambda: saved.append(dict(plugin._setlist))
    plugin._log_event = lambda *args: logged.append(args)

    result = plugin._bind_unowned_setlist_to_context({
        "eventKey": "vj_show:test-2026-09-11",
        "showKit": {"setlist": "xio/show_kit/test.txt"},
    })

    assert result["status"] == "bound"
    assert plugin._setlist["fohEventKey"] == "vj_show:test-2026-09-11"
    assert plugin._setlist["index"] == 1
    assert plugin._setlist["loaded_at"] == "2026-09-11T10:00:00"
    assert saved and logged


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


def test_artnet_dmx_declared_length_is_checked_before_counting_packet():
    header = b"Art-Net\0" + struct.pack("<H", 0x5000) + b"\0\0" + b"\0\0" + struct.pack("<H", 1)
    truncated = header + struct.pack(">H", 2) + b"\x01"
    valid = header + struct.pack(">H", 1) + b"\x01"

    assert FohMonitorPlugin._parse_artnet(truncated) is None
    assert FohMonitorPlugin._parse_artnet(valid) == "OpDmx uni 1"

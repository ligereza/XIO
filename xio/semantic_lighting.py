"""Predictive semantic lighting frames for XIO.

The module is deliberately below the host applications.  It turns a canonical
audio/timecode event into a deterministic scene description and a compact
binary packet that a future edge receiver could expand into ordinary DMX.

This is not a DMX replacement and it does not open sockets.  The important
boundary is explicit: XIO owns the math and provenance; downstream adapters
own the proposal for a visual or lighting host.
"""

from __future__ import annotations

import binascii
import json
import math
import struct
from typing import Any, Mapping, Sequence


SCHEMA = "xio:predictive-semantic-lighting-frame:0.1"
PACKET_MAGIC = b"XSL1"
PACKET_VERSION = 1
DECODER_PROFILE = "phase-chaser-v1"
MAX_FIXTURES = 255
DEFAULT_CHANNELS_PER_FIXTURE = 80
_TAU = math.tau


class SemanticLightingError(ValueError):
    """Raised when a predictive lighting frame is unsafe or malformed."""


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SemanticLightingError(f"{field_name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise SemanticLightingError(f"{field_name} must be finite")
    return result


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticLightingError(f"{field_name} must be non-empty text")
    result = value.strip()
    try:
        result.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SemanticLightingError(f"{field_name} must be ASCII") from exc
    return result


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _fraction(value: float) -> float:
    return value - math.floor(value)


def _quantize_u8(value: float) -> int:
    return int(round(_clamp(value) * 255.0))


def _quantize_u16(value: float) -> int:
    return int(round(_clamp(value) * 65535.0))


def _dequantize_u16(value: int) -> float:
    return value / 65535.0


def _normalized_event(event: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        raise SemanticLightingError("event must be an object")
    event_id = _text(event.get("event_id"), "event.event_id")
    timestamp = _text(event.get("timestamp"), "event.timestamp")
    timecode = _text(event.get("timecode"), "event.timecode")
    sequence = event.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        raise SemanticLightingError("event.sequence must be a positive integer")
    time_seconds = _finite(event.get("time_seconds"), "event.time_seconds")
    if time_seconds < 0:
        raise SemanticLightingError("event.time_seconds must be >= 0")
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise SemanticLightingError("event.payload must be an object")
    amplitude = _finite(payload.get("amplitude", 0.0), "event.payload.amplitude")
    pulse = _finite(payload.get("pulse", 0.0), "event.payload.pulse")
    if not 0.0 <= amplitude <= 1.0 or not 0.0 <= pulse <= 1.0:
        raise SemanticLightingError("event audio values must be between 0 and 1")
    signal_state = _text(payload.get("signal_state", "present"), "event.payload.signal_state")
    if signal_state not in {"present", "missing"}:
        raise SemanticLightingError("event.payload.signal_state must be present or missing")
    return {
        "event_id": event_id,
        "sequence": sequence,
        "timestamp": timestamp,
        "timecode": timecode,
        "time_seconds": time_seconds,
        "amplitude": amplitude if signal_state == "present" else 0.0,
        "pulse": pulse if signal_state == "present" else 0.0,
        "signal_state": signal_state,
    }


def _normalized_parameters(parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(parameters or {})
    cycle_seconds = _finite(raw.get("cycle_seconds", 8.0), "cycle_seconds")
    if cycle_seconds <= 0:
        raise SemanticLightingError("cycle_seconds must be > 0")
    phase_offset = _finite(raw.get("phase_offset", 0.0), "phase_offset")
    angle_offset = _finite(raw.get("angle_offset_degrees", 0.0), "angle_offset_degrees")
    master = _finite(raw.get("master_intensity", 1.0), "master_intensity")
    sensitivity = _finite(raw.get("sensitivity", 1.0), "sensitivity")
    seed = raw.get("seed", 0)
    channels = raw.get("channels_per_fixture", DEFAULT_CHANNELS_PER_FIXTURE)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 65535:
        raise SemanticLightingError("seed must be an integer between 0 and 65535")
    if isinstance(channels, bool) or not isinstance(channels, int) or not 1 <= channels <= 512:
        raise SemanticLightingError("channels_per_fixture must be an integer between 1 and 512")
    if not 0.0 <= master <= 1.0 or sensitivity < 0.0 or sensitivity > 4.0:
        raise SemanticLightingError("master_intensity or sensitivity is outside safe bounds")
    return {
        "cycle_seconds": cycle_seconds,
        "phase_offset": phase_offset,
        "angle_offset_degrees": angle_offset,
        "master_intensity": master,
        "sensitivity": sensitivity,
        "seed": seed,
        "channels_per_fixture": channels,
    }


def _fixture_ids(fixture_ids: Sequence[str]) -> list[str]:
    if isinstance(fixture_ids, (str, bytes)) or not isinstance(fixture_ids, Sequence):
        raise SemanticLightingError("fixture_ids must be a non-empty sequence")
    normalized = [_text(value, "fixture_id") for value in fixture_ids]
    if not normalized:
        raise SemanticLightingError("fixture_ids must be a non-empty sequence")
    if len(normalized) > MAX_FIXTURES:
        raise SemanticLightingError("fixture count exceeds semantic packet limit")
    if len(set(normalized)) != len(normalized):
        raise SemanticLightingError("fixture_ids must be unique")
    return normalized


def _seed_phase(seed: int) -> float:
    # SplitMix-like integer mixing.  It is intentionally deterministic across
    # Python versions and does not use the process-randomized hash function.
    mixed = (seed + 0x9E3779B9) & 0xFFFFFFFF
    mixed = ((mixed ^ (mixed >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
    mixed = ((mixed ^ (mixed >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
    mixed ^= mixed >> 16
    return (mixed & 0xFFFFFFFF) / 4294967296.0


def _wire_packet(frame: Mapping[str, Any]) -> bytes:
    scene = frame["scene"]
    fixtures = frame["fixtures"]
    if len(fixtures) > MAX_FIXTURES:
        raise SemanticLightingError("fixture count exceeds packet limit")
    sequence = frame["sequence"]
    time_ms = int(round(float(frame["time_seconds"]) * 1000.0))
    cycle_ms = int(round(float(scene["cycle_seconds"]) * 1000.0))
    if not 0 <= sequence <= 65535 or not 0 <= time_ms <= 0xFFFFFFFF or not 1 <= cycle_ms <= 0xFFFFFFFF:
        raise SemanticLightingError("frame timing or sequence cannot be packed")
    body = bytearray()
    body.extend(PACKET_MAGIC)
    body.extend(struct.pack(">BBHBIIHBBBBH", PACKET_VERSION, 0, sequence, len(fixtures), time_ms, cycle_ms,
                            _quantize_u16(float(scene["phase"])), _quantize_u8(float(scene["energy"])),
                            _quantize_u8(float(scene["pulse"])), _quantize_u8(float(scene["master_intensity"])),
                            _quantize_u8(float(scene["sensitivity"]) / 4.0), int(scene["seed"])))
    for fixture in fixtures:
        bias = int(round(_clamp(float(fixture["intensity_bias"]), -1.0, 1.0) * 127.0))
        body.extend(struct.pack(">BHHb", int(fixture["index"]), _quantize_u16(float(fixture["phase_offset"])),
                                int(round((float(fixture["angle_offset_degrees"]) % 360.0) / 360.0 * 65535.0)), bias))
    checksum = binascii.crc32(body) & 0xFFFFFFFF
    body.extend(struct.pack(">I", checksum))
    return bytes(body)


def pack_semantic_frame(frame: Mapping[str, Any]) -> bytes:
    """Pack one semantic frame with a CRC32, without performing I/O."""

    if frame.get("schema") != SCHEMA:
        raise SemanticLightingError("unsupported semantic lighting schema")
    return _wire_packet(frame)


def unpack_semantic_frame(packet: bytes) -> dict[str, Any]:
    """Decode and validate the compact packet used by an edge receiver."""

    if not isinstance(packet, (bytes, bytearray)):
        raise SemanticLightingError("packet must be bytes")
    raw = bytes(packet)
    header_size = 4 + struct.calcsize(">BBHBIIHBBBBH")
    if len(raw) < header_size + 4:
        raise SemanticLightingError("semantic packet is truncated")
    if raw[:4] != PACKET_MAGIC:
        raise SemanticLightingError("semantic packet magic is invalid")
    expected = struct.unpack(">I", raw[-4:])[0]
    actual = binascii.crc32(raw[:-4]) & 0xFFFFFFFF
    if expected != actual:
        raise SemanticLightingError("semantic packet CRC mismatch")
    values = struct.unpack(">BBHBIIHBBBBH", raw[4:header_size])
    version, flags, sequence, count, time_ms, cycle_ms, phase, energy, pulse, master, sensitivity, seed = values
    if version != PACKET_VERSION or flags != 0:
        raise SemanticLightingError("semantic packet version or flags are unsupported")
    offset = header_size
    fixtures: list[dict[str, Any]] = []
    fixture_size = struct.calcsize(">BHHb")
    for _ in range(count):
        if offset + fixture_size > len(raw) - 4:
            raise SemanticLightingError("semantic packet fixture table is truncated")
        index, phase_offset, angle_offset, bias = struct.unpack(">BHHb", raw[offset:offset + fixture_size])
        fixtures.append({
            "index": index,
            "phase_offset": _dequantize_u16(phase_offset),
            "angle_offset_degrees": angle_offset / 65535.0 * 360.0,
            "intensity_bias": bias / 127.0,
        })
        offset += fixture_size
    if offset != len(raw) - 4:
        raise SemanticLightingError("semantic packet has trailing bytes")
    return {
        "schema": SCHEMA,
        "version": version,
        "sequence": sequence,
        "fixture_count": count,
        "time_seconds": time_ms / 1000.0,
        "cycle_seconds": cycle_ms / 1000.0,
        "phase": _dequantize_u16(phase),
        "energy": energy / 255.0,
        "pulse": pulse / 255.0,
        "master_intensity": master / 255.0,
        "sensitivity": sensitivity / 255.0 * 4.0,
        "seed": seed,
        "fixtures": fixtures,
        "crc32": f"{expected:08x}",
    }


def build_predictive_frame(
    event: Mapping[str, Any],
    *,
    session_id: str,
    fixture_ids: Sequence[str],
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Render one canonical event into a predictive semantic lighting frame.

    The local renderer uses the same equation an edge node can use:

    ``phase_i = frac(t / cycle + global_offset + i / N + seed_phase * .08)``
    ``intensity = master * clamp(.18 + .46E + .14carrier + .36P)``

    E is audio energy and P is the transient pulse.  The result is deliberately
    bounded, deterministic and inspectable rather than AI-generated.
    """

    normalized_event = _normalized_event(event)
    session_id = _text(session_id, "session_id")
    ids = _fixture_ids(fixture_ids)
    params = _normalized_parameters(parameters)
    count = len(ids)
    time_seconds = normalized_event["time_seconds"]
    energy = normalized_event["amplitude"]
    pulse = normalized_event["pulse"]
    phase = _fraction(time_seconds / params["cycle_seconds"] + params["phase_offset"] + _seed_phase(params["seed"]) * 0.08)
    carrier = 0.5 + 0.5 * math.sin(_TAU * phase)
    scene = {
        "phase": round(phase, 9),
        "cycle_seconds": round(params["cycle_seconds"], 9),
        "energy": round(energy, 9),
        "pulse": round(pulse, 9),
        "master_intensity": round(params["master_intensity"], 9),
        "sensitivity": round(params["sensitivity"], 9),
        "seed": params["seed"],
        "carrier": round(carrier, 9),
    }
    descriptors: list[dict[str, Any]] = []
    lights: list[dict[str, Any]] = []
    for index, fixture_id in enumerate(ids):
        fixture_phase_offset = index / count
        fixture_phase = _fraction(phase + fixture_phase_offset)
        angle = (fixture_phase * 360.0 + params["angle_offset_degrees"]) % 360.0
        fixture_carrier = 0.5 + 0.5 * math.sin(_TAU * fixture_phase)
        pulse_level = _clamp(params["sensitivity"] * (0.55 * pulse + 0.45 * energy))
        intensity = _clamp(params["master_intensity"] * (
            0.18 + 0.46 * energy + 0.14 * fixture_carrier + 0.36 * pulse_level
        ))
        descriptor = {
            "index": index,
            "fixture_id": fixture_id,
            "phase_offset": round(fixture_phase_offset, 9),
            "angle_offset_degrees": round(params["angle_offset_degrees"], 9),
            "intensity_bias": 0.0,
        }
        descriptors.append(descriptor)
        lights.append({
            "fixture_id": fixture_id,
            "phase": round(fixture_phase, 9),
            "angle_degrees": round(angle, 6),
            "intensity": round(intensity, 9),
            "pulse": round(pulse_level, 9),
        })

    frame: dict[str, Any] = {
        "schema": SCHEMA,
        "proposal_only": True,
        "session_id": session_id,
        "event_id": normalized_event["event_id"],
        "sequence": normalized_event["sequence"],
        "timestamp": normalized_event["timestamp"],
        "time_seconds": round(time_seconds, 6),
        "timecode": normalized_event["timecode"],
        "signal_state": normalized_event["signal_state"],
        "scene": scene,
        "fixtures": descriptors,
        "lights": lights,
        "math": {
            "phase": "frac(t / cycle_seconds + phase_offset + fixture_index / fixture_count + seed_phase * 0.08)",
            "angle_degrees": "mod(phase_i * 360 + angle_offset_degrees, 360)",
            "intensity": "master * clamp(0.18 + 0.46*energy + 0.14*carrier_i + 0.36*pulse_level)",
            "pulse_level": "clamp(sensitivity * (0.55*pulse + 0.45*energy))",
        },
        "safety": {
            "proposal_only": True,
            "external_side_effects": False,
            "artnet_emitted": False,
            "osc_emitted": False,
            "predictive_decoder_required": True,
        },
    }
    packet = pack_semantic_frame(frame)
    direct_bytes = count * params["channels_per_fixture"]
    semantic_bytes = len(packet)
    frame["transport"] = {
        "encoding": "XSL1-predictive-semantic",
        "decoder_profile": DECODER_PROFILE,
        "addressing": "fixture_index_requires_preloaded_profile",
        "expands_channels_locally": params["channels_per_fixture"],
        "packet_bytes": semantic_bytes,
        "packet_hex": packet.hex(),
        "direct_dmx": {
            "channels_per_fixture": params["channels_per_fixture"],
            "fixture_count": count,
            "total_channel_bytes": direct_bytes,
            "universes": math.ceil(direct_bytes / 512),
        },
        "compression": {
            "direct_channel_bytes": direct_bytes,
            "semantic_packet_bytes": semantic_bytes,
            "ratio": round(direct_bytes / semantic_bytes, 6),
            "saved_fraction": round(1.0 - semantic_bytes / direct_bytes, 6),
            "lossless_for": "semantic scene descriptor",
            "not_lossless_for": "arbitrary independent DMX channel values",
        },
    }
    return json.loads(json.dumps(frame, ensure_ascii=True, sort_keys=True, allow_nan=False))


__all__ = [
    "DEFAULT_CHANNELS_PER_FIXTURE",
    "DECODER_PROFILE",
    "MAX_FIXTURES",
    "PACKET_MAGIC",
    "PACKET_VERSION",
    "SCHEMA",
    "SemanticLightingError",
    "build_predictive_frame",
    "pack_semantic_frame",
    "unpack_semantic_frame",
]

from __future__ import annotations

import copy

import pytest

from xio.semantic_lighting import (
    SCHEMA,
    SemanticLightingError,
    build_predictive_frame,
    pack_semantic_frame,
    unpack_semantic_frame,
)


def event(**payload):
    return {
        "event_id": "pulse-001",
        "sequence": 1,
        "timestamp": "2026-09-08T00:00:01.250Z",
        "time_seconds": 1.25,
        "timecode": "00:00:01:06",
        "payload": {"amplitude": 0.8, "pulse": 1.0, "signal_state": "present", **payload},
    }


def test_predictive_frame_is_deterministic_and_beats_direct_dmx_budget():
    args = {
        "session_id": "session-001",
        "fixture_ids": [f"wash-{index:02d}" for index in range(20)],
        "parameters": {"cycle_seconds": 6.0, "seed": 42},
    }
    first = build_predictive_frame(event(), **args)
    second = build_predictive_frame(event(), **args)

    assert first == second
    assert first["schema"] == SCHEMA
    assert len(first["lights"]) == 20
    assert first["transport"]["direct_dmx"]["universes"] == 4
    assert first["transport"]["compression"]["ratio"] > 5.0
    assert first["safety"]["external_side_effects"] is False


def test_packet_round_trip_and_crc_guard():
    frame = build_predictive_frame(
        event(), session_id="session-001", fixture_ids=["a", "b", "c"]
    )
    packet = pack_semantic_frame(frame)
    decoded = unpack_semantic_frame(packet)

    assert decoded["schema"] == SCHEMA
    assert decoded["sequence"] == 1
    assert decoded["fixture_count"] == 3
    assert decoded["seed"] == 0
    assert decoded["fixtures"][1]["phase_offset"] == pytest.approx(1 / 3, abs=1 / 65535)

    broken = bytearray(packet)
    broken[10] ^= 0x01
    with pytest.raises(SemanticLightingError, match="CRC"):
        unpack_semantic_frame(bytes(broken))


def test_missing_audio_is_safe_and_duplicate_fixture_ids_are_rejected():
    missing = build_predictive_frame(
        event(amplitude=0.9, pulse=0.9, signal_state="missing"),
        session_id="session-001",
        fixture_ids=["a"],
    )
    assert missing["scene"]["energy"] == 0.0
    assert missing["scene"]["pulse"] == 0.0
    assert missing["lights"][0]["intensity"] < 0.5

    with pytest.raises(SemanticLightingError, match="unique"):
        build_predictive_frame(event(), session_id="session-001", fixture_ids=["a", "a"])


def test_packet_rejects_mutated_schema_without_side_effects():
    frame = build_predictive_frame(event(), session_id="session-001", fixture_ids=["a"])
    invalid = copy.deepcopy(frame)
    invalid["schema"] = "wrong"
    with pytest.raises(SemanticLightingError, match="schema"):
        pack_semantic_frame(invalid)

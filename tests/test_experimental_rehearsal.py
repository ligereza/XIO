from __future__ import annotations

import pytest

from xio.experimental_rehearsal import RehearsalSignalError, extract_pulses, normalize_signal_events


def fixture() -> dict:
    return {
        "fixture_type": "SyntheticAudioRehearsalFixture",
        "fixture_id": "test-audio",
        "sample_rate_hz": 20,
        "duration_seconds": 1.0,
        "samples": [
            {"time_seconds": 0.0, "amplitude": 0.1},
            {"time_seconds": 0.2, "amplitude": 0.8},
            {"time_seconds": 0.6, "amplitude": 0.9},
        ],
        "loss_intervals": [{"start_seconds": 0.4, "end_seconds": 0.5}],
    }


def test_extract_and_normalize_audits_duplicate_and_out_of_order_delivery():
    source = fixture()
    pulses = extract_pulses(source)
    delivery = [pulses[1], pulses[0], pulses[0]]
    delivery.append({
        "event_id": "audio-gap-001",
        "time_seconds": 0.4,
        "amplitude": 0.0,
        "pulse": 0.0,
        "kind": "audio.gap",
        "gap_end_seconds": 0.5,
    })
    result = normalize_signal_events(
        source,
        session_id="test-session",
        session_start="2026-01-01T00:00:00Z",
        source_path="fixture.json",
        ingest_events=delivery,
    )
    assert [event["event_id"] for event in result["events"]] == [
        "pulse-001",
        "audio-gap-001",
        "pulse-002",
    ]
    assert result["audit"]["duplicate_count"] == 1
    assert result["audit"]["out_of_order_count"] == 1
    assert result["events"][1]["payload"]["signal_state"] == "missing"


def test_resume_skips_already_recorded_sequences():
    result = normalize_signal_events(
        fixture(),
        session_id="test-session",
        session_start="2026-01-01T00:00:00Z",
        source_path="fixture.json",
        resume_from_sequence=1,
    )
    assert result["audit"]["resume_applied"] is True
    assert result["events"][0]["sequence"] == 2


def test_conflicting_duplicate_is_blocked():
    source = fixture()
    pulses = extract_pulses(source)
    conflicting = dict(pulses[0])
    conflicting["amplitude"] = 0.99
    with pytest.raises(RehearsalSignalError, match="conflicting duplicate"):
        normalize_signal_events(
            source,
            session_id="test-session",
            session_start="2026-01-01T00:00:00Z",
            source_path="fixture.json",
            ingest_events=[pulses[0], conflicting],
        )

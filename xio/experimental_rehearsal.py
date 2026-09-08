"""Deterministic audio-to-XIO normalization for the Obras rehearsal.

This module deliberately stops at canonical, auditable signal events. It does
not open sockets, emit OSC/Art-Net, or touch a device. The rehearsal runner in
FARMAXIA supplies the fixture and consumes the returned event envelope.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA = "xio:experimental-rehearsal-signal:0.1"
FIXTURE_TYPE = "SyntheticAudioRehearsalFixture"
DEFAULT_FPS = 25
UTC = timezone.utc


class RehearsalSignalError(ValueError):
    """Raised when a rehearsal signal cannot be normalized safely."""


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RehearsalSignalError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise RehearsalSignalError(f"{field_name} must be a finite number")
    return result


def _positive_number(value: Any, field_name: str) -> float:
    result = _finite_number(value, field_name)
    if result <= 0:
        raise RehearsalSignalError(f"{field_name} must be > 0")
    return result


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RehearsalSignalError(f"{field_name} must be non-empty text")
    text = value.strip()
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RehearsalSignalError(f"{field_name} must be ASCII") from exc
    return text


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_json(value: Any) -> str:
    """Return a stable digest for a JSON-compatible value."""

    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def load_fixture(path: str | Path) -> dict[str, Any]:
    fixture_path = Path(path).expanduser().resolve()
    if not fixture_path.is_file():
        raise RehearsalSignalError(f"audio fixture does not exist: {fixture_path}")
    try:
        value = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RehearsalSignalError(f"audio fixture cannot be read: {fixture_path}") from exc
    if not isinstance(value, dict):
        raise RehearsalSignalError("audio fixture must be a JSON object")
    validate_fixture(value)
    return value


def validate_fixture(fixture: Mapping[str, Any]) -> None:
    if fixture.get("fixture_type") != FIXTURE_TYPE:
        raise RehearsalSignalError("unsupported audio fixture type")
    _text(fixture.get("fixture_id"), "fixture_id")
    _positive_number(fixture.get("sample_rate_hz"), "sample_rate_hz")
    duration = _positive_number(fixture.get("duration_seconds"), "duration_seconds")
    samples = fixture.get("samples")
    if not isinstance(samples, list) or not samples:
        raise RehearsalSignalError("audio fixture samples must be non-empty")
    previous_time = -1.0
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            raise RehearsalSignalError(f"sample {index} must be an object")
        sample_time = _finite_number(sample.get("time_seconds"), f"samples[{index}].time_seconds")
        amplitude = _finite_number(sample.get("amplitude"), f"samples[{index}].amplitude")
        if not 0.0 <= amplitude <= 1.0:
            raise RehearsalSignalError(f"samples[{index}].amplitude must be between 0 and 1")
        if sample_time < 0 or sample_time > duration:
            raise RehearsalSignalError(f"samples[{index}].time_seconds is outside duration")
        if sample_time < previous_time:
            raise RehearsalSignalError("fixture samples must be ordered by time_seconds")
        previous_time = sample_time
    intervals = fixture.get("loss_intervals", [])
    if not isinstance(intervals, list):
        raise RehearsalSignalError("loss_intervals must be a list")
    for index, interval in enumerate(intervals):
        if not isinstance(interval, Mapping):
            raise RehearsalSignalError(f"loss_intervals[{index}] must be an object")
        start = _finite_number(interval.get("start_seconds"), f"loss_intervals[{index}].start_seconds")
        end = _finite_number(interval.get("end_seconds"), f"loss_intervals[{index}].end_seconds")
        if start < 0 or end <= start or end > duration:
            raise RehearsalSignalError(f"loss_intervals[{index}] is invalid")


def extract_pulses(
    fixture: Mapping[str, Any],
    *,
    threshold: float = 0.62,
    min_gap_seconds: float = 0.20,
) -> list[dict[str, Any]]:
    """Extract onset-like pulses from the fixture's documented envelope."""

    validate_fixture(fixture)
    threshold = _finite_number(threshold, "threshold")
    min_gap_seconds = _positive_number(min_gap_seconds, "min_gap_seconds")
    pulses: list[dict[str, Any]] = []
    last_pulse = -math.inf
    for index, sample in enumerate(fixture["samples"]):
        amplitude = float(sample["amplitude"])
        at = float(sample["time_seconds"])
        if amplitude < threshold or at - last_pulse < min_gap_seconds:
            continue
        pulse_id = f"pulse-{len(pulses) + 1:03d}"
        pulses.append(
            {
                "event_id": pulse_id,
                "source_index": index,
                "time_seconds": round(at, 6),
                "amplitude": round(amplitude, 6),
                "pulse": 1.0,
                "kind": "audio.pulse",
            }
        )
        last_pulse = at
    return pulses


def _timestamp(start: str, seconds: float) -> str:
    try:
        origin = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RehearsalSignalError("session_start must be ISO-8601") from exc
    if origin.tzinfo is None:
        raise RehearsalSignalError("session_start must include a timezone")
    return (origin.astimezone(UTC) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_timecode(seconds: float, fps: int = DEFAULT_FPS) -> str:
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0 or fps > 240:
        raise RehearsalSignalError("fps must be an integer between 1 and 240")
    total_frames = max(0, int(round(seconds * fps)))
    frames, total_seconds = total_frames % fps, total_frames // fps
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def _loss_event(interval: Mapping[str, Any], index: int) -> dict[str, Any]:
    start = _finite_number(interval["start_seconds"], "loss.start_seconds")
    end = _finite_number(interval["end_seconds"], "loss.end_seconds")
    return {
        "event_id": f"audio-gap-{index + 1:03d}",
        "source_index": -1,
        "time_seconds": round(start, 6),
        "amplitude": 0.0,
        "pulse": 0.0,
        "kind": "audio.gap",
        "gap_end_seconds": round(end, 6),
    }


def normalize_signal_events(
    fixture: Mapping[str, Any],
    *,
    session_id: str,
    session_start: str,
    source_path: str,
    fps: int = DEFAULT_FPS,
    threshold: float = 0.62,
    min_gap_seconds: float = 0.20,
    ingest_events: Iterable[Mapping[str, Any]] | None = None,
    resume_from_sequence: int = 0,
) -> dict[str, Any]:
    """Normalize pulses and gaps into canonical XIO events.

    ``ingest_events`` is intentionally allowed to be a reordered, duplicated
    delivery stream. The returned canonical list is ordered by signal time;
    the audit retains delivery order, duplicates and reordering evidence.
    """

    validate_fixture(fixture)
    session_id = _text(session_id, "session_id")
    source_path = _text(source_path, "source_path")
    if isinstance(resume_from_sequence, bool) or not isinstance(resume_from_sequence, int) or resume_from_sequence < 0:
        raise RehearsalSignalError("resume_from_sequence must be a non-negative integer")
    pulses = extract_pulses(fixture, threshold=threshold, min_gap_seconds=min_gap_seconds)
    base_events = pulses + [_loss_event(interval, index) for index, interval in enumerate(fixture.get("loss_intervals", []))]
    delivered = list(ingest_events) if ingest_events is not None else list(base_events)
    if not delivered:
        raise RehearsalSignalError("delivery stream is empty")

    fixture_digest = sha256_json(fixture)
    seen: OrderedDict[str, tuple[str, Mapping[str, Any]]] = OrderedDict()
    duplicate_count = 0
    duplicate_conflicts: list[str] = []
    out_of_order_count = 0
    previous_time = -math.inf
    delivery_records: list[dict[str, Any]] = []
    for delivery_index, raw in enumerate(delivered):
        if not isinstance(raw, Mapping):
            raise RehearsalSignalError("delivery event must be an object")
        event_id = _text(raw.get("event_id"), "delivery.event_id")
        time_seconds = _finite_number(raw.get("time_seconds"), "delivery.time_seconds")
        if time_seconds < previous_time:
            out_of_order_count += 1
        previous_time = time_seconds
        fingerprint = sha256_json(dict(raw))
        if event_id in seen:
            duplicate_count += 1
            if seen[event_id][0] != fingerprint:
                duplicate_conflicts.append(event_id)
            delivery_records.append({"delivery_index": delivery_index, "event_id": event_id, "status": "duplicate"})
            continue
        seen[event_id] = (fingerprint, raw)
        delivery_records.append({"delivery_index": delivery_index, "event_id": event_id, "status": "accepted"})

    if duplicate_conflicts:
        raise RehearsalSignalError("conflicting duplicate delivery: " + ",".join(sorted(duplicate_conflicts)))

    ordered = sorted(seen.values(), key=lambda item: (float(item[1]["time_seconds"]), str(item[1]["event_id"])))
    canonical_events: list[dict[str, Any]] = []
    for sequence, (_fingerprint, raw) in enumerate(ordered, start=1):
        at = _finite_number(raw["time_seconds"], "event.time_seconds")
        kind = _text(raw.get("kind", "audio.pulse"), "event.kind")
        amplitude = _finite_number(raw.get("amplitude", 0.0), "event.amplitude")
        pulse = _finite_number(raw.get("pulse", 0.0), "event.pulse")
        event = {
            "schema": SCHEMA,
            "session_id": session_id,
            "event_id": str(raw["event_id"]),
            "sequence": sequence,
            "source_sequence": sequence,
            "timestamp": _timestamp(session_start, at),
            "time_seconds": round(at, 6),
            "timecode": format_timecode(at, fps),
            "event_type": kind,
            "payload": {
                "amplitude": round(max(0.0, min(1.0, amplitude)), 6),
                "pulse": round(max(0.0, min(1.0, pulse)), 6),
                "signal_state": "missing" if kind == "audio.gap" else "present",
                "gap_end_seconds": raw.get("gap_end_seconds"),
            },
            "provenance": {
                "source": "synthetic-audio-fixture",
                "fixture_id": fixture["fixture_id"],
                "fixture_sha256": fixture_digest,
                "source_path": source_path,
                "transport": "audio_fixture",
                "delivery_fingerprint": _fingerprint,
            },
        }
        if sequence > resume_from_sequence:
            canonical_events.append(event)

    return {
        "schema": SCHEMA,
        "session_id": session_id,
        "fixture_id": fixture["fixture_id"],
        "fixture_sha256": fixture_digest,
        "session_start": _timestamp(session_start, 0),
        "fps": fps,
        "extraction": {
            "method": "amplitude_threshold_onset",
            "threshold": threshold,
            "min_gap_seconds": min_gap_seconds,
            "source_sample_count": len(fixture["samples"]),
            "pulse_count": len(pulses),
            "loss_interval_count": len(fixture.get("loss_intervals", [])),
        },
        "audit": {
            "delivery_count": len(delivered),
            "unique_delivery_count": len(seen),
            "duplicate_count": duplicate_count,
            "duplicate_conflicts": sorted(duplicate_conflicts),
            "out_of_order_count": out_of_order_count,
            "resume_from_sequence": resume_from_sequence,
            "resume_applied": resume_from_sequence > 0,
            "delivery_records": delivery_records,
        },
        "events": canonical_events,
    }


def write_jsonl(events: Iterable[Mapping[str, Any]], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for event in events:
            handle.write(_canonical_json(dict(event)) + "\n")


__all__ = [
    "DEFAULT_FPS",
    "FIXTURE_TYPE",
    "RehearsalSignalError",
    "SCHEMA",
    "extract_pulses",
    "format_timecode",
    "load_fixture",
    "normalize_signal_events",
    "sha256_json",
    "validate_fixture",
    "write_jsonl",
]

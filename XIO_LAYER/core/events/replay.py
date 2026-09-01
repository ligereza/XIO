"""Pure replay of observations into state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ..contracts import EventRecord, EventReducer
from .log import DuplicateEventError


@dataclass(frozen=True, slots=True)
class ReplayResult:
    state: Mapping[str, Any]
    last_sequence: int
    applied_events: int
    source_clock_ahead_events: int


def replay_events(
    records: Iterable[EventRecord],
    reducer: EventReducer,
    initial_state: Mapping[str, Any] | None = None,
) -> ReplayResult:
    """Apply records in ingestion sequence, de-duplicating identical ids.

    Replay has no action dispatcher and cannot create or execute an action.
    ``occurred_at`` is intentionally not used for ordering: source clocks can
    drift, while the event-log sequence represents what XIO Layer actually saw.
    """

    state = dict(initial_state or {})
    seen: dict[str, str] = {}
    applied = 0
    ahead = 0
    last_sequence = 0
    for record in sorted(records, key=lambda item: item.sequence):
        event = record.event
        previous_fingerprint = seen.get(event.event_id)
        if previous_fingerprint is not None:
            if previous_fingerprint != event.fingerprint:
                raise DuplicateEventError(event.event_id)
            continue
        seen[event.event_id] = event.fingerprint
        state = dict(reducer(state, event))
        applied += 1
        ahead += int(event.source_clock_is_ahead)
        last_sequence = max(last_sequence, record.sequence)

    return ReplayResult(
        state=state,
        last_sequence=last_sequence,
        applied_events=applied,
        source_clock_ahead_events=ahead,
    )

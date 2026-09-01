"""Materialize snapshots without coupling state to a device."""

from __future__ import annotations

from threading import RLock
from typing import Any, Iterable, Mapping

from ..contracts import EventRecord, EventReducer, Snapshot, utc_now
from ..events.replay import replay_events


class SnapshotProjector:
    """Project an event stream into a snapshot using a supplied pure reducer."""

    def __init__(self, reducer: EventReducer, initial_state: Mapping[str, Any] | None = None):
        self.reducer = reducer
        self.initial_state = dict(initial_state or {})

    def project(
        self,
        stream_id: str,
        records: Iterable[EventRecord],
        base_snapshot: Snapshot | None = None,
    ) -> Snapshot:
        records = tuple(sorted(records, key=lambda item: item.sequence))
        base_state = base_snapshot.state if base_snapshot is not None else self.initial_state
        replay = replay_events(records, self.reducer, base_state)
        version = replay.last_sequence
        if not records and base_snapshot is not None:
            version = base_snapshot.version
        source_event_id = records[-1].event.event_id if records else (
            base_snapshot.source_event_id if base_snapshot is not None else None
        )
        return Snapshot(
            stream_id=stream_id,
            version=version,
            state=replay.state,
            captured_at=utc_now(),
            source_event_id=source_event_id,
        )


class SnapshotStore:
    """In-process latest-snapshot store with stale-write protection."""

    def __init__(self) -> None:
        self._snapshots: dict[str, Snapshot] = {}
        self._lock = RLock()

    def save(self, snapshot: Snapshot) -> Snapshot:
        with self._lock:
            current = self._snapshots.get(snapshot.stream_id)
            if current is not None and snapshot.version < current.version:
                raise ValueError("cannot replace a snapshot with an older version")
            self._snapshots[snapshot.stream_id] = snapshot
            return snapshot

    def latest(self, stream_id: str) -> Snapshot | None:
        with self._lock:
            return self._snapshots.get(stream_id)

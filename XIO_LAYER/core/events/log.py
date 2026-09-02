"""Idempotent event log with monotonic ingestion order."""

from __future__ import annotations

from pathlib import Path
import json
import os
from threading import RLock
from typing import Iterable

from ..contracts import Event, EventRecord
from ..file_lock import exclusive_file_lock


class DuplicateEventError(ValueError):
    """The same event id arrived with different content."""


class EventLogPersistenceError(ValueError):
    """Raised when a persistent event log cannot be read or written safely."""


class EventLog:
    """Append-only event log.

    Duplicate ids with identical content are acknowledged idempotently. A
    duplicate id with different content is rejected. The assigned sequence is
    the arrival order and therefore remains stable when source timestamps are
    out of order.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._records: list[EventRecord] = []
        self._by_id: dict[str, EventRecord] = {}
        self._lock = RLock()
        self._lock_path = self.path.with_name(self.path.name + ".lock") if self.path else None
        if self.path is not None and self.path.exists():
            with exclusive_file_lock(self._lock_path):
                self._load()

    def _load(self) -> None:
        assert self.path is not None
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise EventLogPersistenceError("event log could not be read") from exc
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                record = EventRecord.from_dict(json.loads(line))
            except Exception as exc:
                raise EventLogPersistenceError(f"invalid event log line {line_number}: {exc}") from exc
            self._insert_loaded(record)

    def _reload_locked(self) -> None:
        self._records.clear()
        self._by_id.clear()
        if self.path is not None and self.path.exists():
            self._load()

    def _insert_loaded(self, record: EventRecord) -> None:
        existing = self._by_id.get(record.event.event_id)
        if existing is not None:
            if existing.event.fingerprint != record.event.fingerprint:
                raise DuplicateEventError(record.event.event_id)
            return
        if any(item.sequence == record.sequence for item in self._records):
            raise ValueError(f"duplicate event sequence {record.sequence}")
        self._records.append(record)
        self._by_id[record.event.event_id] = record
        self._records.sort(key=lambda item: item.sequence)

    def append(self, event: Event) -> EventRecord:
        if not isinstance(event, Event):
            raise TypeError("append accepts Event only")
        with self._lock:
            if self.path is not None:
                assert self._lock_path is not None
                with exclusive_file_lock(self._lock_path):
                    self._reload_locked()
                    return self._append_locked(event)
            return self._append_locked(event)

    def _append_locked(self, event: Event) -> EventRecord:
        existing = self._by_id.get(event.event_id)
        if existing is not None:
            if existing.event.fingerprint != event.fingerprint:
                raise DuplicateEventError(event.event_id)
            return existing

        next_sequence = max((item.sequence for item in self._records), default=0) + 1
        record = EventRecord(sequence=next_sequence, event=event)
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                encoded = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)
                with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(encoded + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except (OSError, TypeError, ValueError) as exc:
                raise EventLogPersistenceError("event record could not be persisted") from exc
        self._insert_loaded(record)
        return record

    def records(self, stream_id: str | None = None) -> tuple[EventRecord, ...]:
        with self._lock:
            if self.path is not None:
                assert self._lock_path is not None
                with exclusive_file_lock(self._lock_path):
                    self._reload_locked()
                    return self._records_for_stream_locked(stream_id)
            return self._records_for_stream_locked(stream_id)

    def _records_for_stream_locked(self, stream_id: str | None) -> tuple[EventRecord, ...]:
        items: Iterable[EventRecord] = self._records
        if stream_id is not None:
            items = (record for record in items if record.event.stream_id == stream_id)
        return tuple(items)

    def after(self, sequence: int, stream_id: str | None = None) -> tuple[EventRecord, ...]:
        return tuple(
            record
            for record in self.records(stream_id)
            if record.sequence > sequence
        )

    def __len__(self) -> int:
        return len(self.records())

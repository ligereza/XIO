"""Idempotent event log with monotonic ingestion order."""

from __future__ import annotations

from pathlib import Path
import json
from threading import RLock
from typing import Iterable

from ..contracts import Event, EventRecord


class DuplicateEventError(ValueError):
    """The same event id arrived with different content."""


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
        if self.path is not None and self.path.exists():
            self._load()

    def _load(self) -> None:
        assert self.path is not None
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = EventRecord.from_dict(json.loads(line))
            except Exception as exc:
                raise ValueError(f"invalid event log line {line_number}: {exc}") from exc
            self._insert_loaded(record)

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
        with self._lock:
            existing = self._by_id.get(event.event_id)
            if existing is not None:
                if existing.event.fingerprint != event.fingerprint:
                    raise DuplicateEventError(event.event_id)
                return existing

            next_sequence = max((item.sequence for item in self._records), default=0) + 1
            record = EventRecord(sequence=next_sequence, event=event)
            self._insert_loaded(record)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            return record

    def records(self, stream_id: str | None = None) -> tuple[EventRecord, ...]:
        with self._lock:
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
        return len(self._records)

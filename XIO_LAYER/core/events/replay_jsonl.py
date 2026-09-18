"""Deterministic JSONL storage and replay for canonical application events."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable, Mapping

from ..file_lock import exclusive_file_lock
from .application import ApplicationEvent, ApplicationEventContractError


class DuplicateApplicationEventError(ValueError):
    """The same event id appeared with a different fingerprint."""


class ApplicationEventLogPersistenceError(ValueError):
    """Raised when an application event JSONL log cannot persist safely."""


@dataclass(frozen=True, slots=True)
class ApplicationReplayResult:
    state: Mapping[str, Any]
    applied_events: int
    duplicate_events: int
    source_clock_ahead_events: int


class ApplicationEventLog:
    """Append-only JSONL log with idempotent event ids."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    def append(self, event: ApplicationEvent) -> bool:
        if not isinstance(event, ApplicationEvent):
            raise TypeError("append accepts ApplicationEvent only")
        with self._lock:
            with exclusive_file_lock(self._lock_path):
                for existing in self._read_events():
                    if existing.event_id == event.event_id:
                        if existing.fingerprint != event.fingerprint:
                            raise DuplicateApplicationEventError(event.event_id)
                        return False
                try:
                    encoded = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)
                    with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                        stream.write(encoded + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                except (OSError, TypeError, ValueError) as exc:
                    raise ApplicationEventLogPersistenceError(
                        "application event could not be persisted"
                    ) from exc
                return True

    def events(self) -> tuple[ApplicationEvent, ...]:
        with self._lock:
            with exclusive_file_lock(self._lock_path):
                return tuple(self._read_events())

    def replay(
        self,
        reducer: Callable[[Mapping[str, Any], ApplicationEvent], Mapping[str, Any]],
        initial_state: Mapping[str, Any] | None = None,
    ) -> ApplicationReplayResult:
        with self._lock:
            with exclusive_file_lock(self._lock_path):
                return replay_events(self._read_events(), reducer, initial_state)

    def _read_events(self) -> Iterable[ApplicationEvent]:
        if not self.path.exists():
            return ()
        events = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(ApplicationEvent.from_dict(json.loads(line)))
            except Exception as exc:
                raise ApplicationEventContractError(f"invalid JSONL line {line_number}: {exc}") from exc
        return events


def replay_events(
    events: Iterable[ApplicationEvent],
    reducer: Callable[[Mapping[str, Any], ApplicationEvent], Mapping[str, Any]],
    initial_state: Mapping[str, Any] | None = None,
) -> ApplicationReplayResult:
    """Replay by sequence, deduplicating identical event ids."""

    state = dict(initial_state or {})
    unique: dict[str, ApplicationEvent] = {}
    duplicate_events = 0
    for event in events:
        existing = unique.get(event.event_id)
        if existing is not None:
            if existing.fingerprint != event.fingerprint:
                raise DuplicateApplicationEventError(event.event_id)
            duplicate_events += 1
            continue
        unique[event.event_id] = event

    ordered = sorted(
        unique.values(),
        key=lambda item: (item.sequence, item.received_timestamp, item.event_id),
    )
    ahead = 0
    for event in ordered:
        state = dict(reducer(state, event))
        ahead += int(event.source_clock_is_ahead)
    return ApplicationReplayResult(
        state=state,
        applied_events=len(ordered),
        duplicate_events=duplicate_events,
        source_clock_ahead_events=ahead,
    )


def replay_jsonl(
    path: str | Path,
    reducer: Callable[[Mapping[str, Any], ApplicationEvent], Mapping[str, Any]],
    initial_state: Mapping[str, Any] | None = None,
) -> ApplicationReplayResult:
    return ApplicationEventLog(path).replay(reducer, initial_state)

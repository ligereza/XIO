"""Atomic checkpoint persistence and replay-based recovery."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from ..contracts import Checkpoint, Snapshot, utc_now
from ..events.log import EventLog
from ..events.replay import replay_events
from .projector import SnapshotProjector


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    snapshot: Snapshot
    used_checkpoint: bool
    replayed_events: int
    issues: tuple[str, ...] = ()


class CheckpointStore:
    """Store checkpoints as atomic JSON files, never as executable state."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.last_issues: list[str] = []

    @staticmethod
    def _stream_key(stream_id: str) -> str:
        return hashlib.sha256(stream_id.encode("utf-8")).hexdigest()[:24]

    def _path(self, checkpoint: Checkpoint) -> Path:
        return self.directory / f"{self._stream_key(checkpoint.stream_id)}-{checkpoint.sequence:020d}.json"

    def save(self, snapshot: Snapshot) -> Checkpoint:
        checkpoint = Checkpoint.from_snapshot(snapshot)
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self._path(checkpoint)
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.directory, prefix=".checkpoint-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(checkpoint.to_dict(), stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        return checkpoint

    def _candidates(self, stream_id: str) -> list[Path]:
        if not self.directory.exists():
            return []
        prefix = f"{self._stream_key(stream_id)}-"
        return sorted(self.directory.glob(f"{prefix}*.json"), reverse=True)

    def load_latest(self, stream_id: str) -> Checkpoint | None:
        self.last_issues = []
        for path in self._candidates(stream_id):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                checkpoint = Checkpoint.from_dict(data)
                if checkpoint.stream_id != stream_id:
                    raise ValueError("stream id mismatch")
                return checkpoint
            except Exception as exc:
                self.last_issues.append(f"{path.name}: {exc}")
        return None


class RecoveryManager:
    """Resume from a valid checkpoint and replay only the remaining events."""

    def __init__(self, checkpoints: CheckpointStore):
        self.checkpoints = checkpoints

    def recover(self, stream_id: str, events: EventLog, projector: SnapshotProjector) -> RecoveryResult:
        checkpoint = self.checkpoints.load_latest(stream_id)
        records = events.after(checkpoint.sequence, stream_id) if checkpoint else events.records(stream_id)
        replay = replay_events(records, projector.reducer, checkpoint.state if checkpoint else projector.initial_state)
        source_event_id = records[-1].event.event_id if records else (
            checkpoint.source_event_id if checkpoint else None
        )
        version = replay.last_sequence if records else (checkpoint.sequence if checkpoint else 0)
        snapshot = Snapshot(
            stream_id=stream_id,
            version=version,
            state=replay.state,
            captured_at=utc_now(),
            source_event_id=source_event_id,
        )
        return RecoveryResult(
            snapshot=snapshot,
            used_checkpoint=checkpoint is not None,
            replayed_events=replay.applied_events,
            issues=tuple(self.checkpoints.last_issues),
        )

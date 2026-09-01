"""Append-only audit ledger with a small hash chain."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from ..contracts import AuditEntry, content_hash, utc_now


class AuditLedger:
    """Keep an append-only in-memory ledger.

    Persistence is deliberately left behind a port: the core can be used in a
    process, while a host may provide encrypted or retained storage later.
    """

    def __init__(self):
        self._entries: list[AuditEntry] = []
        self._lock = RLock()

    def append(
        self,
        event_type: str,
        subject_id: str,
        outcome: str,
        details: Mapping[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> AuditEntry:
        with self._lock:
            entry = self._build_entry_locked(event_type, subject_id, outcome, details, actor_id)
            self._entries.append(entry)
            return entry

    def _build_entry_locked(
        self,
        event_type: str,
        subject_id: str,
        outcome: str,
        details: Mapping[str, Any] | None,
        actor_id: str | None,
    ) -> AuditEntry:
        previous_hash = self._entries[-1].entry_hash if self._entries else "GENESIS"
        recorded_at = utc_now()
        unsigned = {
            "audit_id": str(uuid4()),
            "recorded_at": recorded_at.isoformat(),
            "event_type": event_type,
            "subject_id": subject_id,
            "actor_id": actor_id,
            "outcome": outcome,
            "details": dict(details or {}),
            "previous_hash": previous_hash,
        }
        return AuditEntry(
            audit_id=unsigned["audit_id"],
            recorded_at=recorded_at,
            event_type=event_type,
            subject_id=subject_id,
            actor_id=actor_id,
            outcome=outcome,
            details=unsigned["details"],
            previous_hash=previous_hash,
            entry_hash=content_hash(unsigned),
        )

    def entries(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    def verify(self) -> bool:
        with self._lock:
            return self._verify_entries(self._entries)

    @staticmethod
    def _verify_entries(entries: list[AuditEntry] | tuple[AuditEntry, ...]) -> bool:
        previous_hash = "GENESIS"
        for entry in entries:
            if entry.previous_hash != previous_hash:
                return False
            if entry.entry_hash != content_hash(entry.unsigned_dict()):
                return False
            previous_hash = entry.entry_hash
        return True


class AuditLedgerPersistenceError(ValueError):
    """Raised when a persisted audit ledger is malformed or tampered with."""


class JsonLineAuditLedger(AuditLedger):
    """Append-only JSONL audit ledger that survives process restarts."""

    def __init__(self, path: str | Path):
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries = self._load_entries()

    def append(
        self,
        event_type: str,
        subject_id: str,
        outcome: str,
        details: Mapping[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> AuditEntry:
        with self._lock:
            try:
                entry = self._build_entry_locked(event_type, subject_id, outcome, details, actor_id)
            except (TypeError, ValueError) as exc:
                raise AuditLedgerPersistenceError("audit entry cannot be represented safely") from exc
            try:
                encoded = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise AuditLedgerPersistenceError("audit entry is not JSON-safe") from exc
            try:
                with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(encoded + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                raise AuditLedgerPersistenceError("audit entry could not be persisted") from exc
            self._entries.append(entry)
            return entry

    def _load_entries(self) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        entries: list[AuditEntry] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                entry = AuditEntry.from_dict(json.loads(line))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise AuditLedgerPersistenceError(
                    f"invalid audit JSONL line {line_number}"
                ) from exc
            entries.append(entry)
        if not self._verify_entries(entries):
            raise AuditLedgerPersistenceError("audit ledger hash chain verification failed")
        return entries


__all__ = [
    "AuditLedger",
    "AuditLedgerPersistenceError",
    "JsonLineAuditLedger",
]

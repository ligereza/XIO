"""Append-only audit ledger with a small hash chain."""

from __future__ import annotations

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
            entry = AuditEntry(
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
            self._entries.append(entry)
            return entry

    def entries(self) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    def verify(self) -> bool:
        with self._lock:
            previous_hash = "GENESIS"
            for entry in self._entries:
                if entry.previous_hash != previous_hash:
                    return False
                if entry.entry_hash != content_hash(entry.unsigned_dict()):
                    return False
                previous_hash = entry.entry_hash
            return True

"""Restart-safe local storage for prepared adapter handoffs."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

from ..core.contracts import content_hash
from ..core.file_lock import exclusive_file_lock
from .handoff import AdapterHandoff, AdapterHandoffError


HANDOFF_STORE_SCHEMA_VERSION = 1
HANDOFF_STORE_GENESIS = "GENESIS"


class HandoffStoreError(ValueError):
    """Raised when a prepared handoff store is malformed."""


class DuplicateHandoffError(HandoffStoreError):
    """Raised when one handoff id is reused with different prepared content."""


class HandoffIntegrityError(HandoffStoreError):
    """Raised when a persisted handoff record fails its hash chain."""


class JsonLineHandoffStore:
    """Append-only JSONL store for privacy-safe prepared handoff records."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def append(self, handoff: AdapterHandoff) -> bool:
        if not isinstance(handoff, AdapterHandoff):
            raise TypeError("handoff must be an AdapterHandoff")
        with self._lock:
            with exclusive_file_lock(self.path.with_name(self.path.name + ".lock")):
                return self._append_unlocked(handoff)

    def _append_unlocked(self, handoff: AdapterHandoff) -> bool:
        if not isinstance(handoff, AdapterHandoff):
            raise TypeError("handoff must be an AdapterHandoff")
        wire = handoff.to_dict()
        fingerprint = _stable_fingerprint(wire)
        entries = self._read_entries()
        for existing in entries:
            existing_handoff = existing["handoff"]
            if existing_handoff.get("handoff_id") != handoff.handoff_id:
                continue
            if _stable_fingerprint(existing_handoff) != fingerprint:
                raise DuplicateHandoffError(handoff.handoff_id)
            return False
        previous_hash = entries[-1]["record_hash"] if entries else HANDOFF_STORE_GENESIS
        entry = {
            "schema_version": HANDOFF_STORE_SCHEMA_VERSION,
            "handoff": wire,
            "previous_hash": previous_hash,
        }
        entry["record_hash"] = _record_hash(entry)
        try:
            encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise HandoffStoreError("handoff is not JSON-safe") from exc
        try:
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise HandoffStoreError("handoff could not be persisted") from exc
        return True

    def replay(self, *, caller_id: str) -> tuple[AdapterHandoff, ...]:
        with self._lock:
            with exclusive_file_lock(self.path.with_name(self.path.name + ".lock")):
                return self._replay_unlocked(caller_id=caller_id)

    def _replay_unlocked(self, *, caller_id: str) -> tuple[AdapterHandoff, ...]:
        """Restore unique prepared handoffs with an explicitly supplied caller id."""

        restored: dict[str, AdapterHandoff] = {}
        fingerprints: dict[str, str] = {}
        for entry in self._read_entries():
            wire = entry["handoff"]
            try:
                handoff = AdapterHandoff.from_dict(wire, caller_id=caller_id)
            except AdapterHandoffError as exc:
                raise HandoffStoreError("stored handoff failed reconstruction") from exc
            fingerprint = _stable_fingerprint(wire)
            existing = restored.get(handoff.handoff_id)
            if existing is not None:
                if fingerprints[handoff.handoff_id] != fingerprint:
                    raise DuplicateHandoffError(handoff.handoff_id)
                continue
            restored[handoff.handoff_id] = handoff
            fingerprints[handoff.handoff_id] = fingerprint
        return tuple(
            sorted(
                restored.values(),
                key=lambda item: (
                    item.message.sequence or 0,
                    item.message.sent_at,
                    item.handoff_id,
                ),
            )
        )

    def _read_entries(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        entries: list[dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise HandoffStoreError("handoff store could not be read") from exc
        previous_hash = HANDOFF_STORE_GENESIS
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, TypeError) as exc:
                raise HandoffStoreError(f"invalid handoff JSONL line {line_number}") from exc
            if not isinstance(value, dict):
                raise HandoffStoreError(f"handoff JSONL line {line_number} must be an object")
            _validate_entry(value, line_number, previous_hash)
            entries.append(value)
            previous_hash = value["record_hash"]
        return tuple(entries)


def _stable_fingerprint(wire: dict[str, Any]) -> str:
    stable = deepcopy(wire)
    stable.pop("prepared_at", None)
    return content_hash(stable)


def _record_hash(entry: dict[str, Any]) -> str:
    unsigned = {
        "schema_version": entry["schema_version"],
        "handoff": entry["handoff"],
        "previous_hash": entry["previous_hash"],
    }
    return content_hash(unsigned)


def _validate_entry(value: dict[str, Any], line_number: int, previous_hash: str) -> None:
    required = {"schema_version", "handoff", "previous_hash", "record_hash"}
    if set(value) != required:
        raise HandoffIntegrityError(f"handoff record fields invalid at line {line_number}")
    if (
        isinstance(value["schema_version"], bool)
        or not isinstance(value["schema_version"], int)
        or value["schema_version"] != HANDOFF_STORE_SCHEMA_VERSION
    ):
        raise HandoffIntegrityError(f"unsupported handoff store schema at line {line_number}")
    if value["previous_hash"] != previous_hash:
        raise HandoffIntegrityError(f"handoff hash chain broken at line {line_number}")
    if not isinstance(value["handoff"], dict):
        raise HandoffIntegrityError(f"handoff payload invalid at line {line_number}")
    if value["record_hash"] != _record_hash(value):
        raise HandoffIntegrityError(f"handoff record tampered at line {line_number}")


__all__ = [
    "DuplicateHandoffError",
    "HANDOFF_STORE_SCHEMA_VERSION",
    "HandoffIntegrityError",
    "HandoffStoreError",
    "JsonLineHandoffStore",
]

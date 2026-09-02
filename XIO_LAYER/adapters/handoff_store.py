"""Restart-safe local storage for prepared adapter handoffs."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any

from ..core.contracts import content_hash
from .handoff import AdapterHandoff, AdapterHandoffError


class HandoffStoreError(ValueError):
    """Raised when a prepared handoff store is malformed."""


class DuplicateHandoffError(HandoffStoreError):
    """Raised when one handoff id is reused with different prepared content."""


class JsonLineHandoffStore:
    """Append-only JSONL store for privacy-safe prepared handoff records."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, handoff: AdapterHandoff) -> bool:
        if not isinstance(handoff, AdapterHandoff):
            raise TypeError("handoff must be an AdapterHandoff")
        wire = handoff.to_dict()
        fingerprint = _stable_fingerprint(wire)
        for existing in self._read_wires():
            if existing.get("handoff_id") != handoff.handoff_id:
                continue
            if _stable_fingerprint(existing) != fingerprint:
                raise DuplicateHandoffError(handoff.handoff_id)
            return False
        try:
            encoded = json.dumps(wire, ensure_ascii=False, sort_keys=True, allow_nan=False)
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
        """Restore unique prepared handoffs with an explicitly supplied caller id."""

        restored: dict[str, AdapterHandoff] = {}
        fingerprints: dict[str, str] = {}
        for wire in self._read_wires():
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

    def _read_wires(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        wires: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, TypeError) as exc:
                raise HandoffStoreError(f"invalid handoff JSONL line {line_number}") from exc
            if not isinstance(value, dict):
                raise HandoffStoreError(f"handoff JSONL line {line_number} must be an object")
            wires.append(value)
        return tuple(wires)


def _stable_fingerprint(wire: dict[str, Any]) -> str:
    stable = deepcopy(wire)
    stable.pop("prepared_at", None)
    return content_hash(stable)


__all__ = [
    "DuplicateHandoffError",
    "HandoffStoreError",
    "JsonLineHandoffStore",
]

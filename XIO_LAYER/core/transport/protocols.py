"""Protocol-specific envelopes kept distinct inside TRANSPORT."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import base64
import json
from typing import Any

from ..contracts import require_utc


def _osc_argument(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class OscEnvelope:
    """OSC address plus typed arguments and optional timetag."""

    address: str
    arguments: tuple[Any, ...] = ()
    timetag: datetime | None = None

    protocol: str = field(init=False, default="osc")

    def __post_init__(self) -> None:
        if not isinstance(self.address, str):
            raise ValueError("OSC address must be a string")
        if not self.address.startswith("/"):
            raise ValueError("OSC address must start with '/'")
        if isinstance(self.arguments, (str, bytes, Mapping)):
            raise ValueError("OSC arguments must be a collection, not text or a mapping")
        try:
            arguments = tuple(deepcopy(self.arguments))
        except TypeError as exc:
            raise ValueError("OSC arguments must be an iterable") from exc
        object.__setattr__(self, "arguments", arguments)
        if self.timetag is not None:
            object.__setattr__(self, "timetag", require_utc(self.timetag, "timetag"))
        try:
            json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("OSC envelope arguments must be JSON-safe") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "address": self.address,
            "arguments": [_osc_argument(value) for value in self.arguments],
            "timetag": self.timetag.isoformat() if self.timetag else None,
        }


@dataclass(frozen=True, slots=True)
class ArtNetEnvelope:
    """Art-Net frame metadata and opaque DMX bytes, not an OSC argument list."""

    universe: int
    data: bytes
    sequence: int = 0
    opcode: str = "ArtDMX"
    physical: int = 0

    protocol: str = field(init=False, default="artnet")

    def __post_init__(self) -> None:
        if isinstance(self.universe, bool) or not isinstance(self.universe, int) or not 0 <= self.universe <= 32767:
            raise ValueError("Art-Net universe must be between 0 and 32767")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or isinstance(self.physical, bool)
            or not isinstance(self.physical, int)
            or not 0 <= self.sequence <= 255
            or not 0 <= self.physical <= 255
        ):
            raise ValueError("Art-Net sequence and physical values must be bytes")
        if not isinstance(self.data, bytes):
            raise TypeError("Art-Net data must be bytes")
        if len(self.data) > 512:
            raise ValueError("Art-Net DMX payload cannot exceed 512 bytes")
        if not isinstance(self.opcode, str) or not self.opcode.strip():
            raise ValueError("Art-Net opcode must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "opcode": self.opcode,
            "universe": self.universe,
            "sequence": self.sequence,
            "physical": self.physical,
            "data_base64": base64.b64encode(self.data).decode("ascii"),
        }

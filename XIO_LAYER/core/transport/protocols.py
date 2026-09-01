"""Protocol-specific envelopes kept distinct inside TRANSPORT."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import base64
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
        if not self.address.startswith("/"):
            raise ValueError("OSC address must start with '/'")
        if self.timetag is not None:
            object.__setattr__(self, "timetag", require_utc(self.timetag, "timetag"))
        object.__setattr__(self, "arguments", tuple(deepcopy(self.arguments)))

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
        if not 0 <= self.universe <= 32767:
            raise ValueError("Art-Net universe must be between 0 and 32767")
        if not 0 <= self.sequence <= 255 or not 0 <= self.physical <= 255:
            raise ValueError("Art-Net sequence and physical values must be bytes")
        if not isinstance(self.data, bytes):
            raise TypeError("Art-Net data must be bytes")
        if len(self.data) > 512:
            raise ValueError("Art-Net DMX payload cannot exceed 512 bytes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "opcode": self.opcode,
            "universe": self.universe,
            "sequence": self.sequence,
            "physical": self.physical,
            "data_base64": base64.b64encode(self.data).decode("ascii"),
        }

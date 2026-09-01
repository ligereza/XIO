"""Injected OSC and Art-Net to ApplicationEvent adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ..core.contracts import utc_now
from ..core.events import ApplicationEvent
from ..core.transport import ArtNetEnvelope, OscEnvelope


@dataclass(frozen=True, slots=True)
class ProtocolEventAdapter:
    source_app: str
    session_id: str
    peer_id: str

    @property
    def supported_event_types(self) -> frozenset[str]:
        return frozenset({"osc.message", "artnet.frame"})

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset({"protocol.osc", "protocol.artnet"})

    def convert(self, record: Mapping[str, Any], event_type: str) -> ApplicationEvent:
        if not isinstance(record, Mapping):
            raise ValueError("protocol source record must be a mapping")
        if event_type == "osc.message":
            envelope = record["envelope"]
            if not isinstance(envelope, OscEnvelope):
                raise TypeError("osc source record requires OscEnvelope")
            return self.from_osc(
                envelope,
                channel=record["channel"],
                sequence=record["sequence"],
                source_timestamp=record.get("source_timestamp"),
                received_timestamp=record.get("received_timestamp"),
                provenance=record.get("provenance"),
            )
        if event_type == "artnet.frame":
            envelope = record["envelope"]
            if not isinstance(envelope, ArtNetEnvelope):
                raise TypeError("artnet source record requires ArtNetEnvelope")
            return self.from_artnet(
                envelope,
                channel=record["channel"],
                sequence=record["sequence"],
                source_timestamp=record["source_timestamp"],
                received_timestamp=record.get("received_timestamp"),
                provenance=record.get("provenance"),
            )
        raise ValueError(f"unsupported protocol event type: {event_type}")

    def from_osc(
        self,
        envelope: OscEnvelope,
        *,
        channel: str,
        sequence: int,
        source_timestamp: datetime | None = None,
        received_timestamp: datetime | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> ApplicationEvent:
        received = received_timestamp or utc_now()
        return ApplicationEvent(
            source_app=self.source_app,
            event_type="osc.message",
            channel=channel,
            payload=envelope.to_dict(),
            source_timestamp=source_timestamp or envelope.timetag or received,
            received_timestamp=received,
            session_id=self.session_id,
            peer_id=self.peer_id,
            sequence=sequence,
            provenance={
                "adapter": "osc",
                "protocol": "osc",
                "envelope": envelope.to_dict(),
                **dict(provenance or {}),
            },
        )

    def from_artnet(
        self,
        envelope: ArtNetEnvelope,
        *,
        channel: str,
        sequence: int,
        source_timestamp: datetime,
        received_timestamp: datetime | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> ApplicationEvent:
        received = received_timestamp or utc_now()
        return ApplicationEvent(
            source_app=self.source_app,
            event_type="artnet.frame",
            channel=channel,
            payload=envelope.to_dict(),
            source_timestamp=source_timestamp,
            received_timestamp=received,
            session_id=self.session_id,
            peer_id=self.peer_id,
            sequence=sequence,
            provenance={
                "adapter": "artnet",
                "protocol": "artnet",
                "envelope": envelope.to_dict(),
                **dict(provenance or {}),
            },
        )

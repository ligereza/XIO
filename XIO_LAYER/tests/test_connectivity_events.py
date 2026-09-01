from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import tempfile
from unittest.mock import patch
import unittest

from XIO_LAYER.adapters import (
    CONNECTIVITY_EVENT_CHANNEL,
    CONNECTIVITY_EVENT_TYPE,
    ConnectivityEventError,
    connectivity_status_to_event,
)
from XIO_LAYER.core.events import ApplicationEvent, ApplicationEventLog
from XIO_LAYER.core.events.replay_jsonl import replay_events as replay_application_events
from XIO_LAYER.core.transport import (
    ConnectionState,
    ConnectionStatus,
    Endpoint,
    NetworkMedium,
    NetworkScope,
)


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
LOCAL_ZONE = timezone(timedelta(hours=-4))


def make_status(medium, state=ConnectionState.CONNECTED, reason="host_probe_ok"):
    return ConnectionStatus(
        endpoint=Endpoint(
            "memory",
            f"{medium.value}-host",
            medium=medium,
            scope=NetworkScope.LAN,
        ),
        state=state,
        checked_at=T0,
        latency_ms=15.0 if state is ConnectionState.CONNECTED else None,
        packets_sent=10,
        packets_received=9,
        packets_lost=1,
        reason=reason,
    )


class ConnectivityEventTests(unittest.TestCase):
    def test_all_supported_media_are_preserved_in_payload_and_provenance(self):
        for medium in (
            NetworkMedium.ETHERNET,
            NetworkMedium.WIFI,
            NetworkMedium.HOTSPOT,
            NetworkMedium.ROUTER,
        ):
            with self.subTest(medium=medium):
                event = connectivity_status_to_event(
                    make_status(medium),
                    source_app="host-monitor",
                    session_id="session-1",
                    peer_id="peer-1",
                    sequence=1,
                    received_timestamp=T0 + timedelta(seconds=1),
                    provenance={"probe_id": "fixture-probe"},
                )

                self.assertEqual(event.event_type, CONNECTIVITY_EVENT_TYPE)
                self.assertEqual(event.channel, CONNECTIVITY_EVENT_CHANNEL)
                self.assertEqual(event.payload["endpoint"]["medium"], medium.value)
                self.assertEqual(event.payload["endpoint"]["scope"], NetworkScope.LAN.value)
                self.assertEqual(event.payload["state"], ConnectionState.CONNECTED.value)
                self.assertEqual(event.payload["latency_ms"], 15.0)
                self.assertEqual(event.payload["packets_sent"], 10)
                self.assertEqual(event.payload["packets_received"], 9)
                self.assertEqual(event.payload["packets_lost"], 1)
                self.assertEqual(event.payload["loss_ratio"], 0.1)
                self.assertEqual(event.payload["checked_at"], T0.isoformat())
                self.assertEqual(event.payload["reason"], "host_probe_ok")
                self.assertEqual(event.provenance["origin"], "host_probe")
                self.assertEqual(event.provenance["probe_id"], "fixture-probe")

    def test_unknown_and_blocked_statuses_keep_optional_values_unknown(self):
        unknown = connectivity_status_to_event(
            make_status(NetworkMedium.WIFI, ConnectionState.UNKNOWN, "not_measured"),
            source_app="host-monitor",
            session_id="session-1",
            peer_id="peer-1",
            sequence=1,
            received_timestamp=T0,
        )
        blocked = connectivity_status_to_event(
            make_status(NetworkMedium.HOTSPOT, ConnectionState.BLOCKED, "policy_denied"),
            source_app="host-monitor",
            session_id="session-1",
            peer_id="peer-1",
            sequence=2,
            received_timestamp=T0,
        )

        self.assertEqual(unknown.payload["state"], "unknown")
        self.assertIsNone(unknown.payload["latency_ms"])
        self.assertEqual(unknown.payload["reason"], "not_measured")
        self.assertEqual(blocked.payload["state"], "blocked")
        self.assertIsNone(blocked.payload["latency_ms"])
        self.assertEqual(blocked.payload["reason"], "policy_denied")

    def test_stale_status_keeps_source_time_separate_from_received_time(self):
        stale_status = ConnectionStatus(
            endpoint=Endpoint(
                "memory",
                "wifi-host",
                medium=NetworkMedium.WIFI,
                scope=NetworkScope.LAN,
            ),
            state=ConnectionState.DEGRADED,
            checked_at=T0 - timedelta(minutes=5),
            latency_ms=None,
            packets_sent=10,
            packets_received=6,
            packets_lost=4,
            reason="stale_measurement",
        )

        event = connectivity_status_to_event(
            stale_status,
            source_app="host-monitor",
            session_id="session-1",
            peer_id="peer-1",
            sequence=4,
            received_timestamp=T0,
        )

        self.assertEqual(event.source_timestamp, T0 - timedelta(minutes=5))
        self.assertEqual(event.received_timestamp, T0)
        self.assertFalse(event.source_clock_is_ahead)
        self.assertEqual(event.payload["state"], "degraded")
        self.assertEqual(event.payload["loss_ratio"], 0.4)
        self.assertEqual(event.payload["reason"], "stale_measurement")

    def test_event_round_trip_keeps_timezone_provenance_and_stable_hash(self):
        status = make_status(NetworkMedium.ETHERNET)
        event = connectivity_status_to_event(
            status,
            source_app="host-monitor",
            session_id="session-1",
            peer_id="peer-1",
            sequence=3,
            received_timestamp=datetime(2026, 9, 1, 8, 0, tzinfo=LOCAL_ZONE),
        )
        restored = ApplicationEvent.from_dict(json.loads(json.dumps(event.to_dict(), sort_keys=True)))
        repeated = connectivity_status_to_event(
            status,
            source_app="host-monitor",
            session_id="session-1",
            peer_id="peer-1",
            sequence=3,
            received_timestamp=T0 + timedelta(hours=1),
        )

        self.assertEqual(event.source_timestamp, T0)
        self.assertEqual(event.received_timestamp, T0)
        self.assertEqual(restored.to_dict(), event.to_dict())
        self.assertEqual(restored.raw_hash, event.raw_hash)
        self.assertEqual(repeated.event_id, event.event_id)

    def test_adapter_does_not_open_sockets_or_measure_on_its_own(self):
        status = make_status(NetworkMedium.ROUTER)
        with patch("socket.socket", side_effect=AssertionError("adapter must not open sockets")) as socket_factory:
            event = connectivity_status_to_event(
                status,
                source_app="host-monitor",
                session_id="session-1",
                peer_id="peer-1",
                sequence=1,
                received_timestamp=T0,
            )

        self.assertEqual(event.payload["state"], "connected")
        self.assertEqual(socket_factory.call_count, 0)

    def test_identical_status_events_are_idempotent_in_log_and_replay(self):
        status = make_status(NetworkMedium.ETHERNET)
        first = connectivity_status_to_event(
            status,
            source_app="host-monitor",
            session_id="session-1",
            peer_id="peer-1",
            sequence=1,
            received_timestamp=T0,
        )
        duplicate = connectivity_status_to_event(
            status,
            source_app="host-monitor",
            session_id="session-1",
            peer_id="peer-1",
            sequence=1,
            received_timestamp=T0,
        )

        def reducer(state, event):
            next_state = dict(state)
            next_state["count"] = next_state.get("count", 0) + 1
            return next_state

        replayed = replay_application_events((first, duplicate), reducer)
        self.assertEqual(first.event_id, duplicate.event_id)
        self.assertEqual(first.fingerprint, duplicate.fingerprint)
        self.assertEqual(replayed.applied_events, 1)
        self.assertEqual(replayed.duplicate_events, 1)
        self.assertEqual(replayed.state, {"count": 1})

        with tempfile.TemporaryDirectory() as directory:
            log = ApplicationEventLog(f"{directory}/connectivity.jsonl")
            self.assertTrue(log.append(first))
            self.assertFalse(log.append(duplicate))
            self.assertEqual(len(log.events()), 1)

    def test_malformed_status_is_rejected_by_the_adapter(self):
        malformed = make_status(NetworkMedium.ROUTER)
        object.__setattr__(malformed, "latency_ms", -1.0)

        with self.assertRaises(ConnectivityEventError):
            connectivity_status_to_event(
                malformed,
                source_app="host-monitor",
                session_id="session-1",
                peer_id="peer-1",
                sequence=1,
                received_timestamp=T0,
            )

    def test_invalid_input_is_rejected_without_inventing_status(self):
        with self.assertRaises(ConnectivityEventError):
            connectivity_status_to_event(
                object(),
                source_app="host-monitor",
                session_id="session-1",
                peer_id="peer-1",
                sequence=1,
                received_timestamp=T0,
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import datetime, timezone
import json
from unittest.mock import patch
import unittest

from XIO_LAYER.core.transport import (
    ConnectionState,
    ConnectionStatus,
    ConnectivityProbeError,
    Endpoint,
    NetworkMedium,
    NetworkScope,
    probe_connectivity,
)


T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class FixedProbe:
    def __init__(self, report):
        self.report = report
        self.calls = []

    def probe(self, endpoint):
        self.calls.append(endpoint)
        return self.report


class ConnectivityContractTests(unittest.TestCase):
    def test_injected_probe_returns_host_measurement_without_mutation(self):
        endpoint = Endpoint(
            "ethernet",
            "mak",
            medium=NetworkMedium.ETHERNET,
            scope=NetworkScope.LAN,
        )
        report = ConnectionStatus(
            endpoint=endpoint,
            state=ConnectionState.CONNECTED,
            checked_at=T0,
            latency_ms=12.5,
            packets_sent=10,
            packets_received=9,
            packets_lost=1,
            reason="host_probe_ok",
        )
        probe = FixedProbe(report)

        result = probe_connectivity(probe, endpoint)

        self.assertIs(result, report)
        self.assertEqual(probe.calls, [endpoint])
        self.assertEqual(result.endpoint.medium, NetworkMedium.ETHERNET)
        self.assertEqual(result.endpoint.scope, NetworkScope.LAN)
        self.assertEqual(result.loss_ratio, 0.1)

    def test_unknown_and_blocked_states_serialize_with_reason(self):
        cases = (
            (NetworkMedium.WIFI, ConnectionState.UNKNOWN, "not_measured"),
            (NetworkMedium.HOTSPOT, ConnectionState.BLOCKED, "policy_denied"),
            (NetworkMedium.ROUTER, ConnectionState.ERROR, "host_probe_error"),
        )
        for medium, state, reason in cases:
            with self.subTest(medium=medium, state=state):
                status = ConnectionStatus(
                    endpoint=Endpoint("memory", "host", medium=medium, scope=NetworkScope.LOCAL),
                    state=state,
                    checked_at=T0,
                    reason=reason,
                )
                wire = json.loads(json.dumps(status.to_dict(), sort_keys=True))
                restored = ConnectionStatus.from_dict(wire)
                self.assertEqual(restored.to_dict(), status.to_dict())
                self.assertIsNone(restored.latency_ms)
                self.assertEqual(restored.reason, reason)

    def test_probe_does_not_open_sockets_or_discover_peers(self):
        endpoint = Endpoint("wifi", "xio", medium=NetworkMedium.WIFI, scope=NetworkScope.LAN)
        report = ConnectionStatus(
            endpoint=endpoint,
            state=ConnectionState.UNKNOWN,
            checked_at=T0,
            reason="host_did_not_measure",
        )

        with patch("socket.socket", side_effect=AssertionError("XIO must not open sockets")) as socket_factory:
            result = probe_connectivity(FixedProbe(report), endpoint)

        self.assertEqual(result.state, ConnectionState.UNKNOWN)
        self.assertEqual(socket_factory.call_count, 0)

    def test_invalid_probe_output_and_endpoint_are_rejected(self):
        endpoint = Endpoint("memory", "queue")
        valid = ConnectionStatus(endpoint=endpoint, state=ConnectionState.UNKNOWN, checked_at=T0)

        with self.assertRaises(ConnectivityProbeError):
            probe_connectivity(FixedProbe({}), endpoint)
        with self.assertRaises(ConnectivityProbeError):
            probe_connectivity(FixedProbe(valid), Endpoint("memory", "other"))
        with self.assertRaises(ConnectivityProbeError):
            probe_connectivity(object(), endpoint)

    def test_probe_failure_is_not_converted_into_an_invented_measurement(self):
        class FailingProbe:
            def probe(self, endpoint):
                raise RuntimeError("host probe unavailable")

        with self.assertRaisesRegex(RuntimeError, "host probe unavailable"):
            probe_connectivity(FailingProbe(), Endpoint("memory", "queue"))


if __name__ == "__main__":
    unittest.main()

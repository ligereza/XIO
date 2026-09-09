"""Injected host probe boundary for offline connectivity capability reports."""

from __future__ import annotations

from typing import Protocol

from .transport import ConnectionStatus, Endpoint


class ConnectivityProbeError(ValueError):
    """Raised when an injected host probe returns an invalid report."""


class ConnectivityProbe(Protocol):
    """Host-owned measurement port; XIO Layer never implements network I/O."""

    def probe(self, endpoint: Endpoint) -> ConnectionStatus: ...


def probe_connectivity(probe: ConnectivityProbe, endpoint: Endpoint) -> ConnectionStatus:
    """Validate one host-provided connectivity report without fallback values."""

    if not isinstance(endpoint, Endpoint):
        raise ConnectivityProbeError("probe endpoint must be an Endpoint")
    method = getattr(probe, "probe", None)
    if not callable(method):
        raise ConnectivityProbeError("probe must provide a callable probe method")
    report = method(endpoint)
    if not isinstance(report, ConnectionStatus):
        raise ConnectivityProbeError("probe must return ConnectionStatus")
    if report.endpoint != endpoint:
        raise ConnectivityProbeError("probe report endpoint does not match requested endpoint")
    return report


__all__ = ["ConnectivityProbe", "ConnectivityProbeError", "probe_connectivity"]

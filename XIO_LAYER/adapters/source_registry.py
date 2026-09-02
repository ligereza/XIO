"""App-agnostic registry for validated source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from ..core.contracts import content_hash, require_utc, utc_now
from ..core.events import ApplicationEvent


class SourceAdapterRegistryError(ValueError):
    """Base error for source adapter declaration and routing failures."""


class DuplicateSourceAdapterError(SourceAdapterRegistryError):
    """Raised when a source_app id is already registered."""


class InvalidSourceAdapterError(SourceAdapterRegistryError):
    """Raised when an adapter declaration is incomplete or not ASCII-safe."""


class UnknownSourceAdapterError(KeyError):
    """Raised when routing requests a source_app that is not registered."""


class UndeclaredEventTypeError(SourceAdapterRegistryError):
    """Raised when a source adapter did not declare an event type."""


class StaleRoutePlanError(SourceAdapterRegistryError):
    """Raised when a caller selects from a route plan that is no longer current."""


class CandidateNotAvailableError(SourceAdapterRegistryError):
    """Raised when the caller selects a source that is not a current candidate."""


class NoRouteMatchError(SourceAdapterRegistryError):
    """Raised when a valid route query has no adapter candidate."""


class SourceAdapter(Protocol):
    """Adapter contract for already validated source records."""

    source_app: str
    supported_event_types: frozenset[str]
    capabilities: frozenset[str]

    def convert(self, record: Mapping[str, Any], event_type: str) -> ApplicationEvent: ...


@dataclass(frozen=True, slots=True)
class SourceAdapterDeclaration:
    """Immutable registry snapshot of one adapter declaration."""

    source_app: str
    supported_event_types: frozenset[str]
    capabilities: frozenset[str]


@dataclass(frozen=True, slots=True)
class AdapterSelection:
    """Caller-owned selection; it grants no execution authority."""

    selection_id: str
    source_app: str
    event_type: str
    required_capabilities: tuple[str, ...]
    plan_fingerprint: str
    caller_id: str
    selected_at: datetime

    def __post_init__(self) -> None:
        _validate_identifier(self.selection_id, "selection_id")
        _validate_identifier(self.source_app, "source_app")
        _validate_identifier(self.event_type, "event_type")
        _validate_identifier(self.caller_id, "caller_id")
        if not isinstance(self.plan_fingerprint, str) or not self.plan_fingerprint.strip():
            raise InvalidSourceAdapterError("plan_fingerprint must be a non-empty string")
        normalized = tuple(sorted(set(self.required_capabilities)))
        for value in normalized:
            _validate_identifier(value, "required_capability")
        object.__setattr__(self, "required_capabilities", normalized)
        object.__setattr__(self, "selected_at", require_utc(self.selected_at, "selected_at"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection_id": self.selection_id,
            "source_app": self.source_app,
            "event_type": self.event_type,
            "required_capabilities": list(self.required_capabilities),
            "plan_fingerprint": self.plan_fingerprint,
            "caller_id": self.caller_id,
            "selected_at": self.selected_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdapterSelection":
        if not isinstance(data, Mapping):
            raise InvalidSourceAdapterError("adapter selection must be a mapping")
        required = {
            "selection_id",
            "source_app",
            "event_type",
            "required_capabilities",
            "plan_fingerprint",
            "caller_id",
            "selected_at",
        }
        if set(data) != required:
            raise InvalidSourceAdapterError("adapter selection fields do not match the contract")
        capabilities = data["required_capabilities"]
        if isinstance(capabilities, str) or not isinstance(capabilities, (list, tuple)):
            raise InvalidSourceAdapterError("required_capabilities must be a list")
        try:
            selected_at = datetime.fromisoformat(str(data["selected_at"]))
        except (TypeError, ValueError) as exc:
            raise InvalidSourceAdapterError("selected_at must be an ISO datetime") from exc
        return cls(
            selection_id=data["selection_id"],
            source_app=data["source_app"],
            event_type=data["event_type"],
            required_capabilities=tuple(capabilities),
            plan_fingerprint=data["plan_fingerprint"],
            caller_id=data["caller_id"],
            selected_at=selected_at,
        )


@dataclass(frozen=True, slots=True)
class _RegisteredSourceAdapter:
    adapter: SourceAdapter
    declaration: SourceAdapterDeclaration


class SourceAdapterRegistry:
    """Register and route source adapters without discovery or network I/O."""

    def __init__(self) -> None:
        self._adapters: dict[str, _RegisteredSourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> SourceAdapterDeclaration:
        declaration = _read_declaration(adapter)
        if declaration.source_app in self._adapters:
            raise DuplicateSourceAdapterError(declaration.source_app)
        self._adapters[declaration.source_app] = _RegisteredSourceAdapter(adapter, declaration)
        return declaration

    def get_adapter(self, source_app: str) -> SourceAdapter:
        registered = self._adapters.get(source_app)
        if registered is None:
            raise UnknownSourceAdapterError(source_app)
        return registered.adapter

    def declaration(self, source_app: str) -> SourceAdapterDeclaration:
        registered = self._adapters.get(source_app)
        if registered is None:
            raise UnknownSourceAdapterError(source_app)
        return registered.declaration

    def source_apps(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a deterministic JSON-safe copy of public adapter declarations."""

        return [
            {
                "source_app": registered.declaration.source_app,
                "supported_event_types": sorted(registered.declaration.supported_event_types),
                "capabilities": sorted(registered.declaration.capabilities),
            }
            for registered in sorted(
                self._adapters.values(),
                key=lambda item: item.declaration.source_app,
            )
        ]

    def candidates(
        self,
        event_type: str,
        required_capabilities: frozenset[str] | set[str] | tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        """Return declarations matching an event type and required capabilities."""

        _validate_identifier(event_type, "event_type")
        required = _read_query_identifiers(required_capabilities)
        return [
            {
                "source_app": registered.declaration.source_app,
                "supported_event_types": sorted(registered.declaration.supported_event_types),
                "capabilities": sorted(registered.declaration.capabilities),
            }
            for registered in sorted(
                self._adapters.values(),
                key=lambda item: item.declaration.source_app,
            )
            if event_type in registered.declaration.supported_event_types
            and required.issubset(registered.declaration.capabilities)
        ]

    def route_plan(
        self,
        event_type: str,
        required_capabilities: frozenset[str] | set[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Return declarative routing metadata without selecting or executing an adapter."""

        _validate_identifier(event_type, "event_type")
        required = _read_query_identifiers(required_capabilities)
        candidates = self.candidates(event_type, required)
        return {
            "status": "matched" if candidates else "no_match",
            "event_type": event_type,
            "required_capabilities": sorted(required),
            "candidates": candidates,
        }

    def select_candidate(
        self,
        *,
        source_app: str,
        event_type: str,
        caller_id: str,
        required_capabilities: frozenset[str] | set[str] | tuple[str, ...] = (),
        plan: Mapping[str, Any] | None = None,
        selected_at: datetime | None = None,
        selection_id: str | None = None,
    ) -> AdapterSelection:
        """Validate one caller choice against the current declarative plan."""

        _validate_identifier(source_app, "source_app")
        _validate_identifier(caller_id, "caller_id")
        required = _read_query_identifiers(required_capabilities)
        current_plan = self.route_plan(event_type, required)
        if plan is not None and dict(plan) != current_plan:
            raise StaleRoutePlanError("route plan is stale or was modified")
        if current_plan["status"] == "no_match":
            raise NoRouteMatchError(
                f"no adapter matches event_type={event_type!r} and required capabilities"
            )
        if source_app not in {item["source_app"] for item in current_plan["candidates"]}:
            raise CandidateNotAvailableError(
                f"source adapter is not a current candidate: {source_app}"
            )
        return AdapterSelection(
            selection_id=selection_id or str(uuid4()),
            source_app=source_app,
            event_type=event_type,
            required_capabilities=tuple(sorted(required)),
            plan_fingerprint=content_hash(current_plan),
            caller_id=caller_id,
            selected_at=selected_at or utc_now(),
        )

    def validate_selection(self, selection: AdapterSelection) -> None:
        """Reject a selection if its candidate or route plan is no longer valid."""

        if not isinstance(selection, AdapterSelection):
            raise TypeError("selection must be an AdapterSelection")
        current_plan = self.route_plan(selection.event_type, selection.required_capabilities)
        if current_plan["status"] == "no_match":
            raise NoRouteMatchError(
                f"no adapter matches event_type={selection.event_type!r} and required capabilities"
            )
        if content_hash(current_plan) != selection.plan_fingerprint:
            raise StaleRoutePlanError("selected route plan is no longer current")
        if selection.source_app not in {item["source_app"] for item in current_plan["candidates"]}:
            raise CandidateNotAvailableError(
                f"source adapter is not a current candidate: {selection.source_app}"
            )

    def route(
        self,
        source_app: str,
        event_type: str,
        record: Mapping[str, Any],
    ) -> ApplicationEvent:
        registered = self._adapters.get(source_app)
        if registered is None:
            raise UnknownSourceAdapterError(source_app)
        if event_type not in registered.declaration.supported_event_types:
            raise UndeclaredEventTypeError(
                f"event type not declared by {source_app}: {event_type}"
            )
        event = registered.adapter.convert(record, event_type)
        if not isinstance(event, ApplicationEvent):
            raise SourceAdapterRegistryError("source adapter must return ApplicationEvent")
        if event.source_app != source_app or event.event_type != event_type:
            raise SourceAdapterRegistryError("adapter output does not match routed declaration")
        return event


def _read_declaration(adapter: SourceAdapter) -> SourceAdapterDeclaration:
    source_app = getattr(adapter, "source_app", None)
    _validate_identifier(source_app, "source_app")
    event_types = _read_identifier_set(adapter, "supported_event_types", allow_empty=False)
    capabilities = _read_identifier_set(adapter, "capabilities", allow_empty=True)
    if not callable(getattr(adapter, "convert", None)):
        raise InvalidSourceAdapterError("adapter must provide a callable convert method")
    return SourceAdapterDeclaration(
        source_app=source_app,
        supported_event_types=event_types,
        capabilities=capabilities,
    )


def _read_identifier_set(adapter: SourceAdapter, field_name: str, *, allow_empty: bool) -> frozenset[str]:
    values = getattr(adapter, field_name, None)
    if isinstance(values, str) or values is None:
        raise InvalidSourceAdapterError(f"{field_name} must be an iterable of identifiers")
    try:
        normalized = frozenset(values)
    except TypeError as exc:
        raise InvalidSourceAdapterError(f"{field_name} must be an iterable of identifiers") from exc
    if not normalized and not allow_empty:
        raise InvalidSourceAdapterError(f"{field_name} cannot be empty")
    for value in normalized:
        _validate_identifier(value, field_name)
    return normalized


def _read_query_identifiers(values: frozenset[str] | set[str] | tuple[str, ...]) -> frozenset[str]:
    if isinstance(values, str) or values is None:
        raise InvalidSourceAdapterError("required_capabilities must be an iterable of identifiers")
    try:
        normalized = frozenset(values)
    except TypeError as exc:
        raise InvalidSourceAdapterError(
            "required_capabilities must be an iterable of identifiers"
        ) from exc
    for value in normalized:
        _validate_identifier(value, "required_capability")
    return normalized


def _validate_identifier(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or not value.isascii():
        raise InvalidSourceAdapterError(f"{field_name} must be a non-empty ASCII identifier")
    if not value[0].isalnum() or any(not (char.isalnum() or char in "._-") for char in value):
        raise InvalidSourceAdapterError(f"{field_name} contains unsupported characters")


__all__ = [
    "AdapterSelection",
    "CandidateNotAvailableError",
    "DuplicateSourceAdapterError",
    "InvalidSourceAdapterError",
    "NoRouteMatchError",
    "SourceAdapter",
    "SourceAdapterDeclaration",
    "SourceAdapterRegistry",
    "SourceAdapterRegistryError",
    "StaleRoutePlanError",
    "UndeclaredEventTypeError",
    "UnknownSourceAdapterError",
]

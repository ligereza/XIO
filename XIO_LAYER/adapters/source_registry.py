"""App-agnostic registry for validated source adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

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


def _validate_identifier(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value or not value.isascii():
        raise InvalidSourceAdapterError(f"{field_name} must be a non-empty ASCII identifier")
    if not value[0].isalnum() or any(not (char.isalnum() or char in "._-") for char in value):
        raise InvalidSourceAdapterError(f"{field_name} contains unsupported characters")


__all__ = [
    "DuplicateSourceAdapterError",
    "InvalidSourceAdapterError",
    "SourceAdapter",
    "SourceAdapterDeclaration",
    "SourceAdapterRegistry",
    "SourceAdapterRegistryError",
    "UndeclaredEventTypeError",
    "UnknownSourceAdapterError",
]

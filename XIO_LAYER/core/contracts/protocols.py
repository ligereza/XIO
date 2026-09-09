"""Small protocols that keep XIO Layer independent of any device or framework."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from .models import Event, ExplicitAction


class EventReducer(Protocol):
    def __call__(self, state: Mapping[str, Any], event: Event) -> Mapping[str, Any]: ...


ActionHandler = Callable[[ExplicitAction], Mapping[str, Any] | None]

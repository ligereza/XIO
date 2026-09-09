"""XIO boundary without Android, Termux, ADB, rish or MAK logic.

The concrete XIO implementation remains outside XIO Layer. This module only makes
the two allowed directions explicit: observe events and execute an already
confirmed action supplied by the core gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from ...core.audit import ActionGate
from ...core.contracts import ActionResult, Event, ExplicitAction


class XioObserver(Protocol):
    def observe(self) -> Iterable[Event]: ...


class XioExecutor(Protocol):
    def execute(self, action: ExplicitAction) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class XioAdapter:
    """Dependency-injected XIO port; it never turns an event into an action."""

    observer: XioObserver
    executor: XioExecutor
    action_gate: ActionGate

    def observe(self) -> tuple[Event, ...]:
        return tuple(self.observer.observe())

    def execute_explicit(self, action: ExplicitAction, required_permission: str) -> ActionResult:
        if not isinstance(action, ExplicitAction):
            raise TypeError("XIO adapter accepts ExplicitAction only")
        return self.action_gate.execute(action, required_permission, self.executor.execute)

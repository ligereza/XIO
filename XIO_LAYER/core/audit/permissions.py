"""Current permission state and explicit action gate."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Mapping

from ..contracts import ActionHandler, ActionResult, ExplicitAction, utc_now
from .ledger import AuditLedger


class PermissionRegistry:
    """Small, revocable permission registry keyed by actor and capability."""

    def __init__(self):
        self._grants: set[tuple[str, str]] = set()
        self._revision = 0
        self._lock = RLock()

    @property
    def revision(self) -> int:
        return self._revision

    def grant(self, actor_id: str, permission: str) -> int:
        with self._lock:
            self._grants.add((actor_id, permission))
            self._revision += 1
            return self._revision

    def revoke(self, actor_id: str, permission: str) -> int:
        with self._lock:
            self._grants.discard((actor_id, permission))
            self._revision += 1
            return self._revision

    def allows(self, actor_id: str, permission: str) -> bool:
        with self._lock:
            return (actor_id, permission) in self._grants

    def run_if_allowed(
        self,
        actor_id: str,
        permission: str,
        handler: Callable[[], Any],
    ) -> tuple[bool, Any]:
        """Run one already explicit operation while holding the permission lock."""

        with self._lock:
            if (actor_id, permission) not in self._grants:
                return False, None
            return True, handler()


@dataclass(frozen=True, slots=True)
class ActionGate:
    """Execute only an explicitly confirmed action with current permission."""

    permissions: PermissionRegistry
    audit: AuditLedger

    def execute(
        self,
        action: ExplicitAction,
        required_permission: str,
        handler: ActionHandler,
    ) -> ActionResult:
        if not isinstance(action, ExplicitAction):
            raise TypeError("ActionGate accepts ExplicitAction, never Proposal or Event")

        started = utc_now()
        if not action.explicitly_confirmed:
            result = ActionResult(
                action_id=action.action_id,
                status="denied",
                started_at=started,
                finished_at=utc_now(),
                error="explicit_confirmation_required",
            )
            self.audit.append(
                "explicit_action.denied",
                action.action_id,
                "denied",
                {"reason": result.error, "permission": required_permission},
                action.actor_id,
            )
            return result

        try:
            def invoke() -> Mapping[str, Any] | None:
                output = handler(action)
                if output is not None and not isinstance(output, Mapping):
                    raise ValueError("action handler output must be a mapping or null")
                return output

            allowed, output = self.permissions.run_if_allowed(
                action.actor_id,
                required_permission,
                invoke,
            )
        except Exception as exc:  # action failures must become inspectable results
            result = ActionResult(
                action_id=action.action_id,
                status="failed",
                started_at=started,
                finished_at=utc_now(),
                error=f"{type(exc).__name__}: {exc}",
            )
            self.audit.append(
                "explicit_action.result",
                action.action_id,
                "failed",
                {"error": result.error, "permission": required_permission},
                action.actor_id,
            )
            return result

        if not allowed:
            result = ActionResult(
                action_id=action.action_id,
                status="denied",
                started_at=started,
                finished_at=utc_now(),
                error="permission_missing_or_revoked",
            )
            self.audit.append(
                "explicit_action.denied",
                action.action_id,
                "denied",
                {"reason": result.error, "permission": required_permission},
                action.actor_id,
            )
            return result

        result = ActionResult(
            action_id=action.action_id,
            status="succeeded",
            started_at=started,
            finished_at=utc_now(),
            output=output or {},
        )
        self.audit.append(
            "explicit_action.result",
            action.action_id,
            "succeeded",
            {"output": dict(result.output), "permission": required_permission},
            action.actor_id,
        )
        return result

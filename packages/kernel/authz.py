"""Authorization. Approving needs two keys: can see the target AND can execute the action."""

from collections.abc import Iterable
from typing import Any

from kernel.errors import PermissionDenied
from kernel.identity import Actor, RoleGrant

ROLES = {"admin", "hr", "recruiter", "manager", "finance", "employee", "auditor", "mediator"}


def _scope_matches(grant: RoleGrant, target: dict[str, Any] | None) -> bool:
    if grant.scope_type is None:
        return True
    if not target:
        return False
    return str(target.get(grant.scope_type)) == grant.scope_id


def has_role(actor: Actor, roles: Iterable[str], target: dict[str, Any] | None = None) -> bool:
    allowed = set(roles)
    return any(grant.role in allowed and _scope_matches(grant, target) for grant in actor.grants)


def require_role(actor: Actor, roles: Iterable[str], target: dict[str, Any] | None = None) -> None:
    if not has_role(actor, roles, target):
        raise PermissionDenied("You do not have access to this.")


def can_approve(
    actor: Actor,
    view_roles: Iterable[str],
    approver_roles: Iterable[str],
    target: dict[str, Any] | None,
) -> bool:
    """Two-key check: seeing the target never implies being allowed to act on it."""
    return has_role(actor, view_roles, target) and has_role(actor, approver_roles, target)

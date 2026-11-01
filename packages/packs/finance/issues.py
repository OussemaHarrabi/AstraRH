"""Validation issues, shared by every entity that is checked.

A check returns issue specs. They are synced onto the entity, keeping what a person already
decided and recomputing everything else.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.db import utcnow
from kernel.errors import Conflict, NotFound, ValidationFailed
from kernel.identity import Actor
from packs.finance.models import ValidationIssue

RESOLVABLE = {"review", "warning", "info"}


def sync(
    session: Session,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
    specs: list[Any],
) -> None:
    """New problems open an issue, fixed ones are cleared, and a person's decision stays."""
    rows = session.scalars(
        select(ValidationIssue)
        .where(ValidationIssue.entity_type == entity_type, ValidationIssue.entity_id == entity_id)
        .order_by(ValidationIssue.created_at)
    ).all()
    latest = {(row.code, row.field): row for row in rows}
    wanted = set()
    for spec in specs:
        key = (spec.code, spec.field)
        wanted.add(key)
        row = latest.get(key)
        if row is None or row.status == "cleared":
            session.add(
                ValidationIssue(
                    tenant_id=tenant_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    code=spec.code,
                    severity=spec.severity,
                    field=spec.field,
                    message=spec.message,
                    next_action=spec.next_action,
                    owner_role=spec.owner_role,
                )
            )
        elif row.status == "open":
            row.severity, row.message = spec.severity, spec.message
            row.next_action, row.owner_role = spec.next_action, spec.owner_role
    for key, row in latest.items():
        if key not in wanted and row.status == "open":
            row.status = "cleared"
            row.resolved_at = utcnow()
    session.flush()


def open_for(session: Session, entity_type: str, entity_id: UUID) -> list[ValidationIssue]:
    return list(
        session.scalars(
            select(ValidationIssue)
            .where(
                ValidationIssue.entity_type == entity_type,
                ValidationIssue.entity_id == entity_id,
                ValidationIssue.status == "open",
            )
            .order_by(ValidationIssue.created_at)
        )
    )


def resolve_issue(session: Session, actor: Actor, issue_id: UUID, reason: str) -> ValidationIssue:
    """A person's decision on a review item, with a reason. A blocking item has to be fixed."""
    from packs.finance import engagements, inputs

    issue = session.get(ValidationIssue, issue_id)
    if issue is None:
        raise NotFound("Issue not found")
    if issue.status != "open":
        raise Conflict(f"This issue is already {issue.status}")
    if issue.severity not in RESOLVABLE:
        raise Conflict("A blocking issue cannot be waved through: fix its cause")
    if len(reason.strip()) < 3:
        raise ValidationFailed("A reason is required")
    issue.status = "resolved"
    issue.resolved_by = actor.user_id
    issue.resolved_at = utcnow()
    issue.resolution_reason = reason.strip()
    session.flush()
    if issue.entity_type == "engagement":
        engagements.validate_engagement(
            session, actor.tenant_id, engagements.get_engagement(session, issue.entity_id)
        )
    elif issue.entity_type == "payroll_input":
        inputs.refresh_batch_of_input(session, actor.tenant_id, issue.entity_id)
    return issue

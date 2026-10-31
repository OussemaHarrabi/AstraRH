"""Workforce event schemas.

Cross-pack events carry IDs only — never case content (confidentiality) and
never anything that identifies an individual's performance. A consumer reads
the referenced rows under its own permissions.
"""

from datetime import date
from uuid import UUID

from pydantic import BaseModel

from kernel.events import event_type


@event_type("workforce.leave.requested.v1")
class LeaveRequested(BaseModel):
    """Internal trigger: a new leave request was filed, run the clash check."""

    leave_request_id: UUID


@event_type("workforce.leave.approved.v1")
class LeaveApproved(BaseModel):
    """Consumed by finance (cost) and by our own capacity recompute."""

    leave_request_id: UUID
    employee_id: UUID
    org_unit_id: UUID
    start: date
    end: date
    leave_type: str


@event_type("workforce.case.filed.v1")
class CaseFiled(BaseModel):
    """Internal trigger: the case summarizer agent runs on the intake text."""

    case_id: UUID


@event_type("workforce.case.opened.v1")
class CaseOpened(BaseModel):
    """Metadata only — never any case content. Routes to the HR queue."""

    case_id: UUID
    org_unit_id: UUID


@event_type("workforce.overload.detected.v1")
class OverloadDetected(BaseModel):
    """Team-level only. `score` is the decimal factor-sum serialised as a string."""

    org_unit_id: UUID
    week: str
    score: str

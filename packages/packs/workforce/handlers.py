"""Effects of approved internal actions. They run only after the trust gate has
passed (a human approved, bound to the payload hash)."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.db import utcnow
from kernel.events import publish
from kernel.ids import uuid7
from kernel.people.models import Employee
from packs.workforce.events import CaseFiled, CaseOpened, LeaveApproved
from packs.workforce.models import (
    Case,
    CaseEvent,
    CaseParty,
    LeaveRequest,
    LeaveType,
    ResolutionPlan,
)


def approve_leave(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    leave = session.get(LeaveRequest, UUID(payload["leave_request_id"]), with_for_update=True)
    if leave is None or leave.status == "approved":
        return "noop"
    leave.status = "approved"
    employee = session.get(Employee, leave.employee_id)
    leave_type = session.get(LeaveType, leave.leave_type_id)
    publish(
        session,
        tenant_id,
        LeaveApproved(
            leave_request_id=leave.id,
            employee_id=leave.employee_id,
            org_unit_id=employee.org_unit_id,
            start=leave.start_date,
            end=leave.end_date,
            leave_type=leave_type.code,
        ),
    )
    return f"approved:{leave.external_id}"


def open_case(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    case = Case(
        tenant_id=tenant_id,
        external_id=f"CASE-{uuid7().hex[:12]}",
        org_unit_id=UUID(payload["org_unit_id"]),
        case_type=payload["case_type"],
        status="opened",
        opened_by=UUID(payload["opened_by"]),
    )
    session.add(case)
    session.flush()
    for party in payload["parties"]:
        session.add(
            CaseParty(tenant_id=tenant_id, case_id=case.id, employee_id=UUID(party), role="party")
        )
    session.add(
        CaseParty(
            tenant_id=tenant_id,
            case_id=case.id,
            employee_id=UUID(payload["mediator"]),
            role="mediator",
        )
    )
    session.add(
        CaseEvent(
            tenant_id=tenant_id,
            case_id=case.id,
            kind="intake",
            at=utcnow(),
            data={"text": payload["intake_text"]},
        )
    )
    # case.filed triggers the summarizer agent; case.opened is metadata only (HR queue).
    publish(session, tenant_id, CaseFiled(case_id=case.id))
    publish(session, tenant_id, CaseOpened(case_id=case.id, org_unit_id=case.org_unit_id))
    return f"case:{case.external_id}"


def close_case(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    case = session.get(Case, UUID(payload["case_id"]), with_for_update=True)
    if case is None or case.status == "resolved":
        return "noop"
    case.status = "resolved"
    outcome = payload.get("outcome", "")
    plan = session.scalar(select(ResolutionPlan).where(ResolutionPlan.case_id == case.id))
    if plan is None:
        session.add(
            ResolutionPlan(
                tenant_id=tenant_id, case_id=case.id, steps=[], outcome=outcome, status="recorded"
            )
        )
    else:
        plan.status = "recorded"
        plan.outcome = outcome
    session.add(
        CaseEvent(
            tenant_id=tenant_id,
            case_id=case.id,
            kind="resolution",
            at=utcnow(),
            data={"text": outcome},
        )
    )
    return f"closed:{case.external_id}"

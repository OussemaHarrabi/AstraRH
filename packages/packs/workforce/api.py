"""Workforce API: team capacity and overload (team-level), leave with clash
detection, and confidential conflict cases. Writes that affect a person go
through the trust gate (propose), never a direct write."""

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.authz import require_role
from kernel.errors import NotFound, ValidationFailed
from kernel.identity.models import UserAccount
from kernel.people.models import Employee, OrgUnit
from kernel.web import request_context
from packs.workforce import scoring, service
from packs.workforce.models import (
    Case,
    CaseEvent,
    CaseParty,
    LeaveRequest,
    LeaveType,
    CapacitySnapshot,
)

READ_ROLES = {"admin", "hr", "manager", "employee", "auditor"}
MANAGE_ROLES = {"admin", "hr", "manager"}
HR_ROLES = {"admin", "hr"}
FILE_ROLES = {"admin", "hr", "manager", "employee"}

router = APIRouter()


class LeaveBody(BaseModel):
    employee_id: UUID
    leave_type: str = Field(min_length=2, max_length=32)
    start: date
    end: date
    note: str | None = Field(default=None, max_length=500)


class CaseBody(BaseModel):
    case_type: str = Field(min_length=2, max_length=32)
    parties: list[UUID] = Field(min_length=1)
    mediator: UUID
    intake_text: str = Field(min_length=10, max_length=8000)


class CloseBody(BaseModel):
    outcome: str = Field(min_length=3, max_length=4000)


def _org_ext(session: Session) -> dict[UUID, str]:
    return {o.id: o.external_id for o in session.scalars(select(OrgUnit))}


def _actor_employee(session: Session, actor) -> Employee | None:
    person_id = session.scalar(select(UserAccount.person_id).where(UserAccount.id == actor.user_id))
    if person_id is None:
        return None
    return session.scalar(select(Employee).where(Employee.person_id == person_id))


# --- capacity + overload (team-level) --------------------------------------

@router.get("/capacity", summary="Team x week capacity, with the overload score")
def capacity(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        org_ext = _org_ext(ctx.session)
        out = []
        for snap in ctx.session.scalars(select(CapacitySnapshot).order_by(CapacitySnapshot.week)):
            _, result = service.overload_score(snap)
            out.append(
                {
                    "org_unit": org_ext.get(snap.org_unit_id),
                    "week": snap.week,
                    "headcount": snap.headcount,
                    "actual_hours": str(snap.actual_hours),
                    "overtime_hours": str(snap.overtime_hours),
                    "score": str(result.score),
                    "overloaded": scoring.is_overloaded(result),
                }
            )
        return out


@router.get("/alerts", summary="Teams currently over the overload threshold")
def alerts(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        org_ext = _org_ext(ctx.session)
        out = []
        for snap in ctx.session.scalars(select(CapacitySnapshot)):
            _, result = service.overload_score(snap)
            if not scoring.is_overloaded(result):
                continue
            out.append(
                {
                    "org_unit": org_ext.get(snap.org_unit_id),
                    "week": snap.week,
                    "score": str(result.score),
                    "factors": [
                        {"label": f.label, "value": str(f.value), "weight": str(f.weight)}
                        for f in result.factors
                    ],
                }
            )
        return out


@router.post("/capacity/scan", summary="Recompute capacity and record overload alerts")
def scan(request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, MANAGE_ROLES)
        service.refresh_capacity(ctx.session, ctx.actor.tenant_id)
        return {"alerts": service.raise_overload_alerts(ctx.session, ctx.actor.tenant_id)}


# --- leave + operational conflict ------------------------------------------

def _leave_json(session: Session, leave: LeaveRequest, codes: dict[UUID, str]) -> dict[str, Any]:
    return {
        "id": str(leave.id),
        "external_id": leave.external_id,
        "employee_id": str(leave.employee_id),
        "leave_type": codes.get(leave.leave_type_id),
        "start": leave.start_date.isoformat(),
        "end": leave.end_date.isoformat(),
        "status": leave.status,
        "clash_of": leave.clash_of or [],
        "note": leave.note,
    }


@router.get("/leave", summary="Leave requests with status and any clash")
def list_leave(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        codes = {lt.id: lt.code for lt in ctx.session.scalars(select(LeaveType))}
        rows = ctx.session.scalars(select(LeaveRequest).order_by(LeaveRequest.external_id))
        return [_leave_json(ctx.session, leave, codes) for leave in rows]


@router.post("/leave", status_code=201, summary="File a leave request (runs the clash check)")
def create_leave(body: LeaveBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, FILE_ROLES)
        if body.end < body.start:
            raise ValidationFailed("End date is before the start date")
        leave_type = service.leave_type_by_code(ctx.session, body.leave_type)
        if leave_type is None:
            raise NotFound(f"Unknown leave type '{body.leave_type}'")
        codes = {lt.id: lt.code for lt in ctx.session.scalars(select(LeaveType))}
        leave = service.request_leave(
            ctx.session, ctx.actor.tenant_id, body.employee_id, leave_type.id, body.start, body.end, body.note
        )
        return _leave_json(ctx.session, leave, codes)


@router.post("/leave/{leave_id}/approve", status_code=202, summary="Propose approval of a leave request (R2)")
def approve_leave(leave_id: UUID, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, MANAGE_ROLES)
        proposal = service.propose_leave_approval(
            ctx.session, ctx.actor.tenant_id, leave_id, requested_by=ctx.actor.user_id
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}


# --- confidential cases -----------------------------------------------------

def _visible_case_ids(session: Session, actor) -> set[UUID] | None:
    """None means 'all' (admin). Otherwise the set of cases this actor is a party
    or mediator of. Enforced here, not just in the UI."""
    if "admin" in actor.roles:
        return None
    employee = _actor_employee(session, actor)
    if employee is None:
        return set()
    rows = session.scalars(select(CaseParty.case_id).where(CaseParty.employee_id == employee.id))
    return set(rows)


@router.get("/cases", summary="Confidential cases you may see (party or mediator)")
def list_cases(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        org_ext = _org_ext(ctx.session)
        visible = _visible_case_ids(ctx.session, ctx.actor)
        query = select(Case).order_by(Case.external_id)
        if visible is not None:
            if not visible:
                return []
            query = query.where(Case.id.in_(visible))
        return [
            {
                "id": str(c.id),
                "external_id": c.external_id,
                "org_unit": org_ext.get(c.org_unit_id),
                "type": c.case_type,
                "status": c.status,
            }
            for c in ctx.session.scalars(query)
        ]


@router.get("/cases/{case_id}", summary="One confidential case (party or mediator only)")
def get_case(case_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        visible = _visible_case_ids(ctx.session, ctx.actor)
        if visible is not None and case_id not in visible:
            raise NotFound("Case not found")  # do not reveal existence to non-parties
        case = ctx.session.get(Case, case_id)
        if case is None:
            raise NotFound("Case not found")
        events = ctx.session.scalars(
            select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.at)
        )
        parties = ctx.session.scalars(select(CaseParty).where(CaseParty.case_id == case_id))
        plan = service.resolution_for(ctx.session, case_id)
        return {
            "external_id": case.external_id,
            "type": case.case_type,
            "status": case.status,
            "parties": [{"employee_id": str(p.employee_id), "role": p.role} for p in parties],
            "events": [{"kind": e.kind, "at": e.at.isoformat(), "data": e.data} for e in events],
            "resolution": (
                {"steps": plan.steps, "citations": plan.policy_citations, "outcome": plan.outcome, "status": plan.status}
                if plan
                else None
            ),
        }


@router.post("/cases", status_code=202, summary="File a confidential case (opening is R2)")
def file_case(body: CaseBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, FILE_ROLES)
        opener = _actor_employee(ctx.session, ctx.actor)
        if opener is None:
            raise ValidationFailed("Only an employee can file a case")
        proposal = service.file_case(
            ctx.session,
            ctx.actor.tenant_id,
            opened_by=opener.id,
            parties=body.parties,
            mediator=body.mediator,
            case_type=body.case_type,
            org_unit_id=opener.org_unit_id,
            intake_text=body.intake_text,
            requested_by=ctx.actor.user_id,
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}


@router.post("/cases/{case_id}/close", status_code=202, summary="Propose closing a case with a resolution (R3)")
def close_case(case_id: UUID, body: CloseBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, HR_ROLES)
        proposal = service.propose_close_case(
            ctx.session, ctx.actor.tenant_id, case_id, body.outcome, requested_by=ctx.actor.user_id
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}

"""Workforce operations shared by the HTTP API, the agents, the demo loader and
the tests. Deterministic: detection and numbers are plain Python; the LLM only
narrates (in the agents). Every action that affects a person goes through the
trust gate, never a direct write here.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.errors import NotFound
from kernel.events import publish
from kernel.explain import DecisionDraft
from kernel.ids import uuid7
from kernel.people.models import Employee, OrgUnit
from packs.workforce import clash, scoring
from packs.workforce.events import LeaveRequested, OverloadDetected
from packs.workforce.models import (
    CapacitySnapshot,
    Case,
    LeaveRequest,
    LeaveType,
    ResolutionPlan,
    Shift,
    TimeEntry,
)

# Named in every workforce DecisionRecord so the guardrail is explicit and auditable.
NOT_CONSIDERED = ["Individual performance", "Who to blame", "Anyone's identity or protected traits"]

ACTIVE_LEAVE = ["requested", "flagged", "approved"]


def _org_of(session: Session) -> dict[UUID, UUID]:
    return {e.id: e.org_unit_id for e in session.scalars(select(Employee))}


# --- tracking: leave + operational conflict --------------------------------

def request_leave(
    session: Session,
    tenant_id: UUID,
    employee_id: UUID,
    leave_type_id: UUID,
    start: date,
    end: date,
    note: str | None = None,
) -> LeaveRequest:
    """File a leave request and run the clash check. Flags same-team overlaps;
    nothing is approved here — approval is a separate R2 action."""
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise NotFound("Employee not found")
    leave = LeaveRequest(
        tenant_id=tenant_id,
        external_id=f"LR-{uuid7().hex[:12]}",
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        start_date=start,
        end_date=end,
        status="requested",
        note=note,
    )
    session.add(leave)
    session.flush()

    org = employee.org_unit_id
    others = session.scalars(
        select(LeaveRequest).where(
            LeaveRequest.id != leave.id, LeaveRequest.status.in_(ACTIVE_LEAVE)
        )
    ).all()
    org_of = _org_of(session)
    clashing = [
        other.external_id
        for other in others
        if org_of.get(other.employee_id) == org
        and other.employee_id != employee_id
        and clash.overlaps(leave.start_date, leave.end_date, other.start_date, other.end_date)
    ]
    if clashing:
        leave.clash_of = clashing
        leave.status = "flagged"
    publish(session, tenant_id, LeaveRequested(leave_request_id=leave.id))
    return leave


def detect_leave_clashes(session: Session) -> list[clash.Clash]:
    org_of = _org_of(session)
    rows = session.scalars(select(LeaveRequest).where(LeaveRequest.status.in_(ACTIVE_LEAVE))).all()
    intervals = [
        clash.LeaveInterval(
            r.external_id,
            str(r.employee_id),
            str(org_of.get(r.employee_id)),
            r.start_date,
            r.end_date,
        )
        for r in rows
    ]
    return clash.detect_leave_clashes(intervals)


def detect_shift_clashes(session: Session) -> list[clash.Clash]:
    rows = session.scalars(select(Shift)).all()
    intervals = [
        clash.ShiftInterval(s.external_id, str(s.employee_id), s.day, s.start_min, s.end_min)
        for s in rows
    ]
    return clash.detect_shift_clashes(intervals)


def propose_leave_approval(
    session: Session, tenant_id: UUID, leave_request_id: UUID, requested_by: UUID | None = None
):
    """Record why, then propose the R2 approval. For a flagged request the clash
    is named in the rationale so the approver decides with the facts in front of them."""
    leave = session.get(LeaveRequest, leave_request_id)
    if leave is None:
        raise NotFound("Leave request not found")
    if leave.clash_of:
        rationale = (
            f"This request overlaps existing leave on the same team ({', '.join(leave.clash_of)}). "
            "Approving it may leave the team short; a manager decides."
        )
    else:
        rationale = "No same-team clash detected. A manager still approves every request."
    draft = DecisionDraft(
        kind="workforce.leave",
        question=f"Approve leave {leave.external_id}?",
        subject={"leave_request_id": str(leave.id)},
        outcome={"status": leave.status, "clash_of": leave.clash_of or []},
        rationale=rationale,
        not_considered=NOT_CONSIDERED,
        view_roles=["admin", "hr", "manager", "employee", "auditor"],
    )
    record = explain.record(session, tenant_id, draft)
    return trust.propose(
        session,
        tenant_id,
        "workforce.leave.approve",
        {"leave_request_id": str(leave.id)},
        f"Approve leave {leave.external_id}",
        record.id,
        f"leave-approve:{leave.id}",
        target={"org_unit": str(session.get(Employee, leave.employee_id).org_unit_id)},
        requested_by=requested_by,
    )


# --- tracking: capacity + the overload alert (team-level only) --------------

def refresh_capacity(session: Session, tenant_id: UUID) -> list[CapacitySnapshot]:
    """Recompute team x week totals from time entries. Headcount and hours come
    from the entries; on-leave and open roles are kept from the existing snapshot."""
    existing = {
        (s.org_unit_id, s.week): s for s in session.scalars(select(CapacitySnapshot))
    }
    agg: dict[tuple[UUID, str], dict] = defaultdict(lambda: {"hours": Decimal(0), "heads": set()})
    for entry in session.scalars(select(TimeEntry)):
        cell = agg[(entry.org_unit_id, entry.week)]
        cell["hours"] += entry.hours
        cell["heads"].add(entry.employee_id)

    snapshots = []
    for (org_unit_id, week), cell in agg.items():
        headcount = len(cell["heads"])
        actual = cell["hours"]
        scheduled = scoring.BASELINE_HOURS * headcount
        overtime = max(Decimal(0), actual - scheduled)
        snap = existing.get((org_unit_id, week))
        if snap is None:
            snap = CapacitySnapshot(tenant_id=tenant_id, org_unit_id=org_unit_id, week=week)
            session.add(snap)
        snap.headcount = headcount
        snap.scheduled_hours = scheduled
        snap.actual_hours = actual
        snap.overtime_hours = overtime
        snapshots.append(snap)
    session.flush()
    return snapshots


def overload_score(snap: CapacitySnapshot):
    inputs = scoring.team_inputs(
        snap.headcount, snap.actual_hours, snap.on_leave_count, snap.open_reqs
    )
    return inputs, scoring.score(inputs)


def raise_overload_alerts(session: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Record an R0 alert (with a replayable DecisionRecord) for every team over
    the threshold. Team-level only: the alert names the team and the factors, never a person."""
    org_ext = {o.id: o.external_id for o in session.scalars(select(OrgUnit))}
    alerts = []
    for snap in session.scalars(select(CapacitySnapshot)):
        inputs, result = overload_score(snap)
        if not scoring.is_overloaded(result):
            continue
        ext = org_ext.get(snap.org_unit_id, str(snap.org_unit_id))
        draft = DecisionDraft(
            kind="workforce.overload",
            question=f"Is {ext} overloaded in {snap.week}?",
            subject={"org_unit": ext, "week": snap.week},
            outcome={
                "overloaded": True,
                "score": str(result.score),
                "headcount": snap.headcount,
                "actual_hours": str(snap.actual_hours),
            },
            score=result.score,
            factors=result.factors,
            scorer=scoring.SCORER,
            scorer_version=scoring.SCORER_VERSION,
            inputs=inputs,
            rationale=(
                f"{ext} crossed the overload threshold in {snap.week}. "
                "Team totals only; no individual is named or scored."
            ),
            not_considered=NOT_CONSIDERED,
            view_roles=["admin", "hr", "manager", "auditor"],
        )
        record = explain.record(session, tenant_id, draft)
        trust.log_action(
            session,
            tenant_id,
            "workforce.overload.alert",
            "system",
            "system",
            decision_record_id=str(record.id),
            data={"org_unit": ext, "week": snap.week, "score": str(result.score)},
        )
        publish(
            session,
            tenant_id,
            OverloadDetected(org_unit_id=snap.org_unit_id, week=snap.week, score=str(result.score)),
        )
        alerts.append(
            {
                "org_unit": ext,
                "week": snap.week,
                "score": str(result.score),
                "decision_record_id": str(record.id),
            }
        )
    return alerts


# --- conflict: confidential cases ------------------------------------------

def file_case(
    session: Session,
    tenant_id: UUID,
    opened_by: UUID,
    parties: list[UUID],
    mediator: UUID,
    case_type: str,
    org_unit_id: UUID,
    intake_text: str,
    requested_by: UUID | None = None,
):
    """A party asks to open a confidential case. HR approval (R2) opens it."""
    draft = DecisionDraft(
        kind="workforce.case",
        question="Open a confidential conflict case?",
        subject={"org_unit": str(org_unit_id), "type": case_type},
        outcome={"parties": len(parties)},
        rationale="A party asked to open a confidential conflict case; HR approval opens it.",
        not_considered=NOT_CONSIDERED,
        view_roles=["admin", "hr"],
    )
    record = explain.record(session, tenant_id, draft)
    payload = {
        "case_type": case_type,
        "org_unit_id": str(org_unit_id),
        "opened_by": str(opened_by),
        "parties": [str(p) for p in parties],
        "mediator": str(mediator),
        "intake_text": intake_text,
    }
    return trust.propose(
        session,
        tenant_id,
        "workforce.case.open",
        payload,
        f"Open a {case_type} case",
        record.id,
        f"case-open:{uuid7().hex}",
        target={"org_unit": str(org_unit_id)},
        requested_by=requested_by,
    )


def propose_close_case(
    session: Session, tenant_id: UUID, case_id: UUID, outcome: str, requested_by: UUID | None = None
):
    """The mediator records a resolution and asks to close the case (R3)."""
    case = session.get(Case, case_id)
    if case is None:
        raise NotFound("Case not found")
    draft = DecisionDraft(
        kind="workforce.case",
        question=f"Close case {case.external_id}?",
        subject={"case": case.external_id},
        outcome={"status": "resolved"},
        rationale="The mediator recorded a resolution and asked to close the case.",
        not_considered=NOT_CONSIDERED,
        view_roles=["admin", "hr"],
    )
    record = explain.record(session, tenant_id, draft)
    return trust.propose(
        session,
        tenant_id,
        "workforce.case.close",
        {"case_id": str(case_id), "outcome": outcome},
        f"Close case {case.external_id}",
        record.id,
        f"case-close:{case_id}",
        target={"org_unit": str(case.org_unit_id)},
        requested_by=requested_by,
    )


def resolution_for(session: Session, case_id: UUID) -> ResolutionPlan | None:
    return session.scalar(select(ResolutionPlan).where(ResolutionPlan.case_id == case_id))


def leave_type_by_code(session: Session, code: str) -> LeaveType | None:
    return session.scalar(select(LeaveType).where(LeaveType.code == code))

"""Load the workforce demo data: leave types, leave requests, shifts, time
entries, capacity snapshots and confidential cases. Idempotent.

Called by kernel.seed for each pack: seed(session, tenant_id, world). Employees
and org units already exist in `core` (kernel seeded them from world.json); we
look them up by external_id. Reads the CSV/JSON in seed/workforce/.
"""

import csv
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.people.models import Employee, OrgUnit
from packs.workforce.clash import minutes
from packs.workforce.models import (
    CapacitySnapshot,
    Case,
    CaseEvent,
    CaseParty,
    LeaveRequest,
    LeaveType,
    Shift,
    TimeEntry,
)

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "workforce"
BASELINE = Decimal("40")


def _rows(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def seed(session: Session, tenant_id: UUID, world: dict) -> None:
    # Idempotent: if leave types are already loaded, assume the pack is seeded.
    if session.scalar(select(LeaveType.id).limit(1)):
        return

    employees = {
        ext: eid for ext, eid in session.execute(select(Employee.external_id, Employee.id))
    }
    orgs = {ext: oid for ext, oid in session.execute(select(OrgUnit.external_id, OrgUnit.id))}

    leave_types = {}
    for row in _rows("leave_types.csv"):
        lt = LeaveType(
            tenant_id=tenant_id,
            external_id=row["leave_type_id"],
            code=row["code"],
            name=row["name"],
            needs_coverage=row["needs_coverage"].strip().lower() == "true",
        )
        session.add(lt)
        session.flush()
        leave_types[row["leave_type_id"]] = lt.id

    for row in _rows("leave_requests.csv"):
        session.add(
            LeaveRequest(
                tenant_id=tenant_id,
                external_id=row["leave_request_id"],
                employee_id=employees[row["employee_id"]],
                leave_type_id=leave_types[row["leave_type_id"]],
                start_date=date.fromisoformat(row["start_date"]),
                end_date=date.fromisoformat(row["end_date"]),
                status=row["status"],
                note=row.get("note") or None,
            )
        )

    # flag the seeded same-team leave overlaps so the clash shows from the start
    session.flush()
    from packs.workforce import service as _service

    for overlap in _service.detect_leave_clashes(session):
        pair = {overlap.a: overlap.b, overlap.b: overlap.a}
        for req in session.scalars(
            select(LeaveRequest).where(LeaveRequest.external_id.in_(list(pair)))
        ):
            others = set(req.clash_of or [])
            others.add(pair[req.external_id])
            req.clash_of = sorted(others)
            req.status = "flagged"

    for row in _rows("shifts.csv"):
        session.add(
            Shift(
                tenant_id=tenant_id,
                external_id=row["shift_id"],
                employee_id=employees[row["employee_id"]],
                org_unit_id=orgs[row["org_unit_id"]],
                day=date.fromisoformat(row["date"]),
                start_min=minutes(row["start"]),
                end_min=minutes(row["end"]),
                role=row["role"],
            )
        )

    # time entries, and a capacity snapshot per team x week derived from them
    snapshots: dict[tuple[str, str], dict] = {}
    for row in _rows("time_entries.csv"):
        hours = Decimal(row["hours"])
        session.add(
            TimeEntry(
                tenant_id=tenant_id,
                employee_id=employees[row["employee_id"]],
                org_unit_id=orgs[row["org_unit_id"]],
                week=row["week"],
                hours=hours,
            )
        )
        agg = snapshots.setdefault(
            (row["org_unit_id"], row["week"]), {"hours": Decimal(0), "heads": set()}
        )
        agg["hours"] += hours
        agg["heads"].add(row["employee_id"])

    for (org_ext, week), agg in snapshots.items():
        headcount = len(agg["heads"])
        actual = agg["hours"]
        scheduled = BASELINE * headcount
        overtime = max(Decimal(0), actual - scheduled)
        session.add(
            CapacitySnapshot(
                tenant_id=tenant_id,
                org_unit_id=orgs[org_ext],
                week=week,
                headcount=headcount,
                scheduled_hours=scheduled,
                actual_hours=actual,
                overtime_hours=overtime,
                on_leave_count=0,
                open_reqs=0,
            )
        )

    # confidential cases: the case, its parties, an intake event, and a
    # resolution plan for any already-resolved case
    cases = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))["cases"]
    for spec in cases:
        case = Case(
            tenant_id=tenant_id,
            external_id=spec["case_id"],
            org_unit_id=orgs[spec["org_unit_id"]],
            case_type=spec["type"],
            status=spec["status"],
            opened_by=employees[spec["opened_by"]],
        )
        session.add(case)
        session.flush()
        for emp_ext in spec["parties"]:
            session.add(
                CaseParty(
                    tenant_id=tenant_id,
                    case_id=case.id,
                    employee_id=employees[emp_ext],
                    role="party",
                )
            )
        session.add(
            CaseParty(
                tenant_id=tenant_id,
                case_id=case.id,
                employee_id=employees[spec["mediator"]],
                role="mediator",
            )
        )
        session.add(
            CaseEvent(
                tenant_id=tenant_id,
                case_id=case.id,
                kind="intake",
                at=_at(spec["opened_at"]),
                data={"text": spec["intake_text"]},
            )
        )
        if spec.get("resolution"):
            session.add(
                CaseEvent(
                    tenant_id=tenant_id,
                    case_id=case.id,
                    kind="resolution",
                    at=_at(spec.get("resolved_at", spec["opened_at"])),
                    data={"text": spec["resolution"]},
                )
            )

    session.flush()

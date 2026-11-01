"""Helpers shared by the finance tests."""

from datetime import date
from uuid import UUID, uuid4

from conftest import as_role

from kernel.db import tenant_session
from kernel.people.models import Employee, OrgUnit, Person, Position


def make_employee(tenant_id: UUID, person_id: UUID | None = None) -> UUID:
    suffix = uuid4().hex[:8]
    with as_role("owner"), tenant_session(tenant_id) as session:
        person = None
        if person_id is None:
            person = Person(tenant_id=tenant_id, external_id=f"P-{suffix}", lifecycle="employee")
            session.add(person)
        org = OrgUnit(tenant_id=tenant_id, external_id=f"O-{suffix}", name="Engineering")
        position = Position(tenant_id=tenant_id, external_id=f"R-{suffix}", title="Engineer")
        session.add_all([org, position])
        session.flush()
        employee = Employee(
            tenant_id=tenant_id,
            external_id=f"E-{suffix}",
            person_id=person_id or person.id,
            display_name="Test Employee",
            email=f"{suffix}@example.test",
            org_unit_id=org.id,
            position_id=position.id,
            start_date=date(2026, 1, 1),
        )
        session.add(employee)
        session.flush()
        return employee.id


def external_id_of(tenant_id: UUID, employee_id: UUID) -> str:
    with as_role("owner"), tenant_session(tenant_id) as session:
        return session.get(Employee, employee_id).external_id


def seed_active_engagement(
    tenant_id: UUID,
    employee_id: UUID,
    starts_on: date = date(2026, 1, 1),
    ends_on: date | None = None,
    head_of_family: bool = False,
    children: tuple[str, ...] = (),
    base_salary: str | None = None,
    type_: str | None = None,
) -> UUID:
    """Only the owner role may create an engagement that is already active, with its pay."""
    from decimal import Decimal

    from packs.finance.models import Engagement, PayItem

    with as_role("owner"), tenant_session(tenant_id) as session:
        row = Engagement(
            tenant_id=tenant_id,
            employee_id=employee_id,
            type=type_ or ("CDI" if ends_on is None else "CDD"),
            status="active",
            starts_on=starts_on,
            ends_on=ends_on,
            job_title="Engineer",
            weekly_hours=40,
            head_of_family=head_of_family,
            children=list(children),
        )
        session.add(row)
        session.flush()
        if base_salary is not None:
            session.add(
                PayItem(
                    tenant_id=tenant_id,
                    engagement_id=row.id,
                    code="BASE_SALARY",
                    amount=Decimal(base_salary),
                    valid_from=starts_on,
                )
            )
        return row.id


def paid_employee(
    tenant_id: UUID,
    base_salary: str = "2000.000",
    head_of_family: bool = True,
    children: tuple[str, ...] = ("child", "child"),
    starts_on: date = date(2026, 1, 1),
) -> tuple[UUID, str, UUID]:
    """An employee with an active CDI and a base salary: (employee id, external id, engagement)."""
    employee = make_employee(tenant_id)
    engagement = seed_active_engagement(
        tenant_id,
        employee,
        starts_on=starts_on,
        head_of_family=head_of_family,
        children=children,
        base_salary=base_salary,
    )
    return employee, external_id_of(tenant_id, employee), engagement


def demo_definition(rule_id: str | None = None, **top_level) -> dict:
    import copy
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data/demo/finance/rule_set_tn_2026_demo.json"
    data = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
    data["id"] = rule_id or f"rs-{uuid4().hex[:8]}"
    data["valid_to"] = None
    data.update(top_level)
    return data


def store_rule_set(tenant_id: UUID, data: dict | None = None, status: str = "active") -> UUID:
    from packs.finance.models import RuleSetRecord
    from packs.finance.payroll import rules

    data = data or demo_definition()
    parsed = rules.parse(data)
    with as_role("owner"), tenant_session(tenant_id) as session:
        record = RuleSetRecord(
            tenant_id=tenant_id,
            rule_id=parsed.id,
            version=parsed.version,
            jurisdiction=parsed.jurisdiction,
            status=status,
            valid_from=parsed.valid_from,
            valid_to=parsed.valid_to,
            is_demo=parsed.is_demo,
            source_ref=parsed.source_ref,
            definition=data,
            definition_hash=parsed.definition_hash,
        )
        session.add(record)
        session.flush()
        return record.id

"""Helpers shared by the finance tests."""

from datetime import date
from uuid import UUID, uuid4

from conftest import as_role

from kernel.db import tenant_session
from kernel.people.models import Employee, OrgUnit, Person, Position


def make_employee(tenant_id: UUID) -> UUID:
    suffix = uuid4().hex[:8]
    with as_role("owner"), tenant_session(tenant_id) as session:
        person = Person(tenant_id=tenant_id, external_id=f"P-{suffix}", lifecycle="employee")
        org = OrgUnit(tenant_id=tenant_id, external_id=f"O-{suffix}", name="Engineering")
        position = Position(tenant_id=tenant_id, external_id=f"R-{suffix}", title="Engineer")
        session.add_all([person, org, position])
        session.flush()
        employee = Employee(
            tenant_id=tenant_id,
            external_id=f"E-{suffix}",
            person_id=person.id,
            display_name="Test Employee",
            email=f"{suffix}@example.test",
            org_unit_id=org.id,
            position_id=position.id,
            start_date=date(2026, 1, 1),
        )
        session.add(employee)
        session.flush()
        return employee.id

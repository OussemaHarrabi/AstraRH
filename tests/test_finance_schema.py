"""Finance tables against the real database, using each process's real role.

These prove the rules that must hold even if application code has a bug: tenant isolation,
the executor's lack of access, append-only bank history, frozen submitted payslips and
immutable closed runs.
"""

import ast
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import as_role
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from kernel.db import Base, tenant_session
from kernel.events import catalogue
from kernel.people.models import Employee, OrgUnit, Person, Position
from kernel.registry import load_manifests
from packs.finance import events as finance_events  # noqa: F401 - registers the events
from packs.finance import models as m

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "packages" / "packs" / "finance"
SENSITIVE = {"gross", "net", "net_pay", "salary", "amount", "iban", "account", "name", "email"}
MONTH = date(2026, 11, 1)


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


def make_engagement(tenant_id: UUID, employee_id: UUID) -> UUID:
    with as_role("worker"), tenant_session(tenant_id) as session:
        row = m.Engagement(
            tenant_id=tenant_id,
            employee_id=employee_id,
            type="CDI",
            starts_on=MONTH,
            job_title="Engineer",
        )
        session.add(row)
        session.flush()
        return row.id


def make_run(tenant_id: UUID, status: str = "draft") -> UUID:
    """Only the owner role (seed and migrations) may create a run that is not a draft."""
    with as_role("worker" if status == "draft" else "owner"), tenant_session(tenant_id) as session:
        run = m.PayrollRun(
            tenant_id=tenant_id,
            period_start=MONTH,
            period_end=date(2026, 11, 30),
            pay_date=date(2026, 11, 30),
            regime_id="TN_PRIVATE_NON_AGRI",
            status=status,
        )
        session.add(run)
        session.flush()
        return run.id


def make_payslip(tenant_id: UUID, run_id: UUID, employee_id: UUID, engagement_id: UUID) -> UUID:
    with as_role("worker"), tenant_session(tenant_id) as session:
        slip = m.Payslip(
            tenant_id=tenant_id,
            run_id=run_id,
            employee_id=employee_id,
            engagement_id=engagement_id,
            gross=Decimal("2000.000"),
            employee_deductions=Decimal("193.600"),
            income_tax=Decimal("253.683"),
            solidarity=Decimal("7.990"),
            net_pay=Decimal("1544.727"),
            employer_cost=Decimal("2341.400"),
        )
        session.add(slip)
        session.flush()
        session.add(
            m.PayslipLine(
                tenant_id=tenant_id,
                payslip_id=slip.id,
                position=1,
                code="GROSS",
                label="Gross salary",
                kind="earning",
                base=Decimal("2000.000"),
                amount=Decimal("2000.000"),
                rule_ref="test#gross",
            )
        )
        return slip.id


def set_run_status(tenant_id: UUID, run_id: UUID, status: str) -> None:
    with as_role("worker"), tenant_session(tenant_id) as session:
        session.get(m.PayrollRun, run_id).status = status


def full_slip(tenant_id: UUID):
    employee = make_employee(tenant_id)
    engagement = make_engagement(tenant_id, employee)
    run = make_run(tenant_id)
    slip = make_payslip(tenant_id, run, employee, engagement)
    return employee, engagement, run, slip


def test_a_tenant_cannot_see_another_tenants_finance_rows(tenant, other_tenant):
    make_engagement(tenant, make_employee(tenant))
    with as_role("api"), tenant_session(tenant) as session:
        assert session.query(m.Engagement).count() == 1
    with as_role("api"), tenant_session(other_tenant) as session:
        assert session.query(m.Engagement).count() == 0


def test_a_tenant_cannot_write_into_another_tenant(tenant, other_tenant):
    employee = make_employee(tenant)
    with pytest.raises(DBAPIError), as_role("worker"), tenant_session(other_tenant) as session:
        session.add(
            m.Engagement(
                tenant_id=tenant,
                employee_id=employee,
                type="CDI",
                starts_on=MONTH,
                job_title="Engineer",
            )
        )
        session.flush()


def test_the_executor_cannot_touch_the_finance_schema(tenant):
    make_engagement(tenant, make_employee(tenant))
    with pytest.raises(DBAPIError, match="permission denied"):
        with as_role("executor"), tenant_session(tenant) as session:
            session.execute(text("SELECT count(*) FROM finance.engagement"))


def test_bank_status_history_is_append_only(tenant):
    employee, engagement, run, slip = full_slip(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        line = m.PaymentLine(
            tenant_id=tenant,
            run_id=run,
            payslip_id=slip,
            amount=Decimal("1544.727"),
            bank_ref_token="tok-1",
            idempotency_key=f"k-{uuid4().hex}",
        )
        session.add(line)
        session.flush()
        event = m.PaymentStatusEvent(
            tenant_id=tenant,
            payment_line_id=line.id,
            provider_ref="batch-1",
            status="paid",
            status_seq=1,
            observed_at=datetime.now(UTC),
        )
        session.add(event)
        session.flush()
        event_id = event.id

    with pytest.raises(DBAPIError, match="permission denied"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payment_status_event SET status = 'failed' WHERE id = :i"),
                {"i": event_id},
            )
    with pytest.raises(DBAPIError, match="not allowed"):
        with as_role("owner"), tenant_session(tenant) as session:
            session.execute(
                text("DELETE FROM finance.payment_status_event WHERE id = :i"), {"i": event_id}
            )
    with pytest.raises(DBAPIError, match="permission denied"):
        with as_role("api"), tenant_session(tenant) as session:
            session.add(
                m.PaymentStatusEvent(
                    tenant_id=tenant,
                    payment_line_id=line.id,
                    provider_ref="batch-1",
                    status="paid",
                    status_seq=2,
                    observed_at=datetime.now(UTC),
                )
            )
            session.flush()


def test_the_api_cannot_write_payslips_or_payments(tenant):
    employee, engagement, run, slip = full_slip(tenant)
    with pytest.raises(DBAPIError, match="permission denied"):
        with as_role("api"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payslip SET net_pay = 9999 WHERE id = :i"), {"i": slip}
            )
    with as_role("api"), tenant_session(tenant) as session:
        assert session.query(m.Payslip).count() == 1


def rule_set_row(tenant_id: UUID, status: str = "draft") -> m.RuleSetRecord:
    return m.RuleSetRecord(
        tenant_id=tenant_id,
        rule_id=f"rs-{uuid4().hex[:6]}",
        version=1,
        jurisdiction="TN",
        status=status,
        valid_from=MONTH,
        definition={"css": {"rate": "0.005"}},
        definition_hash="0" * 64,
    )


def add_rule_set(tenant_id: UUID, role: str, status: str = "draft") -> UUID:
    with as_role(role), tenant_session(tenant_id) as session:
        row = rule_set_row(tenant_id, status)
        session.add(row)
        session.flush()
        return row.id


def test_the_api_cannot_activate_a_rule_set(tenant):
    rule_id = add_rule_set(tenant, "api")
    with pytest.raises(DBAPIError, match="permission denied"):
        with as_role("api"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.rule_set SET status = 'active' WHERE id = :i"), {"i": rule_id}
            )
    for role in ("api", "worker"):
        with pytest.raises(DBAPIError, match="must be a draft"):
            add_rule_set(tenant, role, status="active")


def test_an_active_rule_set_never_changes_even_for_the_owner(tenant):
    active = add_rule_set(tenant, "owner", status="active")
    for role in ("worker", "owner"):
        with pytest.raises(DBAPIError, match="cannot be changed"):
            with as_role(role), tenant_session(tenant) as session:
                session.execute(
                    text(
                        "UPDATE finance.rule_set "
                        'SET definition = \'{"css": {"rate": "0.02"}}\' WHERE id = :i'
                    ),
                    {"i": active},
                )
    with pytest.raises(DBAPIError, match="cannot go from active to draft"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.rule_set SET status = 'draft' WHERE id = :i"), {"i": active}
            )
    with pytest.raises(DBAPIError, match="Only a draft rule set can be deleted"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(text("DELETE FROM finance.rule_set WHERE id = :i"), {"i": active})
    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE finance.rule_set SET status = 'superseded' WHERE id = :i"), {"i": active}
        )


def test_a_draft_rule_set_can_be_edited_activated_or_deleted(tenant):
    draft = add_rule_set(tenant, "worker")
    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE finance.rule_set SET source_ref = 'edited' WHERE id = :i"), {"i": draft}
        )
        session.execute(
            text("UPDATE finance.rule_set SET status = 'active' WHERE id = :i"), {"i": draft}
        )
    other = add_rule_set(tenant, "worker")
    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(text("DELETE FROM finance.rule_set WHERE id = :i"), {"i": other})


def test_a_submitted_run_freezes_its_payslips_and_lines(tenant):
    employee, engagement, run, slip = full_slip(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE finance.payslip_line SET label = 'Edited' WHERE payslip_id = :i"),
            {"i": slip},
        )

    set_run_status(tenant, run, "calculated")
    set_run_status(tenant, run, "approval_pending")
    with pytest.raises(DBAPIError, match="cannot be changed"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payslip_line SET label = 'Again' WHERE payslip_id = :i"),
                {"i": slip},
            )
    with pytest.raises(DBAPIError, match="cannot be changed"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("DELETE FROM finance.payslip_line WHERE payslip_id = :i"), {"i": slip}
            )
    with pytest.raises(DBAPIError, match="cannot be changed"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payslip SET net_pay = 1 WHERE id = :i"), {"i": slip}
            )
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(text("DELETE FROM finance.payslip WHERE id = :i"), {"i": slip})

    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE finance.payslip SET status = 'approved' WHERE id = :i"), {"i": slip}
        )

    set_run_status(tenant, run, "draft")
    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE finance.payslip_line SET label = 'Reopened' WHERE payslip_id = :i"),
            {"i": slip},
        )


def test_a_closed_run_never_changes_and_only_a_draft_can_be_deleted(tenant):
    closed = make_run(tenant, "closed")
    with pytest.raises(DBAPIError, match="closed run cannot be changed"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payroll_run SET status = 'draft' WHERE id = :i"), {"i": closed}
            )

    calculated = make_run(tenant, "calculated")
    with pytest.raises(DBAPIError, match="Only a draft run can be deleted"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("DELETE FROM finance.payroll_run WHERE id = :i"), {"i": calculated}
            )

    draft = make_run(tenant, "draft")
    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(text("DELETE FROM finance.payroll_run WHERE id = :i"), {"i": draft})
        assert session.get(m.PayrollRun, draft) is None


def test_the_same_input_arriving_twice_is_stored_once(tenant):
    employee = make_employee(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        batch = m.PayrollInputBatch(
            tenant_id=tenant, source="time", period_start=MONTH, period_end=date(2026, 11, 30)
        )
        session.add(batch)
        session.flush()

        def add_input() -> m.PayrollInput:
            return m.PayrollInput(
                tenant_id=tenant,
                batch_id=batch.id,
                employee_id=employee,
                kind="hours",
                quantity=Decimal("8"),
                effective_date=MONTH,
                source_event_id="time.approved:evt-1",
            )

        session.add(add_input())
        session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(add_input())
            session.flush()


def test_civp_keeps_the_two_payers_in_separate_rows(tenant):
    employee = make_employee(tenant)
    engagement = make_engagement(tenant, employee)
    with as_role("worker"), tenant_session(tenant) as session:
        placement = m.CivpPlacement(
            tenant_id=tenant,
            engagement_id=engagement,
            participant_category="higher_education_or_bts",
            starts_on=MONTH,
            ends_on=date(2027, 10, 31),
            aneti_allowance_monthly=Decimal("200.000"),
            employer_complement_monthly=Decimal("200.000"),
        )
        session.add(placement)
        session.flush()

        def entry(payer: str) -> m.CivpLedgerEntry:
            return m.CivpLedgerEntry(
                tenant_id=tenant,
                placement_id=placement.id,
                month=MONTH,
                payer=payer,
                due_amount=Decimal("200.000"),
            )

        session.add_all([entry("aneti"), entry("employer")])
        session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(entry("aneti"))
            session.flush()


def test_a_payment_idempotency_key_and_execution_are_unique(tenant):
    employee, engagement, run, slip = full_slip(tenant)
    key = f"k-{uuid4().hex}"
    with as_role("worker"), tenant_session(tenant) as session:
        session.add(
            m.PaymentLine(
                tenant_id=tenant,
                run_id=run,
                payslip_id=slip,
                amount=Decimal("1544.727"),
                bank_ref_token="tok-1",
                idempotency_key=key,
            )
        )
        session.flush()
        execution = uuid4()
        session.add(
            m.PaymentBatch(
                tenant_id=tenant,
                run_id=run,
                release_number=1,
                execution_id=execution,
                total=Decimal("1544.727"),
                line_count=1,
            )
        )
        session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(
                m.PaymentBatch(
                    tenant_id=tenant,
                    run_id=run,
                    release_number=2,
                    execution_id=execution,
                    total=Decimal("1.000"),
                    line_count=1,
                )
            )
            session.flush()


def test_finance_foreign_keys_point_only_into_core_or_finance():
    for table in Base.metadata.tables.values():
        if table.schema != "finance":
            continue
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.schema in {"core", "finance"}, (
                f"{table.name}.{foreign_key.parent.name} points at {foreign_key.column.table}"
            )


def test_every_finance_table_has_a_tenant_and_row_level_security():
    names = {t.name for t in Base.metadata.tables.values() if t.schema == "finance"}
    assert len(names) == 20
    with as_role("owner"), tenant_session(uuid4()) as session:
        enabled = {
            row[0]
            for row in session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'finance' AND rowsecurity")
            )
        }
    assert names == enabled
    for table in Base.metadata.tables.values():
        if table.schema == "finance":
            assert "tenant_id" in table.columns


def test_the_manifest_and_the_event_models_agree():
    manifest = next(item for item in load_manifests() if item.id == "finance")
    defined = {name for name in catalogue() if name.startswith("finance.")}
    assert set(manifest.publishes) == defined
    assert all(name.endswith(".v1") for name in defined)


def test_finance_events_carry_no_salary_bank_or_identity_fields():
    for name, model in catalogue().items():
        if name.startswith("finance."):
            leaked = SENSITIVE & set(model.model_fields)
            assert not leaked, f"{name} carries {leaked}"


def test_the_finance_pack_uses_no_floats():
    for path in PACK.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), path
            assert not (isinstance(node, ast.Name) and node.id == "float"), path


def submitted(tenant_id: UUID):
    employee, engagement, run, slip = full_slip(tenant_id)
    set_run_status(tenant_id, run, "calculated")
    set_run_status(tenant_id, run, "approval_pending")
    return employee, engagement, run, slip


def test_nothing_can_be_added_to_a_submitted_run(tenant):
    employee, engagement, run, slip = submitted(tenant)
    with pytest.raises(DBAPIError, match="cannot be changed"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.add(
                m.PayslipLine(
                    tenant_id=tenant,
                    payslip_id=slip,
                    position=2,
                    code="BONUS",
                    label="Bonus",
                    kind="earning",
                    base=Decimal("1.000"),
                    amount=Decimal("1.000"),
                    rule_ref="test#bonus",
                )
            )
            session.flush()
    other = make_employee(tenant)
    with pytest.raises(DBAPIError, match="cannot be added"):
        make_payslip(tenant, run, other, make_engagement(tenant, other))


def test_payslips_and_lines_cannot_be_moved_out_of_or_into_a_submitted_run(tenant):
    employee, engagement, frozen_run, frozen_slip = submitted(tenant)
    draft_run = make_run(tenant)
    with pytest.raises(DBAPIError, match="cannot be moved"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payslip SET run_id = :r WHERE id = :i"),
                {"r": draft_run, "i": frozen_slip},
            )
    other = make_employee(tenant)
    draft_slip = make_payslip(tenant, draft_run, other, make_engagement(tenant, other))
    with pytest.raises(DBAPIError, match="cannot be changed"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payslip_line SET payslip_id = :f WHERE payslip_id = :d"),
                {"f": frozen_slip, "d": draft_slip},
            )


def test_a_run_follows_the_allowed_path_and_only_the_worker_approves(tenant):
    employee, engagement, run, slip = submitted(tenant)
    with pytest.raises(DBAPIError, match="Only an approved action"):
        with as_role("api"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.payroll_run SET status = 'approved' WHERE id = :i"), {"i": run}
            )
    set_run_status(tenant, run, "approved")
    for role in ("api", "worker"):
        with pytest.raises(DBAPIError, match="cannot go from approved to draft"):
            with as_role(role), tenant_session(tenant) as session:
                session.execute(
                    text("UPDATE finance.payroll_run SET status = 'draft' WHERE id = :i"),
                    {"i": run},
                )
    with pytest.raises(DBAPIError, match="cannot go from draft to paid"):
        set_run_status(tenant, make_run(tenant), "paid")
    with pytest.raises(DBAPIError, match="must be a draft"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.add(
                m.PayrollRun(
                    tenant_id=tenant,
                    period_start=MONTH,
                    period_end=date(2026, 11, 30),
                    pay_date=date(2026, 11, 30),
                    regime_id="TN_PRIVATE_NON_AGRI",
                    status="approved",
                )
            )
            session.flush()

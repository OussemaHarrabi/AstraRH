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
from finance_helpers import make_employee
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from kernel.db import Base, tenant_session
from kernel.events import catalogue
from kernel.registry import load_manifests
from packs.finance import events as finance_events  # noqa: F401 - registers the events
from packs.finance import models as m

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "packages" / "packs" / "finance"
SENSITIVE = {"gross", "net", "net_pay", "salary", "amount", "iban", "account", "name", "email"}
MONTH = date(2026, 11, 1)


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
    assert len(names) == 22
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


def seed_engagement(tenant_id: UUID, employee_id: UUID, status: str) -> UUID:
    """Only the owner role (seed and migrations) may create an engagement that is not a draft."""
    with as_role("owner"), tenant_session(tenant_id) as session:
        row = m.Engagement(
            tenant_id=tenant_id,
            employee_id=employee_id,
            type="CDI",
            status=status,
            starts_on=MONTH,
            job_title="Engineer",
        )
        session.add(row)
        session.flush()
        return row.id


def set_engagement_status(tenant_id: UUID, role: str, engagement_id: UUID, status: str) -> None:
    with as_role(role), tenant_session(tenant_id) as session:
        session.execute(
            text("UPDATE finance.engagement SET status = :s WHERE id = :i"),
            {"s": status, "i": engagement_id},
        )


def test_a_new_engagement_must_be_a_draft_unless_the_owner_seeds_it(tenant):
    employee = make_employee(tenant)
    for role in ("api", "worker"):
        with pytest.raises(DBAPIError, match="must be a draft"):
            with as_role(role), tenant_session(tenant) as session:
                session.add(
                    m.Engagement(
                        tenant_id=tenant,
                        employee_id=employee,
                        type="CDI",
                        status="active",
                        starts_on=MONTH,
                        job_title="Engineer",
                    )
                )
                session.flush()
    seed_engagement(tenant, employee, "active")


def test_only_an_approved_action_can_make_an_engagement_active(tenant):
    employee = make_employee(tenant)
    engagement = make_engagement(tenant, employee)
    set_engagement_status(tenant, "api", engagement, "pending_review")
    set_engagement_status(tenant, "api", engagement, "approved")
    with pytest.raises(DBAPIError, match="Only an approved action"):
        set_engagement_status(tenant, "api", engagement, "active")
    set_engagement_status(tenant, "worker", engagement, "active")


def test_an_engagement_follows_the_allowed_status_path(tenant):
    employee = make_employee(tenant)
    engagement = make_engagement(tenant, employee)
    with pytest.raises(DBAPIError, match="cannot go from draft to active"):
        set_engagement_status(tenant, "worker", engagement, "active")
    with pytest.raises(DBAPIError, match="cannot go from draft to completed"):
        set_engagement_status(tenant, "worker", engagement, "completed")
    active = seed_engagement(tenant, employee, "active")
    with pytest.raises(DBAPIError, match="cannot go from active to draft"):
        set_engagement_status(tenant, "worker", active, "draft")
    set_engagement_status(tenant, "worker", active, "terminated")


def test_an_active_engagement_changes_only_through_the_worker(tenant):
    active = seed_engagement(tenant, make_employee(tenant), "active")
    with pytest.raises(DBAPIError, match="changes only through an approved action"):
        with as_role("api"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.engagement SET job_title = 'CEO' WHERE id = :i"), {"i": active}
            )
    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE finance.engagement SET job_title = 'Lead' WHERE id = :i"), {"i": active}
        )


def test_only_a_draft_engagement_can_be_deleted(tenant):
    employee = make_employee(tenant)
    active = seed_engagement(tenant, employee, "active")
    with pytest.raises(DBAPIError, match="Only a draft engagement can be deleted"):
        with as_role("worker"), tenant_session(tenant) as session:
            session.execute(text("DELETE FROM finance.engagement WHERE id = :i"), {"i": active})
    draft = make_engagement(tenant, employee)
    with as_role("worker"), tenant_session(tenant) as session:
        session.execute(text("DELETE FROM finance.engagement WHERE id = :i"), {"i": draft})


def pay_item(tenant_id: UUID, engagement_id: UUID, code: str = "BASE_SALARY") -> m.PayItem:
    return m.PayItem(
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        code=code,
        amount=Decimal("2000.000"),
        valid_from=MONTH,
    )


def test_pay_of_an_active_engagement_changes_only_through_the_worker(tenant):
    employee = make_employee(tenant)
    draft = make_engagement(tenant, employee)
    with as_role("api"), tenant_session(tenant) as session:
        session.add(pay_item(tenant, draft))

    active = seed_engagement(tenant, employee, "active")
    with as_role("owner"), tenant_session(tenant) as session:
        session.add(pay_item(tenant, active))
    for statement in (
        "UPDATE finance.pay_item SET amount = 9999 WHERE engagement_id = :i",
        "DELETE FROM finance.pay_item WHERE engagement_id = :i",
    ):
        with pytest.raises(DBAPIError, match="changes only through an approved action"):
            with as_role("api"), tenant_session(tenant) as session:
                session.execute(text(statement), {"i": active})
    with pytest.raises(DBAPIError, match="changes only through an approved action"):
        with as_role("api"), tenant_session(tenant) as session:
            session.add(pay_item(tenant, active, "BONUS"))
            session.flush()
    with as_role("worker"), tenant_session(tenant) as session:
        session.add(pay_item(tenant, active, "BONUS"))


def test_a_pay_item_cannot_be_moved_onto_an_active_engagement(tenant):
    employee = make_employee(tenant)
    draft = make_engagement(tenant, employee)
    active = seed_engagement(tenant, employee, "active")
    with as_role("api"), tenant_session(tenant) as session:
        item = pay_item(tenant, draft)
        session.add(item)
        session.flush()
        item_id = item.id
    with pytest.raises(DBAPIError, match="changes only through an approved action"):
        with as_role("api"), tenant_session(tenant) as session:
            session.execute(
                text("UPDATE finance.pay_item SET engagement_id = :a WHERE id = :i"),
                {"a": active, "i": item_id},
            )


def make_input(tenant_id: UUID, role: str = "worker") -> tuple[UUID, UUID, UUID]:
    employee = make_employee(tenant_id)
    with as_role(role), tenant_session(tenant_id) as session:
        batch = m.PayrollInputBatch(
            tenant_id=tenant_id,
            source="csv",
            period_start=MONTH,
            period_end=date(2026, 11, 30),
            file_sha256=uuid4().hex * 2,
        )
        session.add(batch)
        session.flush()
        row = m.PayrollInput(
            tenant_id=tenant_id,
            batch_id=batch.id,
            employee_id=employee,
            kind="hours",
            quantity=Decimal("8"),
            effective_date=MONTH,
            source_event_id=f"row:{uuid4().hex}",
            line_number=2,
        )
        session.add(row)
        session.flush()
        return batch.id, row.id, employee


def run_sql(tenant_id: UUID, role: str, statement: str, **params) -> None:
    with as_role(role), tenant_session(tenant_id) as session:
        session.execute(text(statement), params)


@pytest.mark.parametrize("role", ["api", "worker", "owner"])
def test_the_content_of_an_input_never_changes_for_any_role(tenant, role):
    _, row, _ = make_input(tenant)
    for column, value in (
        ("quantity", "9"),
        ("kind", "'bonus'"),
        ("effective_date", "'2026-11-02'"),
    ):
        with pytest.raises(DBAPIError, match="content of an input cannot be changed"):
            run_sql(
                tenant,
                role,
                f"UPDATE finance.payroll_input SET {column} = {value} WHERE id = :i",
                i=row,
            )


def test_an_input_can_only_move_from_accepted_to_withdrawn(tenant):
    _, row, _ = make_input(tenant)
    run_sql(
        tenant,
        "api",
        "UPDATE finance.payroll_input SET status = 'withdrawn', reject_reason = 'Mistake' "
        "WHERE id = :i",
        i=row,
    )
    for status in ("accepted", "rejected"):
        with pytest.raises(DBAPIError, match="cannot go from withdrawn"):
            run_sql(
                tenant,
                "owner",
                f"UPDATE finance.payroll_input SET status = '{status}' WHERE id = :i",
                i=row,
            )


@pytest.mark.parametrize("role", ["api", "worker", "owner"])
def test_an_input_is_never_deleted(tenant, role):
    _, row, _ = make_input(tenant)
    with pytest.raises(DBAPIError, match="withdrawn, never deleted"):
        run_sql(tenant, role, "DELETE FROM finance.payroll_input WHERE id = :i", i=row)


def test_a_batch_keeps_its_period_and_content_but_its_counts_can_change(tenant):
    batch, _, _ = make_input(tenant)
    run_sql(
        tenant,
        "api",
        "UPDATE finance.payroll_input_batch SET status = 'ready', accepted_rows = 3 WHERE id = :i",
        i=batch,
    )
    for column, value in (
        ("period_end", "'2026-12-31'"),
        ("period_start", "'2026-10-01'"),
        ("file_sha256", "'abc'"),
        ("source", "'time'"),
    ):
        with pytest.raises(DBAPIError, match="cannot be changed"):
            run_sql(
                tenant,
                "owner",
                f"UPDATE finance.payroll_input_batch SET {column} = {value} WHERE id = :i",
                i=batch,
            )
    with pytest.raises(DBAPIError, match="never deleted"):
        run_sql(tenant, "owner", "DELETE FROM finance.payroll_input_batch WHERE id = :i", i=batch)


def test_a_rejection_is_history(tenant):
    batch, _, _ = make_input(tenant)
    with as_role("api"), tenant_session(tenant) as session:
        row = m.PayrollInputRejection(
            tenant_id=tenant, batch_id=batch, line_number=5, code="KIND_UNKNOWN", message="No."
        )
        session.add(row)
        session.flush()
        rejection = row.id
    for statement in (
        "UPDATE finance.payroll_input_rejection SET message = 'edited' WHERE id = :i",
        "DELETE FROM finance.payroll_input_rejection WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="not allowed"):
            run_sql(tenant, "owner", statement, i=rejection)


def test_a_rejection_line_is_recorded_once_per_batch(tenant):
    batch, _, _ = make_input(tenant)
    with as_role("api"), tenant_session(tenant) as session:
        session.add(
            m.PayrollInputRejection(
                tenant_id=tenant, batch_id=batch, line_number=5, code="A", message="First."
            )
        )
        session.flush()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(
                m.PayrollInputRejection(
                    tenant_id=tenant, batch_id=batch, line_number=5, code="B", message="Again."
                )
            )
            session.flush()

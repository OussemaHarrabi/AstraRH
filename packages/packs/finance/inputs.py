"""Payroll inputs: import, check, withdraw. Shared by the API, the tests and, later, event
consumers (an upstream system pushes rows through the same path)."""

import csv
import io
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kernel.canonical import payload_hash, sha256_hex
from kernel.errors import Conflict, NotFound, ValidationFailed
from kernel.events import publish
from kernel.identity import Actor
from kernel.people.models import Employee
from packs.finance import issues
from packs.finance.events import PayrollInputsValidated
from packs.finance.models import (
    Engagement,
    PayrollInput,
    PayrollInputBatch,
    PayrollInputRejection,
    PayrollRun,
    PayrollRunInput,
    ValidationIssue,
)
from packs.finance.validation import inputs as rules

MAX_BYTES = 1_000_000
MAX_ROWS = 5000
MAX_PERIOD_DAYS = 62
COLUMNS = ("employee", "kind", "effective_date", "quantity", "amount", "reference")
RAW_LIMIT = 120
ENTITY = "payroll_input"
SUBMITTED = {"approval_pending", "approved", "payment_pending", "paid", "closed"}


@dataclass(frozen=True)
class RawRow:
    line: int
    data: dict[str, str]
    error: str | None = None


def parse_csv(content: bytes) -> list[RawRow]:
    """Structure only. Whether each value is acceptable is decided row by row."""
    if len(content) > MAX_BYTES:
        raise ValidationFailed(f"The file is larger than {MAX_BYTES // 1000} KB")
    if b"\x00" in content:
        raise ValidationFailed("This is not a text CSV file")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationFailed("The file must be UTF-8 text") from None
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header is None:
            raise ValidationFailed("The file is empty")
        names = [cell.strip().lower() for cell in header]
        if names != list(COLUMNS):
            raise ValidationFailed(f"The header must be exactly: {','.join(COLUMNS)}")
        rows = []
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            if len(rows) >= MAX_ROWS:
                raise ValidationFailed(f"The file has more than {MAX_ROWS} rows")
            if len(cells) != len(COLUMNS):
                rows.append(
                    RawRow(
                        reader.line_num, {}, f"Expected {len(COLUMNS)} columns, got {len(cells)}"
                    )
                )
            else:
                rows.append(RawRow(reader.line_num, dict(zip(COLUMNS, cells, strict=True))))
    except csv.Error as exc:
        raise ValidationFailed(f"The CSV is malformed: {exc}") from None
    return rows


def content_hash_of_file(content: bytes, start: date, end: date) -> str:
    return payload_hash(
        {"period": [start.isoformat(), end.isoformat()], "file": sha256_hex(content)}
    )


def content_hash_of_rows(rows: list[RawRow], start: date, end: date) -> str:
    return payload_hash(
        {
            "period": [start.isoformat(), end.isoformat()],
            "rows": [[r.line, r.data, r.error] for r in rows],
        }
    )


def _source_key(employee_id: UUID, row: rules.ParsedRow) -> str:
    if row.reference:
        return f"ref:{employee_id}:{row.reference}"
    fingerprint = payload_hash(
        [
            str(employee_id),
            row.kind,
            row.effective_date.isoformat(),
            str(row.quantity),
            str(row.amount),
        ]
    )
    return f"row:{fingerprint[:40]}"


def import_rows(
    session: Session,
    tenant_id: UUID,
    submitted_by: UUID,
    source: str,
    period_start: date,
    period_end: date,
    rows: list[RawRow],
    content_hash: str,
) -> tuple[PayrollInputBatch, bool]:
    """Returns the batch and whether it was new. The same content returns the same batch."""
    if period_end < period_start:
        raise ValidationFailed("The period ends before it starts")
    if (period_end - period_start).days >= MAX_PERIOD_DAYS:
        raise ValidationFailed(f"A period is at most {MAX_PERIOD_DAYS} days")
    if not rows:
        raise ValidationFailed("There are no rows to import")
    existing = session.scalar(
        select(PayrollInputBatch).where(PayrollInputBatch.file_sha256 == content_hash)
    )
    if existing is not None:
        return existing, False

    batch = PayrollInputBatch(
        tenant_id=tenant_id,
        source=source,
        period_start=period_start,
        period_end=period_end,
        file_sha256=content_hash,
        submitted_by=submitted_by,
    )
    try:
        with session.begin_nested():
            session.add(batch)
            session.flush()
    except IntegrityError:
        return session.scalar(
            select(PayrollInputBatch).where(PayrollInputBatch.file_sha256 == content_hash)
        ), False

    parsed: list[rules.ParsedRow | rules.Rejection] = []
    for raw in rows:
        if raw.error:
            parsed.append(rules.Rejection(raw.line, "ROW_MALFORMED", raw.error))
        else:
            parsed.append(rules.parse_row(raw.line, raw.data, period_start, period_end))

    wanted = {p.employee for p in parsed if isinstance(p, rules.ParsedRow)}
    employees = {
        e.external_id: e.id
        for e in session.scalars(select(Employee).where(Employee.external_id.in_(wanted)))
    }
    keys = {
        _source_key(employees[p.employee], p)
        for p in parsed
        if isinstance(p, rules.ParsedRow) and p.employee in employees
    }
    already = set(
        session.scalars(
            select(PayrollInput.source_event_id).where(PayrollInput.source_event_id.in_(keys))
        )
    )

    rejections: list[rules.Rejection] = []
    first_line: dict[str, int] = {}
    stored = 0
    for item in parsed:
        if isinstance(item, rules.Rejection):
            rejections.append(item)
            continue
        employee_id = employees.get(item.employee)
        if employee_id is None:
            rejections.append(
                rules.Rejection(item.line, "EMPLOYEE_UNKNOWN", f"No employee {item.employee}.")
            )
            continue
        key = _source_key(employee_id, item)
        if key in first_line:
            rejections.append(
                rules.Rejection(
                    item.line,
                    "DUPLICATE_IN_FILE",
                    f"Same as line {first_line[key]}. Add a different reference if both are real.",
                )
            )
            continue
        if key in already:
            rejections.append(
                rules.Rejection(item.line, "ALREADY_IMPORTED", "This input was imported before.")
            )
            continue
        first_line[key] = item.line
        session.add(
            PayrollInput(
                tenant_id=tenant_id,
                batch_id=batch.id,
                employee_id=employee_id,
                kind=item.kind,
                quantity=item.quantity,
                amount=item.amount,
                effective_date=item.effective_date,
                reference=item.reference,
                line_number=item.line,
                source_event_id=key,
            )
        )
        stored += 1

    raw_by_line = {r.line: r.data for r in rows}
    for rejection in rejections:
        session.add(
            PayrollInputRejection(
                tenant_id=tenant_id,
                batch_id=batch.id,
                line_number=rejection.line,
                code=rejection.code,
                message=rejection.message,
                raw={k: str(v)[:RAW_LIMIT] for k, v in raw_by_line.get(rejection.line, {}).items()},
            )
        )
    batch.accepted_rows = stored
    batch.rejected_rows = len(rejections)
    session.flush()
    validate_batch(session, tenant_id, batch)
    return batch, True


def _view(row: PayrollInput) -> rules.InputView:
    return rules.InputView(
        row.id,
        row.employee_id,
        row.kind,
        row.effective_date,
        row.quantity,
        row.amount,
        row.reference,
    )


def validate_batch(
    session: Session, tenant_id: UUID, batch: PayrollInputBatch
) -> PayrollInputBatch:
    """Idempotent. Judges the batch's inputs against the whole period and the engagements."""
    own = list(
        session.scalars(
            select(PayrollInput).where(
                PayrollInput.batch_id == batch.id, PayrollInput.status == "accepted"
            )
        )
    )
    employees = {row.employee_id for row in own}
    period = list(
        session.scalars(
            select(PayrollInput).where(
                PayrollInput.status == "accepted",
                PayrollInput.employee_id.in_(employees),
                PayrollInput.effective_date.between(batch.period_start, batch.period_end),
            )
        )
    )
    coverage: dict[UUID, list[tuple[date, date | None]]] = {}
    for engagement in session.scalars(
        select(Engagement).where(
            Engagement.status == "active", Engagement.employee_id.in_(employees)
        )
    ):
        coverage.setdefault(engagement.employee_id, []).append(
            (engagement.starts_on, engagement.ends_on)
        )
    found = rules.conflicts([_view(r) for r in period], coverage, {r.id for r in own})
    for row in own:
        issues.sync(session, tenant_id, ENTITY, row.id, found.get(row.id, []))

    counts = issue_counts(session, batch.id)
    batch.accepted_rows = len(own)
    if not own:
        batch.status = "empty"
    elif counts["blocking"] or counts["review"]:
        batch.status = "needs_attention"
    else:
        batch.status = "ready"
    session.flush()
    publish(
        session,
        tenant_id,
        PayrollInputsValidated(
            batch_id=batch.id,
            accepted=batch.accepted_rows,
            rejected=batch.rejected_rows,
            blocking=counts["blocking"],
            review=counts["review"],
            status=batch.status,
        ),
    )
    return batch


def issue_counts(session: Session, batch_id: UUID) -> dict[str, int]:
    rows = session.execute(
        select(ValidationIssue.severity, func.count())
        .join(PayrollInput, PayrollInput.id == ValidationIssue.entity_id)
        .where(
            ValidationIssue.entity_type == ENTITY,
            ValidationIssue.status == "open",
            PayrollInput.batch_id == batch_id,
        )
        .group_by(ValidationIssue.severity)
    ).all()
    counts = {severity: n for severity, n in rows}
    return {name: counts.get(name, 0) for name in ("blocking", "review", "warning")}


def batch_summary(session: Session, batch: PayrollInputBatch) -> dict:
    counts = issue_counts(session, batch.id)
    return {
        "id": str(batch.id),
        "source": batch.source,
        "period_start": batch.period_start.isoformat(),
        "period_end": batch.period_end.isoformat(),
        "status": batch.status,
        "accepted": batch.accepted_rows,
        "rejected": batch.rejected_rows,
        "open_issues": counts,
    }


def get_batch(session: Session, batch_id: UUID) -> PayrollInputBatch:
    batch = session.get(PayrollInputBatch, batch_id)
    if batch is None:
        raise NotFound("Input batch not found")
    return batch


def refresh_batch_of_input(session: Session, tenant_id: UUID, input_id: UUID) -> None:
    row = session.get(PayrollInput, input_id)
    if row is not None:
        validate_batch(session, tenant_id, get_batch(session, row.batch_id))


def withdraw_input(session: Session, actor: Actor, input_id: UUID, reason: str) -> PayrollInput:
    row = session.get(PayrollInput, input_id, with_for_update=True)
    if row is None:
        raise NotFound("Input not found")
    if row.status != "accepted":
        raise Conflict(f"This input is already {row.status}")
    if len(reason.strip()) < 3:
        raise ValidationFailed("A reason is required")
    runs = list(
        session.scalars(
            select(PayrollRun)
            .join(PayrollRunInput, PayrollRunInput.run_id == PayrollRun.id)
            .where(PayrollRunInput.input_id == row.id)
            .with_for_update(of=PayrollRun)
        )
    )
    if any(run.status in SUBMITTED for run in runs):
        raise Conflict(
            "A payroll run that is waiting for approval or already approved uses this input. "
            "Recall the run first"
        )
    for run in runs:
        if run.status == "calculated":
            run.status = "draft"
            run.calculation_state = "idle"
    row.status = "withdrawn"
    row.reject_reason = reason.strip()
    session.flush()
    issues.sync(session, actor.tenant_id, ENTITY, row.id, [])
    validate_batch(session, actor.tenant_id, get_batch(session, row.batch_id))
    return row

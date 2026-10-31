"""Finance operations shared by the HTTP API, the handlers and the tests."""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.errors import Conflict, NotFound, ValidationFailed
from kernel.identity import Actor
from packs.finance import proposals
from packs.finance.models import RuleSetRecord
from packs.finance.payroll import calc, examples, rules

ACTIVATE_ACTION = "finance.rules.activate"
DECISION_VIEW_ROLES = ["admin", "finance", "hr", "auditor"]
DEMO_NOTICE = (
    "Demo values, not certified. Check every rate against the official CNSS, tax and ANETI "
    "texts before real use."
)
UNCHANGED_KEYS = {"id", "version", "valid_from", "source_ref", "examples"}
MAX_CHANGES = 40
# Tunisia keeps UTC+1 all year (no daylight saving since 2009), so a fixed offset is exact.
TUNIS = timezone(timedelta(hours=1), "Africa/Tunis")


def today_in_tunis() -> date:
    return datetime.now(TUNIS).date()


def _text(value: Decimal) -> str:
    return format(value, "f")


def get_rule_set(session: Session, record_id: UUID) -> RuleSetRecord:
    record = session.get(RuleSetRecord, record_id)
    if record is None:
        raise NotFound("Rule set not found")
    return record


def parse_definition(definition: dict[str, Any]) -> rules.RuleSet:
    try:
        return rules.parse(definition)
    except rules.RuleSetInvalid as exc:
        raise ValidationFailed(str(exc)) from exc


def create_rule_set(session: Session, tenant_id: UUID, definition: dict[str, Any]) -> RuleSetRecord:
    """A new rule set always starts as a draft. Only an approved activation makes it count."""
    parsed = parse_definition(definition)
    if session.scalar(select(RuleSetRecord.id).where(RuleSetRecord.rule_id == parsed.id)):
        raise Conflict(f"A rule set with id {parsed.id} already exists")
    record = RuleSetRecord(
        tenant_id=tenant_id,
        rule_id=parsed.id,
        version=parsed.version,
        jurisdiction=parsed.jurisdiction,
        status="draft",
        valid_from=parsed.valid_from,
        valid_to=parsed.valid_to,
        is_demo=parsed.is_demo,
        source_ref=parsed.source_ref,
        definition=definition,
        definition_hash=parsed.definition_hash,
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError:
        raise Conflict(f"A rule set with id {parsed.id} already exists") from None
    return record


def active_rule_sets(session: Session) -> list[rules.RuleSet]:
    records = session.scalars(
        select(RuleSetRecord)
        .where(RuleSetRecord.status == "active")
        .order_by(RuleSetRecord.valid_from)
    ).all()
    parsed = []
    for record in records:
        rule_set = parse_definition(record.definition)
        if rule_set.definition_hash != record.definition_hash:
            raise ValidationFailed(
                f"Active rule set {record.rule_id} no longer matches what was approved. "
                "Nothing is calculated until it is fixed."
            )
        parsed.append(rule_set)
    return parsed


def example_report(parsed: rules.RuleSet) -> dict[str, Any]:
    results = examples.run(parsed)
    return {
        "passed": bool(results) and all(r.passed for r in results),
        "count": len(results),
        "results": [
            {
                "name": r.name,
                "passed": r.passed,
                "error": r.error,
                "mismatches": {
                    field: {"expected": _text(expected), "got": None if got is None else _text(got)}
                    for field, (expected, got) in r.mismatches.items()
                },
            }
            for r in results
        ],
    }


def payslip_json(slip: calc.Payslip, parsed: rules.RuleSet) -> dict[str, Any]:
    return {
        "gross": _text(slip.gross),
        "lines": [
            {
                "code": line.code,
                "label": line.label,
                "kind": line.kind,
                "base": _text(line.base),
                "rate": None if line.rate is None else _text(line.rate),
                "amount": _text(line.amount),
                "rule_ref": line.rule_ref,
            }
            for line in slip.lines
        ],
        "totals": {
            "employee_deductions": _text(slip.employee_deductions),
            "income_tax": _text(slip.income_tax),
            "solidarity": _text(slip.solidarity),
            "net_pay": _text(slip.net_pay),
            "employer_cost": _text(slip.employer_cost),
        },
        "working": {key: _text(value) for key, value in slip.working.items()},
        "rule_set": {
            "id": parsed.id,
            "version": parsed.version,
            "hash": parsed.definition_hash,
            "is_demo": parsed.is_demo,
            "valid_from": parsed.valid_from.isoformat(),
        },
        "notice": DEMO_NOTICE if parsed.is_demo else None,
    }


def calculate_net(session: Session, data: calc.PayslipInput, day: date) -> dict[str, Any]:
    """Gross to net under the rule set in force that day. Nothing is stored."""
    try:
        parsed = rules.select(active_rule_sets(session), day)
        return payslip_json(calc.payslip(data, parsed), parsed)
    except (rules.RuleSetUnavailable, calc.PayslipInvalid) as exc:
        raise ValidationFailed(str(exc)) from exc


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        flat: dict[str, Any] = {}
        for key in sorted(value):
            flat.update(_flatten(value[key], f"{prefix}{key}."))
        return flat
    if isinstance(value, list):
        return {prefix.rstrip("."): json.dumps(value, sort_keys=True)}
    return {prefix.rstrip("."): value}


def describe_changes(old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
    """Field by field differences against the rule set it would follow, for the approver."""
    if old is None:
        return []
    before = _flatten({k: v for k, v in old.items() if k not in UNCHANGED_KEYS})
    after = _flatten({k: v for k, v in new.items() if k not in UNCHANGED_KEYS})
    lines = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            lines.append(f"{key}: {before.get(key, 'none')} -> {after.get(key, 'none')}")
    return lines


def check_activatable(session: Session, record: RuleSetRecord) -> rules.RuleSet:
    """Every condition for activation, shared by the request and the final execution."""
    if record.status != "draft":
        raise Conflict(f"Rule set {record.rule_id} is {record.status}, not a draft")
    parsed = parse_definition(record.definition)
    if parsed.definition_hash != record.definition_hash:
        raise ValidationFailed("The stored rule set no longer matches its hash")
    if not parsed.examples:
        raise ValidationFailed("A rule set needs at least one hand-checked example to be activated")
    report = example_report(parsed)
    if not report["passed"]:
        failed = [r["name"] for r in report["results"] if not r["passed"]]
        raise ValidationFailed(f"These hand-checked examples fail: {', '.join(failed)}")
    for other in active_rule_sets(session):
        if parsed.overlaps(other):
            raise Conflict(f"Rule set {parsed.id} overlaps the active rule set {other.id}")
    return parsed


def request_activation(
    session: Session, tenant_id: UUID, actor: Actor, record_id: UUID
) -> trust.Proposal:
    """Propose activation (R3). Nothing changes until a different person approves it."""
    record = get_rule_set(session, record_id)
    parsed = check_activatable(session, record)
    attempt = proposals.next_attempt(
        session, actor, f"{ACTIVATE_ACTION}:{record.id}:", f"Rule set {record.rule_id}"
    )
    earlier = [r for r in active_rule_sets(session) if r.valid_from <= parsed.valid_from]
    previous_id, previous = None, None
    if earlier:
        previous_id = max(earlier, key=lambda r: r.valid_from).id
        previous = session.scalar(
            select(RuleSetRecord.definition).where(RuleSetRecord.rule_id == previous_id)
        )
    changes = describe_changes(previous, record.definition)
    shown = changes[:MAX_CHANGES]
    more = len(changes) - len(shown)
    if previous is None:
        comparison = "There is no earlier active rule set, so there is nothing to compare with."
    elif not shown:
        comparison = f"No value differs from the previous rule set {previous_id}."
    else:
        comparison = f"Changes against the previous rule set {previous_id}: " + "; ".join(shown)
        comparison += "." + (f" And {more} more." if more > 0 else "")
    rationale = (
        f"Activate {parsed.id} from {parsed.valid_from.isoformat()}. "
        f"{parsed.id} reproduces {len(parsed.examples)} hand-checked examples. {comparison}"
    )
    limits = ["Every value must be checked against the official texts before real use."]
    if parsed.is_demo:
        limits.insert(0, "This rule set is marked as demo values: not verified, not certified.")
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="finance.rules.activation",
            question=f"Should rule set {parsed.id} become the active payroll rules?",
            outcome={
                "rule_set": parsed.id,
                "demo": parsed.is_demo,
                "examples": len(parsed.examples),
            },
            rationale=rationale,
            evidence=[
                explain.Evidence(
                    ref="E1",
                    source_type="rule_set",
                    source_id=parsed.id,
                    quote=(parsed.source_ref or "No source recorded")[:500],
                )
            ],
            limits=limits,
            versions={"definition_hash": parsed.definition_hash},
            view_roles=DECISION_VIEW_ROLES,
        ),
    )
    return trust.propose(
        session,
        tenant_id,
        ACTIVATE_ACTION,
        {"rule_set_id": str(record.id), "definition_hash": parsed.definition_hash},
        f"Activate payroll rule set {parsed.id}",
        decision.id,
        f"{ACTIVATE_ACTION}:{record.id}:{parsed.definition_hash[:16]}:{attempt}",
        requested_by=actor.user_id,
    )

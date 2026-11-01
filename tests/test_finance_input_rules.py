"""Payroll input checks. Pure functions: no database, no model."""

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from packs.finance.validation import inputs as rules

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "packages/packs/finance/validation/inputs.py"
START, END = date(2026, 11, 1), date(2026, 11, 30)


def row(**changes) -> dict[str, str]:
    base = {
        "employee": "EMP-009",
        "kind": "hours",
        "effective_date": "2026-11-05",
        "quantity": "8",
        "amount": "",
        "reference": "",
    }
    base.update(changes)
    return base


def parse(**changes):
    return rules.parse_row(7, row(**changes), START, END)


def test_each_kind_of_row_is_accepted():
    hours = parse()
    assert (hours.kind, hours.quantity, hours.amount) == ("hours", Decimal("8"), None)
    absence = parse(kind="absence", quantity="2")
    assert (absence.kind, absence.quantity) == ("absence", Decimal("2"))
    for kind in ("bonus", "allowance", "reimbursement"):
        paid = parse(kind=kind, quantity="", amount="150.500")
        assert (paid.kind, paid.amount, paid.quantity) == (kind, Decimal("150.500"), None)


def test_a_parsed_row_keeps_its_line_and_reference():
    parsed = parse(reference="TIME-2026-11-0042")
    assert (parsed.line, parsed.employee, parsed.reference) == (7, "EMP-009", "TIME-2026-11-0042")
    assert parsed.effective_date == date(2026, 11, 5)


def test_values_are_trimmed_and_the_kind_ignores_case():
    parsed = parse(
        employee=" EMP-009 ", kind=" Hours ", quantity=" 7.5 ", effective_date=" 2026-11-05 "
    )
    assert (parsed.employee, parsed.kind, parsed.quantity) == ("EMP-009", "hours", Decimal("7.5"))


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"employee": ""}, "EMPLOYEE_INVALID"),
        ({"employee": "EMP 009"}, "EMPLOYEE_INVALID"),
        ({"employee": "EMP-009;DROP"}, "EMPLOYEE_INVALID"),
        ({"employee": "E" * 65}, "EMPLOYEE_INVALID"),
        ({"kind": ""}, "KIND_UNKNOWN"),
        ({"kind": "overtime"}, "KIND_UNKNOWN"),
        ({"effective_date": ""}, "DATE_INVALID"),
        ({"effective_date": "2026-11-5"}, "DATE_INVALID"),
        ({"effective_date": "20261105"}, "DATE_INVALID"),
        ({"effective_date": "05/11/2026"}, "DATE_INVALID"),
        ({"effective_date": "2026-02-30"}, "DATE_INVALID"),
        ({"effective_date": "2026-10-31"}, "DATE_OUTSIDE_PERIOD"),
        ({"effective_date": "2026-12-01"}, "DATE_OUTSIDE_PERIOD"),
        ({"quantity": ""}, "QUANTITY_INVALID"),
        ({"quantity": "0"}, "QUANTITY_INVALID"),
        ({"quantity": "-3"}, "QUANTITY_INVALID"),
        ({"quantity": "24.001"}, "QUANTITY_INVALID"),
        ({"quantity": "25"}, "QUANTITY_INVALID"),
        ({"quantity": "1e1"}, "QUANTITY_INVALID"),
        ({"quantity": "8,5"}, "QUANTITY_INVALID"),
        ({"quantity": ".5"}, "QUANTITY_INVALID"),
        ({"quantity": "5."}, "QUANTITY_INVALID"),
        ({"quantity": "NaN"}, "QUANTITY_INVALID"),
        ({"quantity": "8.0001"}, "QUANTITY_INVALID"),
        ({"quantity": "8", "amount": "10"}, "VALUE_NOT_ALLOWED"),
        ({"kind": "absence", "quantity": "32"}, "QUANTITY_INVALID"),
        ({"kind": "bonus", "quantity": "", "amount": ""}, "AMOUNT_INVALID"),
        ({"kind": "bonus", "quantity": "", "amount": "0"}, "AMOUNT_INVALID"),
        ({"kind": "bonus", "quantity": "", "amount": "-5"}, "AMOUNT_INVALID"),
        ({"kind": "bonus", "quantity": "", "amount": "10000001"}, "AMOUNT_INVALID"),
        ({"kind": "bonus", "quantity": "", "amount": "Infinity"}, "AMOUNT_INVALID"),
        ({"kind": "bonus", "quantity": "", "amount": "5.1234"}, "AMOUNT_INVALID"),
        ({"kind": "bonus", "quantity": "3", "amount": "100"}, "VALUE_NOT_ALLOWED"),
        ({"reference": "=HYPERLINK(1)"}, "REFERENCE_INVALID"),
        ({"reference": "@cmd"}, "REFERENCE_INVALID"),
        ({"reference": "+1"}, "REFERENCE_INVALID"),
        ({"reference": "has space"}, "REFERENCE_INVALID"),
        ({"reference": "r" * 65}, "REFERENCE_INVALID"),
    ],
)
def test_a_bad_row_is_rejected_with_its_reason(changes, code):
    result = parse(**changes)
    assert isinstance(result, rules.Rejection), changes
    assert (result.line, result.code) == (7, code)
    assert result.message


def test_the_period_edges_are_inside():
    assert isinstance(parse(effective_date="2026-11-01"), rules.ParsedRow)
    assert isinstance(parse(effective_date="2026-11-30"), rules.ParsedRow)


def test_a_missing_field_is_treated_as_empty():
    result = rules.parse_row(3, {"employee": "EMP-009", "kind": "hours"}, START, END)
    assert result.code == "DATE_INVALID"


A, B = uuid4(), uuid4()
ONE, TWO, THREE, FOUR = (UUID(int=n) for n in (1, 2, 3, 4))
ACTIVE = {A: [(date(2026, 1, 1), None)], B: [(date(2026, 1, 1), date(2026, 12, 31))]}


def view(
    id_, employee=A, kind="hours", day=date(2026, 11, 5), quantity=Decimal(8), amount=None, ref=None
):
    return rules.InputView(id_, employee, kind, day, quantity, amount, ref)


def codes(items, coverage=ACTIVE, scope=None):
    found = rules.conflicts(items, coverage, scope or {i.id for i in items})
    return {key: sorted(spec.code for spec in specs) for key, specs in found.items()}


def test_a_normal_input_has_no_issue():
    assert codes([view(ONE)]) == {ONE: []}


def test_an_input_without_an_active_engagement_is_blocking():
    stranger = uuid4()
    found = rules.conflicts([view(ONE, employee=stranger)], ACTIVE, {ONE})
    [issue] = found[ONE]
    assert (issue.code, issue.severity, issue.owner_role) == (
        "NO_ACTIVE_ENGAGEMENT",
        "blocking",
        "HR",
    )


@pytest.mark.parametrize(
    ("day", "covered"),
    [
        (date(2026, 12, 31), True),
        (date(2027, 1, 1), False),
        (date(2025, 12, 31), False),
        (date(2026, 1, 1), True),
    ],
)
def test_the_engagement_must_cover_the_day_of_the_input(day, covered):
    result = codes([view(ONE, employee=B, day=day)])
    assert ("NO_ACTIVE_ENGAGEMENT" not in result[ONE]) is covered


def test_the_same_value_twice_with_different_references_is_a_possible_duplicate():
    items = [view(ONE, ref="a"), view(TWO, ref="b")]
    assert codes(items) == {ONE: ["POSSIBLE_DUPLICATE"], TWO: ["POSSIBLE_DUPLICATE"]}


def test_a_different_value_or_day_or_employee_is_not_a_duplicate():
    items = [
        view(ONE),
        view(TWO, quantity=Decimal(4)),
        view(THREE, day=date(2026, 11, 6)),
        view(FOUR, employee=B),
    ]
    assert all("POSSIBLE_DUPLICATE" not in found for found in codes(items).values())


def test_hours_and_an_absence_on_the_same_day_are_flagged_for_both():
    items = [view(ONE), view(TWO, kind="absence", quantity=Decimal(1))]
    assert codes(items) == {
        ONE: ["ABSENCE_AND_HOURS_SAME_DAY"],
        TWO: ["ABSENCE_AND_HOURS_SAME_DAY"],
    }


def test_a_long_day_is_only_a_warning():
    [issue] = rules.conflicts([view(ONE, quantity=Decimal("13"))], ACTIVE, {ONE})[ONE]
    assert (issue.code, issue.severity) == ("LONG_DAY", "warning")
    assert codes([view(ONE, quantity=Decimal(12))]) == {ONE: []}


def test_too_many_hours_in_the_period_needs_a_person():
    """30 days at 11 hours is 330, above 300. Fewer days at 11 hours stay at or under 300."""
    items = [
        view(UUID(int=100 + n), day=date(2026, 11, 1 + n), quantity=Decimal(11)) for n in range(30)
    ]
    flagged = [i for i, found in codes(items).items() if "MONTHLY_HOURS_HIGH" in found]
    assert len(flagged) == len(items)
    assert all("MONTHLY_HOURS_HIGH" not in f for f in codes(items[:27]).values())


def test_exactly_the_limit_is_not_over_it():
    items = [
        view(UUID(int=100 + n), day=date(2026, 11, 1 + n), quantity=Decimal(10)) for n in range(30)
    ]
    assert all("MONTHLY_HOURS_HIGH" not in f for f in codes(items).values())


def test_the_monthly_total_counts_other_batches_but_only_flags_the_scope():
    other = [
        view(UUID(int=200 + n), day=date(2026, 11, 1 + n), quantity=Decimal(10)) for n in range(29)
    ]
    mine = view(ONE, day=date(2026, 11, 30), quantity=Decimal(11))
    result = rules.conflicts([*other, mine], ACTIVE, {ONE})
    assert list(result) == [ONE]
    assert [s.code for s in result[ONE]] == ["MONTHLY_HOURS_HIGH"]


def test_an_unusual_amount_is_only_a_warning():
    big = view(ONE, kind="bonus", quantity=None, amount=Decimal("20000.001"))
    [issue] = rules.conflicts([big], ACTIVE, {ONE})[ONE]
    assert (issue.code, issue.severity) == ("AMOUNT_UNUSUAL", "warning")
    ok = view(ONE, kind="bonus", quantity=None, amount=Decimal("20000"))
    assert codes([ok]) == {ONE: []}


def test_every_issue_says_who_acts_and_what_to_do():
    items = [
        view(ONE, employee=uuid4(), quantity=Decimal(13), ref="a"),
        view(TWO, quantity=Decimal(13), ref="b"),
    ]
    for specs in rules.conflicts(items, ACTIVE, {ONE, TWO}).values():
        for issue in specs:
            assert issue.message and issue.next_action and issue.owner_role


def test_each_input_gets_each_code_at_most_once():
    items = [view(ONE, ref="a"), view(TWO, ref="b"), view(THREE, ref="c")]
    for specs in rules.conflicts(items, ACTIVE, {ONE, TWO, THREE}).values():
        keys = [(s.code, s.field) for s in specs]
        assert len(keys) == len(set(keys))


def test_the_same_inputs_always_give_the_same_issues():
    items = [view(ONE, ref="a"), view(TWO, ref="b")]
    assert rules.conflicts(items, ACTIVE, {ONE, TWO}) == rules.conflicts(items, ACTIVE, {ONE, TWO})


def test_input_validation_is_pure():
    allowed = {
        "re",
        "dataclasses",
        "datetime",
        "decimal",
        "uuid",
        "packs.finance.validation.common",
    }
    imported = set()
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= allowed, imported - allowed
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
        assert not (isinstance(node, ast.Name) and node.id == "float")

"""Engagement checks. Pure functions: no database, no model."""

import ast
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from packs.finance.validation import engagement as rules

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "packages/packs/finance/validation/engagement.py"
ALL_DOCS = frozenset({"identity", "contract", "diploma", "aneti_approval"})


def view(**changes) -> rules.EngagementView:
    base = rules.EngagementView(
        type="CDI",
        starts_on=date(2026, 11, 1),
        ends_on=None,
        job_title="Backend Engineer",
        weekly_hours=Decimal("40"),
        cdd_reason_code=None,
        has_base_salary=True,
        verified_documents=ALL_DOCS,
    )
    return replace(base, **changes)


def codes(**changes) -> set[str]:
    return {issue.code for issue in rules.validate(view(**changes))}


def test_a_complete_cdi_has_no_issues():
    assert rules.validate(view()) == []


def test_a_complete_cdd_with_a_recognised_reason_has_no_issues():
    assert (
        rules.validate(view(type="CDD", ends_on=date(2027, 4, 30), cdd_reason_code="PROJECT")) == []
    )


def test_a_complete_civp_needs_no_base_salary():
    issues = rules.validate(
        view(
            type="CIVP", ends_on=date(2027, 10, 31), has_base_salary=False, weekly_hours=Decimal(40)
        )
    )
    assert issues == []


@pytest.mark.parametrize(
    ("changes", "code", "severity"),
    [
        ({"job_title": "  "}, "JOB_TITLE_MISSING", "blocking"),
        ({"starts_on": None}, "START_DATE_MISSING", "blocking"),
        (
            {"type": "CDD", "ends_on": None, "cdd_reason_code": "PROJECT"},
            "CDD_END_DATE_MISSING",
            "blocking",
        ),
        ({"type": "CIVP", "ends_on": None}, "CIVP_END_DATE_MISSING", "blocking"),
        ({"ends_on": date(2027, 1, 1)}, "CDI_HAS_END_DATE", "blocking"),
        (
            {"type": "CDD", "ends_on": date(2026, 10, 1), "cdd_reason_code": "PROJECT"},
            "DATES_INVALID",
            "blocking",
        ),
        ({"weekly_hours": None}, "WEEKLY_HOURS_MISSING", "blocking"),
        ({"weekly_hours": Decimal(0)}, "WEEKLY_HOURS_MISSING", "blocking"),
        ({"weekly_hours": Decimal("48.5")}, "WEEKLY_HOURS_REVIEW", "review"),
        ({"has_base_salary": False}, "NO_BASE_SALARY", "blocking"),
        ({"verified_documents": frozenset({"identity"})}, "DOCUMENT_NOT_VERIFIED", "blocking"),
    ],
)
def test_each_fault_gives_its_issue_and_severity(changes, code, severity):
    found = [i for i in rules.validate(view(**changes)) if i.code == code]
    assert found, f"{code} not raised"
    assert all(i.severity == severity for i in found)


def test_every_issue_says_who_acts_and_what_to_do():
    for issue in rules.validate(
        view(job_title="", has_base_salary=False, verified_documents=frozenset())
    ):
        assert issue.message and issue.next_action and issue.owner_role


def test_forty_eight_hours_is_allowed():
    assert "WEEKLY_HOURS_REVIEW" not in codes(weekly_hours=Decimal(48))


@pytest.mark.parametrize("reason", ["REPLACEMENT", "seasonal", " Project ", "TEMPORARY_INCREASE"])
def test_recognised_fixed_term_reasons_pass(reason):
    assert "CDD_REASON_REVIEW" not in codes(
        type="CDD", ends_on=date(2027, 4, 30), cdd_reason_code=reason
    )


@pytest.mark.parametrize("reason", [None, "", "WHIM", "REQUIRES_REVIEW"])
def test_missing_or_unlisted_reasons_go_to_a_person(reason):
    issues = rules.validate(view(type="CDD", ends_on=date(2027, 4, 30), cdd_reason_code=reason))
    found = [i for i in issues if i.code == "CDD_REASON_REVIEW"]
    assert len(found) == 1
    assert found[0].severity == "review"
    assert found[0].owner_role == "HR_LEGAL"


def test_only_a_cdd_is_asked_for_a_reason():
    assert "CDD_REASON_REVIEW" not in codes(cdd_reason_code="WHIM")


@pytest.mark.parametrize(
    ("kind", "missing"),
    [
        ("CDI", {"identity", "contract"}),
        ("CDD", {"identity", "contract"}),
        ("CIVP", {"identity", "diploma", "aneti_approval", "contract"}),
    ],
)
def test_each_engagement_type_asks_for_its_documents(kind, missing):
    ends = None if kind == "CDI" else date(2027, 4, 30)
    issues = rules.validate(
        view(type=kind, ends_on=ends, cdd_reason_code="PROJECT", verified_documents=frozenset())
    )
    asked = {i.field.split(".", 1)[1] for i in issues if i.code == "DOCUMENT_NOT_VERIFIED"}
    assert asked == missing


def test_a_civp_longer_than_twelve_months_goes_to_review():
    within = codes(type="CIVP", ends_on=date(2027, 11, 1))
    over = codes(type="CIVP", ends_on=date(2027, 11, 2))
    assert "CIVP_DURATION_REVIEW" not in within
    assert "CIVP_DURATION_REVIEW" in over


def test_an_unknown_type_stops_at_one_issue():
    issues = rules.validate(view(type="FREELANCE"))
    assert [i.code for i in issues] == ["ENGAGEMENT_TYPE_UNKNOWN"]


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2028, 2, 29), 12, date(2029, 2, 28)),
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 5, 15), 14, date(2027, 7, 15)),
        (date(2026, 12, 31), 12, date(2027, 12, 31)),
        (date(2026, 3, 31), 1, date(2026, 4, 30)),
    ],
)
def test_adding_months_keeps_the_day_or_the_last_day(start, months, expected):
    assert rules.add_months(start, months) == expected


def test_the_same_input_always_gives_the_same_issues():
    faulty = view(job_title="", has_base_salary=False, verified_documents=frozenset())
    assert rules.validate(faulty) == rules.validate(faulty)


def test_validation_is_pure():
    allowed = {"dataclasses", "datetime", "decimal", "packs.finance.validation.common"}
    imported = set()
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= allowed, imported - allowed
